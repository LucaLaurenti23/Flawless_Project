"""Domande sui documenti del fascicolo (RAG) e chat libera, con cronologia salvata."""
import re
import time

import numpy as np

from . import config, controlli, db, llm, normativa, ocr, sicurezza
from .documents import page_label

HISTORY_MESSAGES = 6
# Importo espresso in lire: "lire 500", "L. 1.000.000".
RE_LIRE = re.compile(r"\blire\b|\bL\.\s*\d{1,3}(?:\.\d{3})+\b", re.IGNORECASE)
# "come si è conclusa la vicenda?" come prima domanda: in un fascicolo con più vicende il modello le mescolerebbe.
RE_DOMANDA_VAGA = re.compile(r"\b(?:la|il|del|della|sul|sulla|nel|nella|questa|questo)\s+"
                             r"(?:vicenda|caso|causa|processo|procedimento|questione|controversia)\s*\??\s*$", re.IGNORECASE)
CHIEDI_PRECISAZIONE = ("Di quale vicenda parli? Indica il nome di una persona o il provvedimento, ad esempio "
                       "\"come si è concluso il processo a Rossi?\": il fascicolo può contenere vicende diverse.")

# Non accorciare questi prompt né le REGOLE di sicurezza senza ritestare: versioni più brevi (150-170 token in meno,
# circa 8 s) hanno peggiorato le risposte. Prova ripetuta 5 volte su 2 domande: corrette 0/5 contro 5/5.
SYSTEM_RAG = """Sei un assistente per uno studio legale italiano. Rispondi in italiano, in modo preciso e professionale.
Regole obbligatorie:
1. Usa SOLO le informazioni contenute negli estratti numerati che ti vengono forniti. Non usare conoscenze esterne.
2. Dopo ogni affermazione indica la fonte tra parentesi quadre, ad esempio [1] oppure [2][3].
3. Se gli estratti non contengono la risposta, scrivi: "Nei documenti del fascicolo non ho trovato questa informazione."
4. Non inventare mai norme, sentenze, date, importi o nomi.
5. Riporta date, importi e nomi esattamente come compaiono negli estratti.
6. Sii conciso: poche frasi, al massimo 120 parole, salvo che l'avvocato chieda un'analisi dettagliata."""

SYSTEM_NORMA = """Sei un assistente per uno studio legale italiano. Rispondi in italiano, in modo chiaro e preciso.
Ti vengono forniti articoli di legge numerati, nel testo ufficiale vigente (fonte: Normattiva, EUR-Lex).
Regole obbligatorie:
1. Rispondi SOLO in base agli articoli forniti. Non usare conoscenze esterne per numeri di articolo, termini, durate o importi.
2. Indica sempre l'articolo su cui ti basi, con il suo numero tra parentesi quadre: ad esempio "l'art. 1454 c.c. [1]".
3. Riporta termini, durate e importi esattamente come scritti nella norma.
4. Se gli articoli forniti non contengono la risposta, scrivi: "Negli articoli trovati non c'è la risposta: prova a riformulare la domanda o a indicare la legge." Non inventare.
5. Sii conciso: al massimo 150 parole, salvo che l'avvocato chieda un approfondimento."""

SYSTEM_CHAT = """Sei un assistente per avvocati italiani. Rispondi in italiano, in modo chiaro e professionale.
Puoi ragionare su qualunque questione giuridica, anche ipotetica o non regolata espressamente.
Con la domanda ricevi, quando disponibili, articoli di legge numerati dell'archivio, nel testo ufficiale. Non hai accesso ai documenti dello studio.
Regole obbligatorie:
1. Se gli articoli forniti sono pertinenti, parti da quelli e citali con il numero tra parentesi quadre: ad esempio "l'art. 2043 c.c. [1]". Riporta termini, durate e importi esattamente come scritti nella norma.
2. Se gli articoli non bastano o non sono pertinenti, ragiona comunque: puoi formulare supposizioni in base ai principi generali, all'analogia o alle possibili interpretazioni.
3. Ogni supposizione deve iniziare con la parola "Ipotesi:" e non va presentata come certezza.
4. Non inventare sentenze. Se citi una norma che non è tra quelle fornite, scrivi che va verificata su fonti ufficiali.
5. Sii conciso: al massimo 200 parole, salvo che l'avvocato chieda un approfondimento."""

# Le regole di sicurezza contro la prompt injection valgono in tutte le modalità.
SYSTEM_RAG += "\n\n" + sicurezza.REGOLE
SYSTEM_NORMA += "\n\n" + sicurezza.REGOLE
SYSTEM_CHAT += "\n\n" + sicurezza.REGOLE


