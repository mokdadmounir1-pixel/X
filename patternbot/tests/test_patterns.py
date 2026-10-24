import numpy as np
import pytest

from patternbot.config import DetectionConfig, Settings, ToleranceConfig
from patternbot.indicators.core import atr, ema, rsi, stoch_rsi
from patternbot.indicators.structure import find_levels, market_structure, swing_points
from patternbot.patterns.scanner import PatternScanner
from patternbot.patterns.tolerance import deviation_score, soft_ge, soft_le, soft_range, soft_eq
from tests.helpers import bar, downtrend, frame, from_waypoints, mirror

TOL = ToleranceConfig()
LOOSE = Settings.from_dict({"tolerance": {"min_score": 0.01}})


def names(df, settings=None, min_score=0.0):
    sc = PatternScanner(settings or Settings())
    return {(m.name, m.direction): m for m in sc.scan(df) if m.score >= min_score}


# --- tolérance --------------------------------------------------------------
def test_deviation_score_shape():
    assert deviation_score(0.0, TOL) == 1.0
    assert deviation_score(TOL.tolerance_percentage, TOL) == 1.0
    assert deviation_score(TOL.deviation_threshold, TOL) == 0.0
    mid = (TOL.tolerance_percentage + TOL.deviation_threshold) / 2
    assert deviation_score(mid, TOL) == pytest.approx(0.5)


def test_soft_helpers():
    assert soft_ge(2.0, 2.0, TOL) == 1.0 and soft_ge(1.9, 2.0, TOL) == 1.0  # 5% d'écart toléré
    assert soft_ge(1.0, 2.0, TOL) == 0.0
    assert soft_le(0.5, 1.0, TOL) == 1.0 and soft_le(2.0, 1.0, TOL) == 0.0
    assert soft_eq(1.05, 1.0, TOL) == 1.0
    assert soft_range(0.9, 1.0, 2.0, TOL) == 1.0 and soft_range(3.0, 1.0, 2.0, TOL) == 0.0


def test_wider_tolerance_accepts_more():
    strict = ToleranceConfig(tolerance_percentage=0.05, deviation_threshold=0.15)
    loose = ToleranceConfig(tolerance_percentage=0.25, deviation_threshold=0.5)
    assert soft_eq(1.2, 1.0, strict) < soft_eq(1.2, 1.0, loose)


# --- indicateurs ------------------------------------------------------------
def test_indicators_basic():
    df = frame(downtrend(60))
    assert atr(df, 14).iloc[-1] == pytest.approx(1.4, abs=0.05)
    assert rsi(df["close"]).iloc[-1] < 5
    assert ema(df["close"], 10).iloc[-1] > df["close"].iloc[-1]
    assert np.isnan(stoch_rsi(df["close"]).iloc[-1]) or stoch_rsi(df["close"]).iloc[-1] <= 1


def test_swing_points_alternate_and_confirmed():
    df = frame(from_waypoints([100, 130, 110, 140, 105], tail=4))
    pv = swing_points(df["high"].to_numpy(), df["low"].to_numpy(), 3)
    kinds = [p.kind for p in pv]
    assert all(a != b for a, b in zip(kinds, kinds[1:]))
    assert kinds[-1] == "L"
    assert market_structure(pv) in {"up", "down", "range"}
    assert find_levels(pv, 0.5)[0][1] >= 1


# --- chandeliers : parfait, variante, faux positif, miroir --------------------
BASE = downtrend()
CANDLE_CASES = {
    "hammer": BASE + [bar(99.8, 100.2, h=100.4, l=97.0)],
    "bullish_harami": BASE + [bar(104, 100.0, h=104.2, l=99.8), bar(101.0, 102.2, h=102.4, l=100.8)],
    "piercing_line": BASE + [bar(104, 100.0, h=104.2, l=99.8), bar(99.5, 102.6, h=102.8, l=99.3)],
    "morning_star": BASE + [bar(104, 100.0, h=104.2, l=99.8), bar(99.4, 99.6, h=99.8, l=99.2),
                            bar(100.0, 103.4, h=103.6, l=99.8)],
    "three_white_soldiers": BASE + [bar(100.0, 102.0, h=102.1, l=99.9), bar(101.0, 103.2, h=103.3, l=100.9),
                                    bar(102.2, 104.4, h=104.5, l=102.1)],
    "three_outside_up": BASE + [bar(101.5, 100.0, h=101.6, l=99.9), bar(99.8, 102.2, h=102.3, l=99.7),
                                bar(102.1, 103.6, h=103.7, l=102.0)],
    "bullish_kicker": BASE + [bar(101.5, 100.0, h=101.6, l=99.9), bar(102.0, 104.2, h=104.3, l=101.9)],
}


@pytest.mark.parametrize("name", list(CANDLE_CASES))
def test_candle_detected_bullish(name):
    found = names(frame(CANDLE_CASES[name]), LOOSE)
    assert (name, "bullish") in found and found[(name, "bullish")].score >= 0.7, name


@pytest.mark.parametrize("name,bear", [("hammer", "shooting_star"), ("bullish_harami", "bearish_harami"),
                                       ("piercing_line", "dark_cloud_cover"), ("morning_star", "evening_star"),
                                       ("three_white_soldiers", "three_black_crows")])
def test_candle_mirror_gives_bearish_twin(name, bear):
    found = names(frame(mirror(CANDLE_CASES[name])), LOOSE)
    assert (bear, "bearish") in found and found[(bear, "bearish")].score >= 0.7


