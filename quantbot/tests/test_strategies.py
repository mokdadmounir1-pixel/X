import numpy as np
import pandas as pd
import pytest

from quantbot.config import Settings
from quantbot.core.sim import TradingEngine
from quantbot.data.loaders import generate_synthetic
from quantbot.risk.manager import RiskManager
from quantbot.signals.engine import Signal
from quantbot.patterns.base import PatternMatch
from quantbot.strategies import amd, fvg, orb, vwap
from quantbot.strategies.events import Event, EventSignalEngine


def bars(rows, start, freq="15min"):
    idx = pd.date_range(start, periods=len(rows), freq=freq)
    df = pd.DataFrame(rows, columns=["open", "high", "low", "close", "volume"], index=idx)
    return df


# ---------------------------------------------------------------- causalité (aucune fuite) -------------------------------
def _all_events(df):
    return {"amd": amd.events(df), "vwap": vwap.events(df), "orb": orb.events(df), "fvg1h": fvg.events(df, "1h"), "fvg4h": fvg.events(df, "4h")}


def _key(e):
    return (e.ts, e.direction, round(e.stop, 9), None if e.target is None else round(e.target, 9))


def test_events_on_a_prefix_equal_the_prefix_of_events_on_the_full_series():
    df = generate_synthetic(6000, seed=8, freq="15min", start="2024-03-01")
    full = _all_events(df)
    for k in (2500, 4100):
        cut = df.index[k - 1]
        part = _all_events(df.iloc[:k])
        for name in full:
            assert [_key(e) for e in part[name]] == [_key(e) for e in full[name] if e.ts <= cut], (name, k)
    assert all(len(v) > 0 for v in full.values())


def test_altering_the_future_never_changes_past_events():
    df = generate_synthetic(5000, seed=9, freq="15min", start="2024-03-01")
    k = 3000
    alt = df.copy(); alt.iloc[k:, :4] = alt.iloc[k:, :4].to_numpy() * 1.4; alt.iloc[k:, 4] *= 3
    a, b = _all_events(df), _all_events(alt)
    cut = df.index[k - 1]
    for name in a:
        assert [_key(e) for e in a[name] if e.ts <= cut] == [_key(e) for e in b[name] if e.ts <= cut], name


# ---------------------------------------------------------------- règles, sur des journées construites ----------------------
def test_amd_short_after_asian_high_sweep_and_reintegration():
    rows = []
    for i in range(28):                                   # session asiatique 00:00-07:00 UTC : range 100-103
        base = 101.5 + (1.4 if i % 2 else -1.4)
        rows.append((base, base + 0.1, base - 0.1, base, 100))
    rows[3] = (101.5, 103.0, 101.4, 102.9, 100); rows[7] = (101.5, 101.6, 100.0, 100.2, 100)  # bords exacts du range
    rows += [(102.5, 103.6, 102.4, 103.5, 100),           # 07:00 : sweep au-dessus de 103 (extrême 103,6)
             (103.4, 103.5, 102.5, 102.7, 100)]           # 07:15 : clôture réintégrée sous 103 -> signal vendeur
    df = bars(rows, "2024-05-14 00:00")
    ev = amd.events(df)
    assert len(ev) == 1 and ev[0].direction == "bearish" and ev[0].ts == df.index[29]
    assert ev[0].stop > 103.6 and ev[0].target == pytest.approx(100.0)       # stop au-delà du sweep, cible = bas du range
    assert (102.7 - ev[0].target) / (ev[0].stop - 102.7) >= 1.5


def test_amd_ignores_a_sweep_outside_the_manipulation_window_and_requires_enough_asia_bars():
    rows = [(101, 101.2, 100.8, 101, 100)] * 28 + [(101, 101.2, 100.8, 101, 100)] * 12      # 07:00-10:00 plat
    rows += [(101, 104, 100.9, 102.7, 100)]                                                   # sweep à 10:00 : hors fenêtre
    assert amd.events(bars(rows, "2024-05-14 00:00")) == []
    short_asia = [(101, 101.2, 100.8, 101, 100)] * 10 + [(101, 104, 100.9, 100.9, 100)] * 30
    assert amd.events(bars(short_asia, "2024-05-14 00:00")) == []


def test_vwap_fades_a_moderate_extension_with_target_at_vwap():
    rows = [(100 + (0.1 if i % 2 else -0.1),) * 4 + (100,) for i in range(40)]
    rows.append((100.28,) * 4 + (100,))
    df = bars(rows, "2024-05-14 22:00")                   # même journée de marché NY (roll 17:00 = 21:00 UTC en été)
    ev = vwap.events(df)
    assert len(ev) == 1 and ev[0].direction == "bearish" and ev[0].ts == df.index[-1]
    assert ev[0].target == pytest.approx(100.0, abs=0.01) and ev[0].stop > 100.28


def test_vwap_refuses_to_enter_beyond_its_own_stop_and_fires_once_per_side():
    rows = [(100 + (0.1 if i % 2 else -0.1),) * 4 + (100,) for i in range(40)] + [(103.0,) * 4 + (100,)]  # z énorme
    assert vwap.events(bars(rows, "2024-05-14 22:00")) == []   # déjà au-delà du stop : pas d'entrée
    rows2 = [(100 + (0.1 if i % 2 else -0.1),) * 4 + (100,) for i in range(40)] + [(100.28,) * 4 + (100,)] * 3
    assert len(vwap.events(bars(rows2, "2024-05-14 22:00"))) == 1


