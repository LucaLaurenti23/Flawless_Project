"""Riassunto, estrazione di dati chiave, bozze da modello e confronto tra versioni."""
import difflib
import json
import re
from datetime import date

from . import config, controlli, db, llm, ocr, rag, sicurezza
from .documents import extract_pages, full_text, get_document, page_label, split_sections

LEGAL_SYSTEM = ("Sei un assistente per uno studio legale italiano. Scrivi in italiano preciso e professionale.\n\n"
                + sicurezza.REGOLE)


def _documento(testo):
    """Testo di un documento per il prompt: recintato e con gli eventuali passaggi sospetti segnalati."""
    return sicurezza.recinta(sicurezza.marca(testo))


def _load(document_id):
    """Il documento richiesto; se non esiste solleva DocumentError."""
    with db.session() as conn:
        return get_document(conn, document_id)


def _require_text(document, text):
    """Interrompe con un messaggio chiaro se il documento non ha testo leggibile."""
    if not text.replace("[Pagina", "").strip():
        raise ValueError(f"{document['filename']} non contiene testo leggibile (forse è una scansione senza OCR).")


# --- Riassunto ----------------------------------------------------------------

SUMMARY_FORMAT = """Usa questa struttura (ometti le voci che non sono pertinenti):
**Tipo di documento**
**Parti coinvolte** (con il loro ruolo)
**Fatti principali**
**Questioni giuridiche e richieste**
**Decisione o esito** (se presente)
**Date e scadenze rilevanti**
Non aggiungere valutazioni o consigli: riporta solo ciò che il documento dice.
Indica tra parentesi le pagine di riferimento, ad esempio (p. 3), ricavandole dai marcatori [Pagina N].
Non aggiungere informazioni che non sono nel testo: in particolare non citare articoli di legge,
norme o sentenze che il documento non menziona espressamente."""


def summarize(document_id):
    """Riassunto strutturato di un documento, trasmesso a eventi. I documenti lunghi si riassumono a sezioni."""
    document = _load(document_id)
    text = full_text(document["path"])
    _require_text(document, text)
    sections = split_sections(text)

    if len(sections) == 1:
        material = f"Documento: {document['filename']}\n\n{text}"
    else:
        # Documento lungo: prima si riassume ogni sezione, poi si fondono i riassunti parziali.
        partials = []
        for i, section in enumerate(sections, start=1):
            yield {"type": "status", "text": f"Lettura sezione {i} di {len(sections)}…"}
            partials.append(llm.complete([
                {"role": "system", "content": LEGAL_SYSTEM},
                {"role": "user", "content": (
                    f"Questa è la sezione {i} di {len(sections)} del documento {document['filename']}. "
                    "Riassumila in modo dettagliato conservando nomi, ruoli, date, importi, richieste "
                    f"e i riferimenti di pagina [Pagina N].\n\n{_documento(section)}\n\n{sicurezza.PROMEMORIA}"
                )},
            ]))
        material = (f"Riassunti parziali delle {len(sections)} sezioni del documento {document['filename']}:\n\n"
                    + "\n\n".join(f"--- Sezione {i} ---\n{p}" for i, p in enumerate(partials, start=1)))

    yield {"type": "status", "text": "Stesura del riassunto…"}
    riassunto = ""
    for token in llm.chat_stream([
        {"role": "system", "content": LEGAL_SYSTEM},
        {"role": "user", "content": f"Riassumi il seguente documento legale.\n{SUMMARY_FORMAT}\n\n"
                                    f"{_documento(material)}\n\n{sicurezza.PROMEMORIA}"},
    ], max_tokens=config.MAX_LONG_TOKENS):
        riassunto += token
        yield {"type": "token", "text": token}
    avvisi = []
    assenti = controlli.non_nel_testo(riassunto, text)
    if assenti:
        avvisi.append(f"Riferimenti o cifre non presenti nel documento: {', '.join(assenti)}. Verificali.")
    if ocr.MARCATORE in (document["warning"] or ""):
        avvisi.append("Documento letto con l'OCR: cifre, date e nomi possono contenere errori di lettura. Controllali sull'atto.")
    if avvisi:
        yield {"type": "avviso", "testi": avvisi}


