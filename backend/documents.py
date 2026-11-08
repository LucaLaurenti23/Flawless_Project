"""Lettura dei documenti (PDF con PyMuPDF, Word, testo), suddivisione in frammenti e indicizzazione."""
import re
import shutil
import uuid
from pathlib import Path

import docx
import pymupdf

from . import config, db, llm, ocr, sicurezza

SUPPORTED = {".pdf", ".docx", ".txt", ".md"}


class DocumentError(Exception):
    pass


def _clean(text):
    """Ricompone il testo di un PDF: unisce le parole spezzate a fine riga e toglie gli spazi superflui."""
    text = re.sub(r"-\n(\w)", r"\1", text)  # parole spezzate a fine riga
    text = re.sub(r"\s*\n\s*", " ", text)
    return re.sub(r"[ \t]+", " ", text).strip()


def extract_pages(path):
    """Restituisce [(numero_pagina | None, [paragrafi])]. I file Word non hanno pagine: numero None."""
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        pages = []
        riconosciute = ocr.testi(path)
        with pymupdf.open(path) as pdf:
            for number, page in enumerate(pdf, start=1):
                # I blocchi di testo di PyMuPDF corrispondono, in pratica, ai paragrafi.
                blocks = page.get_text("blocks", sort=True)
                paragraphs = [_clean(b[4]) for b in blocks if b[6] == 0]
                if number in riconosciute:   # pagina scansionata: vale il testo letto con l'OCR
                    paragraphs = [_clean(b) for b in riconosciute[number]]
                pages.append((number, [p for p in paragraphs if p]))
        return pages
    if suffix == ".docx":
        document = docx.Document(path)
        paragraphs = [p.text.strip() for p in document.paragraphs if p.text.strip()]
        for table in document.tables:
            for row in table.rows:
                cells = " | ".join(c.text.strip() for c in row.cells if c.text.strip())
                if cells:
                    paragraphs.append(cells)
        return [(None, paragraphs)]
    if suffix in (".txt", ".md"):
        text = path.read_text(encoding="utf-8", errors="replace")
        parts = re.split(r"\n\s*\n", text)
        if len(parts) == 1:
            parts = text.splitlines()
        return [(None, [_clean(p) for p in parts if p.strip()])]
    raise DocumentError(f"Formato non supportato: {suffix}. Formati ammessi: {', '.join(sorted(SUPPORTED))}")


def page_label(page):
    """Etichetta per le citazioni: "p. 3", oppure "testo" per i file senza pagine."""
    return f"p. {page}" if page else "testo"


def pages_text(path):
    """Testo pagina per pagina, per mostrare il documento nell'interfaccia."""
    return [{"page": page, "text": "\n\n".join(paragraphs)} for page, paragraphs in extract_pages(path)]


def full_text(path):
    """Testo completo con i marcatori di pagina, così il modello può indicare dove ha trovato un dato."""
    out = []
    for page, paragraphs in extract_pages(path):
        if page:
            out.append(f"[Pagina {page}]")
        out.extend(paragraphs)
    return "\n".join(out)


def split_sections(text, size=None):
    """Divide un testo lungo in sezioni di circa `size` caratteri, spezzando solo tra una riga e l'altra."""
    size = size or config.SECTION_CHARS
    sections, current, length = [], [], 0
    for line in text.split("\n"):
        if length + len(line) > size and current:
            sections.append("\n".join(current))
            current, length = [], 0
        current.append(line)
        length += len(line) + 1
    if current:
        sections.append("\n".join(current))
    return sections


def chunk_pages(pages):
    """Frammenti per la ricerca. Un frammento non supera mai il confine di pagina, così la citazione è esatta."""
    size, overlap = config.CHUNK_CHARS, config.CHUNK_OVERLAP
    chunks = []
    for page, paragraphs in pages:
        current = ""
        for paragraph in paragraphs:
            while len(paragraph) > size:  # paragrafo troppo lungo: lo si taglia a pezzi sovrapposti
                if current:
                    chunks.append((page, current))
                    current = ""
                chunks.append((page, paragraph[:size]))
                paragraph = paragraph[size - overlap:]
            if len(current) + len(paragraph) + 1 > size and current:
                chunks.append((page, current))
                current = current[-overlap:] + " " + paragraph
            else:
                current = f"{current}\n{paragraph}" if current else paragraph
        if current.strip():
            chunks.append((page, current))
    return chunks


