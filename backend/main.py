"""Server locale: API sotto /api e interfaccia web (cartella frontend) sulla radice.
Avvio: python -m uvicorn backend.main:app --port 8765"""
import json
import logging
import os
import re
import tempfile
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, FastAPI, File, HTTPException, UploadFile
from fastapi.responses import Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import config, db, documents, elements, export, features, jobs, llm, modelli, normativa, rag

log = logging.getLogger("law_prog")


@asynccontextmanager
async def lifespan(app):
    """All'accensione del server prepara l'archivio e avvia il lavoro in background."""
    db.init()
    jobs.start()
    yield


app = FastAPI(title="Flawless Project", description="Assistente IA locale per studi legali", lifespan=lifespan)
api = APIRouter(prefix="/api")


@app.middleware("http")
async def no_cache(request, call_next):
    """Chiede al browser di ricontrollare ogni volta le pagine dell'interfaccia."""
    # Le pagine vengono sempre ricontrollate: dopo un aggiornamento il browser non usa script vecchi.
    response = await call_next(request)
    if not request.url.path.startswith("/api"):
        response.headers["Cache-Control"] = "no-cache"
    return response


def ndjson(events):
    """Trasmette gli eventi uno per riga (JSON). Gli errori diventano un evento, non una connessione interrotta."""
    def body():
        try:
            with llm.interattiva():   # ricerca, lettura e risposta: il lavoro in background aspetta
                for event in events:
                    yield json.dumps(event, ensure_ascii=False) + "\n"
        except Exception as exc:
            log.exception("Errore durante l'elaborazione")
            yield json.dumps({"type": "error", "text": str(exc)}, ensure_ascii=False) + "\n"
        yield json.dumps({"type": "done"}) + "\n"
    return StreamingResponse(body(), media_type="application/x-ndjson")


def _not_found(what):
    """Risponde 404 con un messaggio in italiano."""
    raise HTTPException(status_code=404, detail=f"{what} non trovato")


# --- Stato e modello ------------------------------------------------------------

@api.get("/status")
def status():
    """Stato di Ollama, parametri di ricerca, estrazioni in coda e archivio normativo."""
    return {**llm.status(), "top_k": config.TOP_K, "top_k_deep": config.TOP_K_DEEP, "estrazioni_in_coda": jobs.pending(),
            "normativa": {**normativa.conteggi(), "aggiornamento": normativa.avanzamento["attivo"]}}


class ModelIn(BaseModel):
    model: str


@api.post("/model")
def set_model(body: ModelIn):
    """Cambia il modello di testo, se è installato."""
    available = llm.status().get("models", [])
    if body.model not in available:
        raise HTTPException(400, f"Modello non installato: {body.model}")
    config.CHAT_MODEL = body.model
    return {"ok": True, "chat_model": config.CHAT_MODEL}


# --- Fascicoli ----------------------------------------------------------------

class CaseIn(BaseModel):
    name: str
    client: str = ""
    notes: str = ""


@api.get("/cases")
def list_cases():
    """I fascicoli con il numero di documenti, frammenti e conversazioni."""
    with db.session() as conn:
        return db.rows(conn.execute("""
            SELECT c.*,
                   (SELECT COUNT(*) FROM documents d WHERE d.case_id = c.id) AS documents,
                   (SELECT COUNT(*) FROM chunks k JOIN documents d ON d.id = k.document_id WHERE d.case_id = c.id) AS chunks,
                   (SELECT COUNT(*) FROM conversations v WHERE v.case_id = c.id) AS conversations
            FROM cases c ORDER BY c.name COLLATE NOCASE"""))


@api.post("/cases")
def create_case(case: CaseIn):
    """Crea un fascicolo vuoto. Il nome deve essere unico."""
    name = case.name.strip()
    if not name:
        raise HTTPException(400, "Il nome del fascicolo è obbligatorio")
    with db.session() as conn:
        if conn.execute("SELECT 1 FROM cases WHERE name = ?", (name,)).fetchone():
            raise HTTPException(409, f"Esiste già un fascicolo chiamato «{name}»")
        cur = conn.execute("INSERT INTO cases (name, client, notes) VALUES (?, ?, ?)", (name, case.client, case.notes))
        return {"id": cur.lastrowid}