def test_orb_enters_only_on_the_confirmed_retest_not_on_the_raw_breakout():
    # 2024-07-10 : 09:30 NY = 13:30 UTC
    pre = [(100, 100.1, 99.9, 100, 100)] * 30
    rows = pre + [(100, 100.5, 99.5, 100.1, 100),          # 13:30 : range 99,5-100,5
                  (100.1, 101.2, 100.0, 101.0, 500),       # 13:45 : cassure haussière avec volume (PAS d'entrée)
                  (101.0, 101.3, 100.4, 100.8, 100)]       # 14:00 : re-teste 100,5 et clôture au-dessus -> entrée
    df = bars(rows, "2024-07-10 06:00")
    assert df.index[30] == pd.Timestamp("2024-07-10 13:30")
    ev = orb.events(df)
    assert len(ev) == 1 and ev[0].direction == "bullish" and ev[0].ts == df.index[32] and ev[0].stop == 99.5


def test_orb_cancelled_when_price_closes_beyond_the_opposite_edge():
    pre = [(100, 100.1, 99.9, 100, 100)] * 30
    rows = pre + [(100, 100.5, 99.5, 100.1, 100), (100.1, 101.2, 100.0, 101.0, 500), (101, 101, 99.0, 99.2, 100),
                  (99.2, 101, 100.4, 100.8, 100)]
    assert orb.events(bars(rows, "2024-07-10 06:00")) == []


def test_fvg_long_when_a_bar_mitigates_the_consequent_encroachment():
    def hour(o, hi, lo, c):
        return [(o, hi, lo, c, 100)] * 4
    rows = hour(99.5, 100.0, 99.0, 99.8) + hour(100.5, 102.8, 100.2, 102.5) + hour(102.5, 103.5, 102.0, 103.0)  # gap haussier 100 -> 102
    rows += [(103.0, 103.2, 101.0, 102.2, 100)]                                                                    # touche le CE (101) puis clôture au-dessus du bord bas
    rows += hour(102, 102.5, 101.5, 102)
    df = bars(rows, "2024-05-14 22:00")
    ev = fvg.events(df, "1h")
    assert len(ev) == 1 and ev[0].direction == "bullish" and ev[0].ts == df.index[12]
    assert ev[0].stop < 100.0 and ev[0].meta["ce"] == pytest.approx(101.0)


def test_fvg_zone_is_invalidated_by_a_closed_htf_bar_beyond_the_far_edge():
    def hour(o, hi, lo, c):
        return [(o, hi, lo, c, 100)] * 4
    rows = hour(99.5, 100.0, 99.0, 99.8) + hour(100.5, 102.8, 100.2, 102.5) + hour(102.5, 103.5, 102.0, 103.0)
    rows += hour(103, 103.2, 98.5, 99.0)                   # bougie H1 qui clôture sous le bord lointain (100) : zone morte
    rows += [(99.0, 101.5, 98.9, 101.2, 100)] + hour(101, 101.5, 100.5, 101)
    assert fvg.events(bars(rows, "2024-05-14 22:00"), "1h") == []


# ---------------------------------------------------------------- plomberie : niveaux propres + plancher de stop -------------------
def _sig(direction, price, atr, stop=None, tp=None):
    return Signal(direction, 0.9, price, atr, pd.Timestamp("2024-05-14 10:00"), [PatternMatch("x", "event", direction, 0.9, 0, 1)],
                  stop_price=stop, take_profit_price=tp)


def test_risk_manager_honours_custom_levels_and_floors_tiny_stops():
    s = Settings.from_dict({"risk": {"min_stop_atr": 0.5, "min_reward_risk": 1.5, "max_leverage": 5.0}})
    rm = RiskManager(s.risk)
    p = rm.build_plan(_sig("bullish", 100.0, 1.0, stop=98.0, tp=106.0), 100_000)
    assert p.stop == 98.0 and p.take_profit == pytest.approx(106.0) and p.reward_risk == pytest.approx(3.0)
    tiny = rm.build_plan(_sig("bullish", 100.0, 1.0, stop=99.99), 100_000)
    assert tiny.stop == pytest.approx(99.5)               # stop élargi à 0,5 ATR : jamais de stop à 0,01 % du prix
    assert rm.build_plan(_sig("bullish", 100.0, 1.0, stop=101.0), 100_000) is None and rm.last_rejection == "stop_du_mauvais_cote"
    assert rm.build_plan(_sig("bearish", 100.0, 1.0, stop=102.0, tp=99.5), 100_000) is None and rm.last_rejection == "rr_insuffisant"
    default = rm.build_plan(_sig("bullish", 100.0, 1.0), 100_000)  # sans niveaux : comportement historique inchangé
    assert default.stop == pytest.approx(100.0 - s.risk.atr_stop_mult)


def test_event_engine_trades_the_event_levels_end_to_end():
    df = generate_synthetic(1500, seed=12, freq="15min", start="2024-03-04")
    s = Settings.from_dict({"risk": {"flat_before_weekend": False, "min_stop_atr": 0.5}, "execution": {"fee_rate": 0, "slippage": 0, "spread": 0}})
    t = df.index[400]
    px = float(df["close"].iloc[400]); atr = float(df["high"].iloc[300:400].sub(df["low"].iloc[300:400]).mean())
    ev = Event(t, "bullish", px - 2 * atr, px + 3 * atr, "test")
    eng = TradingEngine(s, signal_engine=EventSignalEngine(s, [ev]))
    eng.run_replay(df); eng.finish(df)
    assert len(eng.broker.trades) == 1
    tr = eng.broker.trades[0]
    assert tr.entry_time == df.index[401] and tr.side == "long"
