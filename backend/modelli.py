"""Modelli dello studio come moduli da compilare.

Un modello è un testo con segnaposto {{nome}}: ogni segnaposto è un campo del modulo. I campi si
compilano a mano o con l'IA (che compila solo i campi: testo e impaginazione del modello restano quelli
dello studio). Il risultato si scarica in Word o come PDF compilabile: i campi brevi sono campi PDF dentro
le frasi, quelli lunghi (premesse, descrizioni...) riquadri su più righe; si modificano con qualsiasi lettore PDF."""
import html
import io
import json
import re
from datetime import date

import pymupdf

from . import controlli, export, llm, rag, sicurezza

# Campo di un modello: "{{nome cliente}}". Cattura il nome.
RE_CAMPO = re.compile(r"\{\{\s*([\w ]+?)\s*\}\}")
LUNGHI = ("corpo", "descrizione", "testo", "premess", "fatti", "motiv", "richiest", "obbligazion", "note", "conclusion")
DATE = ("data",)
# Nome del campo che indica la data dell'atto: "data", "data_lettera", "data della lettera".
RE_DATA_DOCUMENTO = re.compile(r"^data(?:[ _](?:della[ _])?(?:lettera|documento|atto|odierna))?$", re.IGNORECASE)   # l'unica che può essere oggi
IMPORTI = ("importo", "somma", "canone", "euro", "compenso", "corrispettivo")
NBSP = " "
MESI = ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio", "agosto", "settembre",
        "ottobre", "novembre", "dicembre"]


def oggi():
    """La data di oggi in forma estesa."""
    d = date.today()
    return f"{d.day} {MESI[d.month - 1]} {d.year}"


def _tipo(nome):
    """Il tipo di campo dedotto dal nome: lungo, data, importo o breve."""
    n = nome.lower()
    if any(k in n for k in LUNGHI):
        return "lungo"
    if any(n == k or n.startswith(k + "_") or n.endswith("_" + k) for k in DATE):
        return "data"
    if any(k in n for k in IMPORTI):
        return "importo"
    return "breve"


def campi(corpo):
    """I campi di un modello, nell'ordine in cui compaiono: [{nome, etichetta, tipo, predefinito}]."""
    visti = {}
    for m in RE_CAMPO.finditer(corpo):
        nome = m.group(1).strip()
        if nome not in visti:
            tipo = _tipo(nome)
            visti[nome] = {"nome": nome, "etichetta": nome.replace("_", " ").capitalize(), "tipo": tipo,
                           "predefinito": oggi() if nome.lower() == "data" else ""}
    return list(visti.values())


def _etichetta(nome):
    """Il nome del campo da mostrare all'utente."""
    return nome.replace("_", " ")


def compila_testo(corpo, valori):
    """Testo del modello con i valori; i campi vuoti diventano [DA COMPLETARE: ...] (evidenziati in Word e anteprima)."""
    def sostituisci(m):
        valore = (valori.get(m.group(1).strip()) or "").strip()
        return valore if valore else f"[DA COMPLETARE: {_etichetta(m.group(1).strip())}]"
    return RE_CAMPO.sub(sostituisci, corpo)


def anteprima(corpo, valori):
    """Il modello compilato in HTML."""
    return export.to_html(compila_testo(corpo, valori))


def docx(corpo, valori):
    """Il modello compilato in formato Word."""
    return export.to_docx(compila_testo(corpo, valori))


# --- Compilazione con l'IA --------------------------------------------------------

