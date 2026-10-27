import json

import numpy as np
import pandas as pd
import pytest

from quantbot.data import external as ex
from quantbot.risk.overlay import Overlay, news_factor, tail_factor


def _rows(n=300, start="2021-01-05"):
    d = pd.date_range(start, periods=n, freq="7D"); rng = np.random.default_rng(0)
    return [{"report_date_as_yyyy_mm_dd": x.strftime("%Y-%m-%dT00:00:00.000"), "m_money_positions_long_all": str(int(200000 + 5000 * rng.normal() + 100 * i)), "m_money_positions_short_all": "50000", "open_interest_all": "500000"} for i, x in enumerate(d)]


def test_cot_frame_lag_percentile_causality_and_loud_schema_failure():
    cot = ex.cot_frame(_rows()); assert (cot.index - cot["report_date"]).dt.days.eq(3).all()                  # disponible 3 jours après la photo du mardi
    p = ex.cot_percentile(cot); p2 = ex.cot_percentile(ex.cot_frame(_rows()[:200]))
    assert np.allclose(p.iloc[:200].dropna(), p2.dropna()) and p.dropna().between(0, 100).all()               # causal : les 100 dernières semaines ne changent pas le passé
    with pytest.raises(ValueError, match="rien n'est deviné"):
        ex.cot_frame([{"report_date_as_yyyy_mm_dd": "2024-01-02", "autre": 1}])
    assert ex.fetch_cot(lambda url: json.dumps(_rows(60)))["net_mm"].notna().all()


def test_cot_extremity_is_continuous_and_zero_in_neutral_zone():
    v = [ex.cot_extremity(x) for x in (50, 30, 20, 15, 10, 5, 0, 85, 95, 100)]
    assert v[0] == 0 and v[1] == 0 and v[-1] == 1 and v[6] == 1 and 0 < ex.cot_extremity(8) < 1 and v == [ex.cot_extremity(x) for x in (50, 30, 20, 15, 10, 5, 0, 85, 95, 100)]
    assert ex.cot_extremity(float("nan")) == 0.0


def test_nfp_rule_first_friday_and_events_file_merge(tmp_path):
    t = ex.nfp_times(pd.Timestamp("2026-10-01"), pd.Timestamp("2026-12-31")); assert [x.strftime("%Y-%m-%d") for x in t] == ["2026-10-02", "2026-11-06", "2026-12-04"]
    (tmp_path / "data" / "external").mkdir(parents=True); (tmp_path / "data" / "external" / "macro_events.csv").write_text("time_utc,name\n2026-10-28T18:00:00Z,FOMC\n")
    e = ex.load_events(tmp_path, pd.Timestamp("2026-10-01"), pd.Timestamp("2026-11-30")); assert "FOMC" in set(e["name"]) and len(e) == 3


def test_news_factor_is_zero_on_the_event_and_ramps_continuously():
    ev = pd.DataFrame({"time": [pd.Timestamp("2026-10-28 18:00")], "name": ["FOMC"]})
    f = [news_factor(pd.Timestamp("2026-10-28 18:00") + pd.Timedelta(minutes=m), ev, 15.0) for m in (0, 5, 10, 15, 60)]
    assert f == pytest.approx([0, 1 / 3, 2 / 3, 1, 1]) and news_factor(pd.Timestamp("2026-10-28 17:55"), ev, 15) == pytest.approx(1 / 3) and news_factor(pd.Timestamp("2026-01-01"), None) == 1.0


def test_tail_factor_only_reduces_when_recent_tails_widen():
    rng = np.random.default_rng(1); calm = rng.normal(0, 0.001, 6000)
    assert tail_factor(calm) > 0.9
    wild = np.r_[calm[:5500], rng.normal(0, 0.004, 500)]; f = tail_factor(wild); assert 0.25 <= f < 0.8 and f < tail_factor(calm)
    assert tail_factor(calm[:300]) == 1.0                                       # pas d'historique : jamais de réduction sur du vide
    assert all(0.25 <= tail_factor(np.r_[calm[:5500], rng.normal(0, s, 500)]) <= 1.0 for s in (0.001, 0.002, 0.003))


def test_engine_overlay_can_only_reduce_size_and_zero_blocks_entries():
    from quantbot.backtest.engine import Backtester
    from quantbot.config import Settings
    from quantbot.strategies.events import EventSignalEngine, Event
    from quantbot.core.sim import TradingEngine
    from tests.test_apex import _trending
    df = _trending(1500); s = Settings.from_dict({"backtest": {"warmup_bars": 50}})
    ev = [Event(df.index[i], "bullish", float(df.close.iloc[i]) * 0.995, float(df.close.iloc[i]) * 1.01, "t") for i in range(100, 1400, 40)]
    def run(ov):
        e = TradingEngine(s, signal_engine=EventSignalEngine(s, ev), overlay=ov); e.run_replay(df); e.finish(df); return e.broker.trades
    full, half, zero = run(None), run(lambda ts, c: 0.5), run(lambda ts, c: 0.0)
    assert len(full) > 5 and len(half) == len(full) and zero == []
    assert sum(abs(t.size) for t in half) < 0.75 * sum(abs(t.size) for t in full)


def test_sync_external_writes_cot_reports_failures_and_never_invents_fred(tmp_path):
    from quantbot.data.autosync import sync_external
    ok = sync_external(tmp_path, get=lambda u: json.dumps(_rows(80)), fred_key=None)
    assert ok[0]["source"] == "cot" and ok[0]["status"] == "ok" and (tmp_path / "data" / "external" / "cot_gold.csv").exists() and ok[1]["status"] == "non_configure"
    def boom(u): raise OSError("réseau coupé")
    bad = sync_external(tmp_path / "x", get=boom, fred_key="k"); assert bad[0]["status"] == "erreur" and bad[1]["status"] == "erreur" and "réseau coupé" in bad[0]["error"]
