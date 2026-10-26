import numpy as np
import pandas as pd
import pytest

from quantbot.backtest.engine import Backtester
from quantbot.config import ActiveRiskConfig, ConfigError, Settings
from quantbot.risk.active import ActiveRiskGuard, wilson_lower
from quantbot.strategies.events import Event, EventSignalEngine
from tests.synthetic import generate_synthetic

T = pd.Timestamp("2025-03-03 10:00")
BAR = (101.0, 99.0, 100.0)


def guard(**kw):
    return ActiveRiskGuard(ActiveRiskConfig(enabled=True, **kw), base_risk=0.005)


def test_daily_loss_including_unrealized_halts_and_flattens_only_when_in_position():
    g = guard()
    g.evaluate(T, 100_000, BAR)
    d = g.evaluate(T + pd.Timedelta(minutes=15), 98_000, BAR, has_position=True)          # -2 % latent
    assert d.halt_new and d.flatten and "perte journalière" in d.reasons[0]
    assert not g.evaluate(T + pd.Timedelta(minutes=30), 98_000, BAR, has_position=False).flatten
    d2 = g.evaluate(T + pd.Timedelta(days=1), 98_000, BAR)                                # nouveau jour : repart de l'equity du matin
    assert not d2.halt_new


def test_drawdown_throttles_linearly_then_halts_then_resumes_after_cooldown():
    g = guard(dd_throttle_start=0.02, max_drawdown_halt=0.06, halt_cooldown_days=3, daily_loss_halt=0.2)
    g.evaluate(T, 100_000, BAR)
    m = [g.evaluate(T + pd.Timedelta(days=1 + k), 100_000 * (1 - dd), BAR).risk_multiplier for k, dd in enumerate([0.01, 0.03, 0.05])]
    assert m[0] == 1.0 and 1.0 > m[1] > m[2] >= 0.25
    h = g.evaluate(T + pd.Timedelta(days=5), 93_900, BAR)
    assert h.halt_new and "drawdown" in h.reasons[0]
    assert g.evaluate(T + pd.Timedelta(days=7), 99_000, BAR).halt_new                      # toujours dans la période d'arrêt
    assert not g.evaluate(T + pd.Timedelta(days=9), 99_000, BAR).halt_new                  # reprise automatique (risque ensuite réduit par le freinage)


def test_performance_drift_and_losing_streak_halt():
    g = guard(drift_window=20, drift_min_mean_r=-0.3, max_consecutive_losses=99)
    for _ in range(20):
        g.on_trade_close(-0.6, T)
    assert g.evaluate(T, 100_000, BAR).halt_new and "dérive" in g.last.reasons[0]
    g2 = guard(max_consecutive_losses=4, drift_min_mean_r=-9)
    for _ in range(4):
        g2.on_trade_close(-0.1, T)
    assert g2.evaluate(T, 100_000, BAR).halt_new and "pertes consécutives" in g2.last.reasons[0]
    g2.on_trade_close(+1.0, T)
    assert g2.losing_streak == 0


def test_abnormal_volatility_halts_only_while_it_lasts():
    g = guard(vol_ratio_halt=3.0, daily_loss_halt=0.2)
    t = T
    for _ in range(300):
        t += pd.Timedelta(minutes=15); g.evaluate(t, 100_000, (100.5, 99.5, 100.0))
    t += pd.Timedelta(minutes=15)
    calm = g.evaluate(t, 100_000, (100.5, 99.5, 100.0))
    assert not calm.halt_new
    for _ in range(40):                                                                      # volatilité x6
        t += pd.Timedelta(minutes=15); wild = g.evaluate(t, 100_000, (103.0, 97.0, 100.0))
    assert wild.halt_new and "volatilité" in wild.reasons[-1]
    for _ in range(600):
        t += pd.Timedelta(minutes=15); back = g.evaluate(t, 100_000, (100.5, 99.5, 100.0))
    assert not back.halt_new