# --- Estrazione di dati chiave -----------------------------------------------

def _items(*fields):
    """Schema JSON di un elenco di oggetti con questi campi di testo più la pagina."""
    fields = [*fields, "pagina"]
    return {"type": "array", "items": {
        "type": "object",
        "properties": {name: {"type": "string"} for name in fields},
        "required": fields,
    }}


EXTRACT_SCHEMA = {
    "type": "object",
    "properties": {
        "tipo_documento": {"type": "string"},
        "autorita_giudiziaria": {"type": "string"},
        "numeri_ruolo": {"type": "array", "items": {"type": "string"}},
        "parti": _items("nome", "ruolo"),
        "date": _items("data", "descrizione"),
        "scadenze": _items("data", "descrizione"),
        "importi": _items("importo", "descrizione"),
    },
    "required": ["tipo_documento", "autorita_giudiziaria", "numeri_ruolo", "parti", "date", "scadenze", "importi"],
}

EXTRACT_PROMPT = """Estrai dal documento legale i dati richiesti e rispondi solo con JSON.
- tipo_documento: es. contratto, sentenza, atto di citazione, decreto ingiuntivo, diffida.
- autorita_giudiziaria: il giudice o tribunale, se presente, altrimenti stringa vuota.
- numeri_ruolo: numeri di R.G., ruolo o protocollo.
- parti: persone fisiche o giuridiche coinvolte e il loro ruolo (attore, convenuto, locatore, ecc.).
- date: date rilevanti con cosa è avvenuto.
- scadenze: termini e scadenze future o da rispettare.
- importi: somme di denaro con la loro causale.
Per "pagina" usa il numero del marcatore [Pagina N] più vicino precedente, oppure stringa vuota.
Riporta i valori esattamente come scritti nel testo. Non inventare nulla: se un dato manca, lascia vuoto o lista vuota."""

# (chiave nel JSON, etichetta, campo valore, campo dettaglio)
EXTRACT_ROWS = [
    ("parti", "Parte", "nome", "ruolo"),
    ("date", "Data", "data", "descrizione"),
    ("scadenze", "Scadenza", "data", "descrizione"),
    ("importi", "Importo", "importo", "descrizione"),
]


def _normalize(text):
    """Testo minuscolo con spazi uniformi, per confrontare due scritture dello stesso dato."""
    return re.sub(r"\s+", " ", str(text)).strip().lower()


def extract(document_id):
    """Estrae i dati chiave sezione per sezione. Un dato che non compare alla lettera nel testo resta "da verificare"."""
    document = _load(document_id)
    text = full_text(document["path"])
    _require_text(document, text)
    sections = split_sections(text, config.EXTRACT_SECTION_CHARS)

    merged = {"tipo_documento": "", "autorita_giudiziaria": "", "numeri_ruolo": [],
              "parti": [], "date": [], "scadenze": [], "importi": []}
    for i, section in enumerate(sections, start=1):
        yield {"type": "status", "text": f"Estrazione dati: sezione {i} di {len(sections)}…"}
        raw = llm.complete([
            {"role": "system", "content": LEGAL_SYSTEM},
            {"role": "user", "content": f"{EXTRACT_PROMPT}\n\nDocumento:\n{_documento(section)}\n\n{sicurezza.PROMEMORIA}"},
        ], format=EXTRACT_SCHEMA)
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        for key in ("tipo_documento", "autorita_giudiziaria"):
            if not merged[key] and data.get(key):
                merged[key] = data[key]
        for key in ("numeri_ruolo", "parti", "date", "scadenze", "importi"):
            for item in data.get(key) or []:
                if item and item not in merged[key]:
                    merged[key].append(item)

    # Controllo anti-invenzione: il valore estratto compare davvero nel documento?
    haystack = _normalize(text)

    def found(value):
        return "sì" if value and _normalize(value) in haystack else "da verificare"

    def page_number(item):
        digits = re.search(r"\d+", str(item.get("pagina", "")))
        return digits.group() if digits else ""

    result_rows = []
    for key, label in (("tipo_documento", "Tipo di documento"), ("autorita_giudiziaria", "Autorità giudiziaria")):
        if merged[key]:
            result_rows.append({"categoria": label, "valore": merged[key], "dettaglio": "", "pagina": "",
                                "nel_testo": found(merged[key])})
    for number in merged["numeri_ruolo"]:
        result_rows.append({"categoria": "Numero di ruolo", "valore": number, "dettaglio": "", "pagina": "",
                            "nel_testo": found(number)})
    for key, label, value_field, detail_field in EXTRACT_ROWS:
        for item in merged[key]:
            value = item.get(value_field, "")
            if not value:
                continue
            result_rows.append({"categoria": label, "valore": value, "dettaglio": item.get(detail_field, ""),
                                "pagina": page_number(item), "nel_testo": found(value)})

    # Salvati: alimentano gli elementi del fascicolo e lo scadenzario.
    with db.session() as conn:
        db.save_extraction(conn, document_id, "fatto", result_rows)
    yield {"type": "result", "rows": result_rows, "data": merged}


