"""Impaginazione di lettere e atti scritti dal modello: la stessa struttura serve al file Word e all'anteprima.

Il modello scrive testo semplice; qui si riconoscono i blocchi tipici di una lettera o di un atto
(luogo e data, destinatario, modalità di invio, oggetto, corpo, elenchi, titoli, saluti, firma)
e li si impagina come in uno studio legale. I punti [DA COMPLETARE] e [DA VERIFICARE] vengono evidenziati."""
import html
import io
import re

import docx
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_COLOR_INDEX
from docx.oxml.ns import qn
from docx.shared import Cm, Pt

FONT = "Times New Roman"

# Un dato ancora da inserire: "[DA COMPLETARE: importo]".
RE_SEGNAPOSTO = r"\[DA (?:COMPLETARE|VERIFICARE)[^\]]*\]"
# Riga con luogo e data: "Roma, lì 5 marzo 2026".
RE_DATA = re.compile(rf"^(?:{RE_SEGNAPOSTO}|[A-ZÀ-Ý][\w'À-ÿ .-]{{1,40}}),\s*(?:li\s*|lì\s*)?(?:{RE_SEGNAPOSTO}|\d{{1,2}})", re.I)
# Riga del destinatario: "Spett.le Alfa S.r.l.", "Egr. Sig. Rossi", "Al Tribunale di Roma".
RE_DESTINATARIO = re.compile(r"^(?:Spett\.?(?:le|li)?|Egr\.?(?:egio)?|Gent\.?(?:ma|mo|mi)?|Ill\.?(?:mo|ma|mi)|Preg\.?(?:mo|ma)|"
                             r"Al(?:la|lo|l'|)\s|Ai\s|Agli\s|Alle\s|Destinatari[oa]:)", re.I)
# Modalità di invio: "A mezzo PEC", "Raccomandata a.r.".
RE_INVIO = re.compile(r"^(?:a mezzo|tramite|via\s|raccomandata|pec\b|posta elettronica|anticipata|consegna a mano)", re.I)
# Riga dell'oggetto: "Oggetto: diffida".
RE_OGGETTO = re.compile(r"^(?:oggetto|ogg\.)\s*:", re.I)
# Formula di chiusura breve: "Distinti saluti.".
RE_SALUTI = re.compile(r"^(?:distinti|cordiali|i migliori|con osservanza|in attesa|ringraziando|con i migliori)[^.]{0,60}[.,]?$", re.I)
# Riga della firma: "Avv. Mario Rossi", "Il difensore".
RE_FIRMA = re.compile(r"^(?:\(?avv\.|avvocat[oa]|il difensore|firma|f\.to|dott\.|\[DA COMPLETARE: (?:firma|avvocato))", re.I)
# Inizio di una voce di elenco: "- voce", "1. voce", "a) voce".
RE_ELENCO = re.compile(r"^\s*(?:[-–•*]|\d{1,2}[.)]|[a-z][.)])\s+")


def _semplice(riga):
    """La riga senza marcatori markdown, per riconoscerne il tipo."""
    return re.sub(r"\*\*|__|^#+\s*", "", riga).strip()


def _titolo(riga):
    """Righe di titolo degli atti: '# ...' oppure brevi e tutte maiuscole (TRIBUNALE DI MILANO, P.Q.M.)."""
    if re.match(r"^#{1,6}\s", riga):
        return True
    testo = _semplice(riga)
    lettere = [c for c in testo if c.isalpha()]
    return 2 < len(testo) <= 80 and len(lettere) >= 3 and all(c.isupper() for c in lettere) and not RE_SEGNAPOSTO_SOLO.match(testo)


# Una riga composta solo da un dato ancora da inserire.
RE_SEGNAPOSTO_SOLO = re.compile(rf"^{RE_SEGNAPOSTO}$")


def struttura(testo):
    """[(tipo, [righe])]: tipi data, destinatario, invio, oggetto, titolo, elenco, testo, saluti, firma."""
    righe = [r.rstrip() for r in testo.replace("\r", "").split("\n")]
    blocchi, corrente = [], []
    for riga in righe + [""]:
        if riga.strip():
            corrente.append(riga.strip())
        elif corrente:
            blocchi.append(corrente)
            corrente = []

    risultato = []
    for i, blocco in enumerate(blocchi):
        primo = _semplice(blocco[0])
        breve = all(len(_semplice(r)) <= 90 for r in blocco)
        ultimi = i >= len(blocchi) - 3
        if len(blocco) == 1 and len(primo) <= 70 and RE_DATA.match(primo) and not primo.endswith("."):
            risultato.append(("data", blocco))
        elif RE_DESTINATARIO.match(primo) and breve and len(blocco) <= 7:
            risultato.append(("destinatario", blocco))
        elif RE_OGGETTO.match(primo):
            risultato.append(("oggetto", blocco))
        elif RE_INVIO.match(primo) and breve and len(blocco) <= 2:
            risultato.append(("invio", blocco))
        elif ultimi and RE_SALUTI.match(primo) and len(blocco) <= 2:
            risultato.append(("saluti", blocco[:1]))
            if len(blocco) > 1:
                risultato.append(("firma", blocco[1:]))
        elif ultimi and RE_FIRMA.match(primo) and breve and len(blocco) <= 4:
            risultato.append(("firma", blocco))
        else:
            # dentro un blocco di testo: titoli, voci di elenco e paragrafi
            for riga in blocco:
                if _titolo(riga):
                    risultato.append(("titolo", [riga]))
                elif RE_ELENCO.match(riga):
                    risultato.append(("elenco", [riga]))
                else:
                    risultato.append(("testo", [riga]))
    return risultato


