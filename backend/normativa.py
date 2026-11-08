"""Archivio normativo: testi ufficiali di legge (Normattiva, EUR-Lex) divisi per articolo.

Tre modi di trovare le norme, combinati in `cerca`:
- per riferimento esplicito ("art. 1385 c.c.", "art. 2 L. 431/1998"): si legge proprio quell'articolo;
- per parole (indice FTS5 di SQLite): disponibile subito dopo lo scaricamento;
- per significato (embedding bge-m3): calcolati in background, articolo dopo articolo.

Aggiornamento dei testi da riga di comando:  python -m backend.normativa aggiorna [--tutti]"""
import gzip
import html
import logging
import re
import sys
import threading
import time
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import date

import httpx
import numpy as np

from . import config, db, llm
from . import normativa_glossario as glossario
from .normativa_catalogo import EURLEX, NORMATTIVA

log = logging.getLogger("law_prog")

AKN = "{http://docs.oasis-open.org/legaldocml/ns/akn/3.0}"
RAW_DIR = config.DATA_DIR / "normativa"
PARTE_MAX = 1500          # caratteri: gli articoli più lunghi si dividono in parti, ai confini dei commi
EMBED_LOTTO = 4           # gruppi piccoli: una domanda dell'avvocato aspetta al massimo ~2 s il gruppo in corso
PAUSA_DOWNLOAD = 1.0      # secondi tra due richieste, per non sovraccaricare i siti istituzionali
USER_AGENT = "Flawless Project (assistente legale locale, open source)"

LATINI = sorted("bis ter quater quinquies sexies septies octies novies nonies decies undecies duodecies terdecies "
                "quaterdecies quinquiesdecies sexiesdecies septiesdecies octiesdecies".split(), key=len, reverse=True)
# Numero di articolo con eventuale suffisso latino: "2", "2-bis", "2 ter".
RE_NUMERO = re.compile(rf"(\d+)\s*[-.]?\s*({'|'.join(LATINI)})?\b", re.IGNORECASE)


def numero_articolo(testo):
    """'Art. 2-bis.' -> '2-bis'; 'Articolo 1385' -> '1385'."""
    m = RE_NUMERO.search(str(testo))
    if not m:
        return None
    return m.group(1) + (f"-{m.group(2).lower()}" if m.group(2) else "")


def _pulisci(testo):
    """Una riga di testo pulito: niente rinvii alle note e spazi normalizzati (anche gli a capo dell'XML)."""
    testo = html.unescape(testo)
    testo = re.sub(r"\(\(\s*\d{1,4}[a-z]?\s*\)\)", " ", testo)   # ((348)): rinvio a una nota di modifica
    testo = re.sub(r"\(\d{1,4}[a-z]?\)", " ", testo)              # (129a): rinvio a una nota
    testo = testo.replace("((", "").replace("))", "")              # (( testo modificato ))
    return re.sub(r"\s+", " ", testo).strip()


def _righe_pulite(blocchi):
    """I blocchi di testo ripuliti, uno per riga, senza quelli vuoti."""
    return "\n".join(r for r in (_pulisci(b) for b in blocchi) if r)


def _paragrafi(el):
    """Paragrafi di primo livello (quelli annidati sono già dentro il testo del genitore)."""
    for figlio in el:
        if figlio.tag == f"{AKN}paragraph":
            yield figlio
        else:
            yield from _paragrafi(figlio)


def _testo(el, salta=()):
    """Il testo di un elemento Akoma Ntoso, con un comma per riga. Gli elementi in salta si escludono."""
    if el is None:
        return ""
    blocchi = list(_paragrafi(el)) or [x for x in el if x.tag not in salta] or [el]
    return _righe_pulite("".join(b.itertext()) for b in blocchi)   # un comma per riga


# --- Lettura dei formati ufficiali -------------------------------------------------

def leggi_akn(contenuto):
    """Unità di testo di un atto in Akoma Ntoso: [(sezione, numero, rubrica, testo)].
    Nelle leggi ordinarie gli articoli sono elementi <article>; nei codici approvati con decreto
    (codice civile, c.p.a....) ogni articolo è un allegato <doc name="CODICE CIVILE-art. 1284">."""
    root = ET.fromstring(contenuto)
    corpo = root.find(f".//{AKN}act/{AKN}body")
    articoli = []
    for art in (corpo.iter(f"{AKN}article") if corpo is not None else []):
        num, rubrica = art.find(f"{AKN}num"), art.find(f"{AKN}heading")
        articoli.append(["", numero_articolo(num.text if num is not None else ""),
                         _pulisci("".join(rubrica.itertext())).strip("() .") if rubrica is not None else "",
                         _testo(art, salta=(f"{AKN}num", f"{AKN}heading"))])

    allegati = []
    for doc in root.iter(f"{AKN}doc"):
        nome = (doc.get("name") or "").strip()
        testo = _testo(doc.find(f"{AKN}mainBody"))
        m = re.match(r"(.*?)-\s*art\.?\s*(.+)$", nome, re.IGNORECASE)
        if not m:
            allegati.append([nome or "Allegato", None, nome, testo])
            continue
        # il testo comincia con eventuali intestazioni (Libro, Titolo...) e "Art. 1284. (Rubrica)."
        intestazione = re.search(r"Art\.\s*\d+(?:[\s-]*(?:" + "|".join(LATINI) + r"))?\s*\.?\s*(?:\(([^()]{0,200})\)\s*\.?)?",
                                 testo[:600], re.IGNORECASE)
        rubrica = (intestazione.group(1) or "").strip() if intestazione else ""
        if intestazione:
            testo = testo[intestazione.end():].strip()
        else:
            # alcuni codici (c.p.a.) scrivono la rubrica senza "Art.": "Azione di annullamento 1. L'azione..."
            senza_art = re.match(r"([^\n.;:]{3,160}?)\s+(1\.\s.*)", testo, re.S)
            if senza_art:
                rubrica, testo = senza_art.group(1).strip(), senza_art.group(2)
        allegati.append([m.group(1).strip(), numero_articolo(m.group(2)), rubrica, testo])

    numerati = [a for a in allegati if a[1]]
    # Il decreto che approva un codice ha pochi articoli (c.c.: 2, c.p.a.: 2); un codice con molti
    # articoli propri e allegati articolati (contratti pubblici) resta invece il corpo principale.
    if numerati and len(articoli) <= 5 and len(numerati) > len(articoli):
        # Codice in allegato: la parte più ampia è il corpo principale ("art. 1385 c.c."),
        # le altre restano sezioni distinte (preleggi) e gli articoli del decreto diventano "atto di approvazione".
        principale = Counter(a[0] for a in numerati).most_common(1)[0][0]
        for a in allegati:
            if a[0] == principale:
                a[0] = ""
        for a in articoli:
            a[0] = "Atto di approvazione"
    return [tuple(u) for u in articoli + allegati if u[3].strip()]


