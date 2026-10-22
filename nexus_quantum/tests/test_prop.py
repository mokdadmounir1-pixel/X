import random
import pytest
from nexus.prop.rules import FtmoRules, Governor
from nexus.prop.strategy import StratParams, backtest, weights_series
from nexus.prop.challenge import run_phase, two_step
from nexus.prop.synth import make_prices
from nexus.prop.data import load_close_csv, align


def test_no_lookahead_by_truncation():
    px = make_prices(3, 400, seed=5)
    p = StratParams()
    full = weights_series(px, p)
    for k in (150, 250, 399):
        trunc = weights_series({s: v[:k + 1] for s, v in px.items()}, p)
        assert trunc[k] == pytest.approx(full[k])


def test_future_shock_does_not_change_past_returns():
    px = make_prices(3, 400, seed=5)
    r1 = backtest({s: v[:300] for s, v in px.items()}, StratParams())
    r2 = backtest({s: v[:301] for s, v in px.items()}, StratParams())
    assert r1 == r2[:len(r1)]


def test_governor_stricter_than_rules_and_monotone():
    g = Governor()
    assert g.scale(1.1) == 1.0 and g.scale(0.93) == 0.0 and 0 < g.scale(0.955) < 1
    with pytest.raises(ValueError):
        Governor(floor=0.89)
    with pytest.raises(ValueError):
        Governor(daily_stop=0.06)


def test_phase_outcomes_deterministic_rules():
    R, G = FtmoRules(), Governor()
    assert run_phase([0.06] * 10, R, G, 0.10, random.Random(0)) == "PASS"      # cible atteinte au jour 2 mais min_days=4 => PASS au jour 4
    assert run_phase([-0.06], R, G, 0.10, random.Random(0)) == "FAIL_DAILY"
    assert run_phase([0.0], R, G, 0.10, random.Random(0), max_days=50) == "TIMEOUT"


def test_min_days_enforced():
    R, G = FtmoRules(), Governor()
    # +11% en un jour: ne peut passer avant le jour 4
    pool = [0.11, 0.0]
    out = run_phase(pool, R, G, 0.10, random.Random(0), mean_block=10**9, max_days=3)
    assert out == "TIMEOUT"


def test_null_edge_is_not_a_free_pass():
    rng = random.Random(1)
    pool = [rng.gauss(0, 0.006) for _ in range(2000)]
    r = two_step(pool, sims=1000, seed=3, max_days=252)
    assert r["phase1"]["PASS"] < 0.5 and r["phase1"]["FAIL_DAILY"] == 0.0


def test_csv_loader_validates(tmp_path):
    f = tmp_path / "A.csv"; f.write_text("Date,Close\n2020-01-01,1\n2020-01-02,2\n")
    d, p, sha = load_close_csv(f)
    assert d == ["2020-01-01", "2020-01-02"] and len(sha) == 64
    f.write_text("Date,Close\n2020-01-02,1\n2020-01-01,2\n")
    with pytest.raises(ValueError):
        load_close_csv(f)
    f.write_text("Date,Close\n2020-01-01,-1\n")
    with pytest.raises(ValueError):
        load_close_csv(f)


def test_align_intersection():
    d, o = align({"A": (["1", "2", "3"], [1, 2, 3]), "B": (["2", "3", "4"], [5, 6, 7])})
    assert d == ["2", "3"] and o["A"] == [2, 3] and o["B"] == [5, 6]