# --- Bozze da modello ---------------------------------------------------------

MESI = ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio", "agosto", "settembre",
        "ottobre", "novembre", "dicembre"]


def _data_italiana(giorno):
    """Una data in forma estesa, per esempio 5 marzo 2026."""
    return f"{giorno.day} {MESI[giorno.month - 1]} {giorno.year}"


DRAFT_SYSTEM = ("Sei un avvocato italiano esperto nella redazione di atti e lettere. "
                "Scrivi in italiano giuridico formale, chiaro e corretto.\n\n" + sicurezza.REGOLE)


# Il modello a volte aggiunge in coda "Note operative": ripetono le sue istruzioni e finirebbero nel documento.
RE_NOTE_FINALI = re.compile(r"\s*\**\s*(?:note?\s+(?:operativ\w+|per\s+l.avvocato|di\s+redazione|alla\s+bozza)|commenti?)\b", re.IGNORECASE)
# Rimando numerato a una fonte, come " [1]".
RE_RIMANDO = re.compile(r"\s*\[\d{1,2}\]")


def _solo_bozza(flusso):
    """Il testo della bozza riga per riga, senza i rimandi [1] agli estratti e fermandosi alle note del modello."""
    resto = ""
    try:
        for token in flusso:
            resto += token
            while "\n" in resto:
                riga, resto = resto.split("\n", 1)
                if RE_NOTE_FINALI.match(riga):
                    return
                yield RE_RIMANDO.sub("", riga) + "\n"
        if resto and not RE_NOTE_FINALI.match(resto):
            yield RE_RIMANDO.sub("", resto)
    finally:
        flusso.close()


def _avvisi_bozza(testo, dati, destinatario):
    """Gli avvisi per l'avvocato: destinatario assente dalla bozza, riferimenti o cifre non presenti nei dati forniti."""
    avvisi = []
    testa = re.split(r"\bOggetto\b", testo, maxsplit=1, flags=re.IGNORECASE)[0][:600].lower()
    nome = re.sub(r"^(?:Sig\.ra|Sig\.|Dott\.ssa|Dott\.|Avv\.|Spett\.le)\s+", "", destinatario).split(" ")[0].lower()
    if nome and nome not in testa:
        avvisi.append(f"Destinatario: le istruzioni indicano {destinatario}, ma non compare in testa alla bozza. Controllalo.")
    assenti = controlli.non_nel_testo(testo, dati)
    if assenti:
        avvisi.append(f"Riferimenti o cifre non presenti nelle istruzioni né nei documenti: {', '.join(assenti)}. Verificali.")
    return avvisi