def search(query, case_id, k=None, document_ids=None):
    """I brani più simili alla domanda. Quelli molto meno pertinenti del migliore vengono scartati:
    sulla CPU ogni brano nel prompt costa diversi secondi di lettura."""
    sql = """SELECT c.document_id, c.page, c.text, c.embedding, d.filename, d.warning
             FROM chunks c JOIN documents d ON d.id = c.document_id
             WHERE d.case_id = ?"""
    params = [case_id]
    if document_ids:
        sql += f" AND d.id IN ({','.join('?' * len(document_ids))})"
        params += list(document_ids)
    with db.session() as conn:
        found = conn.execute(sql, params).fetchall()
    if not found:
        return []
    query_vector = llm.embed([query])[0]
    matrix = np.stack([db.from_blob(r["embedding"]) for r in found])
    scores = matrix @ query_vector
    best = [i for i in np.argsort(-scores)[: k or config.TOP_K] if scores[i] >= scores.max() - config.SCORE_MARGIN]
    return [
        {
            "n": rank,
            "document_id": found[i]["document_id"],
            "filename": found[i]["filename"],
            "page": found[i]["page"],
            "text": found[i]["text"],
            "score": round(float(scores[i]), 3),
            "sospetto": bool(sicurezza.rileva(found[i]["text"])),
            "ocr": ocr.MARCATORE in (found[i]["warning"] or ""),
        }
        for rank, i in enumerate(best, start=1)
    ]


def format_excerpts(sources):
    """Estratti dei documenti, recintati: per il modello sono dati da analizzare, mai ordini."""
    return sicurezza.recinta("\n\n".join(
        f"[{s['n']}] ({s['filename']}, {page_label(s['page'])})\n{sicurezza.marca(s['text'])}" for s in sources))


def _rifiuta(conversation_id, question):
    """Tentativo di prompt injection nella domanda: risposta fissa, senza interpellare il modello."""
    yield {"type": "token", "text": sicurezza.RIFIUTO}
    with db.session() as conn:
        db.add_message(conn, conversation_id, "user", question)
        db.add_message(conn, conversation_id, "assistant", sicurezza.RIFIUTO)


def _open_conversation(case_id, kind, conversation_id, title):
    """Riapre la conversazione o ne crea una nuova. Una conversazione di un altro fascicolo non si riusa."""
    with db.session() as conn:
        if conversation_id:
            conversation = db.one(conn.execute("SELECT * FROM conversations WHERE id = ?", (conversation_id,)))
            if not conversation or conversation["kind"] != kind:
                raise ValueError(f"Conversazione {conversation_id} non trovata")
            if conversation["case_id"] != case_id:   # la cronologia di un altro fascicolo non deve entrare in questo
                conversation_id = None
        if conversation_id:
            history = db.get_messages(conn, conversation_id)
        else:
            conversation_id = db.create_conversation(conn, case_id, kind, title)
            history = []
    return conversation_id, history


def _history_messages(history):
    """Gli ultimi messaggi della conversazione, nel formato richiesto dal modello."""
    return [{"role": m["role"], "content": m["content"]} for m in history[-HISTORY_MESSAGES:]]


def _ms(start):
    """Millisecondi trascorsi dall'istante indicato."""
    return round((time.perf_counter() - start) * 1000)


def _risposta_fissa(conversation_id, question, text):
    """Risponde con un testo prestabilito, senza interpellare il modello, e lo salva nella cronologia."""
    yield {"type": "token", "text": text}
    with db.session() as conn:
        db.add_message(conn, conversation_id, "user", question)
        db.add_message(conn, conversation_id, "assistant", text)


def _avvisi_norme(risposta, fonti_tagliate, fonti_raccolta=()):
    """Avvisi scritti dal programma, non dal modello: valgono sempre e non dipendono da come il modello formula la risposta."""
    avvisi = []
    if fonti_raccolta:
        avvisi.append(f"Atto della raccolta ({', '.join(s['etichetta'] for s in fonti_raccolta)}): se modifica un'altra legge, "
                      "ne riporta il testo di allora, che può essere stato cambiato. Controlla la legge modificata.")
    if RE_LIRE.search(risposta):
        avvisi.append("Il testo ufficiale in archivio riporta importi in lire. L'importo oggi applicabile può essere diverso "
                      "(conversione in euro e adeguamenti successivi): verificalo prima di usarlo.")
    tagliate = [s["etichetta"] for s in fonti_tagliate if f"[{s['n']}]" in risposta]
    if tagliate:
        avvisi.append(f"Articolo lungo ({', '.join(tagliate)}): il modello ne ha letto solo le parti più vicine alla domanda. "
                      "Controlla il testo intero nella fonte.")
    return "".join(f"\n\n⚠ {a}" for a in avvisi)


