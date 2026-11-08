# Flawless Project

Assistente IA per studi legali italiani che funziona interamente sul computer dell'utente: documenti e conversazioni
non vengono inviati a servizi esterni. Risponde sui documenti del fascicolo e sulla normativa italiana, citando sempre
il testo su cui si basa.

> **Non è un parere legale.** Il programma usa un modello linguistico piccolo e può sbagliare, anche quando trova la
> norma giusta. Ogni risposta va controllata sul testo ufficiale. Il progetto è in fase di prova e non è stato ancora
> valutato da un legale.

## Cosa fa

- **Domande sui documenti** caricati in un fascicolo, con citazioni cliccabili alla pagina usata.
- **Lettura delle scansioni:** le pagine senza testo vengono riconosciute con l'OCR, sul computer, e il programma avvisa
  che cifre, date e nomi possono contenere errori di lettura.
- **Domande sulla normativa**, citando un articolo o descrivendo il problema; sotto la risposta compare il testo ufficiale.
- **Chat libera** su qualunque questione giuridica: parte dai testi di legge in archivio e, se non bastano, ragiona per
  ipotesi, dichiarandole come tali. Il programma segnala articoli e cifre che i testi trovati non contengono.
- **Dati chiave e scadenze** estratti dai documenti.
- **Riassunti, bozze e confronto** tra due versioni di un atto, esportabili in Word.
- **Modelli dello studio** con campi `{{nome}}`, compilabili a mano o dal modello linguistico, esportabili in PDF o Word.
- **Fascicoli separati:** ogni fascicolo vede solo i propri documenti. I testi di legge sono comuni a tutti e
  l'interfaccia non permette di cancellarli.

## Requisiti