def ingest(case_id, filename, source_path):
    """Archivia e indicizza un documento. È un generatore di eventi di avanzamento per l'interfaccia."""
    suffix = Path(filename).suffix.lower()
    if suffix not in SUPPORTED:
        raise DocumentError(f"Formato non supportato: {suffix}. Formati ammessi: {', '.join(sorted(SUPPORTED))}")

    case_dir = config.FILES_DIR / str(case_id)
    case_dir.mkdir(parents=True, exist_ok=True)
    stored = case_dir / f"{uuid.uuid4().hex[:8]}_{Path(filename).name}"
    shutil.copyfile(source_path, stored)

    try:
        pagine_ocr = (yield from ocr.riconosci(stored)) if suffix == ".pdf" else 0
        yield {"type": "status", "text": f"Lettura di {filename}…"}
        pages = extract_pages(stored)
        chars = sum(len(p) for _, paragraphs in pages for p in paragraphs)
        numbered = [p for p, _ in pages if p]
        page_count = len(numbered) or None
        if not chars and suffix != ".pdf":   # un PDF senza testo è una scansione: resta, con l'avviso qui sotto
            raise DocumentError(f"Il file {Path(filename).name} è vuoto: non c'è niente da leggere.")

        warning = ""
        if suffix == ".pdf" and page_count and chars < 50 * page_count:
            warning = ("Il PDF contiene pochissimo testo: probabilmente è una scansione. "
                       "Senza testo riconoscibile il contenuto non può essere cercato né riassunto.")
        if pagine_ocr:
            warning = f"{warning} {ocr.avviso(pagine_ocr)}".strip()
        # possibile prompt injection indiretta: il documento dà ordini all'assistente
        if any(sicurezza.rileva(p) for _, paragraphs in pages for p in paragraphs):
            warning = f"{warning} {sicurezza.AVVISO_DOCUMENTO}".strip()

        chunks = chunk_pages(pages)
        vectors = []
        for start in range(0, len(chunks), llm.EMBED_BATCH):
            yield {"type": "status", "text": f"Indicizzazione {filename}: {start}/{len(chunks)} frammenti…"}
            vectors.extend(llm.embed([text for _, text in chunks[start:start + llm.EMBED_BATCH]]))

        with db.session() as conn:
            cur = conn.execute(
                "INSERT INTO documents (case_id, filename, path, pages, chars, warning) VALUES (?, ?, ?, ?, ?, ?)",
                (case_id, Path(filename).name, str(stored), page_count, chars, warning),
            )
            document_id = cur.lastrowid
            conn.executemany(
                "INSERT INTO chunks (document_id, page, text, embedding) VALUES (?, ?, ?, ?)",
                [(document_id, page, text, db.to_blob(v)) for (page, text), v in zip(chunks, vectors)],
            )
        yield {"type": "result", "document_id": document_id, "chunks": len(chunks), "warning": warning}
    except Exception:
        remove_file(stored)
        raise


def get_document(conn, document_id):
    """La riga del documento; se non esiste solleva DocumentError."""
    document = db.one(conn.execute("SELECT * FROM documents WHERE id = ?", (document_id,)))
    if not document:
        raise DocumentError(f"Documento {document_id} non trovato")
    return document


def delete_document(conn, document_id):
    """Cancella il documento dall'archivio e il suo file dal disco."""
    document = get_document(conn, document_id)
    conn.execute("DELETE FROM documents WHERE id = ?", (document_id,))
    remove_file(document["path"])


def remove_file(path):
    """Cancella dal disco un documento e il testo riconosciuto con l'OCR."""
    Path(path).unlink(missing_ok=True)
    ocr.elimina(path)
