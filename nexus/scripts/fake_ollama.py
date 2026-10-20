"""Faux serveur Ollama pour démonstrations et tests hors ligne. NE PAS utiliser comme modèle réel.
Il répond à /api/chat et /api/tags avec des réponses déterministes simples (règles par mots-clés).
Usage : python scripts/fake_ollama.py --port 11434"""
import argparse, json
from http.server import BaseHTTPRequestHandler, HTTPServer


def reply(system: str, user: str) -> str:
    if "intention JSON" in system:
        u = user.lower()
        if "arr" in u and "workflow" in u:
            return json.dumps({"intent": "request_stop_workflows", "params": {"reason": user[:200]}})
        if "exp" in u:
            return json.dumps({"intent": "run_demo_experiment", "params": {"fast": 10, "slow": 50}})
        if "tâche" in u or "tache" in u:
            return json.dumps({"intent": "create_task", "params": {"title": user[:100]}})
        if "état" in u or "etat" in u or "status" in u:
            return json.dumps({"intent": "show_status", "params": {}})
        return json.dumps({"intent": "unsupported", "params": {}})
    if "JSON" in system:
        return json.dumps({"agreements": ["Le risque existe"], "disagreements": ["Taille de l'échantillon", "Horizon de décision"],
                           "open_questions": ["Quelles données réelles ?"], "recommendation": "Attendre plus de données"})
    if "proposant" in system:
        return "Proposition (réponse de démonstration) : avancer par étapes, en simulation d'abord."
    if "contradicteur" in system:
        return "Contre-analyse (réponse de démonstration) : hypothèses non vérifiées, échantillon trop court."
    return "Résumé de démonstration."


class H(BaseHTTPRequestHandler):
    def _send(self, obj, code=200):
        b = json.dumps(obj).encode(); self.send_response(code); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)

    def do_GET(self):
        self._send({"models": [{"name": "fake-demo"}]} if self.path.startswith("/api/tags") else {"error": "not found"}, 200 if self.path.startswith("/api/tags") else 404)

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0)); body = json.loads(self.rfile.read(n) or b"{}")
        if self.path == "/api/chat":
            m = body.get("messages", [])
            self._send({"message": {"role": "assistant", "content": reply(m[0]["content"], m[1]["content"])}, "done": True})
        else:
            self._send({"error": "not found"}, 404)

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("--port", type=int, default=11434); a = ap.parse_args()
    HTTPServer(("127.0.0.1", a.port), H).serve_forever()