def _pezzi(riga):
    """(testo, grassetto, segnaposto) per una riga: **grassetto** e segnaposti da completare."""
    riga = re.sub(r"^#{1,6}\s*", "", riga)
    for parte in re.split(rf"(\*\*.+?\*\*|{RE_SEGNAPOSTO})", riga):
        if not parte:
            continue
        if parte.startswith("**") and parte.endswith("**"):
            yield parte[2:-2], True, False
        elif re.fullmatch(RE_SEGNAPOSTO, parte):
            yield parte, True, True
        else:
            yield parte.replace("**", ""), False, False


def _voce_elenco(riga):
    """Separa una voce di elenco nel suo segno (trattino, "1.", "a)") e nel testo."""
    m = RE_ELENCO.match(riga)
    segno = m.group(0).strip()
    return ("–" if segno in "-–•*" else segno), riga[m.end():]


# --- Word -----------------------------------------------------------------------

def to_docx(testo):
    """Impagina il testo di una bozza in un documento Word A4 e ne restituisce i byte."""
    documento = docx.Document()
    sezione = documento.sections[0]
    sezione.page_width, sezione.page_height = Cm(21), Cm(29.7)
    sezione.left_margin = sezione.right_margin = Cm(2.5)
    sezione.top_margin = sezione.bottom_margin = Cm(2.5)
    normale = documento.styles["Normal"]
    normale.font.name, normale.font.size = FONT, Pt(12)
    normale.element.rPr.rFonts.set(qn("w:eastAsia"), FONT)
    normale.paragraph_format.space_after = Pt(0)
    normale.paragraph_format.line_spacing = 1.15

    def paragrafo(riga, *, allinea=None, rientro=None, grassetto=False, dopo=0, prima=0, sporgente=None):
        p = documento.add_paragraph()
        formato = p.paragraph_format
        formato.space_after, formato.space_before = Pt(dopo), Pt(prima)
        if allinea is not None:
            p.alignment = allinea
        if rientro is not None:
            formato.left_indent = rientro
        if sporgente is not None:
            formato.first_line_indent = sporgente
        for testo_pezzo, bold, segnaposto in _pezzi(riga):
            run = p.add_run(testo_pezzo)
            run.bold = bold or grassetto
            if segnaposto:
                run.font.highlight_color = WD_COLOR_INDEX.YELLOW
        return p

    precedente = None
    for tipo, righe in struttura(testo):
        ultima = len(righe) - 1
        if precedente == "elenco" and tipo != "elenco":
            documento.add_paragraph().paragraph_format.space_after = Pt(0)   # stacco dopo un elenco
        precedente = tipo
        for n, riga in enumerate(righe):
            dopo = 12 if n == ultima else 0
            if tipo == "data":
                paragrafo(riga, allinea=WD_ALIGN_PARAGRAPH.RIGHT, dopo=18)
            elif tipo == "destinatario":
                paragrafo(riga, rientro=Cm(9), dopo=18 if n == ultima else 0)
            elif tipo == "invio":
                paragrafo(riga, grassetto=True, dopo=dopo)
            elif tipo == "oggetto":
                paragrafo(riga, grassetto=True, allinea=WD_ALIGN_PARAGRAPH.JUSTIFY, dopo=18 if n == ultima else 0)
            elif tipo == "titolo":
                paragrafo(riga, grassetto=True, allinea=WD_ALIGN_PARAGRAPH.CENTER, prima=6, dopo=12)
            elif tipo == "elenco":
                segno, resto = _voce_elenco(riga)
                paragrafo(f"{segno}\t{resto}", allinea=WD_ALIGN_PARAGRAPH.JUSTIFY, rientro=Cm(1), sporgente=Cm(-0.6), dopo=6)
            elif tipo == "saluti":
                paragrafo(riga, dopo=24)
            elif tipo == "firma":
                paragrafo(riga, allinea=WD_ALIGN_PARAGRAPH.RIGHT, dopo=0)
            else:
                paragrafo(riga, allinea=WD_ALIGN_PARAGRAPH.JUSTIFY, dopo=10)
    buffer = io.BytesIO()
    documento.save(buffer)
    return buffer.getvalue()


# --- Anteprima HTML (stesse regole del Word) --------------------------------------

def to_html(testo):
    """Impagina il testo di una bozza in HTML per l'anteprima, evidenziando i campi da completare."""
    def riga_html(riga):
        out = []
        for testo_pezzo, bold, segnaposto in _pezzi(riga):
            t = html.escape(testo_pezzo)
            if segnaposto:
                out.append(f'<mark class="da-completare">{t}</mark>')
            elif bold:
                out.append(f"<b>{t}</b>")
            else:
                out.append(t)
        return "".join(out)

    parti = []
    for tipo, righe in struttura(testo):
        if tipo == "elenco":
            segno, resto = _voce_elenco(righe[0])
            parti.append(f'<p class="b-elenco"><span>{html.escape(segno)}</span>{riga_html(resto)}</p>')
        else:
            parti.append(f'<p class="b-{tipo}">' + "<br>".join(riga_html(r) for r in righe) + "</p>")
    return "\n".join(parti)
