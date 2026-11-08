"""Separazione tra fascicoli e protezione dei testi di legge, su un archivio temporaneo."""
import unittest
from pathlib import Path
from unittest import mock

import numpy as np
from fastapi.testclient import TestClient

from backend import config, db, main, rag

VETTORE = np.array([1.0, 0.0], dtype=np.float32)


class ArchivioDiProva(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        assert config.DATA_DIR != config.ROOT / "data", "I test non devono usare l'archivio reale"
        db.init()
        cls.api = TestClient(main.app)   # senza "with": il lavoro in background non parte

    def nuovo_fascicolo(self, nome):
        risposta = self.api.post("/api/cases", json={"name": nome})
        self.assertEqual(risposta.status_code, 200)
        return risposta.json()["id"]

    def nuovo_documento(self, caso, nome):
        percorso = config.FILES_DIR / f"{caso}_{nome}"
        percorso.write_text("contenuto", encoding="utf-8")
        with db.session() as conn:
            documento = conn.execute("INSERT INTO documents (case_id, filename, path) VALUES (?, ?, ?)",
                                     (caso, nome, str(percorso))).lastrowid
            conn.execute("INSERT INTO chunks (document_id, page, text, embedding) VALUES (?, 1, ?, ?)",
                         (documento, f"Testo di {nome}", db.to_blob(VETTORE)))
        return documento, percorso


class SeparazioneFascicoli(ArchivioDiProva):
    def test_nuovo_fascicolo_senza_documenti_di_altri(self):
        alfa = self.nuovo_fascicolo("Alfa documenti")
        self.nuovo_documento(alfa, "alfa.txt")
        beta = self.nuovo_fascicolo("Beta documenti")
        self.assertEqual(self.api.get(f"/api/cases/{beta}/documents").json(), [])

    def test_la_ricerca_resta_nel_fascicolo(self):
        alfa = self.nuovo_fascicolo("Alfa ricerca")
        beta = self.nuovo_fascicolo("Beta ricerca")
        documento_alfa, _ = self.nuovo_documento(alfa, "alfa.txt")
        self.nuovo_documento(beta, "beta.txt")
        with mock.patch("backend.llm.embed", return_value=[VETTORE]):
            self.assertEqual([f["filename"] for f in rag.search("domanda", beta)], ["beta.txt"])
            self.assertEqual(rag.search("domanda", beta, document_ids=[documento_alfa]), [])

    def test_la_cronologia_non_passa_da_un_fascicolo_all_altro(self):
        alfa = self.nuovo_fascicolo("Alfa cronologia")
        beta = self.nuovo_fascicolo("Beta cronologia")
        conversazione, _ = rag._open_conversation(alfa, "rag", None, "prima domanda")
        with db.session() as conn:
            db.add_message(conn, conversazione, "user", "dato riservato di Alfa")
        nuova, cronologia = rag._open_conversation(beta, "rag", conversazione, "seconda domanda")
        self.assertNotEqual(nuova, conversazione)
        self.assertEqual(cronologia, [])


class LeggiProtette(ArchivioDiProva):
    def conta_norme(self):
        with db.session() as conn:
            return conn.execute("SELECT (SELECT COUNT(*) FROM norme_atti), (SELECT COUNT(*) FROM norme)").fetchone()[:]

    def test_eliminare_un_fascicolo_non_tocca_le_leggi(self):
        with db.session() as conn:
            atto = conn.execute("INSERT INTO norme_atti (sigla, titolo, area, fonte, urn) VALUES ('T.', 'Prova', 'Prova', 'Prova', 'x')").lastrowid
            conn.execute("INSERT INTO norme (atto_id, sezione, articolo, rubrica, parte, testo) "
                         "VALUES (?, '', '1', '', 0, 'Testo di legge')", (atto,))
        prima = self.conta_norme()
        caso = self.nuovo_fascicolo("Da eliminare")
        _, percorso = self.nuovo_documento(caso, "atto.txt")
        self.assertEqual(self.api.delete(f"/api/cases/{caso}").status_code, 200)
        self.assertFalse(Path(percorso).exists())
        self.assertEqual(self.conta_norme(), prima)

    def test_nessuna_funzione_elimina_le_leggi(self):
        cancellazioni = sorted(percorso for percorso, metodi in main.app.openapi()["paths"].items() if "delete" in metodi)
        self.assertEqual(cancellazioni, ["/api/cases/{case_id}", "/api/conversations/{conversation_id}",
                                         "/api/documents/{document_id}", "/api/templates/{template_id}"])

    def test_resta_sempre_un_fascicolo(self):
        for fascicolo in self.api.get("/api/cases").json():
            self.api.delete(f"/api/cases/{fascicolo['id']}")
        self.assertEqual([f["name"] for f in self.api.get("/api/cases").json()], [db.DEFAULT_CASE])


if __name__ == "__main__":
    unittest.main()
