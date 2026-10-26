import numpy as np
import pandas as pd
import pytest

from quantbot.strategies import dealer_gex as gx
from quantbot.strategies.apex import PARAMS as AP
from tests.test_apex import _trending


def _chain(F=2400.0, asof="2026-01-05", short_put_wall=True):
    rows = []
    for k in range(2200, 2601, 25):
        rows += [{"strike": k, "type": "C", "oi": 3000 * np.exp(-((k - (F + 50)) / 60) ** 2) + 100, "iv": 0.16, "expiry": "2026-01-30"},
                 {"strike": k, "type": "P", "oi": 3000 * np.exp(-((k - (F - 50)) / 60) ** 2) * (1.5 if short_put_wall else 0.5) + 100, "iv": 0.16, "expiry": "2026-01-30"}]
    return pd.DataFrame(rows).assign(expiry=lambda d: pd.to_datetime(d.expiry))


def test_bs_gamma_matches_closed_form_and_is_peaked_at_the_money():
    g = gx.bs_gamma(100.0, 100.0, 0.25, 0.2); assert abs(g - 1 / np.sqrt(2 * np.pi) / (100 * 0.2 * 0.5) * np.exp(-0.5 * (0.5 * 0.2 * 0.5) ** 2 / 1)) < 1e-3 * g + 1e-9
    assert gx.bs_gamma(100, 100, .25, .2) > gx.bs_gamma(100, 130, .25, .2) and gx.bs_gamma(100, 100, 0, .2) == 0


def test_refuses_without_real_chain_and_validates_columns(tmp_path):
    with pytest.raises(FileNotFoundError, match="Aucun GEX n'est fabriqué"):
        gx.load_chain(tmp_path / "absent.csv")
    (tmp_path / "bad.csv").write_text("strike,type\n2400,C\n")
    with pytest.raises(ValueError):
        gx.load_chain(tmp_path / "bad.csv")


def test_profile_zero_gamma_and_sign_convention():
    ch = _chain(); prof = gx.gex_profile(ch, 2400.0, pd.Timestamp("2026-01-05"))
    assert prof.zero_gamma is not None and 2250 < prof.zero_gamma < 2550
    assert prof.net_gex[list(prof.strikes).index(2450)] > 0 > prof.net_gex[list(prof.strikes).index(2350)]       # mur de calls positif, mur de puts négatif
    heavy_puts = gx.gex_profile(_chain(short_put_wall=True), 2400.0, pd.Timestamp("2026-01-05")).total; assert heavy_puts < gx.gex_profile(_chain(short_put_wall=False), 2400.0, pd.Timestamp("2026-01-05")).total


def test_g_score_is_continuous_in_unit_interval_and_grows_near_clusters_and_with_velocity():
    prof = gx.gex_profile(_chain(), 2400.0, pd.Timestamp("2026-01-05")); top = prof.strikes[np.argmax(np.abs(prof.net_gex))]
    near, far = gx.g_score(top, prof, 5.0, 2.0)["G"], gx.g_score(top + 80, prof, 5.0, 2.0)["G"]
    assert 0 <= far < near <= 1 and gx.g_score(top, prof, 5.0, 0.0)["G"] == 0 < gx.g_score(top, prof, 5.0, 1.0)["G"] < gx.g_score(top, prof, 5.0, 2.0)["G"]
    assert gx.fused_score(0.9, 0.0, 0.5) == 0 and 0 < gx.fused_score(0.8, 0.6, 0.5) < 0.8


def test_events_need_real_profiles_and_are_gamma_weighted():
    df = _trending(); assert gx.events(df, {}) == []                                            # sans profil réel : aucun signal
    prof = gx.gex_profile(_chain(F=float(df.close.iloc[-1])), float(df.close.iloc[-1]), pd.Timestamp("2024-01-05"))
    days = {d: prof for d in df.index.normalize().unique()}
    loose = gx.events(df, days, {"fused_min": 0.3, "basis": 0.0}); strict = gx.events(df, days, {"fused_min": 0.9})
    assert len(strict) <= len(loose)
    for e in loose:
        px = df.close[e.ts]; assert abs(e.target - px) / abs(px - e.stop) == pytest.approx(3.0) and 0 <= e.meta["G"] <= 1
