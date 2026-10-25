import numpy as np
import pandas as pd
import pytest

from quantbot.lab.walkforward import make_windows, walk_forward

T0 = pd.Timestamp("2024-01-01", tz="UTC")


def trades(rng, n, mean, sd=1.0, days=1100):
    ts = sorted(T0 + pd.Timedelta(days=float(d)) for d in rng.uniform(0, days, n))
    return [(t, float(rng.normal(mean, sd))) for t in ts]


def test_windows_do_not_exceed_end_and_test_windows_do_not_overlap():
    w = make_windows(T0, T0 + pd.Timedelta(days=1000), 365, 90)
    assert w and all(b > a and c > b and c <= T0 + pd.Timedelta(days=1000) for a, b, c in w)
    assert all(w[i][2] == w[i + 1][1] for i in range(len(w) - 1))


def test_pure_noise_has_no_oos_edge_even_though_training_looks_good():
    """Le biais de sélection existe à l'entraînement et DISPARAIT hors échantillon : c'est le but de la méthode."""
    rng = np.random.default_rng(1)
    cfgs = {f"c{i}": trades(rng, 600, 0.0) for i in range(40)}
    res = walk_forward(cfgs, T0, T0 + pd.Timedelta(days=1100), 365, 90, min_train_trades=30)
    s = res.summary
    assert s["n_oos_trades"] > 100
    assert s["mean_train_expectancy_of_chosen"] > 0.1            # le meilleur sur l'entraînement a l'air bon...
    assert abs(s["oos_expectancy_R"]) < 0.15                      # ...et ne l'est pas hors échantillon
    assert s["optimism_gap_R"] > 0.05


def test_real_edge_in_one_config_is_found_out_of_sample():
    rng = np.random.default_rng(2)
    cfgs = {f"c{i}": trades(rng, 600, 0.0) for i in range(9)}
    cfgs["good"] = trades(rng, 600, 0.35)
    res = walk_forward(cfgs, T0, T0 + pd.Timedelta(days=1100), 365, 90, min_train_trades=30)
    assert res.summary["oos_expectancy_R"] > 0.15
    assert sum(w.chosen == "good" for w in res.windows) >= len([w for w in res.windows if w.chosen]) * 0.5


def test_window_choice_never_uses_test_trades():
    """Falsifier un trade du futur (dans la fenêtre de test) ne change pas le choix de la fenêtre."""
    rng = np.random.default_rng(3)
    cfgs = {f"c{i}": trades(rng, 400, 0.0) for i in range(5)}
    base = walk_forward(cfgs, T0, T0 + pd.Timedelta(days=700), 365, 90, 30)
    t_test = base.windows[0].test_start + pd.Timedelta(days=1)
    sabotaged = {k: v + [(t_test, 100.0)] for k, v in cfgs.items()}
    sab = walk_forward({k: sorted(v) for k, v in sabotaged.items()}, T0, T0 + pd.Timedelta(days=700), 365, 90, 30)
    # seule la 1re fenêtre a ce trade dans son TEST (les suivantes l'ont légitimement dans leur entraînement)
    assert sab.windows[0].chosen == base.windows[0].chosen and sab.windows[0].train_expectancy == base.windows[0].train_expectancy


def test_window_without_enough_trades_does_not_trade():
    rng = np.random.default_rng(4)
    res = walk_forward({"a": trades(rng, 5, 0.5)}, T0, T0 + pd.Timedelta(days=700), 365, 90, 30)
    assert res.summary["n_windows_traded"] == 0 and res.summary["oos_expectancy_R"] is None
