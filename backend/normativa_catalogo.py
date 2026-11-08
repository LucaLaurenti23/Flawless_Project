"""Catalogo dei testi di legge integrati nell'archivio normativo.

Fonte: Normattiva (www.normattiva.it), banca dati ufficiale della normativa vigente gestita dall'Istituto
Poligrafico e Zecca dello Stato; dati riutilizzabili con licenza CC BY 4.0. Ogni atto è scaricato in
formato Akoma Ntoso nella versione vigente alla data di scaricamento.
Il Regolamento UE sulla protezione dei dati viene invece da EUR-Lex (eur-lex.europa.eu), fonte ufficiale
del diritto dell'Unione, riutilizzabile citando la fonte (Decisione 2011/833/UE).

`sigla` è il modo in cui l'atto si cita ("art. 1385 c.c."): serve sia alle citazioni sia per riconoscere
nelle domande un riferimento diretto a un articolo. `attivo=False`: atti voluminosi o molto specialistici,
non indicizzati per default (si attivano cambiando il valore e rilanciando l'aggiornamento)."""

NORMATTIVA = [
    # area, sigla, titolo, urn, attivo
    ("Costituzione", "Cost.", "Costituzione della Repubblica italiana", "urn:nir:stato:costituzione", True),

    ("Civile", "c.c.", "Codice civile", "urn:nir:stato:regio.decreto:1942-03-16;262", True),
    ("Civile", "disp. att. c.c.", "Disposizioni per l'attuazione del codice civile", "urn:nir:stato:regio.decreto:1942-03-30;318", True),
    ("Civile", "Cod. consumo", "Codice del consumo (D.Lgs. 206/2005)", "urn:nir:stato:decreto.legislativo:2005-09-06;206", True),
    ("Civile", "Cod. ass. priv.", "Codice delle assicurazioni private (D.Lgs. 209/2005)", "urn:nir:stato:decreto.legislativo:2005-09-07;209", True),
    ("Civile", "L. 24/2017", "Responsabilità professionale sanitaria (legge Gelli-Bianco)", "urn:nir:stato:legge:2017-03-08;24", True),
    ("Civile", "L. 219/2017", "Consenso informato e disposizioni anticipate di trattamento (DAT)", "urn:nir:stato:legge:2017-12-22;219", True),
    ("Locazioni", "L. 392/1978", "Disciplina delle locazioni di immobili urbani (equo canone; locazioni commerciali)", "urn:nir:stato:legge:1978-07-27;392", True),
    ("Locazioni", "L. 431/1998", "Disciplina delle locazioni ad uso abitativo", "urn:nir:stato:legge:1998-12-09;431", True),
    ("Famiglia", "L. 898/1970", "Disciplina dei casi di scioglimento del matrimonio (divorzio)", "urn:nir:stato:legge:1970-12-01;898", True),
    ("Famiglia", "L. 76/2016", "Unioni civili e convivenze (legge Cirinnà)", "urn:nir:stato:legge:2016-05-20;76", True),
    ("Famiglia", "L. 184/1983", "Diritto del minore ad una famiglia (adozione e affidamento)", "urn:nir:stato:legge:1983-05-04;184", True),

    ("Processo civile", "c.p.c.", "Codice di procedura civile", "urn:nir:stato:regio.decreto:1940-10-28;1443", True),
    ("Processo civile", "disp. att. c.p.c.", "Disposizioni per l'attuazione del codice di procedura civile", "urn:nir:stato:regio.decreto:1941-12-18;1368", True),
    ("Processo civile", "D.Lgs. 28/2010", "Mediazione civile e commerciale", "urn:nir:stato:decreto.legislativo:2010-03-04;28", True),
    ("Processo civile", "D.L. 132/2014", "Negoziazione assistita e degiurisdizionalizzazione", "urn:nir:stato:decreto.legge:2014-09-12;132", True),
    ("Processo civile", "D.Lgs. 150/2011", "Riti civili semplificati (anche opposizione a sanzioni amministrative)", "urn:nir:stato:decreto.legislativo:2011-09-01;150", True),
    ("Processo civile", "L. 89/2001", "Equa riparazione per irragionevole durata del processo (legge Pinto)", "urn:nir:stato:legge:2001-03-24;89", True),
    ("Processo civile", "D.P.R. 115/2002", "Testo unico spese di giustizia (contributo unificato, patrocinio a spese dello Stato)", "urn:nir:stato:decreto.del.presidente.della.repubblica:2002-05-30;115", True),
    ("Crisi d'impresa", "CCII", "Codice della crisi d'impresa e dell'insolvenza (D.Lgs. 14/2019)", "urn:nir:stato:decreto.legislativo:2019-01-12;14", True),

    ("Penale", "c.p.", "Codice penale", "urn:nir:stato:regio.decreto:1930-10-19;1398", True),
    ("Penale", "c.p.p.", "Codice di procedura penale", "urn:nir:stato:decreto.del.presidente.della.repubblica:1988-09-22;447", True),
    ("Penale", "disp. att. c.p.p.", "Norme di attuazione del codice di procedura penale", "urn:nir:stato:decreto.legislativo:1989-07-28;271", True),
    ("Penale", "D.Lgs. 231/2001", "Responsabilità amministrativa degli enti", "urn:nir:stato:decreto.legislativo:2001-06-08;231", True),
    ("Penale", "D.P.R. 309/1990", "Testo unico stupefacenti", "urn:nir:stato:decreto.del.presidente.della.repubblica:1990-10-09;309", True),
    ("Penale", "Cod. antimafia", "Codice antimafia e misure di prevenzione (D.Lgs. 159/2011)", "urn:nir:stato:decreto.legislativo:2011-09-06;159", True),
    ("Penale", "L. 689/1981", "Modifiche al sistema penale (sanzioni amministrative)", "urn:nir:stato:legge:1981-11-24;689", True),

    ("Lavoro", "L. 300/1970", "Statuto dei lavoratori", "urn:nir:stato:legge:1970-05-20;300", True),
    ("Lavoro", "L. 604/1966", "Licenziamenti individuali", "urn:nir:stato:legge:1966-07-15;604", True),
    ("Lavoro", "D.Lgs. 23/2015", "Contratto a tutele crescenti (Jobs Act)", "urn:nir:stato:decreto.legislativo:2015-03-04;23", True),
    ("Lavoro", "D.Lgs. 81/2015", "Disciplina organica dei contratti di lavoro", "urn:nir:stato:decreto.legislativo:2015-06-15;81", True),
    ("Lavoro", "Cod. pari opportunità", "Codice delle pari opportunità (D.Lgs. 198/2006)", "urn:nir:stato:decreto.legislativo:2006-04-11;198", True),
    ("Lavoro", "D.Lgs. 81/2008", "Testo unico salute e sicurezza sul lavoro", "urn:nir:stato:decreto.legislativo:2008-04-09;81", True),
    ("Lavoro", "D.Lgs. 151/2001", "Testo unico maternità e paternità", "urn:nir:stato:decreto.legislativo:2001-03-26;151", True),
    ("Lavoro", "L. 223/1991", "Licenziamenti collettivi e mobilità", "urn:nir:stato:legge:1991-07-23;223", True),
    ("Lavoro", "D.Lgs. 66/2003", "Orario di lavoro", "urn:nir:stato:decreto.legislativo:2003-04-08;66", True),
    ("Lavoro", "D.P.R. 1124/1965", "Testo unico infortuni sul lavoro e malattie professionali", "urn:nir:stato:decreto.del.presidente.della.repubblica:1965-06-30;1124", True),
    ("Lavoro", "L. 104/1992", "Assistenza, integrazione sociale e diritti delle persone handicappate", "urn:nir:stato:legge:1992-02-05;104", True),

    ("Civile", "L. 218/1995", "Riforma del sistema italiano di diritto internazionale privato", "urn:nir:stato:legge:1995-05-31;218", True),
    ("Famiglia", "L. 194/1978", "Tutela della maternità e interruzione volontaria della gravidanza", "urn:nir:stato:legge:1978-05-22;194", True),
    ("Famiglia", "L. 40/2004", "Procreazione medicalmente assistita", "urn:nir:stato:legge:2004-02-19;40", True),
    ("Processo civile", "L. 53/1994", "Notificazioni di atti da parte degli avvocati", "urn:nir:stato:legge:1994-01-21;53", True),
    ("Crisi d'impresa", "R.D. 267/1942", "Legge fallimentare (per le procedure anteriori al CCII)", "urn:nir:stato:regio.decreto:1942-03-16;267", True),
    ("Penale", "L. 354/1975", "Ordinamento penitenziario", "urn:nir:stato:legge:1975-07-26;354", True),
    ("Penale", "D.P.R. 448/1988", "Processo penale a carico di imputati minorenni", "urn:nir:stato:decreto.del.presidente.della.repubblica:1988-09-22;448", True),
    ("Penale", "D.Lgs. 274/2000", "Competenza penale del giudice di pace", "urn:nir:stato:decreto.legislativo:2000-08-28;274", True),
    ("Penale", "D.Lgs. 74/2000", "Reati in materia di imposte sui redditi e IVA", "urn:nir:stato:decreto.legislativo:2000-03-10;74", True),
    ("Banche e finanza", "TUB", "Testo unico bancario (D.Lgs. 385/1993)", "urn:nir:stato:decreto.legislativo:1993-09-01;385", True),
    ("Banche e finanza", "TUF", "Testo unico della finanza (D.Lgs. 58/1998)", "urn:nir:stato:decreto.legislativo:1998-02-24;58", True),
    ("Amministrativo", "TUEL", "Testo unico enti locali (D.Lgs. 267/2000)", "urn:nir:stato:decreto.legislativo:2000-08-18;267", True),
    ("Amministrativo", "D.Lgs. 165/2001", "Ordinamento del lavoro alle dipendenze delle pubbliche amministrazioni", "urn:nir:stato:decreto.legislativo:2001-03-30;165", True),
    ("Amministrativo", "D.P.R. 327/2001", "Testo unico espropriazioni per pubblica utilità", "urn:nir:stato:decreto.del.presidente.della.repubblica:2001-06-08;327", True),
    ("Tributario", "D.P.R. 600/1973", "Accertamento delle imposte sui redditi", "urn:nir:stato:decreto.del.presidente.della.repubblica:1973-09-29;600", True),
    ("Tributario", "D.P.R. 602/1973", "Riscossione delle imposte sul reddito", "urn:nir:stato:decreto.del.presidente.della.repubblica:1973-09-29;602", True),
    ("Tributario", "D.P.R. 633/1972", "Imposta sul valore aggiunto (IVA)", "urn:nir:stato:decreto.del.presidente.della.repubblica:1972-10-26;633", True),
    ("Tributario", "L. 212/2000", "Statuto dei diritti del contribuente", "urn:nir:stato:legge:2000-07-27;212", True),

    ("Amministrativo", "L. 241/1990", "Procedimento amministrativo e accesso agli atti", "urn:nir:stato:legge:1990-08-07;241", True),
    ("Amministrativo", "c.p.a.", "Codice del processo amministrativo (D.Lgs. 104/2010)", "urn:nir:stato:decreto.legislativo:2010-07-02;104", True),
    ("Amministrativo", "D.P.R. 445/2000", "Testo unico documentazione amministrativa (autocertificazioni)", "urn:nir:stato:decreto.del.presidente.della.repubblica:2000-12-28;445", True),
    ("Amministrativo", "D.P.R. 380/2001", "Testo unico edilizia", "urn:nir:stato:decreto.del.presidente.della.repubblica:2001-06-06;380", True),
    ("Amministrativo", "CAD", "Codice dell'amministrazione digitale (D.Lgs. 82/2005)", "urn:nir:stato:decreto.legislativo:2005-03-07;82", True),
    ("Amministrativo", "Cod. contratti pubblici", "Codice dei contratti pubblici (D.Lgs. 36/2023)", "urn:nir:stato:decreto.legislativo:2023-03-31;36", True),
    ("Amministrativo", "Cod. beni culturali", "Codice dei beni culturali e del paesaggio (D.Lgs. 42/2004)", "urn:nir:stato:decreto.legislativo:2004-01-22;42", True),
    ("Amministrativo", "D.Lgs. 286/1998", "Testo unico immigrazione", "urn:nir:stato:decreto.legislativo:1998-07-25;286", True),
    ("Amministrativo", "Cod. ambiente", "Norme in materia ambientale (D.Lgs. 152/2006)", "urn:nir:stato:decreto.legislativo:2006-04-03;152", True),

    ("Tributario", "D.Lgs. 546/1992", "Processo tributario", "urn:nir:stato:decreto.legislativo:1992-12-31;546", True),
    ("Tributario", "TUIR", "Testo unico imposte sui redditi (D.P.R. 917/1986)", "urn:nir:stato:decreto.del.presidente.della.repubblica:1986-12-22;917", True),

    ("Circolazione", "C.d.S.", "Codice della strada (D.Lgs. 285/1992)", "urn:nir:stato:decreto.legislativo:1992-04-30;285", True),
    ("Impresa", "c.p.i.", "Codice della proprietà industriale (D.Lgs. 30/2005)", "urn:nir:stato:decreto.legislativo:2005-02-10;30", True),
    ("Impresa", "CTS", "Codice del Terzo settore (D.Lgs. 117/2017)", "urn:nir:stato:decreto.legislativo:2017-07-03;117", True),
    ("Privacy", "Cod. privacy", "Codice in materia di protezione dei dati personali (D.Lgs. 196/2003)", "urn:nir:stato:decreto.legislativo:2003-06-30;196", True),

    ("Professione forense", "L. 247/2012", "Ordinamento della professione forense", "urn:nir:stato:legge:2012-12-31;247", True),
    ("Professione forense", "D.M. 55/2014", "Parametri per i compensi degli avvocati", "urn:nir:ministero.giustizia:decreto:2014-03-10;55", True),
]

EURLEX = [
    # area, sigla, titolo, codice CELEX, attivo
    ("Privacy", "GDPR", "Regolamento (UE) 2016/679 sulla protezione dei dati personali", "32016R0679", True),
]
