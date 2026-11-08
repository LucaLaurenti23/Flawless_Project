"""Accesso a Ollama: generazione di testo (qwen) ed embedding (bge-m3).

Ollama esegue una richiesta alla volta: le richieste dell'avvocato (domande, riassunti, bozze) hanno
la precedenza su quelle in background (estrazione dei dati): quando ne arriva una, la richiesta in background
viene interrotta e ripetuta appena l'avvocato ha finito."""
import http.client
import json
import logging
import select
import threading
from contextlib import contextmanager
from urllib.parse import urlsplit

import numpy as np
import ollama

from . import config

log = logging.getLogger("law_prog")
_client = ollama.Client(host=config.OLLAMA_HOST)

EMBED_BATCH = 16

_local = threading.local()
_turno = threading.Condition()
_interattive = 0   # richieste dell'avvocato in corso


@contextmanager
def background():
    """Le chiamate fatte qui dentro (nello stesso thread) cedono il passo alle richieste dell'avvocato."""
    _local.background = True
    try:
        yield
    finally:
        _local.background = False


def interattiva():
    """Per tutta la durata di una richiesta dell'avvocato il lavoro in background resta fermo."""
    return _precedenza()


@contextmanager
def _precedenza():
    """Dà la precedenza alle domande: il lavoro in background parte solo quando non ce ne sono in corso."""
    global _interattive
    if getattr(_local, "background", False):
        with _turno:
            _turno.wait_for(lambda: _interattive == 0)
        yield
        return
    with _turno:
        _interattive += 1
    try:
        yield
    finally:
        with _turno:
            _interattive -= 1
            _turno.notify_all()


def _options(max_tokens):
    """Le opzioni di generazione per Ollama, uguali in tutte le richieste per non far ricaricare il modello."""
    return {"num_ctx": config.NUM_CTX, "num_thread": config.NUM_THREAD, "temperature": config.TEMPERATURE,
            "num_predict": max_tokens}


def chat_stream(messages, max_tokens=None):
    """Restituisce il testo della risposta un pezzo alla volta."""
    with _precedenza():
        # think=False: il ragionamento esplicito di qwen3.5 raddoppierebbe i tempi sulla CPU.
        for part in _client.chat(
            model=config.CHAT_MODEL, messages=messages, stream=True, think=False,
            keep_alive=config.KEEP_ALIVE, options=_options(max_tokens or config.MAX_ANSWER_TOKENS),
        ):
            if part.message.content:
                yield part.message.content


class _Ceduto(Exception):
    """È arrivata una richiesta dell'avvocato: quella in background si ferma."""


def _chat_interrompibile(payload):
    """Chiamata a Ollama che si interrompe appena arriva una richiesta dell'avvocato. Chiudere la connessione
    fa smettere Ollama; il controllo vale anche mentre legge il prompt, quando ancora non arriva nessun dato."""
    url = urlsplit(config.OLLAMA_HOST)
    classe = http.client.HTTPSConnection if url.scheme == "https" else http.client.HTTPConnection
    conn = classe(url.hostname, url.port or (443 if url.scheme == "https" else 11434), timeout=900)
    try:
        conn.request("POST", "/api/chat", json.dumps(payload), {"Content-Type": "application/json"})
        while not select.select([conn.sock], [], [], 0.25)[0]:
            if _interattive:
                raise _Ceduto
        risposta = conn.getresponse()
        if risposta.status != 200:
            raise RuntimeError(f"Ollama ha risposto {risposta.status}: {risposta.read()[:300]!r}")
        testo = []
        for riga in risposta:
            if _interattive:
                raise _Ceduto
            if riga.strip():
                evento = json.loads(riga)
                if evento.get("error"):
                    raise RuntimeError(evento["error"])
                testo.append(evento.get("message", {}).get("content", ""))
        return "".join(testo)
    finally:
        conn.close()


def _complete_in_background(messages, format, max_tokens):
    """Genera un testo in background; se arriva una domanda dell'avvocato si interrompe, aspetta e ricomincia."""
    payload = {"model": config.CHAT_MODEL, "messages": messages, "stream": True, "think": False,
               "keep_alive": config.KEEP_ALIVE, "options": _options(max_tokens)}
    if format:
        payload["format"] = format
    while True:
        with _turno:
            _turno.wait_for(lambda: _interattive == 0)
        try:
            return _chat_interrompibile(payload)
        except _Ceduto:
            log.info("Lavoro in background interrotto: ha la precedenza una richiesta dell'avvocato")


def complete(messages, format=None, max_tokens=None):
    """Risposta completa in una volta; `format` accetta uno schema JSON per output strutturato."""
    if getattr(_local, "background", False):
        return _complete_in_background(messages, format, max_tokens or config.MAX_LONG_TOKENS)
    with _precedenza():
        response = _client.chat(
            model=config.CHAT_MODEL, messages=messages, stream=False, think=False, format=format,
            keep_alive=config.KEEP_ALIVE, options=_options(max_tokens or config.MAX_LONG_TOKENS),
        )
    return response.message.content


def embed(texts):
    """Embedding normalizzati (norma 1), così la similarità coseno è un semplice prodotto scalare."""
    vectors = []
    for start in range(0, len(texts), EMBED_BATCH):
        batch = texts[start:start + EMBED_BATCH]
        # anche gli embedding in background (indicizzazione della normativa) cedono il passo all'avvocato
        with _precedenza():
            response = _client.embed(model=config.EMBED_MODEL, input=batch, keep_alive=config.KEEP_ALIVE)
        vectors.extend(response.embeddings)
    matrix = np.asarray(vectors, dtype=np.float32)
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    return matrix / np.where(norms == 0, 1, norms)


def warm_up():
    """Carica in memoria i due modelli all'avvio, con le stesse opzioni delle richieste vere:
    così la prima domanda non paga il caricamento."""
    try:
        embed(["avvio"])
        complete([{"role": "user", "content": "Rispondi solo: pronto"}], max_tokens=1)
    except Exception as exc:
        log.warning("Riscaldamento dei modelli non riuscito: %s", exc)


def _with_tag(name):
    """Il nome del modello con l'etichetta, come lo elenca Ollama: senza etichetta vale ":latest"."""
    return name if ":" in name else f"{name}:latest"


EMBEDDING_HINTS = ("embed", "bge", "nomic", "minilm", "e5-")


def chat_models(installed):
    """Modelli installati utilizzabili per il testo: si escludono quelli di embedding."""
    embed_model = _with_tag(config.EMBED_MODEL)
    return sorted(m for m in installed if m != embed_model and not any(h in m.lower() for h in EMBEDDING_HINTS))


def status():
    """Stato di Ollama e dei modelli configurati, oppure l'errore se Ollama non risponde."""
    try:
        installed = {m.model for m in _client.list().models}
    except Exception as exc:
        return {"ollama": False, "chat_model": config.CHAT_MODEL, "embed_model": config.EMBED_MODEL,
                "models": [], "missing_models": [],
                "error": f"Ollama non raggiungibile su {config.OLLAMA_HOST}: {exc}"}
    missing = [m for m in (config.CHAT_MODEL, config.EMBED_MODEL) if _with_tag(m) not in installed]
    return {
        "ollama": True,
        "chat_model": config.CHAT_MODEL,
        "embed_model": config.EMBED_MODEL,
        "models": chat_models(installed),
        "missing_models": missing,
    }
