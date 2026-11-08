"""Lavoro in background, un compito alla volta e sempre dopo le richieste dell'avvocato:
1. estrazione dei dati chiave: da sola per i documenti brevi, a richiesta per quelli lunghi (ha la precedenza);
2. indicizzazione semantica della normativa, un gruppo di articoli alla volta, finché ne restano."""
import logging
import queue
import threading
import time

from . import config, db, features, llm, normativa

log = logging.getLogger("law_prog")
_queue = queue.Queue()
SVEGLIA = object()   # mette in moto il lavoratore (es. dopo un aggiornamento della normativa)


def _status(document_id, status, error=""):
    """Aggiorna lo stato dell'estrazione, se il documento esiste ancora (può essere stato cancellato nel frattempo)."""
    with db.session() as conn:
        if conn.execute("SELECT 1 FROM documents WHERE id = ?", (document_id,)).fetchone():
            db.save_extraction(conn, document_id, status, error=error)


def enqueue(document_id):
    """Mette un documento in coda per l'estrazione."""
    _status(document_id, "in attesa")
    _queue.put(document_id)


def _breve(conn, document_id):
    """Il documento è abbastanza corto per l'estrazione automatica?"""
    trovato = conn.execute("SELECT chars FROM documents WHERE id = ?", (document_id,)).fetchone()
    return bool(trovato) and (trovato[0] or 0) <= config.EXTRACT_AUTO_CHARS


def automatica(document_id):
    """Dopo il caricamento: estrae da solo i documenti brevi. Restituisce True se l'estrazione è partita."""
    with db.session() as conn:
        breve = _breve(conn, document_id)
    if breve:
        enqueue(document_id)
    return breve


def sveglia():
    """Fa ripartire il lavoratore, che altrimenti resterebbe in attesa di un documento."""
    _queue.put(SVEGLIA)


def _estrai(document_id):
    """Esegue l'estrazione di un documento e ne registra l'eventuale errore senza fermare il lavoratore."""
    try:
        _status(document_id, "in corso")
        with llm.background():   # le domande dell'avvocato passano avanti
            for _ in features.extract(document_id):
                pass
    except Exception as exc:
        log.exception("Estrazione del documento %s non riuscita", document_id)
        try:
            _status(document_id, "errore", str(exc))
        except Exception:
            pass


def _indicizza_normativa():
    """Calcola gli embedding di un gruppo di articoli; dopo un errore aspetta un minuto prima di riprovare."""
    try:
        with llm.background():
            normativa.indicizza_lotto()
    except Exception:
        log.exception("Indicizzazione della normativa non riuscita: riprovo tra un minuto")
        time.sleep(60)


def _worker():
    """Ciclo del lavoro in background: estrae i documenti in coda e, nei momenti liberi, indicizza la normativa."""
    while True:
        # Con articoli ancora da indicizzare non si resta fermi ad aspettare documenti.
        attesa = 0 if normativa.da_indicizzare() else None
        try:
            compito = _queue.get(timeout=attesa) if attesa is not None else _queue.get()
        except queue.Empty:
            _indicizza_normativa()
            continue
        if compito is not SVEGLIA:
            _estrai(compito)


def start():
    """Carica i modelli in memoria, poi avvia il lavoratore e riprende le estrazioni brevi rimaste a metà.
    Quelle dei documenti lunghi tornano "non eseguite": è l'avvocato a decidere se rifarle."""
    with db.session() as conn:
        rimaste = [r[0] for r in conn.execute(
            "SELECT document_id FROM extractions WHERE status IN ('in attesa', 'in corso') ORDER BY document_id")]
        pending = [d for d in rimaste if _breve(conn, d)]
        for document_id in rimaste:
            if document_id not in pending:
                db.save_extraction(conn, document_id, "non eseguita")

    def avvio():
        llm.warm_up()
        _worker()
    threading.Thread(target=avvio, daemon=True, name="background").start()
    for document_id in pending:
        enqueue(document_id)


def pending():
    """Quanti documenti sono in coda per l'estrazione."""
    return sum(1 for x in list(_queue.queue) if x is not SVEGLIA)
