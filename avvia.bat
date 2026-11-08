@echo off
rem Avvia Flawless Project in locale e apre il browser quando il server e' pronto.
rem Modelli (Ollama): qwen3.5:4b per il testo, bge-m3 per la ricerca. Per cambiarli: set LAW_CHAT_MODEL=...
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo Ambiente Python non trovato. Esegui prima:
    echo   python -m venv .venv
    echo   .venv\Scripts\python.exe -m pip install -r requirements.txt
    pause
    exit /b 1
)
".venv\Scripts\python.exe" avvia.py
if errorlevel 1 (
    echo.
    echo Il server si e' fermato con un errore: leggi il messaggio qui sopra.
    pause
)