def leggi_eurlex(pagina):
    """Articoli di un atto UE dalla pagina HTML di EUR-Lex (i considerando restano fuori)."""
    pagina = pagina.split('class="oj-final"')[0]
    unita = []
    for blocco in re.split(r'(?=<p[^>]*class="oj-ti-art"[^>]*>)', pagina)[1:]:
        num = re.search(r'class="oj-ti-art"[^>]*>\s*Articolo\s+(\d+[\w-]*)', blocco)
        if not num:
            continue
        rubrica = re.search(r'class="oj-sti-art"[^>]*>(.*?)</p>', blocco, re.S)
        corpo = blocco[(rubrica or num).end():]
        corpo = re.sub(r"<[^>]+>", " ", re.sub(r"</p>|<br\s*/?>|</tr>", "\n", corpo))
        testo = _righe_pulite(corpo.split("\n"))
        testo = re.sub(r"(?m)^(\(?[a-z0-9]{1,3}\))\n", r"\1 ", testo)   # "a)" e il suo testo sulla stessa riga
        unita.append(("", numero_articolo(num.group(1)),
                      _pulisci(re.sub(r"<[^>]+>", " ", rubrica.group(1))) if rubrica else "", testo))
    return unita


def dividi(testo, massimo=PARTE_MAX):
    """Divide un articolo lungo ai confini dei commi (righe), poi delle frasi."""
    if len(testo) <= massimo:
        return [testo]
    pezzi = []
    for riga in testo.split("\n"):
        pezzi.extend(re.split(r"(?<=[.;:])\s+", riga) if len(riga) > massimo else [riga])
    parti, corrente = [], ""
    for pezzo in pezzi:
        if corrente and len(corrente) + len(pezzo) + 1 > massimo:
            parti.append(corrente)
            corrente = ""
        corrente = f"{corrente}\n{pezzo}" if corrente else pezzo
    if corrente:
        parti.append(corrente)
    return parti


# --- Scaricamento e importazione ---------------------------------------------------

def _scarica_normattiva(client, urn):
    """Il file Akoma Ntoso di un atto, vigente oggi. Serve prima la pagina dell'atto, che ne contiene i codici."""
    pagina = client.get(f"https://www.normattiva.it/uri-res/N2Ls?{urn}")
    pagina.raise_for_status()
    m = re.search(r"caricaAKN\?dataGU=(\d+)&(?:amp;)?codiceRedaz=(\w+)", pagina.text)
    if not m:
        raise RuntimeError("atto non trovato su Normattiva")
    time.sleep(PAUSA_DOWNLOAD)
    r = client.get("https://www.normattiva.it/do/atto/caricaAKN",
                   params={"dataGU": m.group(1), "codiceRedaz": m.group(2), "dataVigenza": f"{date.today():%Y%m%d}"})
    r.raise_for_status()
    if b"akomaNtoso" not in r.content[:2000]:
        raise RuntimeError("Normattiva non ha restituito un file Akoma Ntoso")
    return r.content


def _scarica_eurlex(client, celex):
    """Il testo italiano di un atto dell'Unione europea, dato il suo codice CELEX."""
    # Il sito EUR-Lex chiede una verifica anti-robot ai programmi: si usa Cellar, il servizio ufficiale
    # dell'Ufficio delle pubblicazioni dell'UE pensato per l'accesso automatico agli stessi testi.
    r = client.get(f"https://publications.europa.eu/resource/celex/{celex}",
                   headers={"Accept": "application/xhtml+xml, text/html;q=0.9", "Accept-Language": "ita"})
    r.raise_for_status()
    if "oj-ti-art" not in r.text or "Articolo" not in r.text:
        raise RuntimeError("Il servizio dell'Unione europea non ha restituito il testo italiano dell'atto")
    return r.content


def _importa(conn, area, sigla, titolo, fonte, urn, unita):
    """Sostituisce un atto nell'archivio con la versione appena letta, conservando gli embedding del testo invariato."""
    # Gli embedding degli articoli rimasti identici si conservano: niente ricalcolo dopo un aggiornamento.
    vecchi = {(r["sezione"], r["articolo"], r["parte"], r["testo"]): r["embedding"] for r in conn.execute(
        """SELECT n.sezione, n.articolo, n.parte, n.testo, n.embedding FROM norme n JOIN norme_atti a ON a.id = n.atto_id
           WHERE a.sigla = ? AND n.embedding IS NOT NULL""", (sigla,))}
    conn.execute("""INSERT INTO norme_fts(norme_fts, rowid, rubrica, testo)
                    SELECT 'delete', n.id, n.rubrica, n.testo FROM norme n JOIN norme_atti a ON a.id = n.atto_id
                    WHERE a.sigla = ?""", (sigla,))
    conn.execute("DELETE FROM norme_atti WHERE sigla = ?", (sigla,))
    atto_id = conn.execute(
        "INSERT INTO norme_atti (sigla, titolo, area, fonte, urn, vigente_al) VALUES (?, ?, ?, ?, ?, ?)",
        (sigla, titolo, area, fonte, urn, date.today().isoformat())).lastrowid
    righe = []
    for sezione, numero, rubrica, testo in unita:
        for i, parte in enumerate(dividi(testo)):
            righe.append((atto_id, sezione, numero, rubrica, i, parte, vecchi.get((sezione, numero, i, parte))))
    conn.executemany("INSERT INTO norme (atto_id, sezione, articolo, rubrica, parte, testo, embedding) "
                     "VALUES (?, ?, ?, ?, ?, ?, ?)", righe)
    conn.execute("INSERT INTO norme_fts(rowid, rubrica, testo) SELECT id, rubrica, testo FROM norme WHERE atto_id = ?",
                 (atto_id,))
    return len({(u[0], u[1]) for u in unita if u[1]}), len(righe)


