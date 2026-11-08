"""Modelli dello studio ed esportazione in Word, HTML e PDF. Non serve il modello linguistico."""
import unittest

from backend import documents, export, modelli

CORPO = "Spett.le {{destinatario}},\nLa invitiamo a pagare euro {{importo}}.\n\nAvv. {{avvocato}}"


class CompilazioneModelli(unittest.TestCase):
    def test_campi_nell_ordine_del_testo(self):
        self.assertEqual([c["nome"] for c in modelli.campi(CORPO)], ["destinatario", "importo", "avvocato"])

    def test_campi_vuoti_segnalati(self):
        testo = modelli.compila_testo(CORPO, {"destinatario": "Alfa S.r.l."})
        self.assertIn("Spett.le Alfa S.r.l.", testo)
        self.assertIn("[DA COMPLETARE: importo]", testo)

    def test_formati_di_uscita(self):
        valori = {"destinatario": "Alfa S.r.l.", "importo": "4.000", "avvocato": "Laura Verdi"}
        self.assertTrue(modelli.docx(CORPO, valori).startswith(b"PK"))
        self.assertTrue(modelli.pdf(CORPO, valori, "Prova").startswith(b"%PDF"))

    def test_anteprima_evidenzia_i_dati_mancanti(self):
        self.assertIn('class="da-completare"', export.to_html("Importo: [DA COMPLETARE: importo]"))


class LetturaDocumenti(unittest.TestCase):
    def test_parole_spezzate_a_fine_riga(self):
        self.assertEqual(documents._clean("con-\ntratto  di\nlocazione"), "contratto di locazione")

    def test_etichetta_pagina(self):
        self.assertEqual(documents.page_label(3), "p. 3")
        self.assertEqual(documents.page_label(None), "testo")


if __name__ == "__main__":
    unittest.main()
