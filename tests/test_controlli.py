"""Controlli sul testo prodotto dal modello: cifre, articoli e nomi che non stanno nella fonte."""
import unittest

from backend import controlli


class NonNelTesto(unittest.TestCase):
    def test_tutto_presente(self):
        fonte = "Art. 1454. La diffida fissa un termine non inferiore a 15 giorni."
        self.assertEqual(controlli.non_nel_testo("L'art. 1454 prevede 15 giorni.", fonte), [])

    def test_segnala_articolo_e_cifra_inventati(self):
        assenti = controlli.non_nel_testo("L'art. 1455 prevede 30 giorni.", "Art. 1454: 15 giorni.")
        self.assertEqual(assenti, ["art. 1455", "30"])

    def test_segnala_mese_inventato(self):
        self.assertEqual(controlli.non_nel_testo("Canone di gennaio.", "Canone di marzo."), ["gennaio"])

    def test_migliaia_scritte_in_modi_diversi(self):
        self.assertEqual(controlli.non_nel_testo("Sono 24.000 euro.", "Importo: euro 24000."), [])

    def test_numeri_di_una_cifra_ignorati(self):
        self.assertEqual(controlli.non_nel_testo("Vedi il comma 3.", "Testo senza numeri."), [])


class Destinatario(unittest.TestCase):
    def test_societa(self):
        self.assertEqual(controlli.destinatario("Diffida ad Alfa S.r.l. per il canone"), "Alfa S.r.l.")

    def test_senza_destinatario(self):
        self.assertEqual(controlli.destinatario("scrivi una bozza sul canone"), "")


class ValoreSupportato(unittest.TestCase):
    FONTE = "Contratto tra Mario Rossi e Alfa S.r.l., canone di euro 24000 da marzo."

    def test_vuoto(self):
        self.assertTrue(controlli.valore_supportato("  ", self.FONTE))

    def test_dati_presenti(self):
        self.assertTrue(controlli.valore_supportato("Mario Rossi", self.FONTE))
        self.assertTrue(controlli.valore_supportato("24.000", self.FONTE))

    def test_dati_inventati(self):
        self.assertFalse(controlli.valore_supportato("Luigi Bianchi", self.FONTE))
        self.assertFalse(controlli.valore_supportato("31.000", self.FONTE))
        self.assertFalse(controlli.valore_supportato("5 gennaio", self.FONTE))

    def test_solo_cifre_non_guarda_i_nomi(self):
        self.assertTrue(controlli.valore_supportato("Luigi", self.FONTE, solo_cifre=True))


if __name__ == "__main__":
    unittest.main()
