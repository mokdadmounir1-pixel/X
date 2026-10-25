"""Point d'entrée du terminal de bureau (fenêtre native si pywebview est installé, sinon navigateur par défaut). Lecture seule : aucun ordre."""
import sys
import time
import webbrowser

from quantbot.gui.paths import app_root
from quantbot.gui.server import start_background


def main() -> int:
    port, server = start_background(None, app_root(), autosync=True)
    url = f"http://127.0.0.1:{port}/"
    try:
        import webview  # type: ignore
    except ImportError:
        print(f"pywebview absent : ouverture dans le navigateur ({url}) — Ctrl+C pour arrêter")
        webbrowser.open(url)
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass
    else:
        webview.create_window("QUANTBOT — terminal", url, width=1560, height=940, min_size=(1100, 700), background_color="#080a0d")
        webview.start()
    server.should_exit = True
    return 0


if __name__ == "__main__":
    sys.exit(main())
