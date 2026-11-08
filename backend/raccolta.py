"""Raccolta generale: tutti gli atti NON abrogati di Normattiva, nel testo vigente, a integrazione del catalogo.

Il servizio Open Data di Normattiva (dati.normattiva.it) elenca gli atti per anno e per classe; il testo di ciascuno
si scarica in Akoma Ntoso, un atto alla volta, con una pausa: il lavoro dura giorni, ma si può interrompere e riprendere.
I testi "originali" delle collezioni pronte NON si usano: non contengono le modifiche successive, quindi darebbero per
vigente un testo superato. Se il sito rifiuta le richieste il programma si ferma: quei limiti non vanno aggirati.

Uso:  python -m backend.raccolta elenca    costruisce la coda degli atti
      python -m backend.raccolta scarica   scarica fino alla fine (si riprende da dove si era arrivati)
      python -m backend.raccolta stato"""
import logging
import re
import sys
import time
from datetime import date
from xml.etree import ElementTree as ET

import httpx

from . import db
from .normativa import AKN, AREA_RACCOLTA, USER_AGENT, dividi, leggi_akn, _righe_pulite

log = logging.getLogger("law_prog")
API = "https://api.normattiva.it/t/normattiva.api/bff-opendata/v1/api/v1"
PAUSA = 1.5            # secondi tra due richieste, per non sovraccaricare il sito istituzionale
PER_PAGINA = 100
RIFIUTI = {403, 409, 429}
ANNO_MINIMO = 1861

SIGLE = {"LEGGE": "L.", "DECRETO LEGISLATIVO": "D.Lgs.", "DECRETO-LEGGE": "D.L.", "DECRETO DEL PRESIDENTE DELLA REPUBBLICA": "D.P.R.",
         "DECRETO MINISTERIALE": "D.M.", "REGIO DECRETO": "R.D.", "REGIO DECRETO-LEGGE": "R.D.L.", "REGIO DECRETO LEGISLATIVO": "R.D.Lgs.",
         "DECRETO DEL PRESIDENTE DEL CONSIGLIO DEI MINISTRI": "D.P.C.M.", "LEGGE COSTITUZIONALE": "L. cost.",
         "DECRETO LEGISLATIVO LUOGOTENENZIALE": "D.Lgs.Lgt.", "DECRETO LUOGOTENENZIALE": "D.Lgt.", "DECRETO": "Decreto"}
URN = {"LEGGE": "legge", "DECRETO LEGISLATIVO": "decreto.legislativo", "DECRETO-LEGGE": "decreto.legge",
       "DECRETO DEL PRESIDENTE DELLA REPUBBLICA": "decreto.del.presidente.della.repubblica", "REGIO DECRETO": "regio.decreto",
       "REGIO DECRETO-LEGGE": "regio.decreto.legge", "REGIO DECRETO LEGISLATIVO": "regio.decreto.legislativo",
       "LEGGE COSTITUZIONALE": "legge.costituzionale", "DECRETO LEGISLATIVO LUOGOTENENZIALE": "decreto.legislativo.luogotenenziale",
       "DECRETO LUOGOTENENZIALE": "decreto.luogotenenziale"}
FONTI_PRIMARIE = {"LEGGE", "LEGGE COSTITUZIONALE", "DECRETO LEGISLATIVO", "DECRETO-LEGGE"}


class SitoRifiuta(Exception):
    pass


def _priorita(classe, denominazione):
    """Prima gli atti ancora modificati dal legislatore e le fonti primarie; in coda i piccoli atti storici."""
    if classe == "2":
        return 0
    return 1 if denominazione in FONTI_PRIMARIE else 2


def _chiedi(client, metodo, url, **kw):
    """Una richiesta al sito. Se il sito rifiuta (403, 409, 429) solleva SitoRifiuta, che ferma la raccolta."""
    r = client.request(metodo, url, **kw)
    if r.status_code in RIFIUTI:
        raise SitoRifiuta(f"{r.status_code} {r.text[:200]}")
    r.raise_for_status()
    return r


