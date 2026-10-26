import importlib
import pathlib
import subprocess
import sys

import pytest

EX = pathlib.Path(__file__).resolve().parents[1] / "examples"


def _run(script, *args):
    return subprocess.run([sys.executable, str(EX / script), *args], capture_output=True, text=True, timeout=600)


def test_hftbacktest_asset_configures():
    pytest.importorskip("hftbacktest")
    r = _run("hftbacktest_smoke.py"); assert r.returncode == 0 and "Aucun backtest lancé" in r.stdout


def _csv(tmp_path, n=40000):
    import numpy as np, pandas as pd
    rng = np.random.default_rng(0); c = 1.1 * np.exp(np.cumsum(rng.normal(0, 0.0005, n))); idx = pd.date_range("2022-01-03", periods=n, freq="15min", tz="UTC")
    pd.DataFrame({"time": idx.strftime("%Y-%m-%d %H:%M:%S+00:00"), "open": (o := np.r_[c[0], c[:-1]]), "high": np.maximum(o, c) * 1.0002, "low": np.minimum(o, c) * 0.9998, "close": c, "volume": 100}).to_csv(tmp_path / "x.csv", index=False)
    return str(tmp_path / "x.csv")


def test_vectorbt_baseline_runs_on_a_csv(tmp_path):
    pytest.importorskip("vectorbt")
    r = _run("vbt_baseline.py", _csv(tmp_path)); assert r.returncode == 0 and "achat-conservation" in r.stdout


def test_nautilus_backtest_runs_on_a_csv(tmp_path):
    pytest.importorskip("nautilus_trader")
    r = _run("nautilus_bars_backtest.py", _csv(tmp_path)); assert r.returncode == 0 and "Positions clôturées" in r.stdout


def test_examples_refuse_a_history_shorter_than_the_locked_window(tmp_path):
    pytest.importorskip("vectorbt")
    r = _run("vbt_baseline.py", _csv(tmp_path, 3000)); assert r.returncode == 2 and "trop court" in r.stderr