def catalogo(tutti=False):
    """Gli atti da scaricare come (area, sigla, titolo, fonte, urn). Con tutti=True anche quelli facoltativi."""
    voci = [(area, sigla, titolo, "Normattiva", urn) for area, sigla, titolo, urn, attivo in NORMATTIVA if attivo or tutti]
    voci += [(area, sigla, titolo, "EUR-Lex", f"celex:{celex}") for area, sigla, titolo, celex, attivo in EURLEX
             if attivo or tutti]
    return voci


_in_corso = threading.Lock()
avanzamento = {"attivo": False, "fatti": 0, "totale": 0, "atto": "", "errori": []}


def aggiorna(tutti=False, solo=None, stampa=log.info, locale=False):
    """Scarica dai siti ufficiali e importa gli atti del catalogo. Restituisce l'elenco degli errori.
    `locale=True` rilegge le copie già scaricate (dopo una correzione della lettura), senza rete."""
    if not _in_corso.acquire(blocking=False):
        raise RuntimeError("Aggiornamento della normativa già in corso")
    voci = [v for v in catalogo(tutti) if not solo or v[1] in solo]
    avanzamento.update(attivo=True, fatti=0, totale=len(voci), atto="", errori=[])
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    try:
        with httpx.Client(timeout=600, follow_redirects=True, headers={"User-Agent": USER_AGENT}) as client:
            for area, sigla, titolo, fonte, urn in voci:
                avanzamento["atto"] = sigla
                t0 = time.perf_counter()
                try:
                    # copia del testo ufficiale com'era il giorno dello scaricamento
                    copia = RAW_DIR / f"{re.sub(r'[^\w]+', '_', sigla).strip('_')}.{'xml' if fonte == 'Normattiva' else 'html'}.gz"
                    if locale:
                        contenuto = gzip.decompress(copia.read_bytes())
                    elif fonte == "Normattiva":
                        contenuto = _scarica_normattiva(client, urn)
                    else:
                        contenuto = _scarica_eurlex(client, urn.split(":", 1)[1])
                    unita = (leggi_akn(contenuto) if fonte == "Normattiva"
                             else leggi_eurlex(contenuto.decode("utf-8", errors="replace")))
                    if not unita:
                        raise RuntimeError("nessun articolo riconosciuto nel testo")
                    if not locale:
                        copia.write_bytes(gzip.compress(contenuto))
                    with db.session() as conn:
                        articoli, parti = _importa(conn, area, sigla, titolo, fonte, urn, unita)
                    stampa(f"{sigla:24} {articoli:5} articoli, {parti:5} parti, "
                           f"{len(contenuto) / 1e6:5.1f} MB in {time.perf_counter() - t0:4.0f} s")
                except Exception as exc:
                    avanzamento["errori"].append(f"{sigla}: {exc}")
                    stampa(f"{sigla:24} ERRORE: {exc}")
                avanzamento["fatti"] += 1
                if not locale:
                    time.sleep(PAUSA_DOWNLOAD)
        _cache["n"] = -1
        _indici["n"] = -1
        return avanzamento["errori"]
    finally:
        avanzamento.update(attivo=False, atto="")
        _in_corso.release()


# --- Indicizzazione semantica (in background) ----------------------------------------

def etichetta(articolo, sigla, sezione=""):
    """Il nome di un articolo mostrato all'utente, per esempio art. 1454 c.c."""
    if not articolo:
        return f"{sezione or 'Allegato'} – {sigla}"
    if sezione and sezione != "Atto di approvazione":
        return f"art. {articolo} {sezione.lower().capitalize()} ({sigla})"
    if sezione:
        return f"art. {articolo} {sigla} (atto di approvazione)"
    return f"art. {articolo} {sigla}"


PRIORITARI = ["c.c.", "c.p.c.", "Cost.", "c.p.", "c.p.p."]
# Senza un atto indicato valgono le regole generali: un testo speciale (es. processo minorile) non deve scavalcare il codice.
BONUS_CODICI = 0.06
MARGINE_NORME = 0.06
# "appello penale" non deve finire sull'appello civile o amministrativo
BONUS_MATERIA = 0.04
# Parole che collocano la domanda in materia penale: "reato", "querela", "imputato".
RE_PENALE = re.compile(r"\b(?:penal\w*|reat[oi]|imputat\w+|indagat\w+|querel\w+)\b", re.IGNORECASE)
# Parole che collocano la domanda in materia civile: "civile", "civilmente".
RE_CIVILE = re.compile(r"\bcivil\w*\b", re.IGNORECASE)
AREA_RACCOLTA = "Raccolta Normattiva"   # atti cercabili per riferimento e per parole, senza indice semantico
_NEL_CATALOGO = f"(SELECT id FROM norme_atti WHERE area != '{AREA_RACCOLTA}')"


def da_indicizzare():
    """Restano articoli del catalogo senza embedding?"""
    with db.session() as conn:
        return conn.execute(f"SELECT EXISTS(SELECT 1 FROM norme WHERE embedding IS NULL AND atto_id IN {_NEL_CATALOGO})").fetchone()[0] == 1


def conteggi():
    """Numeri per la barra di stato. Solo gli atti principali: contare tutta la raccolta sarebbe lento."""
    with db.session() as conn:
        parti, indicizzate = conn.execute(f"SELECT COUNT(*), COUNT(embedding) FROM norme WHERE atto_id IN {_NEL_CATALOGO}").fetchone()
        atti = conn.execute(f"SELECT COUNT(*) FROM norme_atti WHERE area != '{AREA_RACCOLTA}'").fetchone()[0]
        raccolta = conn.execute(f"SELECT COUNT(*) FROM norme_atti WHERE area = '{AREA_RACCOLTA}'").fetchone()[0]
    return {"atti": atti, "parti": parti, "indicizzate": indicizzate, "raccolta": raccolta}


