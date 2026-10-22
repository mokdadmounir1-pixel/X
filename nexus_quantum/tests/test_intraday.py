import pytest
from nexus.prop.intraday import orb_trades, DAY_OFFSET_MIN
from nexus.prop.mdata import Bars

BASE = 20000 * 1440 + 0   # jour 20000, minutes serveur depuis minuit


def mk(rows, spread=0.1, start=600):
    """rows: liste de (o,h,l,c) par pas de 5 min a partir de 10:00 (GER40: 10:00-18:30)."""
    b = Bars("GER40", "x", [], [], [], [], [], [])
    for k, (o, h, l, c) in enumerate(rows):
        b.ts.append(BASE + start + 5 * k); b.o.append(o); b.h.append(h); b.l.append(l); b.c.append(c)
        b.spread.append(spread)
    return b


RANGE = [(99, 100, 98, 99)] * 6                  # 10:00-10:25 : hi=100 lo=98
FLAT_TAIL = lambda px, n: [(px, px, px, px)] * n  # barres plates jusqu'a 18:25
SLIP = 0.25 * 0.1


def full(rows):
    n = (1110 - 600) // 5
    return rows + FLAT_TAIL(rows[-1][3], n - len(rows))


def test_long_breakout_fill_on_next_open_with_spread_and_eod_exit():
    rows = RANGE + [(100, 101.1, 100, 101), (101.2, 105, 101.2, 105)]
    tr = orb_trades(mk(full(rows)), 30, "EOD")
    assert len(tr) == 1
    entry = 101.2 + 0.1 + SLIP              # ask + slippage, a l'ouverture de la barre SUIVANT le signal
    exit_ = 105 - SLIP
    assert tr[0].r == pytest.approx((exit_ - entry) / (entry - 98))


def test_signal_bar_open_does_not_matter_but_next_open_does():
    a = RANGE + [(100, 101.1, 100, 101), (101.2, 105, 101.2, 105)]
    b = RANGE + [(50, 101.1, 100, 101), (101.2, 105, 101.2, 105)]
    c = RANGE + [(100, 101.1, 100, 101), (102.0, 105, 102.0, 105)]
    ra, rb, rc = (orb_trades(mk(full(x)), 30, "EOD")[0].r for x in (a, b, c))
    assert ra == pytest.approx(rb) and ra != pytest.approx(rc)


def test_stop_has_priority_over_target_in_same_bar():
    rows = RANGE + [(100, 101.1, 100, 101), (101.2, 110, 97, 101)]   # touche cible 2R ET stop
    tr = orb_trades(mk(full(rows)), 30, "2R")[0]
    assert tr.r < -0.9 and tr.mae_r <= tr.r + 1e-9


def test_gap_through_stop_fills_at_open_worse_than_minus_one_r():
    rows = RANGE + [(100, 101.1, 100, 101), (101.2, 101.2, 101.2, 101.2), (90, 90, 90, 90)]
    tr = orb_trades(mk(full(rows)), 30, "EOD")[0]
    assert tr.r < -1.5


def test_short_pays_spread_on_exit():
    rows = RANGE + [(99, 99, 97, 97.5), (97.4, 97.4, 97.4, 97.4)]
    tr = orb_trades(mk(full(rows), spread=0.1), 30, "EOD")[0]
    entry = 97.4 - SLIP
    exit_ = 97.4 + 0.1 + SLIP
    assert tr.r == pytest.approx(-(exit_ - entry) / (100 - entry))


def test_cost_filter_skips_when_spread_dominates_risk():
    narrow = [(99.0, 99.2, 98.9, 99.0)] * 6        # range de 0.3 : cout/risque trop eleve
    rows = narrow + [(99.2, 99.5, 99.2, 99.4), (99.5, 99.9, 99.5, 99.8)]
    assert orb_trades(mk(full(rows), spread=0.1), 30, "EOD") == []


def test_incomplete_range_skips_day():
    rows = RANGE[:4]
    assert orb_trades(mk(rows), 30, "EOD") == []