def elenca(stampa=print):
    """Riempie la coda, anno per anno. Si può ripetere: gli atti già presenti restano come sono."""
    with httpx.Client(timeout=120, headers={"User-Agent": USER_AGENT}) as client:
        for classe in ("2", "1"):
            for anno in range(date.today().year, ANNO_MINIMO - 1, -1):
                pagina, nuovi = 1, 0
                while True:
                    j = _chiedi(client, "POST", f"{API}/ricerca/avanzata", json={
                        "classeProvvedimento": classe, "annoProvvedimento": anno,
                        "paginazione": {"paginaCorrente": pagina, "numeroElementiPerPagina": PER_PAGINA}}).json()
                    lista = j.get("listaAtti") or []
                    with db.session() as conn:
                        for a in lista:
                            nuovi += conn.execute(
                                """INSERT OR IGNORE INTO raccolta_coda
                                   (codice, data_gu, denominazione, numero, giorno, mese, anno, titolo, priorita)
                                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                                (a["codiceRedazionale"], a["dataGU"], a["denominazioneAtto"], a.get("numeroProvvedimento"),
                                 a.get("giornoProvvedimento"), a.get("meseProvvedimento"), a.get("annoProvvedimento"),
                                 a.get("titoloAtto"), _priorita(classe, a["denominazioneAtto"]))).rowcount
                    time.sleep(PAUSA)
                    if not lista or pagina >= (j.get("numeroPagine") or 1):
                        break
                    pagina += 1
                stampa(f"classe {classe} anno {anno}: {nuovi} nuovi", flush=True)


def _sigla(voce):
    """La sigla di un atto: tipo e numero oppure, se manca il numero, la data e il codice."""
    tipo = SIGLE.get(voce["denominazione"], (voce["denominazione"] or "Atto").capitalize())
    numero = str(voce["numero"] or "").strip()
    if numero and numero != "0":
        return f"{tipo} {numero}/{voce['anno']}"
    return f"{tipo} {voce['giorno']}/{voce['mese']}/{voce['anno']} ({voce['codice']})"


def _urn(voce):
    """L'identificatore dell'atto su Normattiva."""
    tipo = URN.get(voce["denominazione"])
    numero = str(voce["numero"] or "").strip()
    if tipo and numero.isdigit() and voce["giorno"] and voce["mese"]:
        return f"urn:nir:stato:{tipo}:{voce['anno']}-{int(voce['mese']):02d}-{int(voce['giorno']):02d};{numero}"
    return f"urn:nir:stato:{voce['codice']}"


def _titolo(voce):
    """Il titolo dell'atto senza parentesi e codice finale; se manca, la sigla."""
    t = re.sub(r"\s+", " ", (voce["titolo"] or "").strip().strip("[]")).strip()
    return re.sub(r"\s*\(\w{8,}\)\s*$", "", t) or _sigla(voce)


def _unita(contenuto):
    """Articoli dell'atto; un atto senza articoli (molti decreti brevi) diventa un unico testo."""
    unita = leggi_akn(contenuto)
    if unita:
        return unita
    corpo = ET.fromstring(contenuto).find(f".//{AKN}act/{AKN}body")
    testo = _righe_pulite(corpo.itertext()) if corpo is not None else ""
    return [("Testo dell'atto", None, "", testo)] if testo else []


def _salva(conn, voce, sigla, unita):
    """Inserisce un atto nell'archivio e nella ricerca testuale; restituisce il numero di parti salvate."""
    atto_id = conn.execute("INSERT INTO norme_atti (sigla, titolo, area, fonte, urn, vigente_al) VALUES (?, ?, ?, ?, ?, ?)",
                           (sigla, _titolo(voce), AREA_RACCOLTA, "Normattiva", _urn(voce), date.today().isoformat())).lastrowid
    righe = [(atto_id, sezione, numero, rubrica, i, parte)
             for sezione, numero, rubrica, testo in unita for i, parte in enumerate(dividi(testo))]
    conn.executemany("INSERT INTO norme (atto_id, sezione, articolo, rubrica, parte, testo) VALUES (?, ?, ?, ?, ?, ?)", righe)
    conn.execute("INSERT INTO raccolta_fts(rowid, rubrica, testo) SELECT id, rubrica, testo FROM norme WHERE atto_id = ?", (atto_id,))
    return len(righe)


def _nel_catalogo(conn, voce):
    """Gli atti principali ci sono già, con il loro nome ("TUB") e l'indice semantico."""
    return conn.execute("SELECT 1 FROM norme_atti WHERE urn = ?", (_urn(voce),)).fetchone() is not None


def scarica(stampa=print, massimo=None):
    """Scarica gli atti in coda, uno alla volta e con una pausa. Si può interrompere e riprendere."""
    fatti, inizio = 0, time.time()
    with httpx.Client(timeout=300, follow_redirects=True, headers={"User-Agent": USER_AGENT}) as client:
        while massimo is None or fatti < massimo:
            with db.session() as conn:
                voce = conn.execute("SELECT * FROM raccolta_coda WHERE stato = 'da fare' ORDER BY priorita, anno DESC LIMIT 1").fetchone()
                if not voce:
                    stampa("Coda finita", flush=True)
                    return
                voce = dict(voce)
                salta = _nel_catalogo(conn, voce)
                if salta:
                    conn.execute("UPDATE raccolta_coda SET stato = 'saltato' WHERE codice = ?", (voce["codice"],))
            if salta:
                continue
            esito, errore = "fatto", ""
            try:
                # il file si ottiene solo dopo aver aperto la pagina dell'atto, che ne dà anche il collegamento
                pagina = _chiedi(client, "GET", "https://www.normattiva.it/atto/caricaDettaglioAtto", params={
                    "atto.dataPubblicazioneGazzetta": voce["data_gu"], "atto.codiceRedazionale": voce["codice"],
                    "atto.articolo.numero": 0, "atto.articolo.sottoArticolo": 1, "atto.articolo.sottoArticolo1": 0,
                    "atto.articolo.tipoArticolo": 0, "qId": "", "tabID": "", "title": "lbl.dettaglioAtto"})
                if "caricaAKN?" not in pagina.text:
                    raise RuntimeError("pagina dell'atto senza file Akoma Ntoso")
                time.sleep(PAUSA)
                r = _chiedi(client, "GET", "https://www.normattiva.it/do/atto/caricaAKN", params={
                    "dataGU": voce["data_gu"].replace("-", ""), "codiceRedaz": voce["codice"], "dataVigenza": f"{date.today():%Y%m%d}"})
                if b"akomaNtoso" not in r.content[:2000]:
                    raise RuntimeError("risposta senza Akoma Ntoso")
                unita = _unita(r.content)
                if not unita:
                    raise RuntimeError("nessun testo nell'atto")
                sigla = _sigla(voce)
                with db.session() as conn:
                    if conn.execute("SELECT 1 FROM norme_atti WHERE sigla = ?", (sigla,)).fetchone():
                        sigla = f"{sigla} ({voce['codice']})"
                    _salva(conn, voce, sigla, unita)
            except SitoRifiuta:
                raise
            except Exception as exc:
                esito, errore = "errore", str(exc)[:300]
            with db.session() as conn:
                conn.execute("UPDATE raccolta_coda SET stato = ?, errore = ? WHERE codice = ?", (esito, errore, voce["codice"]))
            fatti += 1
            if fatti % 200 == 0:
                stampa(f"{fatti} atti in {(time.time() - inizio) / 60:.0f} min; ultimo {voce['denominazione']} {voce['numero']}/{voce['anno']}", flush=True)
            time.sleep(PAUSA)


def stato():
    """Quanti atti ci sono in coda, per priorità e stato."""
    with db.session() as conn:
        return [dict(r) for r in conn.execute("SELECT priorita, stato, COUNT(*) AS n FROM raccolta_coda GROUP BY priorita, stato ORDER BY 1, 2")]


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    db.init()
    comando = sys.argv[1] if len(sys.argv) > 1 else "stato"
    try:
        if comando == "elenca":
            elenca()
        elif comando == "scarica":
            scarica(massimo=int(sys.argv[2]) if len(sys.argv) > 2 else None)
        print(stato(), flush=True)
    except SitoRifiuta as exc:
        print(f"FERMO: il sito ha rifiutato le richieste ({exc}). Non insisto.", flush=True)
        sys.exit(2)