def indicizza_lotto():
    """Calcola gli embedding del prossimo gruppo di articoli; restituisce quanti ne ha fatti."""
    # prima i codici più usati, poi gli altri atti dal più breve: diventano completi il prima possibile
    with db.session() as conn:
        righe = conn.execute(f"""SELECT n.id, n.sezione, n.articolo, n.rubrica, n.testo, a.sigla
                                FROM norme n JOIN norme_atti a ON a.id = n.atto_id
                                WHERE n.embedding IS NULL AND a.area != '{AREA_RACCOLTA}'
                                ORDER BY CASE a.sigla {' '.join(f"WHEN '{s}' THEN {i}" for i, s in enumerate(PRIORITARI))}
                                         ELSE {len(PRIORITARI)} END,
                                         (SELECT COUNT(*) FROM norme x WHERE x.atto_id = n.atto_id), n.id
                                LIMIT ?""", (EMBED_LOTTO,)).fetchall()
    if not righe:
        return 0
    vettori = llm.embed([f"{etichetta(r['articolo'], r['sigla'], r['sezione'])}. {r['rubrica']}\n{r['testo']}"
                         for r in righe])
    with db.session() as conn:
        conn.executemany("UPDATE norme SET embedding = ? WHERE id = ?",
                         [(db.to_blob(v), r["id"]) for v, r in zip(vettori, righe)])
    return len(righe)


def stato():
    """Gli atti del catalogo con i conteggi, lo stato dell'aggiornamento e il numero di atti della raccolta."""
    with db.session() as conn:
        atti = db.rows(conn.execute("""
            SELECT a.id, a.sigla, a.titolo, a.area, a.fonte, a.urn, a.vigente_al,
                   COUNT(DISTINCT n.sezione || '|' || COALESCE(n.articolo, n.id)) AS articoli,
                   COUNT(n.id) AS parti, COUNT(n.embedding) AS indicizzate
            FROM norme_atti a LEFT JOIN norme n ON n.atto_id = a.id
            WHERE a.area != ? GROUP BY a.id ORDER BY a.id""", (AREA_RACCOLTA,)))
        raccolta = conn.execute("SELECT COUNT(*) FROM norme_atti WHERE area = ?", (AREA_RACCOLTA,)).fetchone()[0]
    for a in atti:
        a["url"] = url_atto(a["urn"])
    parti = sum(a["parti"] for a in atti)
    return {"atti": atti, "parti": parti, "indicizzate": sum(a["indicizzate"] for a in atti),
            "aggiornamento": dict(avanzamento), "catalogo": len(catalogo()), "raccolta": raccolta}


# --- Ricerca ----------------------------------------------------------------------

def url_atto(urn, articolo=None):
    """Il collegamento alla fonte ufficiale di un atto o, per Normattiva, di un suo articolo."""
    if urn.startswith("celex:"):
        return f"https://eur-lex.europa.eu/legal-content/IT/TXT/HTML/?uri=CELEX:{urn[6:]}"
    return f"https://www.normattiva.it/uri-res/N2Ls?{urn}" + (f"~art{articolo.replace('-', '')}" if articolo else "")


# Come si chiamano gli atti nelle domande, oltre alla sigla del catalogo.
ALIAS = {
    "c.c.": ["c.c", "cod. civ.", "codice civile"],
    "c.p.c.": ["c.p.c", "cod. proc. civ.", "codice di procedura civile"],
    "c.p.": ["c.p", "cod. pen.", "codice penale"],
    "c.p.p.": ["c.p.p", "cod. proc. pen.", "codice di procedura penale"],
    "Cost.": ["costituzione", "cost"],
    "c.p.a.": ["codice del processo amministrativo"],
    "C.d.S.": ["c.d.s", "cds", "codice della strada"],
    "Cod. consumo": ["cod. cons.", "codice del consumo"],
    "Cod. privacy": ["codice privacy", "codice della privacy", "codice in materia di protezione dei dati personali"],
    "GDPR": ["regolamento (ue) 2016/679", "reg. ue 2016/679", "regolamento generale sulla protezione dei dati"],
    "CCII": ["codice della crisi", "codice della crisi d'impresa"],
    "c.p.i.": ["codice della proprietà industriale"],
    "CAD": ["codice dell'amministrazione digitale"],
    "CTS": ["codice del terzo settore"],
    "Cod. antimafia": ["codice antimafia"],
    "Cod. contratti pubblici": ["codice dei contratti pubblici", "codice appalti"],
    "Cod. ass. priv.": ["codice delle assicurazioni"],
    "L. 300/1970": ["statuto dei lavoratori"],
    "D.P.R. 115/2002": ["testo unico spese di giustizia", "t.u. spese di giustizia"],
    "D.P.R. 380/2001": ["testo unico edilizia", "t.u. edilizia"],
    "D.Lgs. 286/1998": ["testo unico immigrazione", "t.u. immigrazione"],
    "TUB": ["testo unico bancario", "t.u.b"],
    "TUF": ["testo unico della finanza", "t.u.f"],
    "TUEL": ["testo unico enti locali", "testo unico degli enti locali", "t.u.e.l"],
    "TUIR": ["testo unico imposte sui redditi", "testo unico delle imposte sui redditi", "t.u.i.r"],
    "L. 212/2000": ["statuto del contribuente", "statuto dei diritti del contribuente"],
    "R.D. 267/1942": ["legge fallimentare"],
    "L. 354/1975": ["ordinamento penitenziario"],
    "D.Lgs. 81/2008": ["testo unico sicurezza", "testo unico salute e sicurezza"],
    "Cod. ambiente": ["codice dell'ambiente", "testo unico ambientale"],
}
# Citazione di un atto: "L. 604/1966", "d.lgs. n. 81 del 2008". Cattura tipo, numero e anno.
RE_LEGGE = re.compile(r"(?<![\w.])(legge|l\.|d\.\s?lgs\.?|dlgs\.?|decreto legislativo|d\.\s?l\.|decreto[- ]legge|d\.\s?p\.\s?r\.?|dpr|"
                      r"decreto del presidente della repubblica|d\.\s?m\.?|decreto ministeriale|r\.\s?d\.?|regio decreto)"
                      r"\s*(?:n\.?\s*)?(\d+)\s*(?:/\s*|\s+del\s+(?:\d{1,2}\s+\w+\s+)?)(\d{4})", re.IGNORECASE)
# Riferimento ad articolo con suffisso latino: "art. 18", "articolo 2-bis". Cattura il numero.
RE_ARTICOLO = re.compile(rf"\bart(?:icol[oi]|t)?\.?\s*(\d+(?:\s*[-]?\s*(?:{'|'.join(LATINI)})\b)?)", re.IGNORECASE)
# Sigla di un atto della raccolta: "D.Lgs. 81/2008". Cattura tipo, numero e anno.
RE_SIGLA_NUMERO = re.compile(r"(L\.|D\.Lgs\.|D\.P\.R\.|D\.L\.|D\.M\.|R\.D\.)\s*(\d+)/(\d{4})")
# Parte utile di un URN di Normattiva: "stato:legge:1966-07-15;604" dà tipo, anno e numero.
RE_URN = re.compile(r"stato:([a-z.]+):(\d{4})-\d\d-\d\d;(\d+)")
TIPI_URN = {"legge": "l", "decreto.legislativo": "dlgs", "decreto.legge": "dl", "regio.decreto": "rd",
            "decreto.del.presidente.della.repubblica": "dpr"}
