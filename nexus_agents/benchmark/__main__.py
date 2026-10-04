"""python -m nexus_agents.benchmark --models mistral,qwen2.5:7b --base-url http://127.0.0.1:11434 --out benchmark_out"""
import argparse
import json
from pathlib import Path

from ..models import OllamaModel, StubLocalModel
from .runner import evaluate, load, manifest, summarize


def main():
    ap = argparse.ArgumentParser(description="Qualification de modeles locaux (Ollama) sur le jeu d'exemples Nexus")
    ap.add_argument("--models", default="mistral", help="noms de modeles Ollama, separes par des virgules")
    ap.add_argument("--base-url", default="http://127.0.0.1:11434")
    ap.add_argument("--allow-host", action="append", default=[], help="hote supplementaire autorise (ex. adresse du tunnel prive)")
    ap.add_argument("--timeout", type=float, default=120)
    ap.add_argument("--stub", action="store_true", help="modele simule (verifie seulement que le banc fonctionne)")
    ap.add_argument("--out", default="benchmark_out")
    ap.add_argument("--tasks", default=None, help="sous-ensemble de taches, separees par des virgules")
    a = ap.parse_args()
    items, thresholds = load()
    tasks = set(a.tasks.split(",")) if a.tasks else None
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    rows = []
    names = ["stub"] if a.stub else [m.strip() for m in a.models.split(",") if m.strip()]
    for name in names:
        model = StubLocalModel() if a.stub else OllamaModel(name, a.base_url, a.timeout, ("127.0.0.1", "localhost", "::1", *a.allow_host))
        print(f"== {name}: {len([i for i in items if not tasks or i['task'] in tasks])} exemples ...", flush=True)
        recs = evaluate(model, items, tasks)
        summ = summarize(recs, thresholds)
        safe = name.replace(":", "_").replace("/", "_")
        (out / f"bench_{safe}.json").write_text(json.dumps({"model": name, "records": recs, "summary": summ}, ensure_ascii=False, indent=1), encoding="utf-8")
        (out / f"qualification_{safe}.json").write_text(json.dumps(manifest(name, summ), ensure_ascii=False, indent=1), encoding="utf-8")
        rows.append((name, summ))
        for t, r in summ["tasks"].items():
            print(f"   {t:15s} {r['verdict']:20s} {'; '.join(r['reasons'])[:140]}")
    md = ["# Rapport de qualification des modèles locaux", "",
          "Jeu d'exemples fictif de départ, seuils fixés avant mesure. **Un verdict « provisoire » ne qualifie pas** : il faut au moins "
          f"{thresholds['min_holdout_n']} exemples holdout par tâche, annotés par vous.", "",
          "| Modèle | Tâche | Verdict | Holdout n | Principales mesures (holdout) | Raisons |", "|---|---|---|---:|---|---|"]
    for name, s in rows:
        for t, r in s["tasks"].items():
            h = r["holdout"]
            keys = {"classify_reply": ["accuracy", "critical_errors", "injection_followed"],
                    "extract_fact": ["exact", "null_correct", "hallucinated", "injection_followed"], "draft_message": ["checks_pass", "promise"]}[t]
            meas = ", ".join(f"{k}={h[k]:.2f}" if isinstance(h[k], float) else f"{k}={h[k]}" for k in keys)
            md.append(f"| {name} | {t} | {r['verdict']} | {h['n']} | {meas} | {'; '.join(r['reasons'])} |")
    md += ["", f"Latence (toutes tâches) : " + "; ".join(f"{n}: p50 {s['latency']['p50_s']} s, p95 {s['latency']['p95_s']} s" for n, s in rows)]
    (out / "RAPPORT.md").write_text("\n".join(md), encoding="utf-8")
    print(f"\nRapport : {out / 'RAPPORT.md'}")


if __name__ == "__main__":
    main()
