"""Mécanismes de sortie ajoutés pour les algos de Leo : clôture à l'heure serveur, BE/trailing en prix, sortie sur signal,
RR plancher et risque par signal. Heure serveur = Europe/Athens (UTC+2 en janvier)."""
import numpy as np
from helpers import *
from ftmo_algo.algos.base import ExitCfg
from ftmo_algo.engine.sim import Sim, SimConfig

FLAT = [(100, 100.2, 99.8, 100)] * 12


def mk_at(rows, start):
    return build_market("TEST", bars(rows, start=start), ZERO, NewsCalendar(np.array([], dtype="int64")))


def test_flat_at_server_time_closes_at_bar_close():
    # série démarrant 06:00 UTC = 08:00 serveur ; clôture 10:00 serveur = 08:00 UTC = fin de la barre 7
    mk = mk_at(FLAT + [(100, 100.2, 99.8, 100)] * 4, "2024-01-08 06:00")
    s = signal(mk, 2, 1, 90.0, 150.0, ExitCfg(rr=3, time_stop=0, flat_srv_min=600))
    t = run(mk, s).trades.iloc[0]
    assert t.reason == "cloture_session"
    assert t.entry_t == mk.t[3]
    assert t.exit_t == mk.tc[7]                       # clôturée à la CLÔTURE de la barre qui finit à 10:00 serveur


def test_flat_friday_time_overrides_daily_time():
    mk = mk_at(FLAT + [(100, 100.2, 99.8, 100)] * 4, "2024-01-12 06:00")          # vendredi
    s = signal(mk, 2, 1, 90.0, 150.0, ExitCfg(rr=3, time_stop=0, flat_srv_min=1000, flat_fri_srv_min=600))
    t = run(mk, s).trades.iloc[0]
    assert t.reason == "cloture_session" and t.exit_t == mk.tc[7]


def test_never_overnight_when_flat_time_is_missed():
    # clôture réglée à 23:59 (jamais atteinte à la clôture d'une barre) : le changement de jour serveur force la sortie
    mk = mk_at([(100, 100.2, 99.8, 100)] * 30, "2024-01-08 20:00")                 # 22:00 serveur -> passe minuit serveur
    s = signal(mk, 2, 1, 90.0, 150.0, ExitCfg(rr=3, time_stop=0, flat_srv_min=1439))
    t = run(mk, s).trades.iloc[0]
    assert t.reason == "cloture_session"
    assert t.exit_t == mk.tc[7]                       # barre 21:45-22:00 UTC = 23:45-00:00 serveur : minuit franchi


def test_flat_off_by_default_keeps_position():
    mk = mk_at(FLAT + [(100, 100.2, 99.8, 100)] * 4, "2024-01-08 06:00")
    t = run(mk, signal(mk, 2, 1, 90.0, 150.0, ExitCfg(rr=3, time_stop=0))).trades.iloc[0]
    assert t.reason == "fin_donnees"


def test_px_breakeven_locks_gain():
    rows = FLAT[:6] + [(100, 100.6, 99.9, 100.3), (100.3, 100.4, 100.0, 100.2), (100.2, 100.3, 100.1, 100.2)]
    mk = market(rows)
    ex = ExitCfg(rr=3, time_stop=0, px_be_trig=0.5, px_be_lock=0.1)
    t = run(mk, signal(mk, 5, 1, 99.0, 110.0, ex)).trades.iloc[0]
    assert t.reason == "stop" and abs(t.exit - 100.1) < 1e-9 and abs(t.r - 0.1) < 1e-6


def test_px_trailing_follows_close_and_stays_above_entry():
    rows = FLAT[:6] + [(100, 101.0, 100.0, 101.0), (101, 101.1, 100.4, 100.6), (100.6, 100.7, 100.3, 100.4)]
    mk = market(rows)
    ex = ExitCfg(rr=3, time_stop=0, px_trail_dist=0.5, px_trail_step=0.1, px_trail_above_entry=True)
    t = run(mk, signal(mk, 5, 1, 99.0, 110.0, ex)).trades.iloc[0]
    assert t.reason == "stop" and abs(t.exit - 100.5) < 1e-9


def test_px_trailing_never_loosens_stop():
    rows = FLAT[:6] + [(100, 101.0, 100.0, 101.0), (101, 101.0, 100.7, 100.8), (100.8, 100.9, 100.6, 100.7)]
    mk = market(rows)
    ex = ExitCfg(rr=3, time_stop=0, px_trail_dist=0.5, px_trail_step=0.0)
    r = run(mk, signal(mk, 5, 1, 99.0, 110.0, ex))
    t = r.trades.iloc[0]
    assert t.exit >= 100.5 - 1e-9                      # le stop posé à 100.5 n'a pas reculé quand le prix a baissé


def test_signal_exit_executes_next_open():
    rows = FLAT[:6] + [(100, 100.3, 99.9, 100.1)] * 3 + [(100.4, 100.6, 100.2, 100.5)] * 3
    mk = market(rows)
    s = signal(mk, 5, 1, 90.0, 150.0, ExitCfg(rr=3, time_stop=0))
    s.xs = np.zeros(mk.n, np.int8); s.xs[8] = 1
    t = run(mk, s).trades.iloc[0]
    assert t.reason == "signal_sortie" and t.exit_t == mk.t[9] and abs(t.exit - 100.4) < 1e-9


def test_signal_exit_bit_targets_only_matching_side():
    rows = FLAT[:6] + [(100, 100.3, 99.9, 100.1)] * 6
    mk = market(rows)
    s = signal(mk, 5, 1, 90.0, 150.0, ExitCfg(rr=3, time_stop=0))
    s.xs = np.zeros(mk.n, np.int8); s.xs[8] = 2           # bit « fermer les SHORTS » : ne touche pas un long
    assert run(mk, s).trades.iloc[0].reason == "fin_donnees"


def test_per_signal_min_rr_overrides_config():
    rows = FLAT[:6] + [(100, 100.2, 99.8, 100), (100, 100.2, 99.8, 100)]
    mk = market(rows)
    base = lambda: signal(mk, 5, 1, 99.0, 100.8, ExitCfg(rr=3, time_stop=0))      # RR 0,8
    sim = Sim({"TEST": mk}, SimConfig(min_rr_net=2.5, use_guardian=False))
    assert len(sim.run([base()]).trades) == 0
    s = base(); s.min_rr_net = 0.0
    assert len(Sim({"TEST": mk}, SimConfig(min_rr_net=2.5, use_guardian=False)).run([s]).trades) == 1
    s = base(); s.min_rr_net = 5.0
    assert len(Sim({"TEST": mk}, SimConfig(min_rr_net=0.0, use_guardian=False)).run([s]).trades) == 0


def test_per_signal_risk_multiplier_scales_risk():
    rows = FLAT[:6] + [(100, 100.2, 99.8, 100), (100, 104, 99.9, 103)]
    mk = market(rows)
    a = run(mk, signal(mk, 5, 1, 99.0, 103.0)).trades.iloc[0]
    s = signal(mk, 5, 1, 99.0, 103.0); s.risk_mult = np.full(mk.n, 0.5)
    b = run(mk, s).trades.iloc[0]
    assert abs(b.risk_usd / a.risk_usd - 0.5) < 0.02
