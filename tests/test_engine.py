import numpy as np
from helpers import *


FLAT = [(100, 100.5, 99.5, 100)] * 6


def test_entry_at_next_open():
    rows = FLAT + [(101, 101.2, 100.8, 101.1)] + [(101, 101.5, 100.5, 101)] * 3 + [(101, 110, 100.9, 109)]
    mk = market(rows)
    r = run(mk, signal(mk, 5, 1, 99.0, 104.0))   # signal à la clôture de la barre 5, open[6]=101
    t = r.trades.iloc[0]
    assert t.entry == 101.0 and t.entry_t == mk.t[6]
    assert t.entry_t > mk.t[5] and t.reason == "cible"


def test_stop_priority_over_target_same_bar():
    rows = FLAT + [(100, 100.2, 99.8, 100), (100, 106, 98, 105)]   # la barre 7 touche stop (99) ET cible (103)
    mk = market(rows)
    r = run(mk, signal(mk, 5, 1, 99.0, 103.0))
    t = r.trades.iloc[0]
    assert t.reason == "stop" and t.r < 0


def test_gap_beyond_stop_executes_at_open_loss_over_1R():
    rows = FLAT + [(100, 100.2, 99.8, 100), (95, 96, 94, 95)]      # ouverture 95 << stop 99
    mk = market(rows)
    r = run(mk, signal(mk, 5, 1, 99.0, 103.0))
    t = r.trades.iloc[0]
    assert t.reason == "stop_gap" and t.exit == 95.0 and t.r < -4.0


def test_costs_reduce_pnl_and_net_rr():
    rows = FLAT + [(100, 100.2, 99.8, 100)] + [(100, 104, 99.9, 103)]
    a = market(rows, ZERO); b = market(rows, COSTLY)
    ra = run(a, signal(a, 5, 1, 99.0, 103.0)).trades.iloc[0]
    rb = run(b, signal(b, 5, 1, 99.0, 103.0)).trades.iloc[0]
    assert rb.pnl / rb.lots < ra.pnl / ra.lots     # P&L par lot plus faible avec coûts
    # RR net < RR brut : un setup à RR brut 3 est refusé si le seuil net est 2.95 avec coûts
    from ftmo_algo.engine.sim import Sim, SimConfig
    sim = Sim({"TEST": b}, SimConfig(min_rr_net=2.95, use_guardian=False))
    res = sim.run([signal(b, 5, 1, 99.0, 103.0)])
    assert len(res.trades) == 0 and res.rejected.get("rr_net", 0) == 1


def test_short_pays_spread_on_exit():
    rows = FLAT + [(100, 100.2, 99.8, 100)] + [(100, 100.1, 96, 97)]
    a = market(rows, ZERO); b = market(rows, COSTLY)
    ta = run(a, signal(a, 5, -1, 101.0, 97.5)).trades.iloc[0]
    tb = run(b, signal(b, 5, -1, 101.0, 97.5)).trades.iloc[0]
    assert tb.pnl / tb.lots < ta.pnl / ta.lots


def test_lot_rounding_and_risk_cap():
    rows = FLAT + [(100, 100.2, 99.8, 100)] + [(100, 104, 99.9, 103)]
    mk = market(rows)
    r = run(mk, signal(mk, 5, 1, 99.0, 103.0), risk_pct=0.5)
    t = r.trades.iloc[0]
    assert abs(t.lots / 0.01 - round(t.lots / 0.01)) < 1e-6
    assert t.risk_usd <= 500.0 + 1e-6