_indici = {"n": -1, "valori": None}


def _tipo_legge(testo):
    """'decreto legislativo', 'D.Lgs.', 'dlgs' -> 'dlgs': "L. 81/2015" e "D.Lgs. 81/2015" sono atti diversi."""
    t = re.sub(r"[\s.]", "", testo.lower())
    return {"legge": "l", "l": "l", "dlgs": "dlgs", "decretolegislativo": "dlgs", "dl": "dl", "decreto-legge": "dl", "decretolegge": "dl",
            "dpr": "dpr", "decretodelpresidentedellarepubblica": "dpr", "dm": "dm", "decretoministeriale": "dm",
            "rd": "rd", "regiodecreto": "rd"}.get(t, t)


def _indici_atti():
    """Le tabelle per riconoscere gli atti citati, per nome e per numero. Si ricalcolano solo se cambiano gli atti."""
    with db.session() as conn:
        n = conn.execute("SELECT MAX(rowid) FROM norme_atti").fetchone()[0] or 0
        if n == _indici["n"]:
            return _indici["valori"]
        atti = db.rows(conn.execute("SELECT id, sigla, titolo, area, urn FROM norme_atti"))
    nomi, numeri = {}, {}
    for a in atti:
        if a["area"] == AREA_RACCOLTA:   # si citano per tipo e numero: i loro nomi non servono
            numeri.update(((_tipo_legge(t), num, anno), a["id"]) for t, num, anno in RE_SIGLA_NUMERO.findall(a["sigla"]))
    for a in atti:
        if a["area"] == AREA_RACCOLTA:
            continue
        for nome in [a["sigla"], *ALIAS.get(a["sigla"], [])]:
            nomi[nome.lower().rstrip(".")] = a["id"]
        for t, num, anno in RE_SIGLA_NUMERO.findall(f"{a['sigla']} {a['titolo']}"):
            numeri[(_tipo_legge(t), num, anno)] = a["id"]   # gli atti principali prevalgono sulla raccolta
        # i codici si citano anche con l'atto che li approva: "R.D. 262/1942" è il codice civile
        for t, anno, num in RE_URN.findall(a["urn"] or ""):
            if t in TIPI_URN:
                numeri[(TIPI_URN[t], num, anno)] = a["id"]
    re_nomi = re.compile(r"(?<![\w.])(" + "|".join(re.escape(x) for x in sorted(nomi, key=len, reverse=True))
                         + r")\.?(?![\w])", re.IGNORECASE) if nomi else None
    _indici.update(n=n, valori=(nomi, numeri, re_nomi))
    return _indici["valori"]


def _atto_della_legge(numeri, m):
    """L'id dell'atto corrispondente a una citazione trovata con RE_LEGGE, oppure None."""
    return numeri.get((_tipo_legge(m.group(1)), m.group(2), m.group(3)))


def atti_nominati(domanda):
    """Atti nominati nella domanda anche senza un numero di articolo ("nel codice penale...")."""
    nomi, numeri, re_nomi = _indici_atti()
    trovati = [nomi[m.group(1).lower().rstrip(".")] for m in re_nomi.finditer(domanda)] if re_nomi else []
    trovati += [a for a in (_atto_della_legge(numeri, m) for m in RE_LEGGE.finditer(domanda)) if a]
    return list(dict.fromkeys(trovati))


def atti_assenti(domanda):
    """Atti citati per tipo e numero che non sono nell'archivio, e cosa resta della domanda togliendo le citazioni."""
    _, numeri, _ = _indici_atti()
    assenti = [re.sub(r"\s+", " ", m.group(0)) for m in RE_LEGGE.finditer(domanda) if not _atto_della_legge(numeri, m)]
    return list(dict.fromkeys(assenti)), RE_LEGGE.sub(" ", domanda)


def riferimenti(domanda):
    """Articoli citati esplicitamente nella domanda: [(atto_id, articolo)]."""
    nomi, numeri, re_nomi = _indici_atti()
    if not nomi:
        return []
    trovati = []
    for m in RE_ARTICOLO.finditer(domanda):
        coda = domanda[m.end():m.end() + 90]
        coda = re.sub(r"^\s*,?\s*(?:comma|co\.|c\.)\s*\d+\w*\s*,?|^\s*,?\s*lett(?:era|\.)\s*\w\)?\s*,?", "", coda,
                      flags=re.IGNORECASE)
        atto = None
        legge, nome = RE_LEGGE.search(coda), re_nomi.search(coda)
        if legge and (not nome or legge.start() <= nome.start()):
            atto = _atto_della_legge(numeri, legge)
        elif nome and nome.start() < 25:
            atto = nomi.get(nome.group(1).lower().rstrip("."))
        if not atto:   # atto scritto prima dell'articolo: "D.Lgs. 81/2008, art. 18", "c.c. art. 1385"
            prima = domanda[max(0, m.start() - 40):m.start()]
            legge = next(iter(reversed(list(RE_LEGGE.finditer(prima)))), None)
            nome = next(iter(reversed(list(re_nomi.finditer(prima)))), None)
            if legge:
                atto = _atto_della_legge(numeri, legge)
            elif nome and not prima[nome.end():].strip(" ,;:.-–"):
                atto = nomi.get(nome.group(1).lower().rstrip("."))
        if atto:
            trovati.append((atto, numero_articolo(m.group(1))))
    return list(dict.fromkeys(trovati))


STOPWORD = set("""il lo la i gli le un uno una di a da in con su per tra fra e o ed od ma se che chi cosa come quale quali
quanto quanta quanti quante quando dove del dello della dei degli delle al allo alla ai agli alle dal dallo dalla dai
dagli dalle nel nello nella nei negli nelle sul sullo sulla sui sugli sulle è e' sono essere ha hanno ho può possono
puo deve devono non si ci mi ti vi ne anche più piu molto entro dopo prima mio mia tuo suo sua nostro loro questo
questa questi quello quella cui art articolo articoli legge codice norma norme prevede previsto prevista dice stabilisce
fare fa caso casi tempo cosa serve bisogna qual cos""".split())
COPERTURA_MINIMA = 0.6    # quota delle parole della domanda che un articolo trovato solo per parole deve contenere


