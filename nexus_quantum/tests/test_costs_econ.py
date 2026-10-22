import pytest
from nexus.costs import CostModel, Instrument
from nexus.economics import required_gross_edge_per_trade, ruin_probability_mc

MES = Instrument("MES", 0.25, 1.25)


def test_round_trip_arithmetic():
    m = CostModel(0.5, 0.3, 1.0, 0.25)
    # fees 2*(0.8)=1.6 ; ticks (1+0.5)=1.5*1.25=1.875
    assert m.round_trip(MES) == pytest.approx(3.475)
    assert m.round_trip(MES, qty=2, stress=2) == pytest.approx(13.9)
    assert m.breakeven_ticks(MES) == pytest.approx(3.475 / 1.25)


def test_passive_skips_spread():
    m = CostModel(0.5, 0.3, 1.0, 0.0, crosses_spread=False)
    assert m.round_trip(MES) == pytest.approx(1.6)


def test_breakeven_with_fixed_costs():
    assert required_gross_edge_per_trade(3.0, 1000, 500) == pytest.approx(3.5)
    with pytest.raises(ValueError):
        required_gross_edge_per_trade(1, 0, 1)


def test_ruin_monotonic_and_deterministic():
    a = ruin_probability_mc(0.5, 1.0, 0.01, 0.5, 500, sims=3000, seed=1)
    b = ruin_probability_mc(0.5, 1.0, 0.05, 0.5, 500, sims=3000, seed=1)
    assert b > a
    assert a == ruin_probability_mc(0.5, 1.0, 0.01, 0.5, 500, sims=3000, seed=1)
