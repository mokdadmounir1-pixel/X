"""Algos portés des EA de Leo : fidélité de la logique (port littéral de référence), horaires serveur, causalité."""
import numpy as np
import pandas as pd
import pytest
from ftmo_algo.algos import leo
from ftmo_algo.algos.context import Ctx
from ftmo_algo.algos.library import ALGOS, LEO_ALGOS, BASE_ALGOS, EXIT_VARIANTS, exit_names
from ftmo_algo.data.quality import resample_ohlc
from ftmo_algo.data.synth import make_series
from ftmo_algo.engine.news import NewsCalendar
from ftmo_algo.timeutil import SERVER_TZ


# ------------------------------------------------------------------ référence littérale du SuperTrend de l'EA 05
def ea_supertrend(h, l, c, P, mult):
    """Port ligne à ligne de CalculerSuperTrend (indices « série » : 0 = barre la plus récente)."""
    haut, bas, clo = h[::-1], l[::-1], c[::-1]
    nb = len(h)
    tr = lambda hh, bb, cp: max(hh, cp) - min(bb, cp)
    somme = sum(tr(haut[nb - 1 - k], bas[nb - 1 - k], clo[nb - k]) for k in range(1, P + 1))
    depart = nb - 1 - P
    atr = somme / P
    milieu = (haut[depart] + bas[depart]) / 2
    bande_h, bande_b = milieu + mult * atr, milieu - mult * atr
    orient = 1 if clo[depart] >= milieu else -1
    for i in range(depart - 1, -1, -1):
        atr = (atr * (P - 1) + tr(haut[i], bas[i], clo[i + 1])) / P
        milieu = (haut[i] + bas[i]) / 2
        hb, lb = milieu + mult * atr, milieu - mult * atr
        hp, bp = bande_h, bande_b
        bande_h = hb if (hb < hp or clo[i + 1] > hp) else hp
        bande_b = lb if (lb > bp or clo[i + 1] < bp) else bp
        orient = (-1 if clo[i] < bande_b else 1) if orient > 0 else (1 if clo[i] > bande_h else -1)
    return orient, atr


