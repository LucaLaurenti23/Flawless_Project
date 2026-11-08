"""Glossario: dai termini della domanda agli articoli da leggere per primi."""
import unittest

from backend import normativa_glossario as glossario


class Articoli(unittest.TestCase):
    def test_durata_della_custodia(self):
        self.assertEqual(glossario.articoli("Quanto dura la custodia cautelare?"), [("c.p.p.", "303")])

    def test_custodia_cautelare_soglie_prima_dei_criteri(self):
        self.assertEqual(glossario.articoli("Quando si applica la custodia cautelare?"),
                         [("c.p.p.", "280"), ("c.p.p.", "275")])

    def test_forme_verbali_del_recesso(self):
        self.assertEqual(glossario.articoli("Il consumatore può recedere?")[0], ("Cod. consumo", "52"))

    def test_nessun_termine_noto(self):
        self.assertEqual(glossario.articoli("Buongiorno"), [])


if __name__ == "__main__":
    unittest.main()
