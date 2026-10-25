"""DIAGNOSTIC (pas un essai) : les scores flous apportent-ils de l'information AU-DELÀ du simple biais directionnel du marché ?

Compare, sur la période de VALIDATION, l'espérance nette de « prendre TOUS les achats » (resp. toutes les ventes) à celle des achats
(ventes) à score élevé. Si l'écart est nul, le « résultat » vient du bêta (marché haussier), pas des figures.
"""
import json, sys
from pathlib import Path
import numpy as np
ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "scripts"))
from run_mtf import cached_scores
from quantbot.core.labels import compute_labels
from quantbot.data.mt5 import costs_from_frame, load_mt5_csv
from quantbot.data.mtf import resample_base
from quantbot.lab.locked import split_locked
from quantbot.lab.specs import build_settings

def boot_diff(a, b, B=4000, seed=0):
    rng = np.random.default_rng(seed); a, b = a[np.isfinite(a)], b[np.isfinite(b)]
    if len(a) < 30 or len(b) < 30: return None
    d = [rng.choice(a, len(a)).mean() - rng.choice(b, len(b)).mean() for _ in range(B)]
    return [round(float(np.percentile(d, 2.5)), 3), round(float(np.percentile(d, 97.5)), 3)]

def main(spec_path, inst, tf):
    spec = json.loads(Path(spec_path).read_text(encoding="utf-8")); P = spec["procedure"]; tfc = spec["timeframes"][tf]
    df = load_mt5_csv(ROOT / "data" / "real" / spec["instruments"][inst])
    research, _ = split_locked(df, spec["lock_months"], spec["lock_min_frac"])
    base = research if tfc.get("rule") is None else resample_base(research, tfc["rule"])
    s = build_settings(spec, inst, costs_from_frame(df), base).with_overrides({"backtest.max_hold_bars": tfc["max_hold_bars"]})
    bull, bear = cached_scores(base, s, ROOT / "reports" / spec["name"] / "cache")
    lab = compute_labels(base, s); n = len(base); k = int(P["train_frac"] * n); purge = lab.purge_bars(s)
    t = np.arange(n); va = t >= k + purge
    out = {"instrument": inst, "timeframe": tf, "bars_valid": int(va.sum()), "buy_hold_valid_pct": round(float(base.close.iloc[-1] / base.close.iloc[k + purge] - 1) * 100, 1)}
    for side, y, sc in (("long", lab.long_r, bull), ("short", lab.short_r, bear)):
        allv = y[va]; ok = np.isfinite(allv)
        hi = y[va & (sc >= 0.65)]; lo = y[va & (sc < 0.65) & (sc >= 0.35)]; none = y[va & ~(sc >= 0.35)]
        f = lambda a: (int(np.isfinite(a).sum()), round(float(np.nanmean(a)), 4) if np.isfinite(a).any() else None)
        out[side] = {"TOUTES_les_barres (sans condition)": f(allv), "score>=0.65": f(hi), "score 0.35-0.65": f(lo), "score<0.35 (aucun setup)": f(none),
                     "IC95 [E(score>=0.65) - E(sans condition)]": boot_diff(hi, allv)}
    return out

if __name__ == "__main__":
    spec = sys.argv[1]; res = [main(spec, i, tf) for i, tf in [a.split(":") for a in sys.argv[2:]]]
    print(json.dumps(res, indent=1, ensure_ascii=False))
