import numpy as np
import pandas as pd
from helpers import *
from ftmo_algo.engine.guardian import Guardian, PropProfile
from ftmo_algo.engine.market import build_market
from ftmo_algo.engine.sim import Sim, SimConfig


def test_prague_midnight_reset_winter_and_summer():
    def pday(ts):
        idx = pd.DatetimeIndex([pd.Timestamp(ts, tz="UTC")] )
        df = pd.DataFrame({"open": [1.0], "high": [1.0], "low": [1.0], "close": [1.0], "volume": [1]}, index=idx.repeat(2) + pd.to_timedelta([0, 15], unit="min"))
        return build_market("TEST", df, ZERO, NewsCalendar(np.array([], dtype="int64"))).pday[0]
    # hiver : minuit Prague = 23:00 UTC
    assert pday("2024-01-10 22:30") == pday("2024-01-10 12:00")
    assert pday("2024-01-10 23:30") == pday("2024-01-10 12:00") + 1
    # été : minuit Prague = 22:00 UTC
    assert pday("2024-07-10 21:30") == pday("2024-07-10 12:00")
    assert pday("2024-07-10 22:30") == pday("2024-07-10 12:00") + 1


def test_daily_loss_uses_equity_including_floating():
    prof = PropProfile()
    g = Guardian(prof)
    g.new_day(1, balance=100000.0, equity=100000.0)
    # solde inchangé mais flottant -3,6 % : le gardien interne (70 % de 5 % = 3,5 %) doit se déclencher
    assert g.check_close(equity=96400.0) == "flatten_day"
    assert g.blocked_day
    # le flottant seul peut aussi violer la règle officielle (au pire de la barre)
    g2 = Guardian(prof); g2.new_day(1, 100000.0, 100000.0)
    assert g2.check_official(94900.0, 0)["type"] == "daily_loss"


def test_guardian_blocks_after_gap_loss_and_rejects_next_entry():
    # perte de 4R (gap) = 4 % > limite interne de 3,5 % : journée bloquée, l'entrée suivante est refusée
    rows = [(100, 100.5, 99.5, 100)] * 6 + [(100, 100.2, 99.8, 100), (96, 96.5, 95.5, 96)] + [(96, 96.5, 95.5, 96)] * 6
    mk = market(rows)
    s = signal(mk, 5, 1, 99.0, 103.0)
    s.side[9] = 1; s.stop[9] = 95.0; s.target[9] = 99.0; s.grade[9] = 2
    sim = Sim({"TEST": mk}, SimConfig(risk_pct=1.0, min_rr_net=0.0, use_guardian=True, stop_on_breach=False))
    res = sim.run([s])
    assert res.trades.iloc[0].reason == "stop_gap" and res.trades.iloc[0].r < -3.5
    assert any(e["type"] == "guardian" and e["action"] == "flatten_day" for e in res.events)
    assert res.rejected.get("gardien_jour", 0) == 1 and len(res.trades) == 1


def test_pretrade_risk_reserve_prevents_exceeding_internal_limit():
    rows = [(100, 100.5, 99.5, 100)] * 6 + [(100, 100.2, 99.8, 100)] + [(100, 100.1, 98.5, 99)] + [(99, 99.2, 98.8, 99)] * 6
    mk = market(rows)
    s = signal(mk, 5, 1, 99.0, 103.0)
    s.side[9] = 1; s.stop[9] = 98.0; s.target[9] = 102.0; s.grade[9] = 2
    sim = Sim({"TEST": mk}, SimConfig(risk_pct=2.0, min_rr_net=0.0, use_guardian=True, stop_on_breach=False))
    res = sim.run([s])      # -2 % puis nouvelle entrée à 2 % : 4 % > 3,5 % -> refusée
    assert res.rejected.get("reserve_risque_jour", 0) == 1
