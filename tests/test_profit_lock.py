import numpy as np
from helpers import *
from ftmo_algo.engine.guardian import Guardian, PropProfile
from ftmo_algo.engine.sim import Sim, SimConfig

FLAT = [(100, 100.5, 99.5, 100)] * 6
LOCK = ExitCfg("lock", rr=10, time_stop=0, lock_steps=((1.5, 0.0), (2.5, 1.0)))


def test_ratchet_long_locks_gain_and_never_moves_back():
    rows = FLAT + [(100, 100.2, 99.8, 100), (100, 102.2, 99.9, 102), (102, 103.5, 101.5, 103), (103, 103.2, 100.5, 101), (101, 101, 98, 98.5)]
    mk = market(rows)
    t = run(mk, signal(mk, 5, 1, 99.0, 110.0, ex=LOCK)).trades.iloc[0]
    assert t.reason == "stop" and abs(t.r - 1.0) < 1e-6          # palier 2,5 R -> +1 R verrouillé
    base = run(mk, signal(mk, 5, 1, 99.0, 110.0, ex=ExitCfg("fixed", rr=10, time_stop=0))).trades.iloc[0]
    assert base.r < 0                                            # sans verrou : le gain latent est restitué


def test_ratchet_short_mirror():
    rows = FLAT + [(100, 100.2, 99.8, 100), (100, 100.2, 97.8, 98), (98, 98.5, 96.5, 97), (97, 99.2, 96.9, 99)]
    mk = market(rows)
    t = run(mk, signal(mk, 5, -1, 101.0, 90.0, ex=LOCK)).trades.iloc[0]
    assert t.reason == "stop" and abs(t.r - 1.0) < 1e-6


def test_ratchet_pays_spread_on_short():
    rows = FLAT + [(100, 100.2, 99.8, 100), (100, 100.2, 97.8, 98), (98, 98.5, 96.5, 97), (97, 99.9, 96.9, 99.5)]
    a, b = market(rows, ZERO), market(rows, COSTLY)
    ta = run(a, signal(a, 5, -1, 101.0, 90.0, ex=LOCK)).trades.iloc[0]
    tb = run(b, signal(b, 5, -1, 101.0, 90.0, ex=LOCK)).trades.iloc[0]
    assert tb.pnl / tb.lots < ta.pnl / ta.lots


def test_daily_profit_lock_cap_and_giveback():
    pl = {"day_gain_pct": 2.0, "arm_pct": 1.0, "giveback_frac": 0.5}
    g = Guardian(PropProfile(profit_lock=pl))
    g.new_day(1, 100000, 100000)
    g.check_close(101500); assert not g.blocked_gain and g.can_open(101500, 0, 100)[0]
    g.check_close(102100); assert g.blocked_gain and g.can_open(102100, 0, 100) == (False, "verrou_gain")
    g.new_day(2, 102100, 102100); assert not g.blocked_gain
    g.check_close(103300); g.check_close(102800)                  # pic +1200, reste +700 : moins de 50 % restitués
    assert not g.blocked_gain
    g.check_close(102650); assert g.blocked_gain                  # +550 <= 50 % de 1200
    off = Guardian(PropProfile())
    off.new_day(1, 100000, 100000); off.check_close(110000); assert not off.blocked_gain


def test_sim_rejects_new_entry_after_day_gain_cap():
    rows = FLAT + [(100, 100.2, 99.8, 100), (100, 104, 99.9, 103), (103, 103.1, 102.9, 103), (103, 103.1, 102.9, 103),
                   (103, 103.2, 102.8, 103), (103, 103.2, 102.8, 103)]
    mk = market(rows)
    s = signal(mk, 5, 1, 99.0, 103.0)
    s.side[9] = 1; s.stop[9] = 102.0; s.target[9] = 106.0; s.grade[9] = 2
    prof = PropProfile(profit_lock={"day_gain_pct": 1.0})
    res = Sim({"TEST": mk}, SimConfig(min_rr_net=0.0, risk_pct=0.5), prof).run([s])
    assert len(res.trades) == 1 and res.rejected.get("verrou_gain", 0) == 1
    free = Sim({"TEST": mk}, SimConfig(min_rr_net=0.0, risk_pct=0.5), PropProfile()).run([s])
    assert len(free.trades) == 2
