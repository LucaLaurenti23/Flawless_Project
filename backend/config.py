"""Configurazione centrale. Ogni valore si può sovrascrivere con una variabile d'ambiente LAW_<NOME>."""
import os
from pathlib import Path


def _env(name, default, cast=str):
    """Il valore della variabile d'ambiente LAW_<name>, convertito con cast; se manca, il valore predefinito."""
    value = os.environ.get(f"LAW_{name}")
    return cast(value) if value is not None else default


ROOT = Path(__file__).resolve().parent.parent
FRONTEND_DIR = ROOT / "frontend"
DATA_DIR = Path(_env("DATA_DIR", str(ROOT / "data")))
FILES_DIR = DATA_DIR / "documenti"
DB_PATH = DATA_DIR / "law_prog.db"

OLLAMA_HOST = _env("OLLAMA_HOST", "http://localhost:11434")
CHAT_MODEL = _env("CHAT_MODEL", "qwen3.5:4b")
EMBED_MODEL = _env("EMBED_MODEL", "bge-m3")

# Finestra di contesto passata a Ollama: più è grande, più testo entra in un colpo, ma più RAM serve.
# Deve restare uguale in tutte le richieste: cambiarla costringe Ollama a ricaricare il modello (~6 s).
NUM_CTX = _env("NUM_CTX", 16384, int)
# Temperatura bassa: per uso legale vogliamo risposte aderenti al testo, non creative.
TEMPERATURE = _env("TEMPERATURE", 0.0, float)   # 0: la stessa domanda dà la stessa risposta
# Quanto a lungo Ollama tiene i modelli in memoria dopo l'ultima richiesta (predefinito di Ollama: 5 minuti).
KEEP_ALIVE = _env("KEEP_ALIVE", "60m")
# Thread del modello di testo. Misurato su Snapdragon X Plus a 8 core: 4 = 15 token/s in lettura, 6 = 21,
# 8 = il sistema si satura e crolla a 7. Come NUM_CTX, cambiarlo costringe Ollama a ricaricare il modello.
NUM_THREAD = _env("NUM_THREAD", 6, int)

# Tetto ai token scritti: domande e chat (risposte concise) e testi lunghi (riassunti, bozze, analisi).
MAX_ANSWER_TOKENS = _env("MAX_ANSWER_TOKENS", 700, int)
MAX_LONG_TOKENS = _env("MAX_LONG_TOKENS", 2500, int)

# Suddivisione dei documenti per la ricerca semantica. Sulla CPU il modello legge ~21 token/s:
# ogni brano nel prompt costa secondi, quindi brani corti e pochi (3; 6 nella ricerca approfondita).
CHUNK_CHARS = _env("CHUNK_CHARS", 800, int)
CHUNK_OVERLAP = _env("CHUNK_OVERLAP", 150, int)
TOP_K = _env("TOP_K", 3, int)
TOP_K_DEEP = _env("TOP_K_DEEP", 6, int)
# Brani molto meno pertinenti del migliore (somiglianza più bassa di oltre questo margine) non entrano nel prompt.
SCORE_MARGIN = _env("SCORE_MARGIN", 0.15, float)

# Oltre questa lunghezza un documento viene riassunto a sezioni.
SECTION_CHARS = _env("SECTION_CHARS", 20000, int)
# Sezioni più corte per l'estrazione: se una domanda la interrompe, si rifà solo la sezione in corso.
EXTRACT_SECTION_CHARS = _env("EXTRACT_SECTION_CHARS", 6000, int)
# L'estrazione parte da sola solo fino a questa lunghezza (circa 10 pagine); oltre, la avvia l'avvocato.
EXTRACT_AUTO_CHARS = _env("EXTRACT_AUTO_CHARS", 25000, int)

API_HOST = _env("API_HOST", "127.0.0.1")
API_PORT = _env("API_PORT", 8765, int)
