import numpy as np
import pandas as pd
from ftmo_algo.data.loaders import load_csv, merge_bid_ask, data_hash
from ftmo_algo.data.quality import quality_report
from ftmo_algo.data.synth import make_series


def test_csv_autodetect_dukascopy_format_and_timezone(tmp_path):
    p = tmp_path / "EURUSD_M5_bid.csv"
    p.write_text("Gmt time,Open,High,Low,Close,Volume\n01.03.2024 10:00:00.000,1.1,1.2,1.0,1.15,10\n"
                 "01.03.2024 10:05:00.000,1.15,1.2,1.1,1.18,12\n")
    d = load_csv(str(p), instrument="EURUSD")
    assert str(d.index.tz) == "UTC" and d.index[0] == pd.Timestamp("2024-03-01 10:00", tz="UTC")
    assert d.attrs["side"] == "bid"
    q = tmp_path / "XAUUSD.csv"
    q.write_text("<DATE>;<TIME>;<OPEN>;<HIGH>;<LOW>;<CLOSE>;<TICKVOL>\n2024.03.01;10:00:00;1;2;0.5;1.5;5\n2024.03.01;10:05:00;1.5;2;1;1.6;7\n")
    d2 = load_csv(str(q), tz="Europe/Athens")
    assert d2.index[0] == pd.Timestamp("2024-03-01 08:00", tz="UTC")     # fuseau forcé -> UTC


def test_quality_report_flags_problems():
    d = make_series("EURUSD", years=0.3, seed=1)
    d = pd.concat([d.iloc[:1000], d.iloc[1100:]])            # trou
    d.iloc[50, d.columns.get_loc("high")] = d.iloc[50]["low"] - 1e-3   # bougie incohérente
    q = quality_report(d, "EURUSD")
    assert q["gaps_intraday"] >= 1 and q["bad_ohlc"] >= 1 and q["synthetic"]


def test_reproducibility_hash_and_seed():
    a = make_series("US500", years=0.1, seed=4); b = make_series("US500", years=0.1, seed=4)
    assert data_hash({"x": a}) == data_hash({"x": b})
    assert data_hash({"x": a}) != data_hash({"x": make_series("US500", years=0.1, seed=5)})
