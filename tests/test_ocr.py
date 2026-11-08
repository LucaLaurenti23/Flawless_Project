"""OCR delle pagine scansionate, sul vero motore di riconoscimento. Non serve Ollama: gli embedding sono simulati."""
import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np
import pymupdf

from backend import config, db, documents, ocr

FRASE = "Il canone annuo di locazione ammonta a euro 24.000"


def _pagina_digitale(pdf):
    """Una pagina con testo vero."""
    pagina = pdf.new_page()
    pagina.insert_text((50, 100), FRASE, fontsize=14)
    pagina.insert_text((50, 130), "Secondo capoverso con testo selezionabile, sufficiente a superare la soglia.", fontsize=11)


def pdf_digitale(percorso):
    """Crea un PDF con testo vero."""
    with pymupdf.open() as pdf:
        _pagina_digitale(pdf)
        pdf.save(percorso)


def pdf_scansionato(percorso, grigi=True):
    """Crea un PDF di sole immagini, come quello che esce da uno scanner."""
    with pymupdf.open() as origine, pymupdf.open() as scansione:
        _pagina_digitale(origine)
        immagine = origine[0].get_pixmap(dpi=200, colorspace=pymupdf.csGRAY if grigi else pymupdf.csRGB)
        pagina = scansione.new_page(width=origine[0].rect.width, height=origine[0].rect.height)
        pagina.insert_image(pagina.rect, pixmap=immagine)
        scansione.save(percorso)


def consuma(generatore):
    """Esegue un generatore e restituisce eventi e valore finale."""
    eventi = []
    while True:
        try:
            eventi.append(next(generatore))
        except StopIteration as fine:
            return eventi, fine.value


class Riconoscimento(unittest.TestCase):
    def setUp(self):
        cartella = tempfile.TemporaryDirectory()
        self.addCleanup(cartella.cleanup)
        self.cartella = Path(cartella.name)

    def test_i_dati_di_lingua_sono_nel_progetto(self):
        self.assertTrue(ocr.disponibile())

    def test_scansione_in_scala_di_grigi(self):
        percorso = self.cartella / "scansione.pdf"
        pdf_scansionato(percorso)
        eventi, pagine = consuma(ocr.riconosci(percorso))
        self.assertEqual(pagine, 1)
        self.assertIn("pagina 1 di 1", eventi[0]["text"])
        testo = " ".join(documents.extract_pages(percorso)[0][1])
        self.assertIn("24.000", testo)
        self.assertIn("canone", testo)

    def test_il_file_caricato_resta_identico(self):
        percorso = self.cartella / "scansione.pdf"
        pdf_scansionato(percorso, grigi=False)
        prima = hashlib.sha256(percorso.read_bytes()).hexdigest()
        consuma(ocr.riconosci(percorso))
        self.assertEqual(hashlib.sha256(percorso.read_bytes()).hexdigest(), prima)

    def test_i_pdf_digitali_non_passano_dall_ocr(self):
        percorso = self.cartella / "digitale.pdf"
        pdf_digitale(percorso)
        eventi, pagine = consuma(ocr.riconosci(percorso))
        self.assertEqual((eventi, pagine), ([], 0))
        self.assertEqual(ocr.testi(percorso), {})

    def test_una_pagina_illeggibile_non_blocca_il_caricamento(self):
        percorso = self.cartella / "scansione.pdf"
        pdf_scansionato(percorso)
        with mock.patch("backend.ocr._riconosci_pagina", side_effect=RuntimeError("guasto")):
            _, pagine = consuma(ocr.riconosci(percorso))
        self.assertEqual(pagine, 0)

    def test_senza_dati_di_lingua_il_caricamento_continua(self):
        percorso = self.cartella / "scansione.pdf"
        pdf_scansionato(percorso)
        with mock.patch("backend.ocr.disponibile", return_value=False):
            self.assertEqual(consuma(ocr.riconosci(percorso)), ([], 0))


class CaricamentoCompleto(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        db.init()

    def carica(self, nome):
        with tempfile.TemporaryDirectory() as cartella:
            sorgente = Path(cartella) / nome
            pdf_scansionato(sorgente)
            with db.session() as conn:
                caso = conn.execute("INSERT INTO cases (name) VALUES (?)", (f"OCR {self.id()}",)).lastrowid
            with mock.patch("backend.llm.embed", side_effect=lambda testi: [np.array([1.0, 0.0], dtype=np.float32) for _ in testi]):
                eventi, _ = consuma(documents.ingest(caso, nome, sorgente))
        return next(e for e in eventi if e["type"] == "result")

    def test_il_documento_scansionato_e_cercabile_e_segnalato(self):
        esito = self.carica("atto.pdf")
        self.assertGreater(esito["chunks"], 0)
        self.assertIn(ocr.MARCATORE, esito["warning"])
        self.assertNotIn("pochissimo testo", esito["warning"])

    def test_eliminare_il_documento_cancella_anche_il_testo_riconosciuto(self):
        esito = self.carica("da_eliminare.pdf")
        with db.session() as conn:
            percorso = conn.execute("SELECT path FROM documents WHERE id = ?", (esito["document_id"],)).fetchone()[0]
            self.assertTrue(ocr.testi(percorso))
            documents.delete_document(conn, esito["document_id"])
        self.assertFalse(Path(percorso).exists())
        self.assertFalse(Path(f"{percorso}.ocr.json").exists())
        self.assertEqual(list(config.FILES_DIR.glob("*/*da_eliminare*")), [])


if __name__ == "__main__":
    unittest.main()
