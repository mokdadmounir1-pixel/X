"""Batterie journalière EN ARRIÈRE : hypothèses à paramètres FIGÉS (specs/battery_v1.json) sur les années d'H1 qui PRÉCÈDENT la période de recherche.

    python scripts/run_battery_backward.py specs/battery_backward_v1.json

Seules les hypothèses qui n'ont besoin que du prix de 16:00 New York sont possibles en H1 (les créneaux 09:30 et 15:30 n'existent pas sur des barres H1).
La période verrouillée n'est jamais lue. Les résultats sont comptés au registre (un essai par instrument x hypothèse).
"""
import argparse, importlib.util, json, sys
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT))
from quantbot.data.mt5 import costs_from_frame, load_mt5_csv
from quantbot.lab import battery as bt
from quantbot.lab import stats as st
from quantbot.lab.pipeline import data_hash
from quantbot.lab.registry import TrialRegistry, canonical_hash

_sp = importlib.util.spec_from_file_location("run_battery", ROOT / "scripts" / "run_battery.py")
rb = importlib.util.module_from_spec(_sp); _sp.loader.exec_module(rb)


def main():
    [getattr(_s, "reconfigure", lambda **k: None)(encoding="utf-8", errors="replace") for _s in (sys.stdout, sys.stderr)]  # console cp1252 : jamais de crash d'affichage
    ap = argparse.ArgumentParser(); ap.add_argument("spec"); ap.add_argument("--registry", default=str(ROOT / "reports" / "registry.jsonl"))
    args = ap.parse_args()
    bw = json.loads(Path(args.spec).read_text(encoding="utf-8")); base = json.loads((ROOT / bw["base_spec"]).read_text(encoding="utf-8")); R = base["rules"]
    reg = TrialRegistry(args.registry); out_dir = ROOT / "reports" / bw["name"]; out_dir.mkdir(parents=True, exist_ok=True)
    spec_h = canonical_hash({"base": {k: base[k] for k in ("hypotheses", "costs", "rules")}, "segment": bw["name"], "hyps": bw["hypotheses"]})
    results, nets = {}, {}
    for inst, fname in bw["instruments"].items():
        deep = ROOT / bw["deep_dir"] / fname
        if not deep.is_file():
            print(f"[{inst}] SAUTÉ : {deep} absent"); continue
        start = load_mt5_csv(ROOT / "data" / "real" / base["instruments"][inst]).index[0]
        full = load_mt5_csv(deep); seg = full[full.index < start]
        days = (seg.index[-1] - seg.index[0]).days if len(seg) else 0
        if days < bw["min_days"]:
            print(f"[{inst}] SAUTÉ : {days} jours avant {start.date()} (< {bw['min_days']})"); continue
        p = bt.session_prices(seg, bar_minutes=60, slots=("1600",)); c = rb.cost_rt(base, inst, costs_from_frame(seg)); dh = data_hash(seg)
        for hyp in bw["hypotheses"]:
            h = base["hypotheses"][hyp]; res = bt.HYPOTHESES[hyp](p, c, **h.get("params", {})); res2 = bt.HYPOTHESES[hyp](p, 2 * c, **h.get("params", {}))
            s = bt.summarize(res.net, res.bh); s.update(mean_bps_costs_x2=float(res2.net.mean() * 1e4), cost_rt_bps=c * 1e4, n_trades=res.n_trades,
                                                        segment={"start": str(seg.index[0]), "end": str(seg.index[-1]), "bars": len(seg)})
            sr, _, _, n = st.sharpe_moments(res.net.to_numpy()); reg.record_trial(canonical_hash([spec_h, inst, hyp]), dh, sr, n)
            results[(inst, hyp)] = s; nets[(inst, hyp)] = res.net
    if not results:
        print("Aucun résultat : historique H1 profond manquant ou trop court."); return 1
    keys = list(results); idx = sorted(set().union(*[nets[k].index for k in keys]))
    mat = np.column_stack([nets[k].reindex(idx).fillna(0.0).to_numpy() for k in keys])
    rc = st.reality_check(mat, B=R["reality_check"]["B"], mean_block=R["reality_check"]["mean_block"])
    n_trials, var_sr = reg.n_trials(), reg.var_sharpe(); rows = []
    for k in keys:
        s = results[k]; s["dsr"] = st.deflated_sharpe(nets[k].to_numpy(), n_trials, var_sr)
        halves = s["mean_first_half_bps"] > 0 and s["mean_second_half_bps"] > 0
        surv = rc["p"] is not None and rc["p"] < 0.10 and s["t_nw"] > 2.0 and halves and s["mean_bps_costs_x2"] > 0 and s["bh_t_alpha"] > 2.0
        watch = rc["p"] is not None and rc["p"] < 0.20 and halves and s["mean_bps_costs_x2"] > 0
        s["verdict"] = "SURVIVANT" if surv else ("WATCH" if watch else "REJETÉ"); rows.append((k, s))
        (out_dir / f"{k[0]}_{k[1]}.json").write_text(json.dumps({"instrument": k[0], "hypothesis": k[1], **s}, indent=1), encoding="utf-8")
    (out_dir / "summary.json").write_text(json.dumps({"reality_check": rc, "n_trials_registry": n_trials, "n_hypotheses": len(keys), "days": len(idx),
                                                      "results": {f"{k[0]}|{k[1]}": s for k, s in rows}}, indent=1), encoding="utf-8")
    print(f"Reality Check ({len(keys)} hypothèses, {len(idx)} jours) : p = {rc['p']} | essais cumulés = {n_trials}")
    for k, s in sorted(rows, key=lambda r: -r[1]["t_nw"]):
        print(f"{k[0]:8s} {k[1]:12s} {s['segment']['start'][:10]}→{s['segment']['end'][:10]} jours={s['n_days']:5d} moy={s['mean_bps']:6.2f}bps x2={s['mean_bps_costs_x2']:6.2f} "
              f"Sharpe={s['sharpe_annual']:5.2f} t_NW={s['t_nw']:5.2f} 1/2={s['mean_first_half_bps']:6.2f} 2/2={s['mean_second_half_bps']:6.2f} alpha_t={s['bh_t_alpha']:5.2f} DSR={s['dsr']:.2f} {s['verdict']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