def _avviso_ocr(fonti):
    """Avviso scritto dal programma quando la risposta usa documenti letti con l'OCR."""
    nomi = sorted({s["filename"] for s in fonti if s["ocr"]})
    if not nomi:
        return ""
    return (f"\n\n⚠ Documento letto con l'OCR ({', '.join(nomi)}): cifre, date e nomi possono contenere errori di lettura. "
            "Controllali sull'atto.")


def _stream_and_save(conversation_id, question, messages, sources, started, search_ms=0, avvisi=None):
    """Trasmette la risposta del modello, aggiunge gli eventuali avvisi e salva messaggi, fonti e tempi."""
    answer, first_token_ms = [], None
    for token in llm.chat_stream(messages):
        if first_token_ms is None:
            first_token_ms = _ms(started)
            generation_start = time.perf_counter()
        answer.append(token)
        yield {"type": "token", "text": token}
    total_ms = _ms(started)
    generation_s = time.perf_counter() - generation_start if answer else 0
    coda = avvisi("".join(answer)) if avvisi else ""
    if coda:
        answer.append(coda)
        yield {"type": "token", "text": coda}
    # Ollama invia circa un token per pezzo: basta per una stima della velocità.
    meta = {"domanda": question, "modello": config.CHAT_MODEL, "tempi": {
        "ricerca_ms": search_ms, "prima_parola_ms": first_token_ms, "totale_ms": total_ms,
        "tok_s": round((len(answer) - bool(coda)) / generation_s, 1) if generation_s > 0 else None}}
    with db.session() as conn:
        db.add_message(conn, conversation_id, "user", question)
        db.add_message(conn, conversation_id, "assistant", "".join(answer), sources, meta)
    yield {"type": "meta", **meta}


def ask(question, case_id, conversation_id=None, document_ids=None, deep=False):
    """Risponde a una domanda usando solo i documenti del fascicolo, trasmettendo eventi."""
    started = time.perf_counter()
    conversation_id, history = _open_conversation(case_id, "rag", conversation_id, question)
    yield {"type": "conversation", "id": conversation_id}
    if sicurezza.rileva(question):
        yield from _rifiuta(conversation_id, question)
        return

    if not history and RE_DOMANDA_VAGA.search(question):
        yield from _risposta_fissa(conversation_id, question, CHIEDI_PRECISAZIONE)
        return

    # Per le domande di seguito ("e la seconda?") la domanda precedente aiuta a trovare i passi giusti.
    previous =[m["content"] for m in history if m["role"] == "user"][-1:]
    yield {"type": "status", "text": "Ricerca nei documenti…"}
    sources = search(" ".join(previous + [question]), case_id, k=config.TOP_K_DEEP if deep else config.TOP_K,
                     document_ids=document_ids)
    search_ms = _ms(started)
    yield {"type": "sources", "sources": sources}

    if not sources:
        text = "Il fascicolo non contiene documenti indicizzati: carica dei documenti nella scheda Documenti."
        yield {"type": "token", "text": text}
        with db.session() as conn:
            db.add_message(conn, conversation_id, "user", question)
            db.add_message(conn, conversation_id, "assistant", text)
        return

    messages = [{"role": "system", "content": SYSTEM_RAG}, *_history_messages(history), {
        "role": "user",
        "content": f"Estratti dai documenti del fascicolo:\n\n{format_excerpts(sources)}\n\nDomanda: {question}\n\n"
                   f"{sicurezza.PROMEMORIA}",
    }]
    yield {"type": "status", "text": "Generazione della risposta…"}
    yield from _stream_and_save(conversation_id, question, messages, sources, started, search_ms,
                                avvisi=lambda _risposta: _avviso_ocr(sources))