@api.put("/cases/{case_id}")
def update_case(case_id: int, case: CaseIn):
    """Modifica nome, cliente e note di un fascicolo."""
    with db.session() as conn:
        cur = conn.execute("UPDATE cases SET name = ?, client = ?, notes = ? WHERE id = ?",
                           (case.name.strip(), case.client, case.notes, case_id))
        if not cur.rowcount:
            _not_found("Fascicolo")
    return {"ok": True}


@api.delete("/cases/{case_id}")
def delete_case(case_id: int):
    """Elimina il fascicolo con documenti e conversazioni. I testi di legge stanno in altre tabelle e non vengono toccati."""
    with db.session() as conn:
        paths = [r["path"] for r in conn.execute("SELECT path FROM documents WHERE case_id = ?", (case_id,))]
        if not conn.execute("DELETE FROM cases WHERE id = ?", (case_id,)).rowcount:
            _not_found("Fascicolo")
        # il programma lavora sempre dentro un fascicolo: se era l'ultimo ne riparte uno vuoto
        if not conn.execute("SELECT 1 FROM cases LIMIT 1").fetchone():
            conn.execute("INSERT INTO cases (name) VALUES (?)", (db.DEFAULT_CASE,))
    for path in paths:
        documents.remove_file(path)
    return {"ok": True}


@api.get("/cases/{case_id}/elements")
def case_elements(case_id: int):
    """Parti, date, scadenze e importi del fascicolo."""
    return elements.case_elements(case_id)


@api.get("/cases/{case_id}/search")
def search(case_id: int, q: str):
    """Ricerca testuale nei documenti del fascicolo."""
    return {"query": q, "documenti": elements.search(case_id, q)}


@api.get("/cases/{case_id}/timings")
def timings(case_id: int):
    """Tempi di risposta di tutte le domande del fascicolo, dalla più vecchia."""
    with db.session() as conn:
        found = conn.execute("""
            SELECT m.meta, m.created_at FROM messages m JOIN conversations c ON c.id = m.conversation_id
            WHERE c.case_id = ? AND m.role = 'assistant' AND m.meta != '{}' ORDER BY m.id""", (case_id,)).fetchall()
    return [{**json.loads(r["meta"]), "ora": r["created_at"]} for r in found]


# --- Documenti ----------------------------------------------------------------

@api.get("/cases/{case_id}/documents")
def list_documents(case_id: int):
    """I documenti del fascicolo con lo stato dell'estrazione."""
    with db.session() as conn:
        return db.rows(conn.execute("""
            SELECT d.id, d.filename, d.pages, d.chars, d.warning, d.created_at,
                   COALESCE(e.status, 'non eseguita') AS estrazione
            FROM documents d LEFT JOIN extractions e ON e.document_id = d.id
            WHERE d.case_id = ? ORDER BY d.id DESC""", (case_id,)))


@api.post("/cases/{case_id}/documents")
async def upload_document(case_id: int, file: UploadFile = File(...)):
    """Carica un documento e trasmette l'avanzamento di lettura e indicizzazione."""
    with db.session() as conn:
        if not conn.execute("SELECT 1 FROM cases WHERE id = ?", (case_id,)).fetchone():
            _not_found("Fascicolo")
    # Il file va salvato subito: l'upload viene chiuso prima che la risposta in streaming finisca.
    fd, temp_path = tempfile.mkstemp(suffix=Path(file.filename).suffix)
    with os.fdopen(fd, "wb") as out:
        out.write(await file.read())

    def events():
        try:
            for event in documents.ingest(case_id, file.filename, temp_path):
                if event["type"] == "result":
                    # parti, date, scadenze e importi in background (solo documenti brevi)
                    event = {**event, "estrazione_avviata": jobs.automatica(event["document_id"])}
                yield event
        finally:
            os.unlink(temp_path)
    return ndjson(events())


