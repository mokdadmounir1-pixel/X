"""Comparatifs mesurés cœur vs outils open source. Un outil n'est intégré au cœur QUE s'il apporte un gain
mesuré (vitesse ou exactitude). Exécuté dans le venv de la boîte à outils."""
from __future__ import annotations
import json
import subprocess
import sys
import time
from pathlib import Path
from .install import _py, ROOT, VENV

SCRIPT = r'''
import json, time, sys
sys.path.insert(0, sys.argv[1])
import numpy as np, pandas as pd
out = {}
rng = np.random.default_rng(0); n = 200000
c = np.cumsum(rng.standard_normal(n)) + 1000; h = c + rng.random(n); l = c - rng.random(n)
from ftmo_algo.indicators import ema_arr, atr_arr
def timeit(f, k=5):
    t = time.perf_counter(); [f() for _ in range(k)]; return (time.perf_counter() - t) / k
try:
    import talib
    a_core, a_ref = atr_arr(h, l, c, 14), talib.ATR(h, l, c, 14)
    e_core, e_ref = ema_arr(c, 20), talib.EMA(c, 20)
    out["talib_ema"] = {"max_abs_diff_after_warmup": float(np.nanmax(np.abs(e_core[500:] - e_ref[500:]))),
                        "t_core_s": timeit(lambda: ema_arr(c, 20)), "t_tool_s": timeit(lambda: talib.EMA(c, 20))}
    out["talib_atr"] = {"max_abs_diff_after_warmup": float(np.nanmax(np.abs(a_core[500:] - a_ref[500:]))),
                        "t_core_s": timeit(lambda: atr_arr(h, l, c, 14)), "t_tool_s": timeit(lambda: talib.ATR(h, l, c, 14))}
except Exception as e: out["talib"] = "non mesuré: " + repr(e)[:120]
try:
    from sklearn.linear_model import LogisticRegression
    from ftmo_algo.research.ml import Logit
    X = rng.standard_normal((4000, 20)); y = (X[:, 0] + .5 * rng.standard_normal(4000) > 0).astype(float)
    m = Logit(3.0).fit(X, y); p1 = m.predict(X)
    sk = LogisticRegression(C=1/3.0, max_iter=500).fit(X, y); p2 = sk.predict_proba(X)[:, 1]
    out["sklearn_logistic"] = {"max_abs_proba_diff": float(np.abs(p1 - p2).max()),
        "t_core_s": timeit(lambda: Logit(3.0).fit(X, y), 3), "t_tool_s": timeit(lambda: LogisticRegression(C=1/3.0, max_iter=500).fit(X, y), 3)}
except Exception as e: out["sklearn"] = "non mesuré: " + repr(e)[:120]
try:
    import numba
    out["numba"] = "présent (aucun noyau chaud à accélérer : les boucles dominantes sont dans Sim, déjà à événements)"
except Exception as e: out["numba"] = "non mesuré: " + repr(e)[:120]
print(json.dumps(out))
'''


def run_bench(out="results/toolbox_bench.json"):
    if not VENV.exists():
        return {"status": "venv absent : lancer `install` d'abord"}
    r = subprocess.run([_py(), "-I", "-c", SCRIPT, str(ROOT)], capture_output=True, text=True, timeout=900)
    try:
        res = json.loads(r.stdout.strip().splitlines()[-1])
    except Exception:
        res = {"error": (r.stdout + r.stderr)[-500:]}
    for k, v in list(res.items()):
        if isinstance(v, dict) and "t_core_s" in v:
            v["speedup_tool_vs_core"] = round(v["t_core_s"] / max(v["t_tool_s"], 1e-9), 2)
            v["integration"] = ("intégrable (gain de vitesse >2× mesuré)" if v["speedup_tool_vs_core"] > 2 else
                                "non intégré : pas de gain mesuré suffisant ; le cœur reste sans dépendance")
    res["_rule"] = "intégration au cœur uniquement si gain mesuré (vitesse ou exactitude) ; sinon le cœur reste minimal"
    Path(ROOT / out).parent.mkdir(exist_ok=True)
    Path(ROOT / out).write_text(json.dumps(res, indent=1))
    return res