def test_kelly_never_exceeds_base_risk_and_cuts_when_edge_is_not_proven():
    g = guard(kelly_min_trades=30, kelly_fraction=0.25, daily_loss_halt=0.2, drift_min_mean_r=-9, max_consecutive_losses=99)
    rng = np.random.default_rng(0)
    for r in rng.choice([-1.0, 3.0], size=60, p=[0.5, 0.5]):                                  # espérance +1 R, gros avantage
        g.on_trade_close(float(r), T)
    big = g.evaluate(T, 100_000, BAR)
    assert big.kelly_f > 0 and big.risk_multiplier <= 1.0                                     # JAMAIS au-dessus du risque de base
    g2 = guard(kelly_min_trades=30, daily_loss_halt=0.2, drift_min_mean_r=-9, max_consecutive_losses=99)
    for r in rng.choice([-1.0, 1.0], size=60, p=[0.55, 0.45]):                                # espérance négative
        g2.on_trade_close(float(r), T)
    assert g2.evaluate(T, 100_000, BAR).risk_multiplier == pytest.approx(0.25)
    g3 = guard(kelly_min_trades=30)
    for r in [-1.0, 2.0] * 5:                                                                  # trop peu de trades : Kelly ignoré
        g3.on_trade_close(r, T)
    assert g3.evaluate(T, 100_000, BAR).kelly_f is None


def test_wilson_bound_is_conservative():
    assert wilson_lower(60, 100) < 0.6 and wilson_lower(0, 0) == 0.0


def test_invalid_config_is_rejected():
    with pytest.raises(ConfigError):
        ActiveRiskConfig.from_dict({"dd_throttle_start": 0.08, "max_drawdown_halt": 0.05})


def _bt(active):
    df = generate_synthetic(4000, seed=11, freq="15min", start="2024-03-04")
    atr = (df["high"] - df["low"]).rolling(14).mean()
    evs = [Event(df.index[i], "bullish" if i % 2 else "bearish", float(df.close.iloc[i] - (1 if i % 2 else -1) * 2 * atr.iloc[i]), None, "t")
           for i in range(100, 3950, 9) if np.isfinite(atr.iloc[i])]
    s = Settings.from_dict({"backtest": {"max_hold_bars": 8}, "active_risk": active})
    return Backtester(s, signal_engine=EventSignalEngine(s, evs)).run(df)


def test_disabled_guard_changes_nothing_and_enabled_guard_only_reduces_exposure():
    base = _bt({"enabled": False})
    same = _bt({"enabled": False, "daily_loss_halt": 0.01})
    assert [t.pnl for t in base.trades] == [t.pnl for t in same.trades]
    on = _bt({"enabled": True, "daily_loss_halt": 0.004, "max_drawdown_halt": 0.02, "dd_throttle_start": 0.005, "halt_cooldown_days": 5, "max_consecutive_losses": 3})
    assert len(on.trades) < len(base.trades) and on.rejections.get("active_risk_halt", 0) > 0
    worst_dd = lambda r: r.metrics["max_drawdown"]
    assert worst_dd(on) <= worst_dd(base) + 1e-9                                               # le contrôle ne dégrade jamais le pire drawdown


def test_spec_hash_of_old_specs_is_unchanged_when_the_guard_is_disabled():
    from quantbot.lab.pipeline import spec_hash
    s = Settings()
    d = s.to_dict(); d.pop("active_risk")
    for k in ("max_spread_frac", "score_sizing_floor", "score_min_mult"):
        d["risk"].pop(k)                                   # absents de l'identité tant qu'ils sont à leur défaut : les essais passés gardent leur hachage
    from quantbot.lab.registry import canonical_hash
    from quantbot.lab.gates import GateCfg
    d = {k: v for k, v in d.items() if k not in ("logging", "ai", "validation")}
    assert spec_hash(s) == canonical_hash({"spec": d, "gates": GateCfg().to_dict()})


def test_score_sizing_and_spread_firewall_are_continuous_opt_in_and_keep_old_hashes():
    from quantbot.config import Settings
    from quantbot.lab.pipeline import spec_hash
    from quantbot.risk.manager import score_multiplier
    assert score_multiplier(0.95, 0.0, 0.25) == 1.0                                     # désactivé
    m = [score_multiplier(c, 0.6, 0.25) for c in (0.5, 0.75, 0.95, 1.0)]
    assert m == sorted(m) and m[0] == 0.25 and m[-1] == 1.0 and 0.25 < m[1] < m[2] < 1.0   # croissant et continu : 75 % != 95 %
    base = Settings.from_dict({})
    assert spec_hash(base) == spec_hash(Settings.from_dict({"risk": {"max_spread_frac": 0.0, "score_sizing_floor": 0.0}}))
    assert spec_hash(base) != spec_hash(Settings.from_dict({"risk": {"max_spread_frac": 0.001}}))