def compila_ia(corpo, nome_modello, istruzioni, case_id, use_case_docs=False, valori=None):
    """L'IA compila solo i campi del modello, a partire dalle istruzioni (e dai documenti del fascicolo)."""
    if sicurezza.rileva(istruzioni):
        raise ValueError(sicurezza.RIFIUTO)
    elenco = campi(corpo)
    valori = dict(valori or {})
    contesto = ""
    if use_case_docs:
        yield {"type": "status", "text": "Ricerca nei documenti del fascicolo…"}
        fonti = rag.search(f"{nome_modello} {istruzioni}", case_id)
        yield {"type": "sources", "sources": fonti}
        if fonti:
            contesto = ("\n\nEstratti dai documenti del fascicolo (usali solo se pertinenti):\n\n"
                        + rag.format_excerpts(fonti))
    contesti = _contesti(corpo)
    descrizione = "\n".join(
        f"- {c['nome']}: va inserito nella frase «{contesti[c['nome']]}»"
        + {"lungo": "; scrivi la parte mancante della frase, anche più frasi, in stile formale",
           "data": "; data in lettere, es. 3 marzo 2026",
           "importo": "; solo la cifra, es. 1.500,00"}.get(c["tipo"], "")
        for c in elenco)
    gia = {k: v for k, v in valori.items() if v}
    schema = {"type": "object", "properties": {c["nome"]: {"type": "string"} for c in elenco},
              "required": [c["nome"] for c in elenco]}
    yield {"type": "status", "text": "Compilazione dei campi…"}
    risposta = llm.complete([
        {"role": "system", "content": "Sei un assistente di uno studio legale italiano. Compili i campi di un modello "
                                      "di lettera o atto. Rispondi solo con JSON.\n\n" + sicurezza.REGOLE},
        {"role": "user", "content": (
            f"Modello: {nome_modello}\n\nTesto del modello (i campi sono tra doppie graffe):\n{corpo}\n\n"
            f"Campi da compilare:\n{descrizione}\n\n"
            f"Data di oggi: {oggi()}.\n"
            + (f"Valori già inseriti dall'avvocato (non cambiarli): {json.dumps(gia, ensure_ascii=False)}\n" if gia else "")
            + f"\nIstruzioni e dati forniti dall'avvocato:\n{istruzioni}{contesto}\n\n"
            "Regole: usa solo i dati delle istruzioni e degli estratti; se un dato non c'è lascia la stringa vuota "
            "(non inventare nomi, indirizzi, date, importi o coordinate bancarie). Ogni valore sostituisce il "
            "campo nella sua frase: rileggi la frase completa e non ripetere le parole che la frase ha già "
            "(es. se la frase è «Avv. {{avvocato}}» scrivi solo «Laura Verdi»), non aggiungere la punteggiatura "
            "che segue il campo, niente segnaposto né simboli di formattazione.")},
    ], format=schema)
    try:
        proposti = json.loads(risposta)
    except json.JSONDecodeError:
        proposti = {}
    # Il modello a volte riempie un campo con un dato che nessuno gli ha dato (es. la data di oggi come scadenza): si lascia vuoto.
    fonte = "\n".join([istruzioni, contesto, *gia.values()])
    scartati = []
    for c in elenco:
        if valori.get(c["nome"]):
            continue
        valore = _adatta(str(proposti.get(c["nome"]) or ""), corpo, c["nome"])
        ammessa_oggi = RE_DATA_DOCUMENTO.match(c["nome"].strip())
        if not controlli.valore_supportato(valore, fonte + (f"\n{oggi()}" if ammessa_oggi else ""), solo_cifre=c["tipo"] == "lungo"):
            scartati.append(c["nome"])
            valore = ""
        valori[c["nome"]] = valore
    yield {"type": "result", "valori": valori, "scartati": scartati}


def _contesti(corpo):
    """Per ogni campo, la riga del modello in cui compare la prima volta."""
    contesti = {}
    for riga in corpo.split("\n"):
        for m in RE_CAMPO.finditer(riga):
            contesti.setdefault(m.group(1).strip(), riga.strip())
    return contesti


def _adatta(valore, corpo, nome):
    """Ripulisce un valore proposto dall'IA perché si incastri nella frase del modello: niente parola iniziale
    già scritta prima del campo («Avv. Avv. Laura Verdi») e niente punteggiatura doppia («;;»)."""
    valore = valore.strip()
    m = re.search(r"(\S+)\s*\{\{\s*" + re.escape(nome) + r"\s*\}\}(.?)", corpo)
    if not m or not valore:
        return valore
    prima, dopo = m.group(1), m.group(2)
    if valore.lower().startswith(prima.lower() + " "):
        valore = valore[len(prima):].strip()
    sigla = re.search(r"(?:\b\w\.){2,}$", valore)   # "S.r.l." tiene il suo punto
    if dopo and dopo in ".,;:" and valore[-1:] in ".,;:" and not (sigla and dopo != "."):
        valore = valore[:-1].rstrip()
    return valore


# --- PDF compilabile ----------------------------------------------------------------

