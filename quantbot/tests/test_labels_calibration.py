"""Les labels doivent être IDENTIQUES au moteur ; la calibration ne doit rien inventer."""
import numpy as np
import pandas as pd
import pytest

from quantbot.config import Settings
from quantbot.core.calibration import CalibrationModel, Curve, fit_curve, isotonic_fit
from quantbot.core.labels import compute_labels
from quantbot.core.sim import TradingEngine
from quantbot.data.loaders import generate_synthetic
from quantbot.signals.engine import Signal
from quantbot.signals.scoring import direction_scores, floored_atr
from quantbot.patterns.base import PatternMatch
from quantbot.patterns.scanner import PatternScanner


class FixedSignals:
    """Émet un signal (direction donnée) UNIQUEMENT aux barres demandées, avec l'ATR plancher du moteur réel."""

    def __init__(self, settings, at, direction):
        self.s, self.at, self.direction = settings, set(at), direction
        self.scanner = PatternScanner(settings)

    def evaluate(self, window, htf=None):
        if window.index[-1] not in self.at:
            return None
        self.scanner.scan(window)
        atr = floored_atr(self.scanner.last_context, self.s.signals)
        m = PatternMatch("fixed", "candle", self.direction, 0.9, 0, 1)
        return Signal(self.direction, 0.9, float(window["close"].iloc[-1]), atr, window.index[-1], [m])


def _cfg(**risk):
    return Settings.from_dict({
        "risk": {"flat_before_weekend": False, **risk},
        "signals": {"atr_floor_frac": 0.5},
        "execution": {"fee_rate": 2e-5, "slippage": 1e-5, "spread": 4e-5},
    })


@pytest.mark.parametrize("direction,side_attr", [("bullish", "long_r"), ("bearish", "short_r")])
def test_labels_equal_engine_trades(direction, side_attr):
    s = _cfg(max_leverage=1.0)  # levier serré : le plafond doit aussi être identique
    df = generate_synthetic(1800, seed=21, freq="1h")
    labels = compute_labels(df, s)
    at_idx = list(range(150, 1500, 170))
    eng = TradingEngine(s, signal_engine=FixedSignals(s, [df.index[i] for i in at_idx], direction))
    eng.run_replay(df)
    eng.finish(df)
    trades = {t.entry_time: t for t in eng.broker.trades}
    assert len(trades) >= 6
    for i in at_idx:
        t = trades.get(df.index[i + 1])
        if t is None:
            continue
        assert getattr(labels, side_attr)[i] == pytest.approx(t.r_nominal, rel=1e-9, abs=1e-9), (i, t.reason)


def test_labels_respect_weekend_and_gaps_like_the_engine():
    s = Settings.from_dict({"risk": {"flat_before_weekend": True}, "execution": {"fee_rate": 0, "slippage": 0, "spread": 0}})
    df = generate_synthetic(1500, seed=5, freq="1h")
    lab = compute_labels(df, s)
    from quantbot.risk.calendar import in_weekend_blackout as w
    for i in np.flatnonzero(np.isfinite(lab.long_r))[:200]:
        assert not w(df.index[i]) and not w(df.index[i + 1])
    hole = df.copy()
    hole.index = list(df.index[:700]) + [t + pd.Timedelta(days=40) for t in df.index[700:]]
    lh = compute_labels(hole, Settings.from_dict({"execution": {"fee_rate": 0, "slippage": 0, "spread": 0}}))
    warm = Settings().backtest.warmup_bars
    assert np.isnan(lh.long_r[699])                                  # pas d'entrée à cheval sur le trou
    assert np.isnan(lh.long_r[700: 700 + warm - 1]).all()            # ré-échauffement après le trou


def test_isotonic_is_monotone_and_pools_violations():
    x = np.array([1, 2, 3, 4, 5.]); y = np.array([1, 3, 2, 4, 3.5])
    ux, f = isotonic_fit(x, y)
    assert np.all(np.diff(f) >= -1e-12) and f[1] == f[2] == 2.5
    rng = np.random.default_rng(0)
    xs = rng.random(500); ys = rng.normal(0, 1, 500)
    _, fz = isotonic_fit(xs, ys)
    assert np.all(np.diff(fz) >= -1e-12) and abs(fz.mean()) < 0.2     # du bruit pur donne une courbe quasi plate


def test_curve_never_extrapolates_below_min_score_or_with_little_data():
    c = fit_curve([0.2, 0.5, 0.8, 0.9], [-1, 0, 1, 2], min_score=0.4, min_support=3)
    assert c.predict(0.3) is None and c.predict(0.5) is not None
    tiny = fit_curve([0.5, 0.6], [1, 1], min_score=0.4, min_support=50)
    assert tiny.predict(0.55) is None and tiny.n_train == 2


def test_model_decision_margin_and_roundtrip(tmp_path):
    long = Curve([0.4, 1.0], [-0.2, 0.5], 100, 0.4)
    short = Curve([0.4, 1.0], [-0.5, -0.1], 100, 0.4)
    m = CalibrationModel(long, short, margin=0.1)
    assert m.decide(0.99, 0.99)[0] == "bullish"
    assert m.decide(0.45, 0.99) is None            # espérance en dessous de la marge : on s'abstient
    assert m.decide(0.1, 0.1) is None              # hors zone de score : jamais d'extrapolation
    p = tmp_path / "m.json"; m.save(p)
    m2 = CalibrationModel.load(p)
    assert m2.hash() == m.hash() and m2.decide(0.99, 0.0) == m.decide(0.99, 0.0)
    assert CalibrationModel(long, short, margin=0.2).hash() != m.hash()  # la marge fait partie de l'identité


