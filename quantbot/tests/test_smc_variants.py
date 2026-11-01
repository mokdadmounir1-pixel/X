import json
from pathlib import Path

import pytest

from quantbot.data.mtf import group_keys
from quantbot.strategies import smc
from quantbot.strategies.build import STRATEGY_CODES, events_for, strategy_code
from tests.test_mtf_confluence import _long

ROOT = Path(__file__).resolve().parents[1]
S = lambda n: json.loads((ROOT / "specs" / f"{n}.json").read_text(encoding="utf-8"))


def test_free_params_equal_the_original_except_take_all_and_fallback_and_scale():
    o = S("smc_v1b")["strategies"]["smc_h1"]["params"]
    for spn, name, rule in (("smc_free_v1", "smc_h1_free", "1h"), ("smc_free_v1", "smc_h4_free", "4h"), ("smc_free_v1", "smc_m15_free", "15min")):
        sc = S(spn)["strategies"][name]; assert sc["rule"] == rule and {k: v for k, v in sc["params"].items() if k not in ("take_all", "fallback_rr")} == o and sc["params"]["take_all"] is True and sc["params"]["fallback_rr"] == 2.0
    for name, rule in (("smc_h4", "4h"), ("smc_m15", "15min")):
        sc = S("smc_orig_v1")["strategies"][name]; assert sc["rule"] == rule and sc["params"] == o
    assert S("smc_free_v1")["settings"]["risk"]["min_reward_risk"] == 0.1 and S("smc_orig_v1")["settings"]["risk"]["min_reward_risk"] == 3.0
    for n in ("smc_orig_v1", "smc_free_v1"):
        assert S(n)["trials"] == 0 and S(n)["max_trials_budget"] == 500


def test_hold_is_48_scale_bars_for_every_version():
    assert {S("smc_free_v1")["strategies"][k]["max_hold_bars"] for k in ("smc_h1_free",)} == {192}
    assert S("smc_free_v1")["strategies"]["smc_h4_free"]["max_hold_bars"] == S("smc_orig_v1")["strategies"]["smc_h4"]["max_hold_bars"] == 768
    assert S("smc_free_v1")["strategies"]["smc_m15_free"]["max_hold_bars"] == S("smc_orig_v1")["strategies"]["smc_m15"]["max_hold_bars"] == 48


def test_15min_group_keys_are_one_group_per_m15_bar_and_causal_ordering():
    df = _long(300); g = group_keys(df.index, "15min"); assert (g[1:] - g[:-1] == 1).all()


@pytest.mark.parametrize("rule,spn,orig,free", [("1h", "smc_free_v1", "smc_h1", "smc_h1_free"), ("4h", "smc_free_v1", "smc_h4", "smc_h4_free"), ("15min", "smc_free_v1", "smc_m15", "smc_m15_free")])
def test_free_is_a_superset_of_the_original_with_identical_shared_trades_and_fixed_2r_extras(rule, spn, orig, free):
    df = _long(30000, seed=4); o = S("smc_v1b")["strategies"]["smc_h1"]["params"]
    eo = smc.events(df, rule, {**smc.PARAMS, **o}); ef = smc.events(df, rule, {**smc.PARAMS, **o, "take_all": True, "fallback_rr": 2.0})
    key = lambda e: (e.ts, e.direction, round(e.stop, 8), round(e.target, 8))
    assert len(eo) > 0 and len(ef) > len(eo) and {key(e) for e in eo} <= {key(e) for e in ef}
    extra = [e for e in ef if key(e) not in {key(x) for x in eo}]
    for e in extra:
        assert abs(e.meta["rr"] - 2.0) < 1e-6          # cible de repli fixe à 2 R : seulement là où l'original IGNORE
    for e in eo:
        assert e.meta["rr"] >= 3.0 - 1e-9


def test_free_events_are_causal_and_dispatch_and_codes_exist():
    df = _long(30000, seed=4); sc = S("smc_free_v1")["strategies"]["smc_m15_free"]; full = events_for("smc_m15_free", sc, df); cut = int(len(df) * 0.7); part = events_for("smc_m15_free", sc, df.iloc[:cut]); lim = df.index[cut - 300]
    k = lambda ev: [(e.ts, e.direction, round(e.stop, 6), round(e.target, 6)) for e in ev if e.ts < lim]
    assert full and k(full) == k(part)
    for n in ("smc_h4", "smc_m15", "smc_h1_free", "smc_h4_free", "smc_m15_free"):
        assert n in STRATEGY_CODES and strategy_code(n).startswith("SMC_OB_FVG")


def test_entry_filter_keeps_a_subset_and_unfiltered_is_untouched():
    from quantbot.strategies import smc_filters as sf
    df = _long(30000, seed=4); sc = S("smc_free_v1")["strategies"]["smc_m15_free"]; base = events_for("smc_m15_free", sc, df); assert base
    for spec in ({"name": "session"}, {"name": "stop_wide", "threshold": 1.0}, {"name": "trend_aligned"}, {"name": "vol_high", "threshold": 1.0}):
        kept = sf.apply(df, base, spec); assert len(kept) <= len(base) and {e.ts for e in kept} <= {e.ts for e in base}
    assert all(7 <= e.ts.hour < 20 for e in sf.apply(df, base, {"name": "session"})) and sf.apply(df, base, None) == base
    f = S("smc_filt_free_v1")["strategies"]["smc_m15_free_f"]; assert {e.ts for e in events_for("smc_m15_free_f", f, df)} <= {e.ts for e in base} and f["entry_filter"]["name"] == "stop_wide"
    with pytest.raises(ValueError):
        sf.keep_mask([{"hour": 1}], {"name": "inconnu"})