A4 = pymupdf.paper_rect("a4")
MARGINE = 72  # 2,5 cm
CSS_PDF = """
body { margin: 0; }
* { font-family: Times; font-size: 12pt; line-height: 1.35; color: #161616; }
p { margin: 0 0 10pt 0; text-align: justify; }
.b-data { text-align: right; margin-bottom: 18pt; }
.b-destinatario { margin-left: 230pt; text-align: left; margin-bottom: 18pt; }
.b-invio, .b-oggetto { font-weight: bold; }
.b-oggetto { margin-bottom: 18pt; }
.b-titolo { text-align: center; font-weight: bold; margin: 6pt 0 12pt 0; }
.b-elenco { margin: 0 0 5pt 0; padding-left: 28pt; text-indent: -16pt; }
.b-saluti { margin: 14pt 0 24pt 0; text-align: left; }
.b-firma { text-align: right; margin: 0; }
.slot { color: white; }
.riquadro { color: white; }
"""
GRASSETTO = {"invio", "oggetto", "titolo"}
COLORE_VUOTO = (1, 0.95, 0.70)      # campo da compilare: giallo, come nell'anteprima
COLORE_RIGA = (0.62, 0.62, 0.62)    # campo compilato: trasparente con una sottile sottolineatura, come su un modulo


def _righe_modello(corpo, valori):
    """Coppie (riga del modello, riga compilata) delle righe non vuote, per riconoscere la struttura."""
    coppie = []
    for riga in corpo.replace("\r", "").split("\n"):
        if riga.strip():
            coppie.append((riga.strip(), compila_testo(riga.strip(), valori).replace("\n", " ")))
    return coppie


