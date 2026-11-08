"""Fascicoli di prova con dati inventati, sul server acceso e con i modelli: nessun passaggio di documenti,
elementi, ricerche o cronologia. I fascicoli si cancellano alla fine; i risultati si leggono a schermo.

Avvio: .venv\\Scripts\\python.exe tests\\integrazione\\separazione_fascicoli.py"""
import json

import httpx

B = "http://127.0.0.1:8765/api"
C = httpx.Client(timeout=900)
A_T = "Fascicolo Alfa. Il testimone Giovanni Neri ha dichiarato che l'auto targata ZZ999AA era rossa. L'udienza è fissata il 14 marzo 2027."
B_T = "Fascicolo Beta. La perizia della dottoressa Anna Viola stabilisce che l'orologio ritrovato era fermo alle ore 9 e 12."


def ask(caso, q, conv=None, rotta="/ask", documenti=None):
    testo, fonti, cid = "", [], None
    with C.stream("POST", B + rotta, json={"question": q, "case_id": caso, "conversation_id": conv, "document_ids": documenti}) as r:
        for riga in r.iter_lines():
            e = json.loads(riga)
            if e["type"] == "conversation":
                cid = e["id"]
            elif e["type"] == "token":
                testo += e["text"]
            elif e["type"] == "sources":
                fonti = [s.get("filename") or s.get("etichetta") for s in e["sources"]]
    return " ".join(testo.split()), fonti, cid


alfa = C.post(B + "/cases", json={"name": "PROVA ALFA (cancellabile)", "client": "", "notes": ""}).json()["id"]
beta = C.post(B + "/cases", json={"name": "PROVA BETA (cancellabile)", "client": "", "notes": ""}).json()["id"]
vuoto = C.post(B + "/cases", json={"name": "PROVA VUOTO (cancellabile)", "client": "", "notes": ""}).json()["id"]
try:
    ids = {}
    for caso, nome, testo in ((alfa, "alfa.txt", A_T), (beta, "beta.txt", B_T)):
        with C.stream("POST", f"{B}/cases/{caso}/documents", files={"file": (nome, testo.encode())}) as r:
            ids[nome] = next(e["document_id"] for e in map(json.loads, r.iter_lines()) if e["type"] == "result")
    print("documenti:", {k: [d["filename"] for d in C.get(f"{B}/cases/{k}/documents").json()] for k in (1, alfa, beta, vuoto)}, flush=True)
    print("nuovo fascicolo vuoto, domanda:", ask(vuoto, "Di che colore era l'auto?")[:2], flush=True)
    print("nuovo fascicolo vuoto, dato di alfa:", ask(vuoto, "Chi è Giovanni Neri?")[:2], flush=True)
    print("nuovo fascicolo vuoto, legge:", ask(vuoto, "Cosa prevede l'art. 2043 del codice civile?", rotta="/ask-normativa")[:2], flush=True)
    r = ask(beta, "Di che colore era l'auto targata ZZ999AA?")
    print("beta chiede un dato di alfa:", r[:2], flush=True)
    print("beta con un documento di alfa:", ask(beta, "Di che colore era l'auto?", documenti=[ids["alfa.txt"]])[:2], flush=True)
    print("ricerca in beta di 'Neri':", C.get(f"{B}/cases/{beta}/search", params={"q": "Neri"}).json()["documenti"], flush=True)
    print("ricerca in alfa di 'Neri':", len(C.get(f"{B}/cases/{alfa}/search", params={"q": "Neri"}).json()["documenti"]), flush=True)
    _, _, conv_alfa = ask(alfa, "Quando è fissata l'udienza?")
    t, f, conv_beta = ask(beta, "Quale udienza hai appena indicato?", conv=conv_alfa)
    print("conversazione di alfa usata in beta:", (t, f), "nuova conversazione:", conv_beta != conv_alfa, flush=True)
    print("conversazioni alfa:", len(C.get(f"{B}/cases/{alfa}/conversations").json()), "beta:", len(C.get(f"{B}/cases/{beta}/conversations").json()), flush=True)
    elementi = C.get(f"{B}/cases/{vuoto}/elements").json()["elementi"]
    print("nuovo fascicolo vuoto, elementi:", sum(len(v) for v in elementi.values()), flush=True)
finally:
    print("cancellati:", [C.delete(f"{B}/cases/{k}").status_code for k in (alfa, beta, vuoto)], flush=True)
    print("rimasti:", [(x["id"], x["name"], x["documents"], x["conversations"]) for x in C.get(B + "/cases").json()], flush=True)