def _trending_ohlc(seed, n):
    rng = np.random.default_rng(seed)
    drift = np.repeat(rng.choice([-0.4, 0.4, 0.0], size=n // 25 + 1), 25)[:n]
    c = 100 + np.cumsum(rng.normal(drift, 1.0))
    o = np.r_[c[0], c[:-1]]
    h = np.maximum(o, c) + rng.uniform(0, 0.8, n)
    l = np.minimum(o, c) - rng.uniform(0, 0.8, n)
    return h, l, c


@pytest.mark.parametrize("seed", range(6))
@pytest.mark.parametrize("nb", [60, 133, 300, 421])
def test_supertrend_matches_literal_port_of_the_ea(seed, nb):
    h, l, c = _trending_ohlc(seed, 500)
    h, l, c = h[-nb:], l[-nb:], c[-nb:]
    o_ref, atr_ref = ea_supertrend(h, l, c, 10, 3.0)
    atr = leo.atr_wilder(h, l, c, 10, skip_first=True)
    assert abs(atr[-1] - atr_ref) < 1e-9
    assert int(leo.supertrend(h, l, c, atr, 3.0)[-1]) == o_ref


def test_supertrend_flips_both_ways_on_trending_data():
    h, l, c = _trending_ohlc(1, 800)
    st = leo.supertrend(h, l, c, leo.atr_wilder(h, l, c, 10, skip_first=True), 3.0)
    assert (st > 0).any() and (st < 0).any() and (st[:10] == 0).all()


def test_atr_sma_is_mt5_iatr_simple_mean_of_true_range():
    h, l, c = _trending_ohlc(2, 60)
    tr = np.maximum(h[1:] - l[1:], np.maximum(np.abs(h[1:] - c[:-1]), np.abs(l[1:] - c[:-1])))
    got = leo.atr_sma(h, l, c, 14)
    assert abs(got[30] - tr[16:30].mean()) < 1e-9 and np.isnan(got[12])


# ------------------------------------------------------------------ pivots fractals
def brute_pivots(h, l, nl, nr):
    hi, lo = [], []
    for s in range(nl, len(h) - nr):
        if all(h[s] > h[s - k] for k in range(1, nl + 1)) and all(h[s] > h[s + k] for k in range(1, nr + 1)):
            hi.append((s + nr, h[s]))
        if all(l[s] < l[s - k] for k in range(1, nl + 1)) and all(l[s] < l[s + k] for k in range(1, nr + 1)):
            lo.append((s + nr, l[s]))
    return hi, lo


@pytest.mark.parametrize("nl,nr", [(3, 3), (5, 5), (12, 12), (4, 7)])
def test_pivot_confirms_equals_bruteforce_definition(nl, nr):
    h, l, _ = _trending_ohlc(7, 900)
    ch, lh, cl, ll = leo.pivot_confirms(h, l, nl, nr)
    bh, bl = brute_pivots(h, l, nl, nr)
    assert list(zip(ch.tolist(), lh.tolist())) == bh
    assert list(zip(cl.tolist(), ll.tolist())) == bl
    assert len(bh) > 3


def test_pivot_confirmation_is_causal():
    h, l, _ = _trending_ohlc(8, 900)
    full = leo.pivot_confirms(h, l, 5, 5)
    k = 600
    pre = leo.pivot_confirms(h[:k + 1], l[:k + 1], 5, 5)
    assert np.array_equal(full[0][full[0] <= k], pre[0]) and np.array_equal(full[2][full[2] <= k], pre[2])


def test_breaks_touch_properties():
    h, l, c = _trending_ohlc(9, 1500)
    ch, lh, _, _ = leo.pivot_confirms(h, l, 6, 6)
    sig, trg = leo.breaks_touch(h, l, c, ch, lh, True, 0.0, 300)
    assert sig.sum() > 3
    for j in np.flatnonzero(sig):
        k = int(np.searchsorted(ch, j, side="right")) - 1                    # dernier pivot confirmé à la barre j
        assert ch[k] < j and trg[j] == lh[k] and h[j] >= trg[j] and c[j] >= trg[j]
        assert (h[ch[k] + 1:j] < trg[j]).all()                              # jamais touché avant (sinon consommé)


def test_breaks_cross_first_close_beyond_level_only_once_per_pivot():
    h, l, c = _trending_ohlc(10, 1500)
    ch, lh, _, _ = leo.pivot_confirms(h, l, 3, 3)
    sig = leo.breaks_cross(c, ch, lh, True, 0.0, 300, 3)
    for t, (ik, lv) in enumerate(zip(ch, lh)):
        idx = np.flatnonzero(c[ik + 1:ik - 3 + 301] > lv)
        if len(idx):
            assert sig[ik + 1 + idx[0]]                                      # première clôture au-delà : signal


# ------------------------------------------------------------------ machine d'états Cloud
def fresh():
    return dict(susp=False, locked=False, episode=False, prevSet=False, prevReg=False, prevP=False, lastBuy=False)


def seq(*steps):
    s, out = fresh(), []
    for bull, P, D, H in steps:
        out.append(leo.cloud_step(s, bull, P, D, H))
    return out, s


def test_cloud_bull_buys_until_portal_closes_it():
    out, s = seq((True, False, False, False), (True, True, False, False), (True, False, False, False), (True, True, True, False))
    assert out == [True, False, False, True]          # portail ouvert sans D ni H : suspension ; elle persiste portail fermé


def test_cloud_h12_override_keeps_the_buy_when_daily_is_weak():
    out, _ = seq((True, True, False, True))
    assert out == [True]


def test_cloud_bear_rebound_then_lock_then_bull_resets():
    out, s = seq(
        (True, False, True, True),        # haussier : achat
        (False, True, True, False),       # bascule baissière, portail s'ouvre -> épisode, D haussier -> rebond
        (False, True, False, False),      # D retombe après un achat -> verrouillé
        (False, False, True, True),       # verrouillé : aucun achat même si D haussier
        (True, False, False, False))      # retour haussier : verrou levé
    assert out == [True, True, False, False, True]
    assert not s["locked"] and not s["episode"] and not s["susp"]


def test_cloud_bear_without_portal_never_buys():
    out, _ = seq(*[(False, False, True, True)] * 5)
    assert out == [False] * 5


# ------------------------------------------------------------------ données et contextes partagés
@pytest.fixture(scope="module")
def world():
    M5 = make_series("XAUUSD", years=3.0, seed=11)
    M15 = resample_ohlc(M5, "M15").drop(columns=["close_time"])
    M15.attrs.update(M5.attrs)
    news = NewsCalendar(np.array([], dtype="int64"))
    return M15, news, Ctx("XAUUSD", M15, news=news)


def sig(ctx, name):
    a = ALGOS[name]
    return a.generate(ctx, a.default, EXIT_VARIANTS["native"])


def test_leo_algos_registered_and_use_native_exit_only():
    assert len(LEO_ALGOS) == 14 and all(n in BASE_ALGOS for n in LEO_ALGOS)
    for n in LEO_ALGOS:
        assert exit_names(n) == ["native"] and ALGOS[n].default_exit == "native" and ALGOS[n].family == "leo"
        assert all(ALGOS[n].default[k] in v for k, v in ALGOS[n].grid.items())      # le défaut est dans la grille (plateau)
    for n in BASE_ALGOS:
        if n not in LEO_ALGOS:
            assert "native" not in exit_names(n)


def test_server_bars_are_closed_aligned_and_anchored_on_server_midnight(world):
    _, _, ctx = world
    tc = ctx.mk.tc
    for tf in ("D1", "W1", "H12"):
        df, ix = leo.server_bars(ctx, tf)
        ct = df["close_time"].to_numpy("datetime64[ns]").astype("int64")
        ok = ix >= 0
        assert (ct[ix[ok]] <= tc[ok]).all()                                  # barre utilisée = déjà close
        has_next = ix[ok] + 1 < len(ct)
        assert (ct[np.minimum(ix[ok] + 1, len(ct) - 1)][has_next] > tc[ok][has_next]).all()   # et la plus récente
        loc = df["close_time"].dt.tz_convert(SERVER_TZ)
        assert (loc.dt.minute == 0).all() and (loc.dt.hour.isin([0] if tf != "H12" else [0, 12])).all()
    w1 = leo.server_bars(ctx, "W1")[0]
    assert (w1.index.tz_convert(SERVER_TZ).dayofweek == 0).all()             # semaines lundi 00:00 serveur


def test_future_data_cannot_change_past_server_bars(world):
    M15, news, ctx = world
    k = int(len(M15) * 0.6)
    poisoned = M15.copy()
    poisoned.iloc[k:, :4] = poisoned.iloc[k:, :4].to_numpy() * 3.1
    poisoned["high"] = poisoned[["open", "high", "close"]].max(axis=1)
    poisoned["low"] = poisoned[["open", "low", "close"]].min(axis=1)
    p = Ctx("XAUUSD", poisoned, news=news)
    for tf in ("D1", "W1", "H12"):
        a, ia = leo.server_bars(ctx, tf)
        b, ib = leo.server_bars(p, tf)
        va, vb = a.close.to_numpy()[ia[:k][ia[:k] >= 0]], b.close.to_numpy()[ib[:k][ib[:k] >= 0]]
        assert np.allclose(va, vb)


@pytest.mark.parametrize("name", LEO_ALGOS)
def test_signals_on_prefix_identical_to_full_series(world, name):
    M15, news, full = world
    k = int(len(M15) * 0.72)
    pre = Ctx("XAUUSD", M15.iloc[:k], news=news)
    a, b = sig(full, name), sig(pre, name)
    assert np.array_equal(a.side[:k], b.side)
    m = b.side != 0
    assert np.allclose(a.stop[:k][m], b.stop[m], equal_nan=True) and np.allclose(a.target[:k][m], b.target[m], equal_nan=True)
    if a.xs is not None:
        assert np.array_equal(a.xs[:k], b.xs)
    if a.risk_mult is not None:
        assert np.allclose(a.risk_mult[:k][m], b.risk_mult[m])
    assert (a.side != 0).sum() > 0                                           # le test n'est pas vide de sens


@pytest.mark.parametrize("name", ["leo_double_croisement", "leo_hybride_supertrend", "leo_cloud_ema_atr"])
def test_daily_decision_algos_fire_once_per_server_day_at_decision_time(world, name):
    _, _, ctx = world
    s = sig(ctx, name)
    i = s.idx()
    minute = 90 if name == "leo_cloud_ema_atr" else 60
    mk = ctx.mk
    assert (mk.srv_min_c[i] == minute).all() and (mk.srv_dow_c[i] <= 4).all() and (s.stop[i] < ctx.c[i]).all()
    assert len(set(mk.srv_day_c[i].tolist())) == len(i) and (s.side[i] > 0).all()      # long seul, une fois par jour
    assert s.exit.flat_srv_min == (21 * 60 + 45 if name == "leo_cloud_ema_atr" else 21 * 60 + 30)


def test_double_croisement_requires_both_states(world):
    _, _, ctx = world
    s = sig(ctx, "leo_double_croisement")
    w1, ixw = leo.server_bars(ctx, "W1"); d1, ixd = leo.server_bars(ctx, "D1")
    wc, dc = w1.close.to_numpy(), d1.close.to_numpy()
    from ftmo_algo.indicators import ema_arr
    for j in s.idx()[:200]:
        assert ema_arr(wc, 4)[ixw[j]] > ema_arr(wc, 29)[ixw[j]] and ema_arr(dc, 10)[ixd[j]] > ema_arr(dc, 15)[ixd[j]]


def test_range_breakout_one_trade_per_day_after_range_and_before_flat(world):
    _, _, ctx = world
    s = sig(ctx, "leo_range_breakout")
    omin, _, oday = leo.srv_open(ctx)
    i = s.idx()
    assert len(set(oday[i].tolist())) == len(i)                               # première cassure du jour seulement
    assert (omin[i] >= 450).all() and (omin[i] + 15 <= 18 * 60).all()
    assert s.exit.flat_srv_min == 18 * 60
    # stop = bord opposé de la plage 00:00-07:30
    win = (omin >= 0) & (omin + 15 <= 450)
    for j in i[:60]:
        d = oday == oday[j]
        hi, lo = ctx.h[d & win].max(), ctx.l[d & win].min()
        assert (s.stop[j] == lo and s.side[j] > 0 and ctx.c[j] > hi) or (s.stop[j] == hi and s.side[j] < 0 and ctx.c[j] < lo)


def test_range_breakout_rejects_days_with_incomplete_range():
    idx = pd.date_range("2024-01-08 00:00", periods=96 * 7, freq="15min", tz="UTC")
    n = len(idx)
    px = np.full(n, 100.0)
    df = pd.DataFrame({"open": px, "high": px + 0.1, "low": px - 0.1, "close": px, "volume": 100}, index=idx)
    # journée serveur du 11/01 : plage 22:00 UTC (10/01) -> 05:30 UTC ; on la complète puis on casse
    day0 = pd.Timestamp("2024-01-10 22:00", tz="UTC")
    win = (df.index >= day0) & (df.index < day0 + pd.Timedelta(minutes=450))
    df.loc[win, "high"] = 100.5; df.loc[win, "low"] = 99.5
    brk = df.index.get_loc(day0 + pd.Timedelta(minutes=450 + 120))            # 2 h après la fin de plage
    df.iloc[brk:, df.columns.get_loc("close")] = 102.0
    df.iloc[brk:, df.columns.get_loc("high")] = 102.2
    ctx = Ctx("XAUUSD", df, news=NewsCalendar(np.array([], dtype="int64")))
    s = leo.LeoRangeBreakout().generate(ctx, {"end_min": 450, "sl_pct": 0.0}, EXIT_VARIANTS["native"])
    assert list(np.flatnonzero(s.side)) == [brk] and s.side[brk] == 1 and abs(s.stop[brk] - 99.5) < 1e-9
    # plage incomplète (barres retirées) : jour ignoré
    holes = df.drop(df.index[win][:20])
    ctx2 = Ctx("XAUUSD", holes, news=NewsCalendar(np.array([], dtype="int64")))
    s2 = leo.LeoRangeBreakout().generate(ctx2, {"end_min": 450, "sl_pct": 0.0}, EXIT_VARIANTS["native"])
    assert s2.side.sum() == 0


def test_bandito_decides_on_h1_close_with_indicator_exits_and_native_geometry(world):
    _, _, ctx = world
    s = sig(ctx, "leo_bandito")
    mk = ctx.mk
    idx = np.flatnonzero((s.side != 0) | (s.xs != 0))
    assert ((mk.tc[idx] // 60_000_000_000) % 60 == 0).all()                  # uniquement à la clôture d'une barre H1
    pip = ctx.spec.tick * 10
    j = s.idx()[0]
    sd = int(s.side[j])
    assert abs((ctx.c[j] - s.stop[j]) * sd - 180 * pip) < 1e-9 and abs((s.target[j] - ctx.c[j]) * sd - 130 * pip) < 1e-9
    assert s.min_rr_net == 0.0 and (s.xs & 3).any() and s.exit.px_trail_dist == 180 * pip


def test_happy_gold_and_gold_scalping_trade_only_inside_their_schedule(world):
    _, _, ctx = world
    mk = ctx.mk
    for name in ("leo_happy_gold", "leo_gold_scalping"):
        s = sig(ctx, name)
        i = s.idx()
        fri = mk.srv_dow_c[i] == 4
        end = np.where(fri, 12 * 60 if name == "leo_happy_gold" else 19 * 60, 19 * 60)
        assert (mk.srv_min_c[i] >= 180).all() and (mk.srv_min_c[i] < end).all() and (mk.srv_dow_c[i] <= 4).all()
        assert (np.abs(s.target[i] - ctx.c[i]) > 0).all() and s.exit.px_trail_dist > 0
    hg = sig(ctx, "leo_happy_gold")
    assert (hg.side > 0).any() and not (hg.side < 0).any()                  # long seul par défaut
    gs = sig(ctx, "leo_gold_scalping")
    assert (gs.side > 0).any() and (gs.side < 0).any()                      # les deux sens


def test_gold_scalping_filters_apply_after_pivot_consumption(world):
    _, _, ctx = world
    a = ALGOS["leo_gold_scalping"]
    loose = a.generate(ctx, {"piv": 3, "adx_min": 0.0}, EXIT_VARIANTS["native"])
    strict = a.generate(ctx, {"piv": 3, "adx_min": 40.0}, EXIT_VARIANTS["native"])
    assert (strict.side != 0).sum() < (loose.side != 0).sum()
    assert not ((strict.side != 0) & (loose.side == 0)).any()               # un filtre plus strict ne crée jamais de signal


def test_superselector_modules_follow_the_ea_rules(world):
    _, _, ctx = world
    mon = sig(ctx, "leo_ss_monday")
    assert (ctx.mk.srv_dow_c[mon.idx()] == 0).all() and (mon.risk_mult[mon.idx()] == 1.0).all() and (mon.grade[mon.idx()] == 2).all()
    for name in ("leo_ss_lcrb", "leo_ss_volshock", "leo_ss_ldr", "leo_ss_ibi", "leo_ss_eef"):
        s = sig(ctx, name)
        i = s.idx()
        assert len(i) > 0 and np.allclose(s.risk_mult[i], 0.15 / 0.35) and (s.grade[i] == 1).all()
        sd = s.side[i].astype(float)
        a = (np.abs(ctx.c[i] - s.stop[i]) / np.abs(s.target[i] - ctx.c[i]))
        assert np.allclose(a, a[0])                                          # géométrie SL/TP constante en ATR
        assert s.min_rr_net == 0.0
    selector = sig(ctx, "leo_superselector")
    union = np.zeros(ctx.n, bool)
    for name in ("leo_ss_monday", "leo_ss_lcrb", "leo_ss_volshock", "leo_ss_ldr", "leo_ss_ibi", "leo_ss_eef"):
        union |= sig(ctx, name).side != 0
    assert ((selector.side != 0) <= union).all() and (selector.side != 0).sum() > 0   # jamais plus que l'union des modules


def test_superselector_priority_order_is_monday_first(world):
    _, _, ctx = world
    selector = sig(ctx, "leo_superselector")
    mon = sig(ctx, "leo_ss_monday")
    both = (mon.side != 0) & (selector.side != 0)
    assert both.any() and (selector.side[both] == mon.side[both]).all() and (selector.risk_mult[both] == 1.0).all()


def test_min_score_filters_the_selector(world):
    _, _, ctx = world
    a = ALGOS["leo_superselector"]
    lo = a.generate(ctx, {"min_score": 70.0}, EXIT_VARIANTS["native"])
    hi = a.generate(ctx, {"min_score": 80.0}, EXIT_VARIANTS["native"])
    assert (hi.side != 0).sum() < (lo.side != 0).sum()


def test_leo_signals_flow_through_the_pessimistic_engine(world):
    from ftmo_algo.research.wf import sim_trades
    _, _, ctx = world
    for name in ("leo_range_breakout", "leo_bandito", "leo_double_croisement"):
        tr = sim_trades(ctx, sig(ctx, name))
        assert len(tr) > 10 and np.isfinite(tr.r.to_numpy()).all()
    tr = sim_trades(ctx, sig(ctx, "leo_range_breakout"))
    assert set(tr.reason) <= {"stop", "stop_gap", "cloture_session", "fin_donnees"}   # jamais d'overnight, pas de TP


def test_research_path_keeps_native_exits(world):
    """Non-régression : run_variants ne doit pas remplacer la sortie native (clôture de session, BE, trailing) par celle du
    catalogue — sinon les positions étaient tenues des mois."""
    from ftmo_algo.research.wf import run_variants, dvkey
    _, _, ctx = world
    out = run_variants({"XAUUSD": ctx}, ["leo_double_croisement", "leo_range_breakout"], only={
        "leo_double_croisement": {dvkey("leo_double_croisement")}, "leo_range_breakout": {dvkey("leo_range_breakout")}})
    dc = out["leo_double_croisement"][dvkey("leo_double_croisement")]
    rb = out["leo_range_breakout"][dvkey("leo_range_breakout")]
    assert len(dc) > 10 and len(rb) > 50
    assert dc.bars.max() < 120 and rb.bars.max() < 120                     # intrajournalier : jamais plus d'une séance
    assert (dc.reason == "cloture_session").mean() > 0.5


def test_null_test_stays_passable_when_many_algos_are_tested():
    """Régression de résolution : avec 22 tests, alpha de Šidák = 0,0048 < 1/(99+1) : 99 tirages rendaient le test nul
    infranchissable pour TOUS les algos. Le nombre de tirages/décalages doit être relevé ; inchangé pour ≤ 9 algos."""
    from ftmo_algo.research.gates import GateCfg, null_resolution, null_gate
    cfg = GateCfg()
    legacy = null_resolution(8, 99, cfg)
    assert legacy["null_B"] == 99 and legacy["jours_de_decalage"] == 50 and not legacy["relevé"]
    big = null_resolution(22, 99, cfg)
    assert big["relevé"] and big["null_B"] > 99 and big["p_min_atteignable"] < big["alpha_par_test"] / 1.2
    assert 2 * big["jours_de_decalage"] >= big["null_B"] - 1
    # un edge décisif (observé > tous les nuls) franchit effectivement la porte avec la résolution relevée
    ok, p, alpha = null_gate(1.0, np.zeros(big["null_B"]), 22, cfg)
    assert ok and p < alpha
    ok99, _, _ = null_gate(1.0, np.zeros(99), 22, cfg)
    assert not ok99                                                              # et jamais avec 99 : le défaut du protocole