def draft(doc_type, instructions, case_id, template_id=None, use_case_docs=False):
    """Scrive una bozza dalle istruzioni, da un modello dello studio o dai documenti del fascicolo, trasmessa a eventi."""
    if sicurezza.rileva(f"{doc_type} {instructions}"):
        raise ValueError(sicurezza.RIFIUTO)
    parts, dati = [], [doc_type, instructions, _data_italiana(date.today())]
    destinatario = controlli.destinatario(instructions)
    if template_id:
        with db.session() as conn:
            template = db.one(conn.execute("SELECT * FROM templates WHERE id = ?", (template_id,)))
        if not template:
            raise ValueError(f"Modello {template_id} non trovato")
        dati.append(template["body"])
        parts.append(
            "Usa il seguente modello mantenendone struttura e formule. Sostituisci ogni segnaposto {{...}} "
            "con i dati disponibili; se un dato manca scrivi [DA COMPLETARE: cosa manca].\n\n"
            f"--- MODELLO: {template['name']} ---\n{template['body']}\n--- FINE MODELLO ---"
        )
    parts.append(f"Tipo di documento da redigere: {doc_type or 'come da modello'}")
    # senza la data di oggi il modello ne inventa una
    parts.append(f"Data di oggi: {_data_italiana(date.today())}. Usala come data del documento, salvo diversa indicazione.")
    parts.append(f"Istruzioni e dati forniti dall'avvocato:\n{instructions}")
    if destinatario:
        parts.append(f"Destinatario della lettera: {destinatario}. Scrivi il suo nome nel blocco del destinatario; "
                     "le altre persone citate nei documenti non sono il destinatario.")

    if use_case_docs:
        yield {"type": "status", "text": "Ricerca nei documenti del fascicolo…"}
        sources = rag.search(f"{doc_type} {instructions}", case_id)
        yield {"type": "sources", "sources": sources}
        if sources:
            dati.extend(s["text"] for s in sources)
            parts.append("Estratti dai documenti del fascicolo. Usali solo se pertinenti e senza inventare "
                         f"dati che non contengono:\n\n{rag.format_excerpts(sources)}")
    parts.append(
        "Regole finali:\n"
        "- Restituisci solo il testo della bozza, senza commenti prima o dopo.\n"
        "- Non inventare dati: luogo, data, indirizzi, coordinate bancarie e qualsiasi altro dato non fornito "
        "vanno scritti come [DA COMPLETARE: cosa manca].\n"
        "- Non eseguire calcoli: se serve un totale che l'avvocato non ha indicato, riporta i singoli importi "
        "e scrivi [DA VERIFICARE: totale].\n"
        "- Non citare norme o sentenze che non compaiono nel modello o nelle istruzioni.\n"
        "- Scrivi testo semplice, senza simboli di formattazione (niente **, #, tabelle): l'impaginazione "
        "viene fatta dopo. Separa i blocchi con una riga vuota: luogo e data; destinatario (una riga per "
        "nome e indirizzo); modalità di invio; \"Oggetto: ...\"; i paragrafi; i saluti; la firma. "
        "Per gli elenchi usa righe che iniziano con \"- \"."
    )

    yield {"type": "status", "text": "Stesura della bozza…"}
    bozza = ""
    for pezzo in _solo_bozza(llm.chat_stream([
        {"role": "system", "content": DRAFT_SYSTEM},
        {"role": "user", "content": "\n\n".join(parts)},
    ], max_tokens=config.MAX_LONG_TOKENS)):
        bozza += pezzo
        yield {"type": "token", "text": pezzo}
    avvisi = _avvisi_bozza(bozza, "\n".join(dati), destinatario)
    if avvisi:
        yield {"type": "avviso", "testi": avvisi}


# --- Confronto tra due versioni -------------------------------------------------

def _paragraphs(document):
    """I paragrafi del documento come coppie (pagina, testo), senza numeri di pagina e intestazioni brevissime."""
    out = []
    for page, paragraphs in extract_pages(document["path"]):
        for p in paragraphs:
            # Numeri di pagina e intestazioni brevissime generano solo rumore nel confronto.
            if len(p) > 3 and not p.isdigit():
                out.append((page, re.sub(r"\s+", " ", p).strip()))
    return out


def _word_diff(old, new):
    """Le differenze parola per parola tra due paragrafi: elenco di [equal|delete|insert, testo]."""
    a, b = old.split(" "), new.split(" ")
    segments = []
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if op == "equal":
            segments.append(["equal", " ".join(a[i1:i2])])
        if op in ("delete", "replace"):
            segments.append(["delete", " ".join(a[i1:i2])])
        if op in ("insert", "replace"):
            segments.append(["insert", " ".join(b[j1:j2])])
    return segments