- [Python](https://www.python.org/) 3.13
- [Ollama](https://ollama.com/) in esecuzione
- 16 GB di RAM. Non serve una scheda grafica: su un portatile Snapdragon X Plus una risposta richiede in genere 15-100 secondi.

Il programma è stato provato solo su Windows 11; `avvia.bat` è specifico per Windows.

## Installazione

```
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
ollama pull qwen3.5:4b
ollama pull bge-m3
```

Il repository non contiene l'archivio delle leggi, che va costruito una volta scaricandolo dalle fonti ufficiali:

```
.venv\Scripts\python.exe -m backend.normativa aggiorna
```

Il comando scarica i 74 atti principali del catalogo (Costituzione, codici, leggi di settore e GDPR). La ricerca per
numero di articolo funziona subito; quella per significato si completa in background mentre il server è acceso e,
senza scheda grafica, può richiedere molte ore.

Facoltativo: `python -m backend.raccolta elenca` e poi `python -m backend.raccolta scarica` aggiungono altri atti,
consultabili solo citandoli per tipo e numero. Il download è lento di proposito e si ferma se il sito rifiuta le richieste.

## Avvio

Doppio clic su `avvia.bat`, oppure:

```
.venv\Scripts\python.exe avvia.py
```

L'interfaccia si apre su `http://127.0.0.1:8765`; la documentazione delle API è su `/docs`.

## Struttura del codice

```
avvia.py, avvia.bat   avvio del server e apertura del browser
backend/              server FastAPI e logica del programma
frontend/             interfaccia web, senza librerie esterne
tessdata/             dati della lingua italiana per l'OCR
tests/                test automatici e prove d'integrazione
data/                 archivio e documenti dell'utente (creata al primo avvio, esclusa dal repository)
```

| File in `backend/` | Compito |
|---|---|
| `main.py` | Tutte le API: il punto d'ingresso per capire cosa fa il programma |
| `rag.py` | Costruzione delle risposte: ricerca, prompt, modello, avvisi, cronologia |
| `normativa.py` | Archivio delle leggi: scaricamento, lettura Akoma Ntoso, indicizzazione e ricerca |
| `normativa_catalogo.py` | Elenco degli atti principali |
| `normativa_glossario.py` | Termini giuridici collegati agli articoli da leggere per primi |
| `raccolta.py` | Scaricamento facoltativo degli altri atti da Normattiva |
| `documents.py` | Lettura dei file caricati e divisione in frammenti |
| `ocr.py` | Riconoscimento del testo nelle pagine scansionate |
| `features.py` | Riassunti, estrazione dei dati, bozze e confronto |
| `modelli.py` | Modelli dello studio, compilazione e PDF |
| `export.py` | Impaginazione in Word e HTML |
| `elements.py` | Parti, date, scadenze e importi del fascicolo |
| `controlli.py` | Verifiche scritte nel programma su ciò che il modello produce |
| `sicurezza.py` | Difese contro la prompt injection |
| `jobs.py` | Lavoro in background, che cede sempre il passo alle domande |
| `llm.py` | Comunicazione con Ollama e precedenze |
| `db.py` | Archivio SQLite e schema delle tabelle |
| `config.py` | Impostazioni |

**Da dove iniziare a leggere:** `rag.py` (`ask_normativa`) mostra il percorso completo di una domanda; da lì si arriva a
`normativa.py` (`cerca`), che decide quali articoli vengono letti.

**Il percorso di una domanda:** il filtro di `sicurezza.py` controlla il testo; `cerca` trova prima gli articoli citati,
poi quelli indicati dal glossario, poi quelli vicini per significato; il modello risponde solo su quei testi;
`controlli.py` e `rag.py` aggiungono gli avvisi; risposta e fonti vengono salvate.

## Scelte da conoscere prima di modificare il codice

- **Prompt:** non vanno accorciati senza ripetere le prove. Una versione più breve è passata da 5 risposte corrette su 5 a 0 su 5.
- **Controlli nel codice, non nel prompt:** ciò che deve valere sempre si verifica in `controlli.py`, comunque il modello formuli il testo.
- **Temperatura 0:** la stessa domanda dà la stessa risposta, quindi anche un errore si ripete.
- **Leggi di modifica:** gli atti della raccolta entrano nella risposta solo se citati, perché possono riportare testo poi superato.
- **Testi di legge protetti:** le API non offrono alcun modo di cancellarli, e un test lo verifica.

## Configurazione

Le impostazioni sono in `backend/config.py` e si cambiano con variabili d'ambiente `LAW_<NOME>`, per esempio
`LAW_NUM_CTX=8192` per ridurre la RAM usata.

Il nome interno `law_prog` resta nel file del database, nei log e nella cartella del progetto.

## Test

```
.venv\Scripts\python.exe -m unittest discover -s tests -t .
```

I test in `tests/` usano un archivio temporaneo e non richiedono Ollama. Le prove in `tests/integrazione/` richiedono
invece Ollama e l'archivio delle leggi; ognuna spiega all'inizio come si avvia.

## Fonti dei testi di legge

- **Normattiva** (Poligrafico e Zecca dello Stato), licenza CC BY 4.0, formato Akoma Ntoso.
- **GDPR** dal servizio Cellar dell'Ufficio delle pubblicazioni dell'Unione europea.

## Limiti noti

- Non contiene tutta la legislazione, né giurisprudenza, dottrina, leggi regionali e contratti collettivi.
- Gli articoli lunghi vengono letti solo in parte; il programma lo segnala.
- Il glossario non è stato rivisto da un legale.
- Le bozze possono contenere errori di significato e vanno rilette per intero.
- L'OCR può sbagliare, soprattutto su fotocopie rovinate, timbri e scrittura a mano; richiede circa 3 secondi a pagina.

## Licenza

Distribuito con licenza [GNU AGPL 3.0](LICENSE), senza alcuna garanzia. Il progetto usa [PyMuPDF](https://pymupdf.io/),
disponibile con licenza AGPL 3.0 o commerciale. I dati in `tessdata/` provengono dal progetto Tesseract e hanno licenza
[Apache 2.0](tessdata/LICENSE). I testi di legge non fanno parte del repository e restano soggetti alle
condizioni delle rispettive fonti.
