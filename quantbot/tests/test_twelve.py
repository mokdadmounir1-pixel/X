import json

import numpy as np
import pandas as pd
import pytest

from quantbot.ml import rl_agent
from quantbot.risk.tail_dependence import tail_dependence
from quantbot.stat import avellaneda, vol_arb
from quantbot.strategies import cot_extremes, external_data, fixing_seasonality, kalman_ou, macro_tips, ofi_depth, orderflow_iceberg
from quantbot.strategies.build import events_for, strategy_code
from tests.test_mtf_confluence import _long


def _ou(n=12000, seed=5):
    rng = np.random.default_rng(seed); x = np.zeros(n)
    for i in range(1, n):
        x[i] = 0.9 * x[i - 1] + rng.normal(0, 1.0)
    c = 2000 + x * 1.5; o = np.r_[c[0], c[:-1]]
    return pd.DataFrame({"open": o, "high": np.maximum(o, c) + 0.5, "low": np.minimum(o, c) - 0.5, "close": c, "volume": 100.0}, index=pd.date_range("2024-01-01", periods=n, freq="15min"))


def _valid(df, ev):
    for e in ev:
        px = df.close[e.ts]; assert (e.stop < px < e.target) if e.direction == "bullish" else (e.target < px < e.stop)


@pytest.mark.parametrize("mod,df_fn", [(kalman_ou, _ou), (orderflow_iceberg, _long), (fixing_seasonality, _long)])
def test_levels_valid_and_causal(mod, df_fn):
    df = df_fn(); ev = mod.events(df); _valid(df, ev)
    cut = int(len(df) * 0.7); part = mod.events(df.iloc[:cut]); k = lambda ev: [(e.ts, e.direction, round(e.stop, 6)) for e in ev]
    lim = df.index[cut - 300]
    assert k([e for e in ev if e.ts < lim]) == k([e for e in part if e.ts < lim])


def test_kalman_ou_trades_ou_and_dispatch():
    df = _ou(); ev = kalman_ou.events(df); assert ev and {e.direction for e in ev} == {"bullish", "bearish"}
    assert events_for("kalman_ou", {"params": {}}, df) == ev and strategy_code("kalman_ou") == "KALMAN_OU_REVERT"


def test_data_required_strategies_emit_nothing_without_data(tmp_path):
    df = _long(3000)
    for mod in (cot_extremes, macro_tips, ofi_depth):
        assert mod.events(df, {"root": str(tmp_path)}) == []
    assert set(external_data.REQUIRES) == {"cot_extremes", "macro_tips", "ofi_depth"} and external_data.missing("macro_tips", tmp_path)


def test_depth_loader_reads_real_files(tmp_path):
    d = tmp_path / "data" / "live" / "depth"; d.mkdir(parents=True)
    rows = [{"t": 1_700_000_000 + 60 * i, "bids": [[1.0, 30]], "asks": [[1.1, 10]]} for i in range(40)]
    (d / "XAUUSD_x.jsonl").write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    s = external_data.load_depth_imbalance(tmp_path); assert s is not None and (s > 0).all() and not external_data.missing("ofi_depth", tmp_path)


def test_fred_lag_one_day(tmp_path):
    d = tmp_path / "data" / "external"; d.mkdir(parents=True); (d / "fred_DFII10.csv").write_text("DATE,VALUE\n2024-01-02,1.5\n2024-01-03,.\n", encoding="utf-8")
    s = external_data.load_fred("DFII10", tmp_path); assert list(s.index) == [pd.Timestamp("2024-01-03")] and s.iloc[0] == 1.5


def test_avellaneda_quotes_skew_against_inventory():
    flat = avellaneda.quotes(100.0, 0, 0.5, 0.5); long = avellaneda.quotes(100.0, 3, 0.5, 0.5); short = avellaneda.quotes(100.0, -3, 0.5, 0.5)
    assert flat["reservation"] == pytest.approx(100.0) and long["reservation"] < 100 < short["reservation"] and flat["ask"] > flat["bid"]
    r = avellaneda.simulate(_ou(1500)); assert r["max_abs_inventory"] <= 5 and r["fills"] > 0


def test_vol_arb_and_tail_dependence():
    df = _long(2000); rv = vol_arb.realized_vol(df); assert (rv.dropna() > 0).all()
    assert np.isnan(vol_arb.variance_premium_z(float("nan"), rv))
    rng = np.random.default_rng(1); a = rng.standard_t(3, 4000); ind = tail_dependence(a, rng.standard_t(3, 4000)); dep = tail_dependence(a, a + 0.1 * rng.normal(size=4000))
    assert dep["lower"] > ind["lower"] and dep["lower_ratio"] > 3


def test_rl_walk_forward_runs_and_is_deterministic():
    df = _long(6000); a = rl_agent.walk_forward(df, train_bars=2000, test_bars=800, episodes=2); b = rl_agent.walk_forward(df, train_bars=2000, test_bars=800, episodes=2)
    assert a["n_windows"] >= 2 and a == b


def test_omega_merges_members_dedupes_same_direction_and_drops_opposite_conflicts():
    import json, pathlib
    from quantbot.strategies import build
    from quantbot.strategies.events import Event
    spec = json.loads((pathlib.Path(__file__).parents[1] / "specs" / "omega_v1.json").read_text(encoding="utf-8")); cfg = spec["strategies"]["omega"]
    assert set(cfg["members"]) == {"fvg_h1", "amd", "vwap"} and spec["trials"] == 0
    df = _long(6000); ev = build.events_for("omega", cfg, df); assert ev and all((e.stop < df.close[e.ts]) == (e.direction == "bullish") for e in ev)
    assert {e.meta["member"] for e in ev} <= {"fvg_h1", "amd", "vwap"} and strategy_code("omega") == "OMEGA_TRIO"
    assert [e.ts for e in ev] == sorted(e.ts for e in ev)
    n_members = sum(len(build.events_for(m, c, df)) for m, c in cfg["members"].items()); assert len(ev) <= n_members
    t0 = df.index[10]; fake = {"a": [Event(t0, "bullish", 1.0), Event(df.index[11], "bullish", 1.0), Event(df.index[30], "bullish", 1.0), Event(df.index[50], "bullish", 1.0)], "b": [Event(df.index[50], "bearish", 1.0)]}
    orig = build.events_for; build.events_for = lambda n, c, d: fake[n]
    try:
        out = build.omega_events(df, {"members": {"a": {}, "b": {}}, "params": {"cooldown": 4}})
    finally:
        build.events_for = orig
    assert [e.ts for e in out] == [t0, df.index[30]]                    # 11 = même idée que 10 ; 50 = conflit de sens, écarté