@api.get("/documents/{document_id}")
def get_document(document_id: int):
    """Un documento con il testo pagina per pagina."""
    with db.session() as conn:
        try:
            document = documents.get_document(conn, document_id)
        except documents.DocumentError:
            _not_found("Documento")
    return {"id": document["id"], "case_id": document["case_id"], "filename": document["filename"],
            "warning": document["warning"], "created_at": document["created_at"],
            "pages": documents.pages_text(document["path"])}


@api.delete("/documents/{document_id}")
def delete_document(document_id: int):
    """Elimina un documento dal fascicolo."""
    with db.session() as conn:
        try:
            documents.delete_document(conn, document_id)
        except documents.DocumentError:
            _not_found("Documento")
    return {"ok": True}


# --- Domande, chat e storico ---------------------------------------------------

class AskIn(BaseModel):
    question: str
    case_id: int
    conversation_id: int | None = None
    document_ids: list[int] | None = None
    deep: bool = False   # ricerca approfondita: più brani, risposta più completa ma più lenta


class ChatIn(BaseModel):
    message: str
    case_id: int
    conversation_id: int | None = None


@api.post("/ask")
def ask(body: AskIn):
    """Domanda sui documenti del fascicolo."""
    return ndjson(rag.ask(body.question, body.case_id, body.conversation_id, body.document_ids, body.deep))


@api.post("/chat")
def chat(body: ChatIn):
    """Domanda libera, senza documenti né normativa."""
    return ndjson(rag.chat(body.message, body.case_id, body.conversation_id))


# --- Normativa ----------------------------------------------------------------------

class AskNormIn(BaseModel):
    question: str
    case_id: int
    conversation_id: int | None = None
    deep: bool = False
    atti: list[int] | None = None   # limita la ricerca ad alcuni atti (es. solo il codice civile)


@api.post("/ask-normativa")
def ask_normativa(body: AskNormIn):
    """Domanda sull'archivio normativo."""
    return ndjson(rag.ask_normativa(body.question, body.case_id, body.conversation_id, body.deep, body.atti))


@api.get("/normativa")
def stato_normativa():
    """Gli atti in archivio e lo stato dell'aggiornamento."""
    return normativa.stato()


@api.post("/normativa/aggiorna")
def aggiorna_normativa():
    """Riscarica i testi dai siti ufficiali in background; poi riparte l'indicizzazione semantica."""
    if normativa.avanzamento["attivo"]:
        raise HTTPException(409, "Aggiornamento già in corso")

    def lavoro():
        try:
            normativa.aggiorna()
        except Exception:
            log.exception("Aggiornamento della normativa non riuscito")
        finally:
            jobs.sveglia()
    threading.Thread(target=lavoro, daemon=True, name="aggiorna-normativa").start()
    return {"ok": True}


@api.get("/normativa/norme/{norma_id}")
def norma(norma_id: int):
    """Il testo di un articolo con i riferimenti a quello precedente e successivo."""
    trovata = normativa.scheda(norma_id)
    if not trovata:
        _not_found("Articolo")
    return trovata


@api.get("/normativa/cerca")
def cerca_normativa(q: str, k: int = 12):
    """Cerca negli articoli di legge, restituendo al massimo 30 risultati."""
    return {"query": q, "risultati": normativa.cerca(q, k=min(k, 30))}


@api.get("/cases/{case_id}/conversations")
def list_conversations(case_id: int):
    """Le conversazioni del fascicolo, dalla più recente."""
    with db.session() as conn:
        conversations = db.rows(conn.execute("""
            SELECT c.id, c.kind, c.title, c.created_at,
                   (SELECT MAX(created_at) FROM messages m WHERE m.conversation_id = c.id) AS updated_at,
                   (SELECT COUNT(*) FROM messages m WHERE m.conversation_id = c.id AND m.role = 'user') AS domande,
                   (SELECT content FROM messages m WHERE m.conversation_id = c.id AND m.role = 'assistant'
                    ORDER BY m.id DESC LIMIT 1) AS ultima_risposta,
                   (SELECT meta FROM messages m WHERE m.conversation_id = c.id AND m.role = 'assistant'
                    ORDER BY m.id DESC LIMIT 1) AS meta
            FROM conversations c WHERE c.case_id = ? ORDER BY COALESCE(updated_at, c.created_at) DESC""", (case_id,)))
    for c in conversations:
        c["meta"] = json.loads(c["meta"] or "{}")
    return conversations


