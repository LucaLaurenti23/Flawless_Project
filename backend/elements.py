"""Elementi del fascicolo (parti, date, scadenze, importi) raccolti dalle estrazioni dei documenti, e ricerca testuale."""
import json
import re
from datetime import date

from . import db

MONTHS = {m: i for i, m in enumerate(
    ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio", "agosto",
     "settembre", "ottobre", "novembre", "dicembre"], start=1)}

KINDS = {"Parte": "parti", "Data": "date", "Scadenza": "scadenze", "Importo": "importi"}


def parse_date(text):
    """Data in formato ISO se il testo ne contiene una riconoscibile (12/03/2026, 12.3.26, 12 marzo 2026)."""
    text = str(text).lower()
    match = re.search(r"\b(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{2,4})\b", text)
    if match:
        day, month, year = (int(g) for g in match.groups())
    else:
        match = re.search(r"\b(\d{1,2})(?:°|º)?\s+(" + "|".join(MONTHS) + r")\s+(\d{4})\b", text)
        if not match:
            return None
        day, month, year = int(match.group(1)), MONTHS[match.group(2)], int(match.group(3))
    if year < 100:
        year += 2000
    try:
        return date(year, month, day).isoformat()
    except ValueError:
        return None


def _key(text):
    """Forma semplificata di un testo, per riconoscere la stessa voce scritta in modi diversi."""
    return re.sub(r"[^\w]+", " ", str(text).lower()).strip()


def case_elements(case_id):
    """Parti, date, scadenze e importi estratti dai documenti del fascicolo, senza doppioni, con l'elenco dei documenti."""
    with db.session() as conn:
        found = db.rows(conn.execute("""
            SELECT d.id AS document_id, d.filename, e.status, e.rows, e.error
            FROM documents d LEFT JOIN extractions e ON e.document_id = d.id
            WHERE d.case_id = ? ORDER BY d.id""", (case_id,)))

    result = {kind: [] for kind in KINDS.values()}
    parties = {}
    documents = []
    for doc in found:
        rows = json.loads(doc["rows"] or "[]")
        kind_of = next((r["valore"] for r in rows if r["categoria"] == "Tipo di documento"), "")
        documents.append({"id": doc["document_id"], "filename": doc["filename"], "tipo": kind_of,
                          "estrazione": doc["status"] or "non eseguita", "errore": doc["error"] or "",
                          "numeri_ruolo": [r["valore"] for r in rows if r["categoria"] == "Numero di ruolo"],
                          "autorita": next((r["valore"] for r in rows if r["categoria"] == "Autorità giudiziaria"), "")})
        source = {"document_id": doc["document_id"], "filename": doc["filename"]}
        for row in rows:
            kind = KINDS.get(row["categoria"])
            if not kind:
                continue
            verified = row["nel_testo"] == "sì"
            if kind == "parti":
                # La stessa parte compare in più documenti: una voce sola, con tutti i ruoli e le fonti.
                party = parties.setdefault(_key(row["valore"]), {
                    "nome": row["valore"], "ruoli": [], "fonti": [], "verificato": False})
                if row["dettaglio"] and row["dettaglio"] not in party["ruoli"]:
                    party["ruoli"].append(row["dettaglio"])
                party["fonti"].append({**source, "pagina": row["pagina"]})
                party["verificato"] = party["verificato"] or verified
            else:
                result[kind].append({"valore": row["valore"], "dettaglio": row["dettaglio"], "pagina": row["pagina"],
                                     "verificato": verified, "data_iso": parse_date(row["valore"]), **source})
    result["parti"] = sorted(parties.values(), key=lambda p: (-len(p["fonti"]), p["nome"].lower()))
    for kind in ("date", "scadenze"):
        result[kind].sort(key=lambda e: (e["data_iso"] is None, e["data_iso"] or "", e["valore"]))
    return {"elementi": result, "documenti": documents}


def search(case_id, query, context=180):
    """Ricerca testuale (non semantica): i passaggi dei documenti che contengono la parola cercata."""
    query = query.strip()
    if not query:
        return []
    with db.session() as conn:
        found = conn.execute("""
            SELECT c.document_id, c.page, c.text, d.filename FROM chunks c JOIN documents d ON d.id = c.document_id
            WHERE d.case_id = ? AND instr(lower(c.text), lower(?)) > 0 ORDER BY c.document_id, c.id""",
                             (case_id, query)).fetchall()
    documents, seen = {}, set()
    pattern = re.compile(re.escape(query), re.IGNORECASE)
    for row in found:
        doc = documents.setdefault(row["document_id"], {"id": row["document_id"], "filename": row["filename"],
                                                        "brani": []})
        for match in pattern.finditer(row["text"]):
            start, end = max(0, match.start() - context), min(len(row["text"]), match.end() + context)
            snippet = row["text"][start:end]
            # i frammenti si sovrappongono: lo stesso passaggio si mostra una volta sola
            key = (row["document_id"], row["page"], row["text"][max(0, match.start() - 40):match.end() + 40])
            if key in seen:
                continue
            seen.add(key)
            doc["brani"].append({"page": row["page"], "testo": ("…" if start else "") + snippet
                                 + ("…" if end < len(row["text"]) else "")})
    return list(documents.values())