def test_direction_scores_are_shared_definition():
    s = Settings()
    ms = [PatternMatch("a", "candle", "bullish", 0.8, 0, 1), PatternMatch("b", "chart", "bullish", 0.7, 0, 1, confirmed=False),
          PatternMatch("c", "candle", "bearish", 0.6, 0, 1)]
    bull, bear = direction_scores(ms, s.signals)
    assert bull == pytest.approx(0.8 * 0.8 + s.signals.confluence_bonus)  # meilleur (candle 0.8*0.8) + 1 catégorie en plus
    assert bear == pytest.approx(0.6 * 0.8) and direction_scores([], s.signals) == (0.0, 0.0)


def test_calibrated_engine_abstains_or_trades_according_to_the_model():
    from quantbot.signals.calibrated import CalibratedSignalEngine
    s = Settings.from_dict({"tolerance": {"min_score": 0.3}, "signals": {"atr_floor_frac": 0.5}})
    df = generate_synthetic(900, seed=2, freq="1h")
    never = CalibrationModel(Curve([0.3, 1.0], [-0.5, -0.1], 999, 0.3), Curve([0.3, 1.0], [-0.5, -0.1], 999, 0.3), 0.1)
    always = CalibrationModel(Curve([0.3, 1.0], [0.9, 0.9], 999, 0.3), Curve([0.3, 1.0], [0.2, 0.2], 999, 0.3), 0.1)
    a, b = CalibratedSignalEngine(s, never), CalibratedSignalEngine(s, always)
    got = [b.evaluate(df.iloc[: t + 1].tail(300)) for t in range(300, 900, 7)]
    assert all(a.evaluate(df.iloc[: t + 1].tail(300)) is None for t in range(300, 900, 7))
    sigs = [g for g in got if g is not None]
    assert sigs and all(g.atr > 0 and g.matches for g in sigs)
    assert all(g.direction == "bullish" or g.direction == "bearish" for g in sigs)


def test_training_scores_equal_runtime_scores():
    from quantbot.core.scores import compute_scores
    s = Settings.from_dict({"tolerance": {"min_score": 0.3}})
    df = generate_synthetic(700, seed=4, freq="1h")
    bull, bear = compute_scores(df, s)
    sc = PatternScanner(s)
    for t in (150, 333, 512, 699):
        w = df.iloc[: t + 1].tail(s.backtest.window_bars)
        rb, rr = direction_scores(sc.scan(w), s.signals)
        assert (bull[t], bear[t]) == pytest.approx((rb, rr))
    assert np.isnan(bull[:s.backtest.warmup_bars]).all()


def test_spec_extra_changes_identity_only_when_given():
    from quantbot.lab.pipeline import spec_hash
    s = Settings()
    assert spec_hash(s) == spec_hash(s, extra=None) != spec_hash(s, extra="modele-A") != spec_hash(s, extra="modele-B")


def _scalp_cfg(**risk):
    return Settings.from_dict({"risk": {"flat_before_weekend": False, "max_leverage": 1.0, **risk},
                               "signals": {"atr_floor_frac": 0.5},
                               "execution": {"fee_rate": 2e-5, "slippage": 1e-5, "spread": 4e-5}})


@pytest.mark.parametrize("risk", [dict(session_utc_start=7, session_utc_end=17), dict(max_cost_r=0.4),
                                  dict(session_utc_start=7, session_utc_end=17, max_cost_r=0.3)])
def test_session_window_and_cost_filter_identical_in_engine_and_labels(risk):
    s = _scalp_cfg(**risk)
    df = generate_synthetic(2200, seed=33, freq="15min")
    labels = compute_labels(df, s)
    at_idx = list(range(150, 1900, 5))  # beaucoup de candidats, l'engine n'en prend que d'espacés
    eng = TradingEngine(s, signal_engine=FixedSignals(s, [df.index[i] for i in at_idx], "bullish"))
    eng.run_replay(df)
    eng.finish(df)
    taken = {t.entry_time: t for t in eng.broker.trades}
    assert taken
    for i in at_idx:
        t = taken.get(df.index[i + 1])
        if t is not None:                      # tout trade pris par le moteur a un label identique
            assert labels.long_r[i] == pytest.approx(t.r_nominal, rel=1e-9, abs=1e-9)
            assert s.risk.session_utc_start <= df.index[i].hour < s.risk.session_utc_end
    # et là où le label est NaN à cause de la fenêtre/coût, le moteur ne trade jamais
    blocked = [i for i in at_idx if not np.isfinite(labels.long_r[i]) and df.index[i + 1] in taken]
    assert not blocked


def test_cost_filter_rejects_when_cost_exceeds_risk_budget_and_is_off_by_default():
    from quantbot.risk.manager import RiskManager
    sig = Signal("bullish", 0.9, 4000.0, 0.8, pd.Timestamp("2025-06-02 10:00"), [PatternMatch("x", "candle", "bullish", 0.9, 0, 1)])
    on = RiskManager(Settings.from_dict({"risk": {"max_cost_r": 0.10}}).risk)
    assert on.build_plan(sig, 100_000, cost_frac=5e-4) is None and on.last_rejection == "cout_trop_eleve"  # 0,5 pb = 2 $ / 1,2 $ de stop
    assert on.build_plan(sig, 100_000, cost_frac=1e-5) is not None
    assert RiskManager(Settings().risk).build_plan(sig, 100_000, cost_frac=5e-4) is not None  # désactivé par défaut
    with pytest.raises(Exception):
        Settings.from_dict({"risk": {"session_utc_start": 17, "session_utc_end": 7}})
