"""Glossario giuridico: termini con cui si chiede una norma che il testo dell'articolo non usa alla lettera.

Le voci sono state scritte senza la revisione di un legale: vanno rilette. Ordine: dalla più specifica alla più generale.
Una voce vale quando la domanda non indica già un articolo o un atto."""
import re

# (espressione nella domanda, articoli da leggere per primi)
VOCI = [
    # Procedura civile
    (r"decreto ingiuntivo.*(?:provvisori|esecutiv)|(?:provvisori|esecutiv).*decreto ingiuntivo", [("c.p.c.", "642"), ("c.p.c.", "648")]),
    (r"opposizione.*decreto ingiuntivo|decreto ingiuntivo.*opposizione", [("c.p.c.", "641"), ("c.p.c.", "645")]),
    (r"decreto ingiuntivo", [("c.p.c.", "633"), ("c.p.c.", "641")]),
    (r"sequestro conservativo", [("c.p.c.", "671")]),
    (r"sequestro giudiziario", [("c.p.c.", "670")]),
    (r"sfratto", [("c.p.c.", "657"), ("c.p.c.", "658")]),
    (r"pignoramento", [("c.p.c.", "492")]),
    (r"(?:termin|entro).*appello.*civil|appello civil", [("c.p.c.", "325"), ("c.p.c.", "327")]),
    (r"ricorso per cassazione.*civil|civil.*ricorso per cassazione", [("c.p.c.", "360"), ("c.p.c.", "325")]),
    # Procedura penale
    (r"(?:termin|entro).*appello.*penal|appello penal", [("c.p.p.", "585"), ("c.p.p.", "593")]),
    (r"ricorso per cassazione.*penal|penal.*ricorso per cassazione", [("c.p.p.", "606"), ("c.p.p.", "585")]),
    (r"custodia cautelare.*(?:dura|durata|quanto)|(?:durata|quanto).*custodia cautelare", [("c.p.p.", "303")]),
    (r"custodia cautelare", [("c.p.p.", "280"), ("c.p.p.", "275")]),   # il 280 dà le soglie di pena: il modello le perdeva dietro al 275
    (r"(?:criteri|scelta).*misur\w* cautelar|misur\w* cautelar.*(?:criteri|scelta)", [("c.p.p.", "275")]),
    (r"esigenze cautelari", [("c.p.p.", "274")]),
    (r"sequestro preventivo", [("c.p.p.", "321")]),
    (r"sequestro probatorio", [("c.p.p.", "253")]),
    (r"riesame", [("c.p.p.", "309")]),
    (r"patteggiamento", [("c.p.p.", "444")]),
    (r"(?:giudizio|rito) abbreviato", [("c.p.p.", "438")]),
    (r"messa alla prova", [("c.p.", "168-bis"), ("c.p.p.", "464-bis")]),
    # Penale
    (r"querela", [("c.p.", "124")]),
    (r"prescrizione.*reat|reat.*prescri", [("c.p.", "157")]),
    (r"sospensione condizionale", [("c.p.", "163")]),
    (r"omess\w* versament\w*.*iva|iva.*omess\w* versament|omett\w*.*versament\w*.*iva|iva.*omett\w*.*versament", [("D.Lgs. 74/2000", "10-ter")]),
    # Contratti e obbligazioni
    (r"clausol\w* vessatori|condizioni generali di contratto", [("c.c.", "1341"), ("c.c.", "1342"), ("Cod. consumo", "33")]),
    (r"clausola penale", [("c.c.", "1382")]),
    (r"caparra penitenziale", [("c.c.", "1386")]),
    (r"interessi moratori|interessi di mora", [("c.c.", "1224")]),
    (r"(?:vizi|difformit)\w*.*appalto|appalto.*(?:vizi|difformit)", [("c.c.", "1667")]),
    (r"rovina.*edific|gravi difetti.*(?:edific|immobil)", [("c.c.", "1669")]),
    (r"responsabilit\w* contrattuale|inadempimento dell.obbligazione", [("c.c.", "1218")]),
    (r"danno non patrimoniale|danni non patrimoniali|danno morale", [("c.c.", "2059")]),
    (r"rece(?:ss|d)\w*.*(?:contratt\w* a distanza|fuori dai locali)|(?:contratt\w* a distanza|fuori dai locali).*rece(?:ss|d)|consumator\w*.*rece(?:ss|d)|rece(?:ss|d)\w*.*consumator", [("Cod. consumo", "52"), ("Cod. consumo", "54")]),
    # Famiglia e successioni
    (r"mantenimento.*(?:coniuge|separat)|(?:coniuge|separat).*mantenimento", [("c.c.", "156")]),
    (r"assegno divorzile|assegno.*divorzio|divorzio.*assegno", [("L. 898/1970", "5")]),
    (r"affidamento.*figli|figli.*affidamento", [("c.c.", "337-ter")]),
    (r"rinuncia.*eredit", [("c.c.", "519")]),
    (r"beneficio d.inventario", [("c.c.", "484")]),
    (r"successione legittima", [("c.c.", "565")]),
    # Lavoro e locazioni
    (r"impugn\w*.*licenziament|licenziament.*impugn", [("L. 604/1966", "6")]),
    (r"giusta causa", [("c.c.", "2119")]),
    (r"recesso.*conduttore|conduttore.*recesso", [("L. 392/1978", "27")]),
    # Possesso e responsabilità sanitaria
    (r"azione di reintegrazione|spoglio", [("c.c.", "1168")]),
    (r"responsabilit\w*.*(?:medic|sanitari)|(?:medic|sanitari).*responsabilit", [("L. 24/2017", "7")]),
]
_VOCI = [(re.compile(espressione, re.IGNORECASE | re.DOTALL), articoli) for espressione, articoli in VOCI]


def articoli(domanda):
    """Gli articoli della prima voce che corrisponde alla domanda: [(sigla, numero)]."""
    return next((voce for espressione, voce in _VOCI if espressione.search(domanda)), [])
