import numpy as np
import pandas as pd
import pytest

from quantbot.data.mt5 import broker_clock_to_utc, costs_from_frame, find_holes, load_mt5_csv, weekly_open_check
from quantbot.exceptions import DataValidationError


def _broker_clock(utc):
    """Inverse de la règle us_dst : serveur UTC+3 en heure d'été US, UTC+2 sinon."""
    ny = utc.tz_localize("UTC").tz_convert("America/New_York")
    dst = (ny.tz_localize(None) - utc) == pd.Timedelta(hours=-4)
    return pd.DatetimeIndex(np.where(dst, utc + pd.Timedelta(hours=3), utc + pd.Timedelta(hours=2)))


def test_clock_conversion_roundtrip_outside_transition_hours():
    utc = pd.date_range("2024-01-02", "2024-12-20", freq="1h")
    back = broker_clock_to_utc(_broker_clock(utc), "us_dst")
    wrong = (back != utc).sum()
    assert wrong <= 2 * 3  # au plus quelques heures ambiguës autour des 2 changements d'heure
    assert broker_clock_to_utc(_broker_clock(pd.DatetimeIndex(["2024-07-10 12:00"])), "us_dst")[0] == pd.Timestamp("2024-07-10 12:00")
    assert broker_clock_to_utc(_broker_clock(pd.DatetimeIndex(["2024-01-10 12:00"])), "us_dst")[0] == pd.Timestamp("2024-01-10 12:00")


def test_fixed_offset_rule_and_unknown_rule():
    clock = pd.DatetimeIndex(["2024-01-10 15:00"])
    assert broker_clock_to_utc(clock, "fixed3")[0] == pd.Timestamp("2024-01-10 12:00")
    with pytest.raises(ValueError):
        broker_clock_to_utc(clock, "magic")


def _week_frame(rule_clock_open="00:00"):
    """Semaines FX dont l'ouverture est à 17:00 New York (donc 21:00/22:00 UTC)."""
    rows = []
    for monday in pd.date_range("2024-01-01", "2024-12-23", freq="W-MON"):
        sunday = monday - pd.Timedelta(days=1)
        ny_open = pd.Timestamp(f"{sunday.date()} 17:00").tz_localize("America/New_York").tz_convert("UTC").tz_localize(None)
        rows += list(pd.date_range(ny_open, periods=8, freq="15min"))
    idx = pd.DatetimeIndex(rows)
    return pd.DataFrame({"open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": 1}, index=idx)


def test_weekly_open_shifts_one_hour_between_seasons_with_true_utc():
    chk = weekly_open_check(_week_frame())
    assert chk["summer_median_utc"] == 21.0 and chk["winter_median_utc"] == 22.0 and chk["shift_hours"] == 1.0


def test_fixed_offset_conversion_is_detected_as_wrong():
    df = _week_frame()
    broker = _broker_clock(df.index)
    wrong = df.copy()
    wrong.index = broker - pd.Timedelta(hours=3)  # ce que fait la colonne `time` fournie
    assert weekly_open_check(wrong)["shift_hours"] == 0.0  # pas de décalage saisonnier = conversion fausse en hiver


def test_find_holes_ignores_weekends_but_flags_long_gaps():
    idx = list(pd.date_range("2024-03-01", periods=10, freq="15min")) + \
          list(pd.date_range("2024-03-04", periods=10, freq="15min")) + list(pd.date_range("2024-05-01", periods=10, freq="15min"))
    df = pd.DataFrame({"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0, "volume": 1}, index=pd.DatetimeIndex(idx))
    df.iloc[20:, 0] = 104.0
    holes = find_holes(df)
    assert len(holes) == 1 and holes[0]["price_jump_pct"] == 4.0 and holes[0]["hours"] > 1000


def test_costs_reliability():
    idx = pd.date_range("2025-01-01", periods=100, freq="15min")
    base = pd.DataFrame({"close": 100.0}, index=idx)
    ok = base.assign(spread=0.02)
    assert costs_from_frame(ok)["reliable"] and costs_from_frame(ok)["spread_frac"] == pytest.approx(2e-4)
    zeros = base.assign(spread=0.0)
    out = costs_from_frame(zeros)
    assert not out["reliable"] and out["spread_frac"] is None  # un spread nul n'est JAMAIS pris pour un coût nul


def test_load_mt5_csv_end_to_end(tmp_path):
    utc = pd.date_range("2024-07-01 10:00", periods=40, freq="15min")
    clock = _broker_clock(utc)
    df = pd.DataFrame({"time_broker_epoch": ((clock - pd.Timestamp("1970-01-01")).total_seconds().astype("int64")), "open": 1.1, "high": 1.2, "low": 1.0,
                       "close": 1.1, "tick_volume": 10, "spread": 0.0001, "spread_points": 10})
    p = tmp_path / "x.csv"; df.to_csv(p, index=False)
    out = load_mt5_csv(p, "us_dst")
    assert out.index[0] == utc[0] and out.attrs["clock_rule"] == "us_dst" and (out["spread"] > 0).all()
    with pytest.raises(DataValidationError):
        load_mt5_csv(tmp_path / "absent.csv")
    df.drop(columns="time_broker_epoch").to_csv(p, index=False)
    with pytest.raises(DataValidationError):
        load_mt5_csv(p)


def test_eu_rule_is_default_and_differs_from_us_only_in_the_mismatch_weeks():
    clock = pd.date_range("2024-01-01", "2024-12-31", freq="1h")
    eu, us = broker_clock_to_utc(clock), broker_clock_to_utc(clock, "us_dst")
    diff = pd.Series(eu != us, index=clock)
    assert 0 < diff.sum() < 24 * 40                       # quelques semaines seulement
    assert set(diff[diff].index.month) <= {3, 10, 11}     # fenêtres où les calendriers UE et US divergent
    assert eu[clock.get_loc(pd.Timestamp("2024-07-10 12:00"))] == pd.Timestamp("2024-07-10 09:00")  # été : UTC+3
    assert eu[clock.get_loc(pd.Timestamp("2024-01-10 12:00"))] == pd.Timestamp("2024-01-10 10:00")  # hiver : UTC+2
