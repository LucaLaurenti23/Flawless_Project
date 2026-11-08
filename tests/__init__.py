"""Test automatici. Lavorano su un archivio temporaneo: l'archivio reale in data/ non viene mai toccato.

La cartella temporanea va impostata qui, prima che qualunque test importi backend.config."""
import atexit
import os
import shutil
import tempfile

_CARTELLA = tempfile.mkdtemp(prefix="flawless_test_")
os.environ["LAW_DATA_DIR"] = _CARTELLA
atexit.register(shutil.rmtree, _CARTELLA, ignore_errors=True)
