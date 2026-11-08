"""Controlli scritti nel programma sul testo prodotto dal modello: valgono sempre, comunque il modello formuli il testo."""
import re

# Un riferimento ad articolo: "art. 18", "artt. 2043", "articolo 2-bis". Cattura il numero.
RE_ARTICOLO = re.compile(r"\bart(?:icol[oi]|t)?\.?\s*(\d+(?:-[a-z]+)?)", re.IGNORECASE)
# Un numero anche con separatori: "24.000", "3,5", "183/2010".
RE_NUMERO = re.compile(r"\d+(?:[.,/]\d+)*")
MESI = "gennaio febbraio marzo aprile maggio giugno luglio agosto settembre ottobre novembre dicembre".split()
# "Diffida ad Alfa S.r.l. per..." cattura "Alfa S.r.l.". Il nome deve avere l'iniziale maiuscola.
RE_DESTINATARIO = re.compile(
    r"\b(?i:diffid\w*|letter\w*|comunicazion\w*|sollecit\w*|messa in mora|destinatari\w*:?)\s+(?i:(?:ad?|al|alla|allo|nei confronti d\w+)\s+)?"
    r"((?:(?:Sig\.ra|Sig\.|Dott\.ssa|Dott\.|Avv\.|Spett\.le)\s+)?[A-Z][\w'&.-]*(?:\s+(?:[A-Z][\w'&.-]*))*)")


def _numeri(testo):
    """I numeri di un testo, senza il punto delle migliaia: "24.000" e "24000" sono lo stesso numero."""
    return {re.sub(r"[.,]00$", "", n).replace(".", "") for n in RE_NUMERO.findall(testo)}


def non_nel_testo(uscita, fonte):
    """Articoli e cifre del testo prodotto che la fonte non contiene. I numeri di una cifra (commi, elenchi) non si contano."""
    articoli_fonte = {a.lower() for a in RE_ARTICOLO.findall(fonte)} | _numeri(fonte)
    articoli = [f"art. {a}" for a in dict.fromkeys(RE_ARTICOLO.findall(uscita)) if a.lower() not in articoli_fonte]
    senza_articoli = RE_ARTICOLO.sub(" ", uscita)
    numeri_fonte = _numeri(fonte)
    numeri = [n for n in dict.fromkeys(RE_NUMERO.findall(senza_articoli))
              if len(re.sub(r"\D", "", n)) >= 2 and re.sub(r"[.,]00$", "", n).replace(".", "") not in numeri_fonte]
    mesi = [m for m in MESI if re.search(rf"\b{m}\b", uscita, re.IGNORECASE) and not re.search(rf"\b{m}\b", fonte, re.IGNORECASE)]
    return articoli + numeri + mesi


def destinatario(istruzioni):
    """Il destinatario indicato nelle istruzioni ("Diffida ad Alfa S.r.l. per..."), se si riconosce."""
    m = RE_DESTINATARIO.search(istruzioni)
    return m.group(1).strip() if m else ""


def valore_supportato(valore, fonte, solo_cifre=False):
    """Un campo compilato dal modello regge solo se cifre, mesi e nomi propri stanno nei dati forniti."""
    if not valore.strip():
        return True
    minuscola = fonte.lower()
    if any(n not in _numeri(fonte) for n in _numeri(valore)):
        return False
    if any(m in valore.lower() and m not in minuscola for m in MESI):
        return False
    if solo_cifre:
        return True
    nomi = re.findall(r"\b[A-ZÀ-Ý][\wà-ÿ']{2,}", valore)
    return all(n.lower() in minuscola for n in nomi)
