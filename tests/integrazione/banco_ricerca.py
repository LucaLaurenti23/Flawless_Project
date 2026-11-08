"""Banco di prova della ricerca: domande in linguaggio naturale e articolo atteso. Usa l'archivio reale e bge-m3.

Avvio: .venv\\Scripts\\python.exe tests\\integrazione\\banco_ricerca.py [controllo]"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from backend import db, normativa as N

# (domanda, sigla, articolo). SVILUPPO serve a capire il problema; CONTROLLO si guarda solo alla fine.
SVILUPPO = [
    ("Qual è il termine per proporre appello?", "c.p.c.", "325"),
    ("Entro quanti giorni si propone opposizione al decreto ingiuntivo?", "c.p.c.", "641"),
    ("In quanto tempo si prescrivono i diritti in via ordinaria?", "c.c.", "2946"),
    ("In quanto tempo si prescrive il risarcimento del danno da fatto illecito?", "c.c.", "2947"),
    ("Entro quanti giorni minimi deve adempiere chi riceve una diffida ad adempiere?", "c.c.", "1454"),
    ("Cos'è la caparra confirmatoria?", "c.c.", "1385"),
    ("Chi causa un danno ingiusto deve risarcirlo?", "c.c.", "2043"),
    ("I genitori rispondono dei danni causati dai figli minori?", "c.c.", "2048"),
    ("Quando si applica la legittima difesa?", "c.p.", "52"),
    ("Qual è la pena per il furto?", "c.p.", "624"),
    ("A che età si diventa maggiorenni?", "c.c.", "2"),
    ("Come si fa un testamento olografo?", "c.c.", "602"),
    ("Dopo quanti anni si usucapisce un immobile?", "c.c.", "1158"),
    ("Per quanto tempo resta efficace il precetto?", "c.p.c.", "481"),
    ("Entro quanto tempo va presentata la querela?", "c.p.", "124"),
    ("La Costituzione tutela il diritto di difesa?", "Cost.", "24"),
    ("Quali sono i termini per l'appello penale?", "c.p.p.", "585"),
    ("Entro quante ore va notificata una violazione dei dati personali al garante?", "GDPR", "33"),
    ("Qual è la sanzione per la guida in stato di ebbrezza?", "C.d.S.", "186"),
    ("Il consumatore ha diritto di recesso nei contratti a distanza?", "Cod. consumo", "52"),
]
CONTROLLO = [
    ("Qual è il tasso degli interessi legali?", "c.c.", "1284"),
    ("Le parti devono comportarsi in buona fede nelle trattative?", "c.c.", "1337"),
    ("Cos'è la fideiussione?", "c.c.", "1936"),
    ("Chi risponde dei danni causati dalle cose in custodia?", "c.c.", "2051"),
    ("Chi risponde dei danni da circolazione dei veicoli?", "c.c.", "2054"),
    ("Cosa succede se il venditore consegna una cosa con vizi?", "c.c.", "1490"),
    ("Entro quando il compratore deve denunciare i vizi?", "c.c.", "1495"),
    ("Quando il contratto si può risolvere per inadempimento?", "c.c.", "1453"),
    ("Le clausole vessatorie devono essere approvate per iscritto?", "c.c.", "1341"),
    ("Qual è la quota riservata ai figli nella successione?", "c.c.", "537"),
    ("Qual è la pena per la truffa?", "c.p.", "640"),
    ("Quale pena per l'omicidio colposo?", "c.p.", "589"),
    ("Quando si può chiedere il sequestro conservativo?", "c.p.c.", "671"),
    ("Di quali cause è competente il giudice di pace?", "c.p.c.", "7"),
    ("Quali sono i criteri di scelta delle misure cautelari?", "c.p.p.", "275"),
    ("Quanto può durare la custodia cautelare?", "c.p.p.", "303"),
    ("La Costituzione tutela la libertà di manifestazione del pensiero?", "Cost.", "21"),
    ("Quando il giudice pronuncia la separazione dei coniugi?", "c.c.", "151"),
    ("Come funziona l'assegno di mantenimento per il coniuge separato?", "c.c.", "156"),
    ("Chi può impugnare il licenziamento illegittimo e la reintegrazione?", "L. 300/1970", "18"),
]


def valuta(lista, stampa=True):
    a1 = a3 = 0
    for q, sigla, art in lista:
        f = N.cerca(q, k=3)
        trovati = [(x["atto"], x["articolo"]) for x in f]
        pos = trovati.index((sigla, art)) + 1 if (sigla, art) in trovati else 0
        a1 += pos == 1
        a3 += pos > 0
        if stampa:
            print(f"{'ok' + str(pos) if pos else 'NO '} {sigla} {art:5} | {q[:58]:58} | " + ", ".join(f"{s} {a}" for s, a in trovati), flush=True)
    print(f"primo: {a1}/{len(lista)}  nei primi 3: {a3}/{len(lista)}", flush=True)


if __name__ == "__main__":
    with db.session() as conn:
        for _, sigla, art in SVILUPPO + CONTROLLO:
            if not conn.execute("SELECT 1 FROM norme n JOIN norme_atti a ON a.id = n.atto_id WHERE a.sigla = ? AND n.articolo = ?", (sigla, art)).fetchone():
                print("ATTENZIONE, assente dall'archivio:", sigla, art, flush=True)
    if "controllo" in sys.argv:
        valuta(CONTROLLO)
    else:
        valuta(SVILUPPO)
