import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from quantbot.live.strategies import load_spec, strategy_settings
from quantbot.strategies import intraday_momentum as im, overnight_premium as on
from quantbot.strategies.build import STRATEGY_CODES, events_for, strategy_code
from quantbot.ui.institutional60 import S60, institutional60
from tests.test_mtf_confluence import _long

ROOT = Path(__file__).resolve().parents[1]


def _ny(ts):
    t = ts.tz_localize("UTC").tz_convert("America/New_York"); return t.hour * 60 + t.minute, t.dayofweek


def test_overnight_premium_buys_at_ny_close_monday_to_thursday_with_valid_levels():
    df = _long(12000); ev = on.events(df); assert len(ev) > 40
    for e in ev:
        hm, dow = _ny(e.ts); px = df.close[e.ts]
        assert hm == 15 * 60 + 45 and dow in (0, 1, 2, 3) and e.direction == "bullish" and e.stop < px < e.target


def test_intraday_momentum_follows_the_morning_move_and_confidence_is_continuous():
    df = _long(12000); ev = im.events(df); assert len(ev) > 10
    for e in ev:
        hm, _ = _ny(e.ts); px = df.close[e.ts]
        assert hm == 15 * 60 + 15 and (e.direction == "bullish") == (e.meta["z"] > 0) and abs(e.meta["z"]) >= 1.0 and 0.55 <= e.meta["confidence"] <= 0.95
        assert (e.stop < px < e.target) if e.direction == "bullish" else (e.target < px < e.stop)
    assert len({round(e.meta["confidence"], 3) for e in ev}) > 3                       # continue, pas en paliers


@pytest.mark.parametrize("mod", [on, im])
def test_causal_prefix_and_dispatch(mod):
    df = _long(12000); cut = 9000; full = mod.events(df); part = mod.events(df.iloc[:cut]); lim = df.index[cut - 100]
    k = lambda ev: [(e.ts, e.direction, round(e.stop, 6)) for e in ev if e.ts < lim]
    assert k(full) == k(part)
    name = mod.__name__.rsplit(".", 1)[1]; assert events_for(name, {"params": {}}, df) == full and strategy_code(name) == STRATEGY_CODES[name]


def test_spec_is_paper_only_zero_trials_and_loads_settings_for_each_index():
    spec = load_spec(ROOT / "specs" / "institutional60_v1.json"); assert spec["trials"] == 0 and set(spec["strategies"]) == {"overnight_premium", "intraday_momentum"}
    hist = _long(600); spec = {**spec, "costs": {k: ({**v, "spread_frac": 1e-4} if isinstance(v, dict) else v) for k, v in spec["costs"].items()}}      # spread déclaré : la synthèse n'en mesure pas
    for name, sc in spec["strategies"].items():
        for inst in sc["instruments"]:
            assert inst in spec["costs"] and strategy_settings(spec, name, inst, hist) is not None


def test_catalog_of_60_is_complete_honest_and_points_at_real_modules():
    assert [r[0] for r in S60] == list(range(1, 61)) and len({r[1] for r in S60}) == 60
    assert {r[3] for r in S60} <= {"CODEE", "COUVERTE", "OUTIL", "DONNEES", "HORS_PORTEE"}
    for n, name, fam, st, module, note in S60:
        assert note and (module is None) == (st in ("DONNEES", "HORS_PORTEE"))
        if st in ("CODEE", "COUVERTE") and "/" not in module:
            assert module in STRATEGY_CODES, (n, module)
        if st == "OUTIL" and "/" in module:
            assert (ROOT / "quantbot" / module).exists(), (n, module)
    c = institutional60(ROOT); assert sum(c["counts"].values()) == 60 and c["counts"]["CODEE"] >= 6 and "validée" in c["note"]