def pdf(corpo, valori, titolo="Modulo"):
    """PDF A4 impaginato come il Word, con i campi del modello compilabili."""
    # la struttura (data, destinatario, oggetto...) si riconosce sul testo compilato; ogni riga riconosciuta
    # si ricollega poi alla riga del modello da cui viene, che è nello stesso ordine
    struttura = export.struttura(_testo_con_blocchi(corpo, valori))
    modello_iter = iter(m for m, _ in _righe_modello(corpo, valori))
    area = A4 + (MARGINE, MARGINE, -MARGINE, -MARGINE)

    widget, parti_html = [], []
    contatore = {}

    def nome_unico(nome):
        contatore[nome] = contatore.get(nome, 0) + 1
        return nome if contatore[nome] == 1 else f"{nome}_{contatore[nome]}"

    def riga_html(riga_modello, tipo):
        """Testo statico + segnaposto: campi brevi dentro la frase; con un campo lungo, tutta la riga è un riquadro."""
        if any(_tipo(m.group(1).strip()) == "lungo" for m in RE_CAMPO.finditer(riga_modello)):
            ident = f"r{len(widget)}"
            testo = compila_testo(riga_modello, valori)
            vuoto = "[DA COMPLETARE" in testo
            rientro = 12 if tipo == "elenco" else 0
            righe = _a_capo(testo, area.width - rientro - 6, tipo in GRASSETTO) + ([""] if vuoto else [])   # spazio per scrivere
            # il riquadro contiene tutta la frase (anche eventuali campi brevi): prende il nome del campo lungo
            lungo = next(m.group(1).strip() for m in RE_CAMPO.finditer(riga_modello) if _tipo(m.group(1).strip()) == "lungo")
            widget.append({"id": ident, "nome": nome_unico(lungo),
                           "valore": "\n".join(righe).rstrip(), "multilinea": True, "vuoto": vuoto,
                           "grassetto": tipo in GRASSETTO, "righe": len(righe), "rientro": rientro})
            # la stessa altezza di righe, invisibile, riserva il posto del riquadro nell'impaginazione
            return f'<span id="{ident}" class="riquadro">' + "<br>".join(html.escape(r) or NBSP for r in righe) + "</span>"
        pezzi, pos = [], 0
        for m in RE_CAMPO.finditer(riga_modello):
            pezzi.append(html.escape(riga_modello[pos:m.start()]))
            nome = m.group(1).strip()
            valore = (valori.get(nome) or "").strip()
            ident = f"s{len(widget)}"
            # lo spazio riservato è il valore stesso (invisibile; lo mostra il campo) o una riga vuota;
            # i due spazi in più compensano il margine interno del campo, che altrimenti taglierebbe le ultime lettere
            riserva = (valore.replace(" ", NBSP) if valore else NBSP * 26) + NBSP
            widget.append({"id": ident, "nome": nome_unico(nome), "valore": valore, "multilinea": False,
                           "vuoto": not valore, "grassetto": tipo in GRASSETTO,
                           "larghezza": _larghezza(riserva, tipo in GRASSETTO),
                           "dopo_spazio": riga_modello[:m.start()].endswith(" ")})
            pezzi.append(f'<span id="{ident}" class="slot">{html.escape(riserva)}</span>')
            pos = m.end()
        pezzi.append(html.escape(riga_modello[pos:]))
        return "".join(pezzi)

    for tipo, righe in struttura:
        righe_modello = [next(modello_iter) for _ in righe]
        if tipo == "elenco":
            corpo_riga = re.sub(r"^\s*(?:[-–•*])\s+", "– ", righe_modello[0])
            parti_html.append(f'<p class="b-elenco">{riga_html(corpo_riga, tipo)}</p>')
        else:
            parti_html.append(f'<p class="b-{tipo}">' + "<br>".join(riga_html(r, tipo) for r in righe_modello) + "</p>")

    # impaginazione con Story, pagina per pagina, registrando dove finiscono i campi
    story = pymupdf.Story(html="".join(parti_html), user_css=CSS_PDF)
    posizioni = {}
    flusso = io.BytesIO()
    writer = pymupdf.DocumentWriter(flusso)
    pagina, altro = 0, True

    def registra(p):   # chiamata da Story durante element_positions, per la pagina corrente
        if p.id:
            posizioni.setdefault(p.id, []).append((pagina, pymupdf.Rect(p.rect)))

    while altro:
        dispositivo = writer.begin_page(A4)
        altro, _ = story.place(area)
        story.element_positions(registra)
        story.draw(dispositivo)
        writer.end_page()
        pagina += 1
    writer.close()
    buffer = pymupdf.open("pdf", flusso.getvalue())

    for w in widget:
        for n, rect in posizioni.get(w["id"], [])[:1]:
            campo = pymupdf.Widget()
            campo.field_type = pymupdf.PDF_WIDGET_TYPE_TEXT
            campo.field_name = w["nome"]
            campo.field_label = w["nome"].replace("_", " ")
            campo.field_value = w["valore"]
            campo.text_font = "TiBo" if w["grassetto"] else "TiRo"
            campo.text_fontsize = 12
            campo.text_color = (0.09, 0.09, 0.09)
            if w["vuoto"]:
                campo.fill_color, campo.border_width = COLORE_VUOTO, 0
            else:
                # senza sfondo: il testo fisso accanto (virgole, spazi) resta visibile anche se il campo lo sfiora
                campo.border_style, campo.border_color, campo.border_width = "U", COLORE_RIGA, 0.5
            # Story dà l'inizio del campo (compreso lo spazio che lo precede) ma non la larghezza:
            # la si calcola con le misure del Times, lo stesso carattere del testo
            if w["multilinea"]:
                campo.field_flags |= pymupdf.PDF_TX_FIELD_IS_MULTILINE
                campo.rect = pymupdf.Rect(area.x0 + w["rientro"], rect.y0, area.x1, rect.y0 + w["righe"] * RIGA + 3)
            else:
                x0 = rect.x0 + (_larghezza(" ", w["grassetto"]) if w["dopo_spazio"] else 0)
                campo.rect = pymupdf.Rect(x0, rect.y0 - 1, min(x0 + w["larghezza"], area.x1 + 4), rect.y0 + RIGA - 2)
            buffer[n].add_widget(campo)
    buffer.set_metadata({"title": titolo, "creator": "Flawless Project", "producer": "Flawless Project (PyMuPDF)"})
    return buffer.tobytes(garbage=3, deflate=True)


RIGA = 12 * 1.35   # altezza di una riga: corpo 12 e interlinea 1,35, come nel CSS


def _larghezza(testo, grassetto=False):
    """Larghezza in punti di un testo nel carattere Times da 12 usato nel PDF."""
    return pymupdf.get_text_length(testo.replace(NBSP, " "), fontname="tibo" if grassetto else "tiro", fontsize=12)


def _a_capo(testo, larghezza, grassetto=False):
    """Divide il testo in righe che stanno nella larghezza del riquadro: l'aspetto dei campi
    generato da PyMuPDF non va a capo da solo."""
    righe, corrente = [], ""
    for parola in testo.split():
        prova = f"{corrente} {parola}".strip()
        if corrente and _larghezza(prova, grassetto) > larghezza:
            righe.append(corrente)
            corrente = parola
        else:
            corrente = prova
    return righe + [corrente] if corrente else righe or [""]


def _testo_con_blocchi(corpo, valori):
    """Testo compilato con le stesse righe vuote del modello: la struttura (blocchi) resta quella dello studio."""
    righe = []
    for riga in corpo.replace("\r", "").split("\n"):
        righe.append(compila_testo(riga.strip(), valori).replace("\n", " ") if riga.strip() else "")
    return "\n".join(righe)