def compare(document_a, document_b):
    """Confronta due documenti paragrafo per paragrafo: blocchi di differenze e statistiche. Non usa il modello."""
    a_doc, b_doc = _load(document_a), _load(document_b)
    a, b = _paragraphs(a_doc), _paragraphs(b_doc)
    matcher = difflib.SequenceMatcher(None, [t for _, t in a], [t for _, t in b], autojunk=False)

    blocks, stats = [], {"aggiunti": 0, "rimossi": 0, "modificati": 0, "invariati": 0}

    def removed(item):
        stats["rimossi"] += 1
        blocks.append({"op": "delete", "page_a": item[0], "text": item[1]})

    def added(item):
        stats["aggiunti"] += 1
        blocks.append({"op": "insert", "page_b": item[0], "text": item[1]})

    for op, i1, i2, j1, j2 in matcher.get_opcodes():
        if op == "equal":
            stats["invariati"] += i2 - i1
            blocks.append({"op": "equal", "count": i2 - i1})
        elif op == "delete":
            for item in a[i1:i2]:
                removed(item)
        elif op == "insert":
            for item in b[j1:j2]:
                added(item)
        else:
            old, new = a[i1:i2], b[j1:j2]
            for (page_a, old_text), (page_b, new_text) in zip(old, new):
                # Paragrafi troppo diversi: meglio mostrarli come rimosso + aggiunto che come modifica.
                if difflib.SequenceMatcher(None, old_text, new_text).quick_ratio() < 0.4:
                    removed((page_a, old_text))
                    added((page_b, new_text))
                    continue
                stats["modificati"] += 1
                blocks.append({"op": "replace", "page_a": page_a, "page_b": page_b,
                               "segments": _word_diff(old_text, new_text)})
            for item in old[len(new):]:
                removed(item)
            for item in new[len(old):]:
                added(item)

    return {"a": a_doc["filename"], "b": b_doc["filename"], "stats": stats, "blocks": blocks}


MAX_CHANGES_CHARS = 14000


def _describe_changes(result):
    """Le differenze in forma di testo per il modello, con il limite di lunghezza e l'indicazione se è stato applicato."""
    lines = []
    for block in result["blocks"]:
        if block["op"] == "delete":
            lines.append(f"RIMOSSO ({page_label(block['page_a'])} versione A): {block['text']}")
        elif block["op"] == "insert":
            lines.append(f"AGGIUNTO ({page_label(block['page_b'])} versione B): {block['text']}")
        elif block["op"] == "replace":
            old = " ".join(t for op, t in block["segments"] if op != "insert")
            new = " ".join(t for op, t in block["segments"] if op != "delete")
            lines.append(f"MODIFICATO ({page_label(block['page_b'])} versione B):\n  PRIMA: {old}\n  DOPO: {new}")
    text = "\n\n".join(lines)
    truncated = len(text) > MAX_CHANGES_CHARS
    return text[:MAX_CHANGES_CHARS], truncated


def analyze_comparison(document_a, document_b):
    """Commento del modello alle differenze sostanziali tra due versioni di un documento, trasmesso a eventi."""
    yield {"type": "status", "text": "Confronto dei testi…"}
    result = compare(document_a, document_b)
    changes, truncated = _describe_changes(result)
    if not changes:
        yield {"type": "token", "text": "Le due versioni non presentano differenze nel testo."}
        return
    if truncated:
        yield {"type": "token", "text": "⚠ Le modifiche sono molte: l'analisi considera solo la prima parte.\n\n"}
    yield {"type": "status", "text": "Analisi delle modifiche…"}
    for token in llm.chat_stream([
        {"role": "system", "content": LEGAL_SYSTEM},
        {"role": "user", "content": (
            f"Ecco le differenze tra la versione A ({result['a']}) e la versione B ({result['b']}) "
            "di un documento legale. Per ogni modifica sostanziale spiega cosa cambia e quale impatto "
            "giuridico può avere per le parti. Metti in evidenza all'inizio le modifiche più rischiose. "
            "Ignora le modifiche puramente formali o di punteggiatura. Basati solo sul testo fornito.\n\n"
            f"{_documento(changes)}\n\n{sicurezza.PROMEMORIA}"
        )},
    ], max_tokens=config.MAX_LONG_TOKENS):
        yield {"type": "token", "text": token}
