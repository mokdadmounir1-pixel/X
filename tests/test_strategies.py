import pytest

from quantlab.engine import EngineCfg, run
from quantlab.strategies import REGISTRY
from quantlab.synth import make_ohlcv

DF = make_ohlcv(8000, seed=3)


@pytest.mark.parametrize("name", [n for n in REGISTRY if n != "ml_direction"])
def test_strategy_runs_and_is_causal(name):
    """Signals on a prefix must equal signals on the full series for the same bars."""
    full = REGISTRY[name]().signals(DF).side
    cut = 5000
    part = REGISTRY[name]().signals(DF.iloc[:cut]).side
    assert (full[:cut - 1] == part[:cut - 1]).all()
    tr, eq = run(DF, REGISTRY[name]().signals(DF), EngineCfg())
    assert len(eq) == len(DF)