def _termini(testo):
    """Le parole utili di una domanda, ridotte alla radice e al massimo 12, per la ricerca testuale."""
    parole = [p for p in re.findall(r"[^\W\d_]+|\d+", testo.lower()) if p not in STOPWORD and len(p) > 2]
    # radice approssimata: "locazione", "locazioni", "locatore" -> locaz*
    return [p[:max(5, len(p) - 3)] + "*" if len(p) > 6 else p for p in dict.fromkeys(parole)][:12]


def _query_fts(testo):
    """La domanda scritta come ricerca FTS5: basta che compaia uno dei termini."""
    return " OR ".join(_termini(testo))


def _copre_la_domanda(riga, testo):
    """L'articolo contiene una quota sufficiente delle parole della domanda?"""
    termini = _termini(testo)
    articolo_testo = f"{riga['rubrica']} {riga['testo']}".lower()
    presenti = sum(bool(re.search(rf"\b{re.escape(t.rstrip('*'))}", articolo_testo)) for t in termini)
    return bool(termini) and presenti / len(termini) >= COPERTURA_MINIMA


def cerca_parole(testo, atti=None, limite=30, senza_indice=False, raccolta=False):
    """Ricerca per parole negli atti principali o, con `raccolta=True`, nella raccolta generale:
    lì devono esserci tutte le parole, perché tra tanti atti una sola parola in comune non significa nulla."""
    termini = _termini(testo)
    if not termini:
        return []
    query = " ".join(termini) if raccolta else " OR ".join(termini)
    tabella = "raccolta_fts" if raccolta else "norme_fts"
    filtro = f" AND n.atto_id IN ({','.join('?' * len(atti))})" if atti else ""
    if senza_indice:
        filtro += " AND n.embedding IS NULL"
    with db.session() as conn:
        try:
            return [r[0] for r in conn.execute(
                f"""SELECT n.id FROM {tabella} f JOIN norme n ON n.id = f.rowid
                    WHERE {tabella} MATCH ?{filtro} ORDER BY bm25({tabella}, 3.0, 1.0) LIMIT ?""",
                [query, *(atti or []), limite])]
        except Exception as exc:   # sintassi FTS imprevista: meglio nessun risultato che un errore
            log.warning("Ricerca per parole non riuscita (%s): %s", query, exc)
            return []


_cache = {"n": -1, "ids": None, "atti": None, "matrice": None}
_cache_lock = threading.Lock()


def _matrice():
    """Id, atti ed embedding di tutti gli articoli indicizzati, in memoria; si rileggono solo se il numero cambia."""
    with _cache_lock, db.session() as conn:
        n = conn.execute("SELECT COUNT(*) FROM norme WHERE embedding IS NOT NULL").fetchone()[0]
        if n != _cache["n"]:
            righe = conn.execute("SELECT id, atto_id, embedding FROM norme WHERE embedding IS NOT NULL").fetchall()
            _cache.update(n=n, ids=np.array([r[0] for r in righe]), atti=np.array([r[1] for r in righe]),
                          matrice=np.stack([db.from_blob(r[2]) for r in righe]) if righe else None)
        return _cache["ids"], _cache["atti"], _cache["matrice"]


def _id_codici(sigle=PRIORITARI):
    """Gli id degli atti con queste sigle."""
    with db.session() as conn:
        return [r[0] for r in conn.execute(
            f"SELECT id FROM norme_atti WHERE sigla IN ({','.join('?' * len(sigle))})", list(sigle))]


def cerca_significato(testo, atti=None, limite=30, margine=None):
    """`margine`: scarta ciò che è molto meno pertinente del migliore. Ogni articolo inutile costa secondi di lettura
    e può portare il modello fuori strada."""
    ids, atti_righe, matrice = _matrice()
    if matrice is None:
        return []
    punteggi = matrice @ llm.embed([testo])[0]
    if atti:
        punteggi = np.where(np.isin(atti_righe, atti), punteggi, -1)
    else:
        punteggi = punteggi + BONUS_CODICI * np.isin(atti_righe, _id_codici())
        if RE_PENALE.search(testo):
            punteggi = punteggi + BONUS_MATERIA * np.isin(atti_righe, _id_codici(("c.p.", "c.p.p.")))
        if RE_CIVILE.search(testo):
            punteggi = punteggi + BONUS_MATERIA * np.isin(atti_righe, _id_codici(("c.c.", "c.p.c.")))
    soglia = punteggi.max() - margine if margine is not None else 0
    return [int(ids[i]) for i in np.argsort(-punteggi)[:limite] if punteggi[i] > 0 and punteggi[i] >= soglia]


_CAMPI_ATTO = "a.sigla, a.titolo, a.urn, a.fonte AS fonte_atto, a.vigente_al, a.area"


def _righe(conn, ids):
    """Le righe degli articoli richiesti con i dati dell'atto, indicizzate per id."""
    if not ids:
        return {}
    righe = conn.execute(f"""SELECT n.*, {_CAMPI_ATTO} FROM norme n JOIN norme_atti a ON a.id = n.atto_id
                             WHERE n.id IN ({','.join('?' * len(ids))})""", ids).fetchall()
    return {r["id"]: dict(r) for r in righe}


def _fonte(riga, testo=None):
    """Una riga dell'archivio nel formato usato da risposte e interfaccia."""
    return {"norma_id": riga["id"], "atto": riga["sigla"], "titolo_atto": riga["titolo"], "articolo": riga["articolo"],
            "rubrica": riga["rubrica"], "sezione": riga["sezione"],
            "etichetta": etichetta(riga["articolo"], riga["sigla"], riga["sezione"]),
            "text": testo if testo is not None else riga["testo"], "atto_id": riga["atto_id"],
            "fonte": riga["fonte_atto"], "vigente_al": riga["vigente_al"], "raccolta": riga["area"] == AREA_RACCOLTA,
            "url": url_atto(riga["urn"], riga["articolo"] if not riga["sezione"] else None)}