def test_imperfect_hammer_is_still_valid_variant():
    # mèche basse = 1.6x le corps (idéal 2x) : toléré, avec un score un peu plus bas
    perfect = names(frame(BASE + [bar(99.8, 100.2, h=100.4, l=97.0)]), LOOSE)[("hammer", "bullish")].score
    variant = names(frame(BASE + [bar(99.8, 100.2, h=100.4, l=99.1)]), LOOSE)[("hammer", "bullish")].score
    assert 0.6 <= variant <= perfect


def test_non_hammer_rejected_by_default_threshold():
    marubozu = names(frame(BASE + [bar(99.0, 101.0, h=101.05, l=98.95)]))  # min_score 0.6
    assert ("hammer", "bullish") not in marubozu


def test_hammer_without_prior_downtrend_scores_lower():
    flat = [bar(100, 100.1, h=100.3, l=99.9) for _ in range(30)]
    with_ctx = names(frame(BASE + [bar(99.8, 100.2, h=100.4, l=97.0)]), LOOSE)[("hammer", "bullish")].score
    no_ctx = names(frame(flat + [bar(99.8, 100.2, h=100.4, l=97.0)]), LOOSE)[("hammer", "bullish")].score
    assert no_ctx < with_ctx


def test_too_few_bars_is_safe():
    assert names(frame(BASE[:3]), LOOSE) == {}


# --- figures chartistes -----------------------------------------------------
def test_double_bottom_and_top():
    rows = from_waypoints([130, 100, 120, 100.5])
    m = names(frame(rows), LOOSE)[("double_bottom", "bullish")]
    assert m.score >= 0.9 and not m.confirmed
    assert ("double_top", "bearish") in names(frame(mirror(rows)), LOOSE)


def test_double_bottom_variant_vs_mismatch():
    ok = names(frame(from_waypoints([130, 100, 120, 103.5])), LOOSE)[("double_bottom", "bullish")].score  # 17% de la hauteur
    bad = names(frame(from_waypoints([130, 100, 120, 108])), LOOSE)
    assert 0.3 < ok < 1.0
    assert ("double_bottom", "bullish") not in bad or bad[("double_bottom", "bullish")].score < 0.1


def test_double_bottom_confirmed_on_breakout():
    rows = from_waypoints([130, 100, 120, 100.5], tail=0) + [bar(100.6, 121.0, h=121.2, l=100.4)] * 4
    # barres de sortie : la dernière clôture dépasse la neckline
    rows = rows[:-4] + [bar(100.6, 104, wick=0.1), bar(104, 108, wick=0.1), bar(108, 114, wick=0.1), bar(114, 122, wick=0.1)]
    m = names(frame(rows), LOOSE).get(("double_bottom", "bullish"))
    assert m is not None and m.confirmed


def test_inverse_head_shoulders():
    rows = from_waypoints([140, 110, 125, 100, 125, 111])
    m = names(frame(rows), LOOSE)[("inverse_head_shoulders", "bullish")]
    assert m.score >= 0.9
    assert ("head_and_shoulders", "bearish") in names(frame(mirror(rows)), LOOSE)


def test_head_not_deeper_than_shoulders_rejected():
    rows = from_waypoints([140, 110, 125, 112, 125, 111])  # tête pas plus basse
    assert ("inverse_head_shoulders", "bullish") not in names(frame(rows))


def test_ascending_triangle():
    rows = from_waypoints([150, 120, 140, 127, 140, 134, 140.2, 138])
    m = names(frame(rows), LOOSE)[("ascending_triangle", "bullish")]
    assert m.score >= 0.9
    assert ("descending_triangle", "bearish") in names(frame(mirror(rows)), LOOSE)


# --- harmoniques ------------------------------------------------------------
GARTLEY = [100, 200, 138.2, 176.4, 121.4]


def test_gartley_best_match_and_mirror():
    found = names(frame(from_waypoints(GARTLEY)), LOOSE)
    g = found[("gartley", "bullish")].score
    assert g >= 0.95 and g > found[("bat", "bullish")].score > found[("crab", "bullish")].score
    assert ("gartley", "bearish") in names(frame(mirror(from_waypoints(GARTLEY))), LOOSE)


def test_gartley_imperfect_ratios_still_detected_but_wrong_rejected():
    sloppy = [100, 200, 143, 176.4, 123.5]  # B ~0.57, D ~0.765 : écarts de quelques %
    assert names(frame(from_waypoints(sloppy)))[("gartley", "bullish")].score >= 0.6
    wrong = [100, 200, 170, 190, 150]  # ratios incohérents
    assert ("gartley", "bullish") not in names(frame(from_waypoints(wrong)))


def test_crab_ratios():
    crab = [100, 200, 161.8, 190, 38.2]  # D = 1.618 XA
    assert names(frame(from_waypoints(crab, bars_per_leg=10)), LOOSE)[("crab", "bullish")].score > 0.8


def test_enabled_filter_and_error_isolation(monkeypatch):
    s = Settings.from_dict({"detection": {"enabled": ["hammer"]}, "tolerance": {"min_score": 0.01}})
    sc = PatternScanner(s)
    assert [d.family for d in sc.detectors] == ["hammer"]
    monkeypatch.setattr(sc.detectors[0], "detect", lambda *a: (_ for _ in ()).throw(RuntimeError("boom")))
    assert sc.scan(frame(BASE + [bar(99.8, 100.2, h=100.4, l=97.0)])) == [] and sc.errors == 1
