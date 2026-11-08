"""Riconoscimento del testo (OCR) nelle pagine scansionate dei PDF.

Il file caricato non viene modificato: il testo riconosciuto si salva accanto, in <file>.ocr.json, così l'OCR si fa una
volta sola e chi legge il documento lo ritrova senza rifarlo. I PDF con testo vero non passano da qui."""
import json
import logging
from pathlib import Path

import pymupdf

from . import config

log = logging.getLogger("law_prog")

CARTELLA_LINGUE = config.ROOT / "tessdata"
LINGUA = "ita"
MIN_CARATTERI = 50   # sotto questa soglia una pagina con un'immagine si considera scansionata
RESA_DPI = 300       # risoluzione consigliata per Tesseract: le scansioni più povere vengono ingrandite
MARCATORE = "riconosciuto con OCR"   # compare nell'avviso del documento e serve a riconoscerlo in seguito


def disponibile():
    """Il file della lingua italiana è presente?"""
    return (CARTELLA_LINGUE / f"{LINGUA}.traineddata").exists()


def _file_testi(path):
    """Dove si salva il testo riconosciuto di un documento."""
    return Path(f"{path}.ocr.json")


def _da_riconoscere(pdf):
    """Gli indici delle pagine che hanno un'immagine e quasi nessun testo."""
    return [i for i, pagina in enumerate(pdf) if len(pagina.get_text().strip()) < MIN_CARATTERI and pagina.get_images()]


def _riconosci_pagina(pagina):
    """I blocchi di testo riconosciuti in una pagina."""
    # L'immagine deve essere a colori: in scala di grigi la libreria restituisce una pagina vuota, senza dare errore.
    immagine = pagina.get_pixmap(dpi=RESA_DPI, colorspace=pymupdf.csRGB, alpha=False)
    with pymupdf.open("pdf", immagine.pdfocr_tobytes(language=LINGUA, tessdata=str(CARTELLA_LINGUE))) as risultato:
        return [b[4] for b in risultato[0].get_text("blocks", sort=True) if b[6] == 0 and b[4].strip()]


def riconosci(path):
    """Esegue l'OCR sulle pagine scansionate, trasmettendo l'avanzamento. Restituisce quante pagine ha letto.
    Una pagina che non si riesce a leggere non blocca il caricamento: resta senza testo."""
    if not disponibile():
        log.warning("OCR non disponibile: manca %s.traineddata in %s", LINGUA, CARTELLA_LINGUE)
        return 0
    testi = {}
    with pymupdf.open(path) as pdf:
        indici = _da_riconoscere(pdf)
        for fatte, indice in enumerate(indici, start=1):
            yield {"type": "status", "text": f"Riconoscimento del testo (OCR): pagina {fatte} di {len(indici)}…"}
            try:
                blocchi = _riconosci_pagina(pdf[indice])
            except Exception:
                log.exception("OCR non riuscito a pagina %s di %s", indice + 1, path)
                continue
            if blocchi:
                testi[indice + 1] = blocchi
    if testi:
        _file_testi(path).write_text(json.dumps(testi, ensure_ascii=False), encoding="utf-8")
    return len(testi)


def testi(path):
    """Il testo riconosciuto di un documento: {numero di pagina: [blocchi]}. Vuoto se l'OCR non è servito."""
    file = _file_testi(path)
    if not file.exists():
        return {}
    return {int(pagina): blocchi for pagina, blocchi in json.loads(file.read_text(encoding="utf-8")).items()}


def elimina(path):
    """Cancella il testo riconosciuto di un documento, se esiste."""
    _file_testi(path).unlink(missing_ok=True)


def avviso(pagine):
    """L'avviso da mostrare per un documento letto in parte con l'OCR."""
    return (f"Testo {MARCATORE} ({pagine} pagine scansionate): cifre, date e nomi possono contenere errori di lettura. "
            "Controllali sull'atto.")