def articolo(atto_id, numero, sezione="", massimo=3000):
    """Testo intero di un articolo (tutte le parti), troncato a `massimo` caratteri per il prompt."""
    with db.session() as conn:
        parti = conn.execute(f"""SELECT n.*, {_CAMPI_ATTO} FROM norme n JOIN norme_atti a ON a.id = n.atto_id
                                WHERE n.atto_id = ? AND n.articolo = ? AND n.sezione = ? ORDER BY n.parte""",
                             (atto_id, numero, sezione)).fetchall()
    if not parti:
        return None
    testo = "\n".join(p["testo"] for p in parti)
    return _fonte(dict(parti[0]), testo if len(testo) <= massimo else testo[:massimo] + " […]")


# Inizio di una nota nel testo di Normattiva: "--------- AGGIORNAMENTO".
RE_NOTA = re.compile(r"-{3,}\s*AGGIORNAMENTO", re.IGNORECASE)
# Parole delle note che possono cambiare la risposta.
NOTE_DA_TENERE = re.compile(r"illegittimit|corte costituzionale|abrogat|\beuro\b", re.IGNORECASE)
ANNO_NOTE_RECENTI = 2015
MASSIMO_PER_MODELLO = 3000
NOTE_PER_MODELLO = 800


def _nota_utile(nota):
    """Le note che possono cambiare la risposta: incostituzionalità, abrogazioni, importi, riforme recenti."""
    return bool(NOTE_DA_TENERE.search(nota)) or any(
        int(anno) >= ANNO_NOTE_RECENTI for anno in re.findall(r"\b(?:19|20)\d\d\b", nota))


def togli_note_storiche(testo):
    """Toglie le note di aggiornamento solo storiche: allungano la lettura sulla CPU e non cambiano la risposta."""
    corpo, *note = RE_NOTA.split(testo)
    utili = [f"AGGIORNAMENTO: {n.strip()}" for n in note if _nota_utile(n)]
    return "\n".join([corpo.rstrip(), *utili]).strip()


def _parti_pertinenti(fonte, domanda, massimo):
    """Articolo lungo: le parti più vicine alla domanda, in ordine, più le note che possono cambiare la risposta.
    Leggere solo l'inizio perderebbe i commi successivi. Usa gli embedding già salvati: nessun calcolo sul testo."""
    with db.session() as conn:
        parti = conn.execute("SELECT parte, testo, embedding FROM norme WHERE atto_id = ? AND articolo = ? AND sezione = ? ORDER BY parte",
                             (fonte["atto_id"], fonte["articolo"], fonte["sezione"])).fetchall()
    if not domanda or len(parti) < 2 or any(p["embedding"] is None for p in parti):
        return None
    corpi, in_nota = [], False
    for p in parti:
        corpo = "" if in_nota else RE_NOTA.split(p["testo"], maxsplit=1)[0].strip()
        in_nota = in_nota or bool(RE_NOTA.search(p["testo"]))
        corpi.append(corpo)
    _, *note = RE_NOTA.split("\n".join(p["testo"] for p in parti))
    utili = sorted((n.strip() for n in note if _nota_utile(n)), key=lambda n: not re.search("illegittimit", n, re.IGNORECASE))
    testo_note = "\n".join(f"AGGIORNAMENTO: {n}" for n in utili)[:NOTE_PER_MODELLO]
    domanda_vettore = llm.embed([domanda])[0]
    punteggi = [float(db.from_blob(p["embedding"]) @ domanda_vettore) for p in parti]
    # l'inizio dell'articolo c'è sempre: contiene la regola principale ("Cosa stabilisce l'art. 18?" non ha parole utili per scegliere)
    scelte, usati = {0}, len(testo_note) + len(corpi[0])
    for i in sorted((i for i, c in enumerate(corpi) if c and i), key=lambda i: -punteggi[i]):
        if usati + len(corpi[i]) <= massimo:
            scelte.add(i)
            usati += len(corpi[i])
    pezzi, ultimo = [], -1
    for i in sorted(scelte):
        pezzi.append(("[…]\n" if i != ultimo + 1 else "") + corpi[i])
        ultimo = i
    if any(corpi[i] for i in range(ultimo + 1, len(corpi))):
        pezzi.append("[…]")
    return "\n".join([*pezzi, *([testo_note] if testo_note else [])])


def testo_per_modello(fonte, domanda="", massimo=MASSIMO_PER_MODELLO):
    """Il testo di una fonte da dare al modello; l'avvocato continua a vedere l'articolo con tutte le note."""
    testo = fonte["text"]
    if testo.endswith(" […]") and fonte["articolo"]:   # il taglio potrebbe aver escluso una nota importante
        testo = articolo(fonte["atto_id"], fonte["articolo"], fonte["sezione"], massimo=10 ** 7)["text"]
    elif fonte["articolo"]:
        # una parte centrale di un articolo lungo può contenere solo il seguito di una nota
        with db.session() as conn:
            prima = conn.execute("""SELECT p.testo FROM norme n JOIN norme p ON p.atto_id = n.atto_id AND p.sezione = n.sezione
                                    AND p.articolo = n.articolo AND p.parte < n.parte
                                    WHERE n.id = ? ORDER BY p.parte""", (fonte["norma_id"],)).fetchall()
        if any(RE_NOTA.search(p[0]) for p in prima) and not _nota_utile(testo):
            testo = prima[0][0]
    pulito = togli_note_storiche(testo)
    if len(pulito) <= massimo:
        return pulito
    scelte = fonte["articolo"] and _parti_pertinenti(fonte, domanda, massimo)
    return scelte or pulito[:massimo] + " […]"


def _inizio_atti(atti):
    """Domanda su un atto senza parole utili ("cosa dice la legge 194/1978?"): i suoi primi articoli."""
    with db.session() as conn:
        return [r[0] for r in conn.execute(
            f"SELECT id FROM norme WHERE atto_id IN ({','.join('?' * len(atti))}) AND parte = 0 ORDER BY id LIMIT 6", atti)]


def _dal_glossario(domanda):
    """Gli articoli indicati dal glossario per i termini della domanda."""
    voci = glossario.articoli(domanda)
    if not voci:
        return []
    with db.session() as conn:
        id_atti = {r[0]: r[1] for r in conn.execute(
            f"SELECT sigla, id FROM norme_atti WHERE sigla IN ({','.join('?' * len(voci))})", [s for s, _ in voci])}
    trovati = (articolo(id_atti[s], n) for s, n in voci if s in id_atti)
    return [f for f in trovati if f]