@api.get("/conversations/{conversation_id}")
def get_conversation(conversation_id: int):
    """Una conversazione con tutti i messaggi."""
    with db.session() as conn:
        conversation = db.one(conn.execute("SELECT * FROM conversations WHERE id = ?", (conversation_id,)))
        if not conversation:
            _not_found("Conversazione")
        conversation["messages"] = db.get_messages(conn, conversation_id)
    return conversation


@api.delete("/conversations/{conversation_id}")
def delete_conversation(conversation_id: int):
    """Elimina una conversazione."""
    with db.session() as conn:
        if not conn.execute("DELETE FROM conversations WHERE id = ?", (conversation_id,)).rowcount:
            _not_found("Conversazione")
    return {"ok": True}


# --- Riassunto, estrazione, bozze, confronto -----------------------------------

class DocumentIn(BaseModel):
    document_id: int


class DraftIn(BaseModel):
    case_id: int
    doc_type: str = ""
    instructions: str
    template_id: int | None = None
    use_case_docs: bool = False


class CompareIn(BaseModel):
    document_a: int
    document_b: int


@api.post("/summarize")
def summarize(body: DocumentIn):
    """Riassunto di un documento."""
    return ndjson(features.summarize(body.document_id))


@api.post("/documents/{document_id}/extraction")
def start_extraction(document_id: int):
    """Mette in coda l'estrazione: gira in background e lascia sempre passare le domande."""
    with db.session() as conn:
        if not conn.execute("SELECT 1 FROM documents WHERE id = ?", (document_id,)).fetchone():
            _not_found("Documento")
        found = conn.execute("SELECT status FROM extractions WHERE document_id = ?", (document_id,)).fetchone()
    if not found or found[0] not in ("in attesa", "in corso"):
        jobs.enqueue(document_id)
    return {"ok": True}


@api.get("/documents/{document_id}/extraction")
def get_extraction(document_id: int):
    """I dati estratti da un documento."""
    with db.session() as conn:
        found = db.one(conn.execute("SELECT * FROM extractions WHERE document_id = ?", (document_id,)))
    if not found:
        return {"status": "non eseguita", "rows": []}
    return {**found, "rows": json.loads(found["rows"] or "[]")}


@api.post("/draft")
def draft(body: DraftIn):
    """Scrive una bozza."""
    return ndjson(features.draft(body.doc_type, body.instructions, body.case_id, body.template_id, body.use_case_docs))


@api.post("/compare")
def compare(body: CompareIn):
    """Differenze tra due documenti."""
    try:
        return features.compare(body.document_a, body.document_b)
    except documents.DocumentError as exc:
        raise HTTPException(404, str(exc))


@api.post("/compare/analyze")
def analyze_comparison(body: CompareIn):
    """Commento del modello alle differenze tra due documenti."""
    return ndjson(features.analyze_comparison(body.document_a, body.document_b))


class ExportIn(BaseModel):
    title: str
    text: str


class AnteprimaIn(BaseModel):
    text: str


@api.post("/export/anteprima")
def export_anteprima(body: AnteprimaIn):
    """La bozza impaginata come nel file Word, per mostrarla nella pagina."""
    return {"html": export.to_html(body.text)}


@api.post("/export/docx")
def export_docx(body: ExportIn):
    """Scarica un testo in formato Word."""
    name = re.sub(r'[\\/:*?"<>|]+', " ", body.title).strip() or "documento"
    return Response(
        export.to_docx(body.text),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(name)}.docx"},
    )


# --- Modelli di bozza -----------------------------------------------------------

class TemplateIn(BaseModel):
    name: str
    body: str


