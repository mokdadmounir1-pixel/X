import json

import numpy as np
import pandas as pd
import pytest

from quantbot.config import Settings, load_settings, save_settings
from quantbot.data.loaders import generate_synthetic, load_csv, resample_ohlcv
from quantbot.data.validation import validate_ohlcv
from quantbot.exceptions import ConfigError, DataFetchError, DataValidationError
from tests.helpers import make_index


def test_defaults_valid_and_roundtrip(tmp_path):
    s = Settings()
    path = tmp_path / "c.json"
    save_settings(s, path)
    assert load_settings(path).to_dict() == s.to_dict()


def test_shipped_default_config_matches_defaults():
    from pathlib import Path
    shipped = Path(__file__).resolve().parents[1] / "config" / "default.json"
    assert load_settings(shipped).to_dict() == Settings().to_dict()


@pytest.mark.parametrize("bad", [
    {"tolerance": {"tolerance_percentage": 0.5, "deviation_threshold": 0.3}},
    {"tolerance": {"unknown": 1}},
    {"nope": {}},
    {"risk": {"risk_per_trade": 0.5}},
    {"validation": {"split": [0.5, 0.2, 0.2]}},
    {"signals": {"trend_filter": "magic"}},
])
def test_invalid_config_rejected(bad):
    with pytest.raises(ConfigError):
        Settings.from_dict(bad)


def test_overrides_validated():
    s = Settings().with_overrides({"tolerance.min_score": 0.7})
    assert s.tolerance.min_score == 0.7
    with pytest.raises(ConfigError):
        Settings().with_overrides({"tolerance.nope": 1})
    with pytest.raises(ConfigError):
        Settings().with_overrides({"tolerance.min_score": 5})


def test_missing_and_bad_config_file(tmp_path):
    with pytest.raises(ConfigError):
        load_settings(tmp_path / "absent.json")
    bad = tmp_path / "bad.json"
    bad.write_text("{oops")
    with pytest.raises(ConfigError):
        load_settings(bad)


def _ok_frame(n=10):
    return pd.DataFrame({"open": 10.0, "high": 11.0, "low": 9.0, "close": 10.5, "volume": 1.0}, index=make_index(n))


def test_validate_ok_and_missing_volume():
    df = _ok_frame().drop(columns="volume")
    assert "volume" in validate_ohlcv(df)


def test_validate_rejects_bad_data():
    df = _ok_frame()
    bad = df.copy(); bad.iloc[3, bad.columns.get_loc("high")] = 5.0
    with pytest.raises(DataValidationError):
        validate_ohlcv(bad)
    nan = df.copy(); nan.iloc[2, 0] = np.nan
    with pytest.raises(DataValidationError):
        validate_ohlcv(nan)
    with pytest.raises(DataValidationError):
        validate_ohlcv(df.drop(columns="close"))
    with pytest.raises(DataValidationError):
        validate_ohlcv(df.reset_index(drop=True))
    dup = pd.concat([df, df.iloc[:1]])
    with pytest.raises(DataValidationError):
        validate_ohlcv(dup)


def test_validate_repair():
    df = _ok_frame()
    df.iloc[3, df.columns.get_loc("high")] = 5.0
    df.iloc[2, 0] = np.nan
    out = validate_ohlcv(df, repair=True)
    assert len(out) == 9 and (out["high"] >= out[["open", "close"]].max(axis=1)).all()


def test_synthetic_valid_and_deterministic():
    a, b = generate_synthetic(300, seed=1), generate_synthetic(300, seed=1)
    pd.testing.assert_frame_equal(a, b)
    validate_ohlcv(a)


def test_csv_loading(tmp_path):
    df = generate_synthetic(50)
    path = tmp_path / "d.csv"
    df.reset_index(names="timestamp").to_csv(path, index=False)
    assert len(load_csv(path)) == 50
    with pytest.raises(DataFetchError):
        load_csv(tmp_path / "missing.csv")


def test_resample():
    df = generate_synthetic(48)
    r = resample_ohlcv(df, "4h")
    assert len(r) == 12 and r["high"].iloc[0] == df["high"].iloc[:4].max()