def cerca(domanda, k=None, atti=None, contesto=""):
    """Le norme più utili per la domanda: prima gli articoli citati, poi quelli vicini per significato.
    La ricerca per parole serve dove il significato non arriva, cioè per gli articoli non ancora indicizzati."""
    k = k or config.TOP_K
    fonti = []
    for atto_id, numero in riferimenti(domanda):
        if atti and atto_id not in atti:
            continue
        trovato = articolo(atto_id, numero)
        if trovato:
            fonti.append(trovato)
    # Con un articolo citato esplicitamente la risposta è lì: altri articoli allungherebbero solo i tempi
    # (sulla CPU ogni articolo costa secondi di lettura). La ricerca approfondita li aggiunge comunque.
    if fonti and k <= config.TOP_K:
        k = len(fonti)
    if not fonti and not atti and not atti_nominati(domanda):
        fonti = _dal_glossario(domanda)[:k]
    if len(fonti) < k:
        testo = f"{contesto} {domanda}".strip()
        # "nel codice penale..." senza numero di articolo: si cerca solo in quel codice
        ambito = atti or atti_nominati(domanda) or None
        # Misurato su domande di prova: dove un articolo è indicizzato il significato lo trova molto meglio delle
        # parole, e fonderle lo peggiora. Ma gli atti non ancora indicizzati li raggiungono solo le parole.
        significato = cerca_significato(testo, ambito, margine=MARGINE_NORME if k <= config.TOP_K else None)
        parole = cerca_parole(testo, ambito, senza_indice=bool(significato))
        if ambito:
            parole += cerca_parole(testo, ambito, raccolta=True) or _inizio_atti(ambito)
        candidati = (significato or parole)[:k * 6]
        # Posto riservato agli atti principali non ancora indicizzati. La raccolta entra solo se l'atto è citato: una legge
        # che ne modifica un'altra riporta il testo di allora (art. 32 L. 183/2010: 270 giorni, oggi 180 nell'art. 6 L. 604/1966).
        riserve = parole[:10] if significato else []
        with db.session() as conn:
            righe = _righe(conn, candidati + riserve)

        def abrogato(riga):
            return re.match(r"\s*(?:articolo|provvedimento) abrogato", riga["testo"], re.IGNORECASE)

        # un posto va al miglior articolo non indicizzato, se contiene davvero le parole della domanda
        riserva = next((righe[nid] for nid in riserve if nid in righe and not abrogato(righe[nid])
                        and _copre_la_domanda(righe[nid], testo)), None)
        posti = k - 1 if riserva and len(fonti) < k - 1 else k
        # un articolo lungo ha più parti: ne entra al massimo una, la più pertinente
        gia = {(f["atto_id"], f["sezione"], f["articolo"] or f["norma_id"]) for f in fonti}
        for nid in candidati:
            if len(fonti) >= posti:
                break
            riga = righe.get(nid)
            chiave = riga and (riga["atto_id"], riga["sezione"], riga["articolo"] or nid)
            if not riga or chiave in gia or abrogato(riga):
                continue
            # il più pertinente entra intero (le parti di un articolo lungo perdono il contesto),
            # gli altri con la sola parte trovata, per non allungare troppo il prompt
            intero = not fonti and riga["articolo"] and articolo(riga["atto_id"], riga["articolo"], riga["sezione"])
            fonti.append(intero or _fonte(riga))
            gia.add(chiave)
        if riserva and len(fonti) < k:
            fonti.append(_fonte(riserva))
    for n, fonte in enumerate(fonti[:k], start=1):
        fonte["n"] = n
        fonte["parziale"] = _parziale(fonte)
    return fonti[:k]


def _parziale(fonte):
    """La fonte contiene solo un brano dell'articolo? L'interfaccia lo dichiara accanto al testo ufficiale."""
    if fonte["text"].endswith(" […]"):
        return True
    if not fonte["articolo"]:
        return False
    with db.session() as conn:
        intero = conn.execute("SELECT SUM(LENGTH(testo)) FROM norme WHERE atto_id = ? AND articolo = ? AND sezione = ?",
                              (fonte["atto_id"], fonte["articolo"], fonte["sezione"])).fetchone()[0]
    return len(fonte["text"]) < (intero or 0)


def scheda(norma_id):
    """Articolo intero per la pagina di consultazione, con i vicini per scorrere il codice."""
    with db.session() as conn:
        riga = conn.execute("SELECT atto_id, sezione, articolo FROM norme WHERE id = ?", (norma_id,)).fetchone()
        if not riga:
            return None
        vicini = conn.execute("""
            SELECT (SELECT id FROM norme WHERE atto_id = :a AND id < :primo AND parte = 0 ORDER BY id DESC LIMIT 1),
                   (SELECT id FROM norme WHERE atto_id = :a AND id > :ultimo AND parte = 0 ORDER BY id LIMIT 1)""",
            {"a": riga["atto_id"],
             "primo": conn.execute("SELECT MIN(id) FROM norme WHERE atto_id = ? AND sezione = ? AND articolo IS ?",
                                   (riga["atto_id"], riga["sezione"], riga["articolo"])).fetchone()[0],
             "ultimo": conn.execute("SELECT MAX(id) FROM norme WHERE atto_id = ? AND sezione = ? AND articolo IS ?",
                                    (riga["atto_id"], riga["sezione"], riga["articolo"])).fetchone()[0]}).fetchone()
    if riga["articolo"]:
        fonte = articolo(riga["atto_id"], riga["articolo"], riga["sezione"], massimo=10**9)
    else:
        with db.session() as conn:
            fonte = _fonte(_righe(conn, [norma_id])[norma_id])
    return {**fonte, "precedente": vicini[0], "successivo": vicini[1]}


# --- Riga di comando -----------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    db.init()
    if len(sys.argv) > 1 and sys.argv[1] == "aggiorna":
        solo = [a for a in sys.argv[2:] if not a.startswith("--")] or None
        errori = aggiorna(tutti="--tutti" in sys.argv, solo=solo, stampa=print, locale="--locale" in sys.argv)
        s = stato()
        print(f"\nAtti nell'archivio: {len(s['atti'])} · parti: {s['parti']} · errori: {len(errori)}")
        for e in errori:
            print("  ", e)
    else:
        s = stato()
        for a in s["atti"]:
            print(f"{a['sigla']:24} {a['articoli']:5} articoli  vigente al {a['vigente_al']}  "
                  f"semantica {a['indicizzate']}/{a['parti']}")