@api.get("/templates")
def list_templates():
    """I modelli dello studio, condivisi tra tutti i fascicoli."""
    with db.session() as conn:
        return db.rows(conn.execute("SELECT * FROM templates ORDER BY name COLLATE NOCASE"))


@api.post("/templates")
def create_template(template: TemplateIn):
    """Crea un modello. Il nome deve essere unico."""
    with db.session() as conn:
        if conn.execute("SELECT 1 FROM templates WHERE name = ?", (template.name.strip(),)).fetchone():
            raise HTTPException(409, f"Esiste già un modello chiamato «{template.name}»")
        cur = conn.execute("INSERT INTO templates (name, body) VALUES (?, ?)", (template.name.strip(), template.body))
        return {"id": cur.lastrowid}


@api.put("/templates/{template_id}")
def update_template(template_id: int, template: TemplateIn):
    """Modifica nome e testo di un modello."""
    with db.session() as conn:
        cur = conn.execute("UPDATE templates SET name = ?, body = ? WHERE id = ?",
                           (template.name.strip(), template.body, template_id))
        if not cur.rowcount:
            _not_found("Modello")
    return {"ok": True}


def _modello(template_id):
    """Il modello richiesto; se non esiste risponde 404."""
    with db.session() as conn:
        trovato = db.one(conn.execute("SELECT * FROM templates WHERE id = ?", (template_id,)))
    if not trovato:
        _not_found("Modello")
    return trovato


class ValoriIn(BaseModel):
    valori: dict[str, str] = {}


class CompilaIn(BaseModel):
    case_id: int
    instructions: str = ""
    use_case_docs: bool = False
    valori: dict[str, str] = {}


def _scaricabile(contenuto, tipo, nome, estensione):
    """Risposta HTTP che il browser salva come file, con un nome privo di caratteri non validi."""
    nome = re.sub(r'[\\/:*?"<>|]+', " ", nome).strip() or "documento"
    return Response(contenuto, media_type=tipo,
                    headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(nome)}.{estensione}"})


@api.get("/templates/{template_id}/campi")
def campi_modello(template_id: int):
    """I campi da compilare di un modello."""
    modello = _modello(template_id)
    return {"campi": modelli.campi(modello["body"])}


@api.post("/templates/{template_id}/anteprima")
def anteprima_modello(template_id: int, body: ValoriIn):
    """Anteprima HTML del modello con i valori inseriti."""
    return {"html": modelli.anteprima(_modello(template_id)["body"], body.valori)}


@api.post("/templates/{template_id}/pdf")
def pdf_modello(template_id: int, body: ValoriIn):
    """Scarica il modello come PDF compilabile."""
    modello = _modello(template_id)
    return _scaricabile(modelli.pdf(modello["body"], body.valori, modello["name"]), "application/pdf", modello["name"], "pdf")


@api.post("/templates/{template_id}/docx")
def docx_modello(template_id: int, body: ValoriIn):
    """Scarica il modello compilato in formato Word."""
    modello = _modello(template_id)
    return _scaricabile(modelli.docx(modello["body"], body.valori),
                        "application/vnd.openxmlformats-officedocument.wordprocessingml.document", modello["name"], "docx")


@api.post("/templates/{template_id}/compila")
def compila_modello(template_id: int, body: CompilaIn):
    """Compila con il modello linguistico i campi di un modello dello studio."""
    modello = _modello(template_id)
    return ndjson(modelli.compila_ia(modello["body"], modello["name"], body.instructions, body.case_id,
                                     body.use_case_docs, body.valori))


@api.delete("/templates/{template_id}")
def delete_template(template_id: int):
    """Elimina un modello dello studio."""
    with db.session() as conn:
        if not conn.execute("DELETE FROM templates WHERE id = ?", (template_id,)).rowcount:
            _not_found("Modello")
    return {"ok": True}


app.include_router(api)
# Le pagine dell'interfaccia: montate per ultime, così non coprono le rotte /api.
app.mount("/", StaticFiles(directory=config.FRONTEND_DIR, html=True), name="frontend")
