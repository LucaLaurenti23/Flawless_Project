"""Avvia il server locale e apre l'interfaccia nel browser quando è pronta.
Il server resta attivo finché la finestra del terminale è aperta (Ctrl+C per fermarlo)."""
import threading
import time
import webbrowser

import httpx
import uvicorn

from backend import config

URL = f"http://{config.API_HOST}:{config.API_PORT}"


def server_attivo():
    """Il server risponde già?"""
    try:
        return httpx.get(f"{URL}/api/status", timeout=2).is_success
    except httpx.HTTPError:
        return False


def apri_quando_pronto():
    """Aspetta fino a un minuto che il server sia pronto, poi apre il browser."""
    for _ in range(120):
        if server_attivo():
            webbrowser.open(URL)
            return
        time.sleep(0.5)


def main():
    """Avvia il server e apre il browser; se il server è già attivo apre soltanto il browser."""
    if server_attivo():
        print(f"Flawless Project è già in esecuzione: apro {URL}")
        webbrowser.open(URL)
        return
    print(f"Flawless Project · assistente legale locale\nInterfaccia: {URL}\nChiudi questa finestra (o Ctrl+C) per fermarlo.\n")
    threading.Thread(target=apri_quando_pronto, daemon=True).start()
    uvicorn.run("backend.main:app", host=config.API_HOST, port=config.API_PORT, log_level="warning")


if __name__ == "__main__":
    main()
