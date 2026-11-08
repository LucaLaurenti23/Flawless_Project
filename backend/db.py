"""Archivio SQLite: fascicoli, documenti, frammenti indicizzati, conversazioni e modelli di bozza."""
import json
import sqlite3
from contextlib import contextmanager

import numpy as np

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS cases (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    client TEXT DEFAULT '',
    notes TEXT DEFAULT '',
    created_at TEXT DEFAULT (datetime('now', 'localtime'))
);
CREATE TABLE IF NOT EXISTS documents (
    id INTEGER PRIMARY KEY,
    case_id INTEGER NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
    filename TEXT NOT NULL,
    path TEXT NOT NULL,
    pages INTEGER,
    chars INTEGER,
    warning TEXT DEFAULT '',
    created_at TEXT DEFAULT (datetime('now', 'localtime'))
);
CREATE TABLE IF NOT EXISTS chunks (
    id INTEGER PRIMARY KEY,
    document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    page INTEGER,
    text TEXT NOT NULL,
    embedding BLOB NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_chunks_document ON chunks(document_id);
CREATE TABLE IF NOT EXISTS conversations (
    id INTEGER PRIMARY KEY,
    case_id INTEGER REFERENCES cases(id) ON DELETE CASCADE,
    kind TEXT NOT NULL CHECK (kind IN ('rag', 'norm', 'chat')),
    title TEXT NOT NULL,
    created_at TEXT DEFAULT (datetime('now', 'localtime'))
);
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY,
    conversation_id INTEGER NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    sources TEXT DEFAULT '[]',
    meta TEXT DEFAULT '{}',
    created_at TEXT DEFAULT (datetime('now', 'localtime'))
);
CREATE TABLE IF NOT EXISTS extractions (
    document_id INTEGER PRIMARY KEY REFERENCES documents(id) ON DELETE CASCADE,
    status TEXT NOT NULL,
    rows TEXT DEFAULT '[]',
    error TEXT DEFAULT '',
    updated_at TEXT DEFAULT (datetime('now', 'localtime'))
);
CREATE TABLE IF NOT EXISTS templates (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    body TEXT NOT NULL,
    created_at TEXT DEFAULT (datetime('now', 'localtime'))
);

