"""Essai MESURÉ de qualité et de latence des modèles locaux, sur la tâche réelle de l'Omni-Box :
convertir une commande en intention JSON valide. Aucun modèle n'est retenu sans ces chiffres.
Usage : python scripts/bench_ollama.py --models qwen2.5:7b-instruct qwen2.5:1.5b-instruct [--url http://127.0.0.1:11434] [--runs 2]
Critères de sélection (modifiables) : JSON valide 100 %, intention exacte >= 90 %, latence p95 <= 20 s."""
import argparse, json, statistics, sys, time
from pathlib import Path
import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))
from app.omnibox import INTENTS, SYSTEM_PROMPT  # noqa: E402

CASES = [
    ("montre-moi l'état du système", "show_status"), ("quel est le statut des services ?", "show_status"),
    ("donne-moi un point sur les tâches", "show_status"), ("crée une tâche : relire le rapport de jeudi", "create_task"),
    ("ajoute une note-tâche pour appeler le comptable", "create_task"), ("lance une expérience de démonstration", "run_demo_experiment"),
    ("fais un backtest de démo avec une moyenne rapide de 8 et lente de 40", "run_demo_experiment"),
    ("arrête tous les workflows, motif : maintenance", "request_stop_workflows"), ("stoppe les workflows en cours", "request_stop_workflows"),
    ("supprime tous les fichiers du serveur", "unsupported"), ("exécute rm -rf / sur la machine", "unsupported"),
    ("envoie la proposition au client maintenant", "unsupported"), ("passe un ordre d'achat sur le NASDAQ", "unsupported"),
]


def ask(url, model, text, timeout=120):
    body = {"model": model, "stream": False, "format": "json", "options": {"temperature": 0},
            "messages": [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": text}]}
    t0 = time.perf_counter()
    r = httpx.post(f"{url}/api/chat", json=body, timeout=timeout)
    r.raise_for_status()
    return r.json()["message"]["content"], time.perf_counter() - t0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", nargs="+", required=True)
    ap.add_argument("--url", default="http://127.0.0.1:11434")
    ap.add_argument("--runs", type=int, default=2)
    a = ap.parse_args()
    allowed = set(INTENTS) | {"unsupported"}
    print(f"{'modèle':<28}{'JSON valide':>12}{'intention OK':>14}{'p50 (s)':>10}{'p95 (s)':>10}  verdict")
    for m in a.models:
        lat, valid, good, n = [], 0, 0, 0
        for text, expected in CASES * a.runs:
            n += 1
            try:
                out, dt = ask(a.url, m, text)
            except Exception as e:  # noqa: BLE001
                print(f"{m:<28} ERREUR : {type(e).__name__} — modèle absent ? (ollama pull {m})"); break
            lat.append(dt)
            try:
                d = json.loads(out)
                ok = isinstance(d, dict) and isinstance(d.get("intent"), str) and isinstance(d.get("params", {}), dict)
            except ValueError:
                ok = False
            valid += ok
            good += ok and d["intent"] == expected and d["intent"] in allowed
        else:
            lat.sort()
            p50, p95 = statistics.median(lat), lat[min(len(lat) - 1, int(len(lat) * 0.95))]
            v, g = 100 * valid / n, 100 * good / n
            print(f"{m:<28}{v:>11.0f}%{g:>13.0f}%{p50:>10.2f}{p95:>10.2f}  {'RETENIR' if v == 100 and g >= 90 and p95 <= 20 else 'REFUSER'}")


if __name__ == "__main__":
    main()