def ask_normativa(question, case_id, conversation_id=None, deep=False, atti=None):
    """Risponde a una domanda usando solo gli articoli trovati nell'archivio normativo, trasmettendo eventi."""
    started = time.perf_counter()
    conversation_id, history = _open_conversation(case_id, "norm", conversation_id, question)
    yield {"type": "conversation", "id": conversation_id}
    if sicurezza.rileva(question):
        yield from _rifiuta(conversation_id, question)
        return

    assenti, resto = normativa.atti_assenti(question)
    nota_assenti = ""
    if assenti and not atti:
        nota_assenti = (f"⚠ {', '.join(assenti)}: non nell'archivio. Può essere abrogato, non ancora scaricato o senza un "
                        "testo scaricabile: verifica su normattiva.it.")
        if len(normativa._termini(resto)) <= 1:   # la domanda riguarda solo quell'atto: gli altri articoli non servono
            yield from _risposta_fissa(conversation_id, question, nota_assenti)
            return
        nota_assenti += " Di seguito, gli altri articoli trovati.\n\n"
        yield {"type": "token", "text": nota_assenti}

    previous = [m["content"] for m in history if m["role"] == "user"][-1:]
    yield {"type": "status", "text": "Ricerca nella normativa…"}
    sources = normativa.cerca(question, k=config.TOP_K_DEEP if deep else config.TOP_K, atti=atti,
                              contesto=" ".join(previous))
    search_ms = _ms(started)
    yield {"type": "sources", "sources": sources}

    if not sources:
        text = ("Non ho trovato articoli pertinenti nell'archivio normativo. Se l'archivio è vuoto, "
                "scarica i testi dalla scheda Leggi; altrimenti prova a riformulare o a indicare la legge.")
        yield {"type": "token", "text": text}
        with db.session() as conn:
            db.add_message(conn, conversation_id, "user", question)
            db.add_message(conn, conversation_id, "assistant", text)
        return

    estratti, tagliate, raccolta = _norme_per_modello(sources, question)
    messages = [{"role": "system", "content": SYSTEM_NORMA}, *_history_messages(history), {
        "role": "user", "content": f"Articoli di legge:\n\n{sicurezza.recinta(estratti)}\n\nDomanda: {question}\n\n"
                                   f"{sicurezza.PROMEMORIA}"}]
    yield {"type": "status", "text": "Generazione della risposta…"}
    yield from _stream_and_save(conversation_id, question, messages, sources, started, search_ms,
                                avvisi=lambda risposta: _avvisi_norme(risposta, tagliate, raccolta))


def _norme_per_modello(sources, question):
    """Gli articoli trovati nel formato per il modello, con quelli letti solo in parte e quelli della raccolta."""
    # il primo articolo si legge per esteso, gli altri in breve: ogni 1.000 caratteri costano circa 12 s sulla CPU
    testi = [normativa.testo_per_modello(s, question, normativa.MASSIMO_PER_MODELLO if i == 0 else normativa.PARTE_MAX)
             for i, s in enumerate(sources)]
    # il nome dell'atto dice al modello a chi si applica la norma (es. "imputati minorenni"); i codici non ne hanno bisogno
    estratti = "\n\n".join(
        f"[{s['n']}] {s['etichetta']}{'' if s['atto'] in normativa.PRIORITARI else ' (' + s['titolo_atto'][:100] + ')'}"
        f"{' – ' + s['rubrica'] if s['rubrica'] else ''}\n{t}" for s, t in zip(sources, testi))
    tagliate = [s for s, t in zip(sources, testi) if "[…]" in t]
    return estratti, tagliate, [s for s in sources if s.get("raccolta")]


def _avvisi_chat(risposta, testo_noto, tagliate, raccolta):
    """Avvisi della chat libera: il modello può ragionare oltre i testi, quindi si segnala ciò che i testi non contengono."""
    assenti = controlli.non_nel_testo(risposta, testo_noto)
    fuori = (f"\n\n⚠ Riferimenti o cifre non presenti negli articoli trovati: {', '.join(assenti)}. Verificali su fonti ufficiali."
             if assenti else "")
    return fuori + _avvisi_norme(risposta, tagliate, raccolta)


def chat(message, case_id, conversation_id=None):
    """Chat libera: parte dagli articoli dell'archivio normativo e può formulare ipotesi oltre i testi. Non usa i documenti."""
    started = time.perf_counter()
    conversation_id, history = _open_conversation(case_id, "chat", conversation_id, message)
    yield {"type": "conversation", "id": conversation_id}
    if sicurezza.rileva(message):
        yield from _rifiuta(conversation_id, message)
        return
    previous = [m["content"] for m in history if m["role"] == "user"][-1:]
    yield {"type": "status", "text": "Ricerca nella normativa…"}
    sources = normativa.cerca(message, contesto=" ".join(previous))
    search_ms = _ms(started)
    yield {"type": "sources", "sources": sources}
    estratti, tagliate, raccolta = _norme_per_modello(sources, message)
    corpo = f"Articoli di legge:\n\n{sicurezza.recinta(estratti)}\n\nDomanda: {message}\n\n{sicurezza.PROMEMORIA}" if sources else message
    messages = [{"role": "system", "content": SYSTEM_CHAT}, *_history_messages(history), {"role": "user", "content": corpo}]
    yield {"type": "status", "text": "Generazione della risposta…"}
    yield from _stream_and_save(conversation_id, message, messages, sources, started, search_ms,
                                avvisi=lambda risposta: _avvisi_chat(risposta, f"{estratti} {message}", tagliate, raccolta))