-- Archivio normativo: un atto (legge, codice) e i suoi articoli, divisi in parti se lunghi.
CREATE TABLE IF NOT EXISTS norme_atti (
    id INTEGER PRIMARY KEY,
    sigla TEXT NOT NULL UNIQUE,
    titolo TEXT NOT NULL,
    area TEXT NOT NULL,
    fonte TEXT NOT NULL,
    urn TEXT NOT NULL,
    vigente_al TEXT,
    scaricato_il TEXT DEFAULT (datetime('now', 'localtime'))
);
CREATE TABLE IF NOT EXISTS norme (
    id INTEGER PRIMARY KEY,
    atto_id INTEGER NOT NULL REFERENCES norme_atti(id) ON DELETE CASCADE,
    sezione TEXT DEFAULT '',          -- '' = corpo principale; es. 'Disposizioni sulla legge in generale'
    articolo TEXT,                    -- numero normalizzato: '1385', '2-bis'; NULL per gli allegati
    rubrica TEXT DEFAULT '',
    parte INTEGER DEFAULT 0,          -- articoli lunghi: 0, 1, 2...
    testo TEXT NOT NULL,
    embedding BLOB
);
CREATE INDEX IF NOT EXISTS idx_norme_articolo ON norme(atto_id, articolo);
CREATE INDEX IF NOT EXISTS idx_norme_da_indicizzare ON norme(id) WHERE embedding IS NULL;
CREATE INDEX IF NOT EXISTS idx_norme_indicizzate ON norme(id) WHERE embedding IS NOT NULL;
CREATE VIRTUAL TABLE IF NOT EXISTS norme_fts USING fts5(
    rubrica, testo, content='norme', content_rowid='id', tokenize='unicode61 remove_diacritics 2'
);
-- La raccolta generale (tutti gli atti non abrogati) ha un indice a parte: le ricerche sugli atti principali restano veloci.
CREATE VIRTUAL TABLE IF NOT EXISTS raccolta_fts USING fts5(
    rubrica, testo, content='norme', content_rowid='id', tokenize='unicode61 remove_diacritics 2'
);
CREATE TABLE IF NOT EXISTS raccolta_coda (
    codice TEXT PRIMARY KEY,          -- codice redazionale della Gazzetta Ufficiale
    data_gu TEXT NOT NULL,
    denominazione TEXT,
    numero TEXT,
    giorno INTEGER, mese INTEGER, anno INTEGER,
    titolo TEXT,
    priorita INTEGER NOT NULL,
    stato TEXT NOT NULL DEFAULT 'da fare',   -- da fare, fatto, errore, saltato
    errore TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_raccolta_coda ON raccolta_coda(stato, priorita, anno);
"""

DEFAULT_CASE = "Generale"

# Modelli di esempio: vanno rivisti e adattati dallo studio prima dell'uso reale.
SEED_TEMPLATES = {
    "Diffida ad adempiere": """{{luogo}}, {{data}}

Spett.le {{destinatario}}
{{indirizzo_destinatario}}

Raccomandata A/R / PEC

Oggetto: diffida ad adempiere ai sensi dell'art. 1454 c.c.

Scrivo in nome e per conto del/della mio/a assistito/a {{cliente}}, che sottoscrive per conferimento di incarico.

Premesso che:
- in data {{data_contratto}} è stato stipulato tra le parti {{descrizione_contratto}};
- {{descrizione_inadempimento}};

con la presente La diffido formalmente ad adempiere alla seguente obbligazione: {{obbligazione}}, entro e non oltre {{termine}} giorni dal ricevimento della presente.

Decorso inutilmente tale termine, il contratto s'intenderà risolto di diritto ai sensi dell'art. 1454 c.c., fatto salvo il diritto al risarcimento di tutti i danni subiti e subendi.

Distinti saluti.

Avv. {{avvocato}}
""",
    "Sollecito di pagamento": """{{luogo}}, {{data}}

Spett.le {{destinatario}}
{{indirizzo_destinatario}}

Oggetto: sollecito di pagamento – {{riferimento}}

Scrivo in nome e per conto di {{cliente}}.

Dalla documentazione in mio possesso risulta che la S.V. non ha ancora provveduto al pagamento dell'importo di € {{importo}}, dovuto a titolo di {{causale}} e scaduto in data {{data_scadenza}}.

La invito pertanto a provvedere al saldo entro {{termine}} giorni dal ricevimento della presente, mediante bonifico sulle seguenti coordinate: {{coordinate}}.

In mancanza, mi vedrò costretto/a ad agire nelle opportune sedi per il recupero del credito, con aggravio di spese, interessi e oneri a Suo carico.

Distinti saluti.

Avv. {{avvocato}}
""",
    "Lettera generica": """{{luogo}}, {{data}}

Spett.le {{destinatario}}
{{indirizzo_destinatario}}

Oggetto: {{oggetto}}

{{corpo}}

Distinti saluti.

Avv. {{avvocato}}
""",
}


def connect():
    """Apre una connessione con righe leggibili per nome, chiavi esterne attive e modalità WAL."""
    conn = sqlite3.connect(config.DB_PATH, timeout=60)   # la raccolta scrive da un processo separato
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


@contextmanager
def session():
    """Contesto per usare l'archivio: conferma le modifiche se non ci sono errori e chiude sempre la connessione."""
    conn = connect()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _migra_conversazioni():
    """Archivi creati prima della modalità Normativa: il vincolo sul tipo di conversazione va allargato.
    SQLite non modifica i vincoli: si ricrea la tabella, con le chiavi esterne spente per non perdere i messaggi."""
    conn = sqlite3.connect(config.DB_PATH)
    try:
        sql = conn.execute("SELECT sql FROM sqlite_master WHERE name = 'conversations'").fetchone()
        if not sql or "'norm'" in sql[0]:
            return
        conn.execute("PRAGMA foreign_keys = OFF")
        conn.executescript("""
            BEGIN;
            CREATE TABLE conversations_nuova (
                id INTEGER PRIMARY KEY,
                case_id INTEGER REFERENCES cases(id) ON DELETE CASCADE,
                kind TEXT NOT NULL CHECK (kind IN ('rag', 'norm', 'chat')),
                title TEXT NOT NULL,
                created_at TEXT DEFAULT (datetime('now', 'localtime'))
            );
            INSERT INTO conversations_nuova SELECT id, case_id, kind, title, created_at FROM conversations;
            DROP TABLE conversations;
            ALTER TABLE conversations_nuova RENAME TO conversations;
            COMMIT;""")
    finally:
        conn.close()


def init():
    """Prepara cartelle e tabelle, aggiorna gli archivi creati da versioni precedenti e inserisce i dati iniziali."""
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    config.FILES_DIR.mkdir(parents=True, exist_ok=True)
    _migra_conversazioni()
    with session() as conn:
        conn.executescript(SCHEMA)
        # archivi creati prima dei tempi di risposta: aggiunge la colonna mancante
        if "meta" not in {r["name"] for r in conn.execute("PRAGMA table_info(messages)")}:
            conn.execute("ALTER TABLE messages ADD COLUMN meta TEXT DEFAULT '{}'")
        conn.execute("INSERT OR IGNORE INTO cases (name) VALUES (?)", (DEFAULT_CASE,))
        if conn.execute("SELECT COUNT(*) FROM templates").fetchone()[0] == 0:
            conn.executemany("INSERT INTO templates (name, body) VALUES (?, ?)", SEED_TEMPLATES.items())


def rows(cursor):
    """Tutte le righe del cursore, come dizionari."""
    return [dict(r) for r in cursor.fetchall()]


def one(cursor):
    """La prima riga del cursore come dizionario, oppure None."""
    row = cursor.fetchone()
    return dict(row) if row else None


# --- Embedding <-> BLOB -----------------------------------------------------

def to_blob(vector):
    """Converte un vettore di embedding in byte (float a 32 bit) per salvarlo nell'archivio."""
    return np.asarray(vector, dtype=np.float32).tobytes()


def from_blob(blob):
    """Ricostruisce un vettore di embedding dai byte salvati nell'archivio."""
    return np.frombuffer(blob, dtype=np.float32)


# --- Conversazioni ------------------------------------------------------------

def create_conversation(conn, case_id, kind, title):
    """Crea una conversazione e ne restituisce l'id. Il titolo si ferma a 80 caratteri."""
    cur = conn.execute(
        "INSERT INTO conversations (case_id, kind, title) VALUES (?, ?, ?)",
        (case_id, kind, title[:80]),
    )
    return cur.lastrowid


def add_message(conn, conversation_id, role, content, sources=None, meta=None):
    """Salva un messaggio con le fonti usate e i dati accessori (per esempio i tempi di risposta)."""
    conn.execute(
        "INSERT INTO messages (conversation_id, role, content, sources, meta) VALUES (?, ?, ?, ?, ?)",
        (conversation_id, role, content, json.dumps(sources or [], ensure_ascii=False),
         json.dumps(meta or {}, ensure_ascii=False)),
    )


def get_messages(conn, conversation_id):
    """I messaggi di una conversazione in ordine cronologico, con fonti e dati accessori già decodificati."""
    messages = rows(conn.execute(
        "SELECT role, content, sources, meta, created_at FROM messages WHERE conversation_id = ? ORDER BY id",
        (conversation_id,),
    ))
    for m in messages:
        m["sources"] = json.loads(m["sources"] or "[]")
        m["meta"] = json.loads(m["meta"] or "{}")
    return messages


# --- Estrazione dei dati chiave -------------------------------------------------

def save_extraction(conn, document_id, status, rows=None, error=""):
    """Stato dell'estrazione di un documento; `rows=None` lascia i dati già estratti."""
    if rows is None:
        conn.execute("""INSERT INTO extractions (document_id, status, error) VALUES (?, ?, ?)
                        ON CONFLICT(document_id) DO UPDATE SET status = excluded.status, error = excluded.error,
                        updated_at = datetime('now', 'localtime')""", (document_id, status, error))
    else:
        conn.execute("""INSERT INTO extractions (document_id, status, rows, error) VALUES (?, ?, ?, ?)
                        ON CONFLICT(document_id) DO UPDATE SET status = excluded.status, rows = excluded.rows,
                        error = excluded.error, updated_at = datetime('now', 'localtime')""",
                     (document_id, status, json.dumps(rows, ensure_ascii=False), error))
