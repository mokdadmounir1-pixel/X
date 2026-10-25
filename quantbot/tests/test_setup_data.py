import hashlib
import importlib.util
import json
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "setup_data.py"
spec = importlib.util.spec_from_file_location("setup_data", SCRIPT)
sd = importlib.util.module_from_spec(spec); spec.loader.exec_module(sd)


def make(tmp, monkeypatch, contents):
    root = tmp / "proj"; (root / "data" / "real").mkdir(parents=True)
    insts = [{"file": f"{n}_M15.csv", "sha256": hashlib.sha256(c).hexdigest()} for n, c in contents.items()]
    (root / "data" / "real" / "PROVENANCE.json").write_text(json.dumps({"instruments": insts}), encoding="utf-8")
    monkeypatch.setattr(sd, "ROOT", root); monkeypatch.setattr(sd, "PROV", root / "data" / "real" / "PROVENANCE.json")
    return root


def test_finds_files_by_hash_whatever_their_name_and_never_touches_sources(tmp_path, monkeypatch):
    data = {"EURUSD": b"a" * 2000, "XAUUSD": b"b" * 2000}
    root = make(tmp_path, monkeypatch, data)
    src = tmp_path / "Downloads" / "x"; src.mkdir(parents=True)
    (src / "export (1).csv").write_bytes(data["EURUSD"]); (src / "gold.csv").write_bytes(data["XAUUSD"])
    (src / "decoy.csv").write_bytes(b"c" * 2000)
    assert sd.main(["--from", str(tmp_path / "Downloads")]) == 0
    assert (root / "data" / "real" / "EURUSD_M15.csv").read_bytes() == data["EURUSD"]
    assert (src / "gold.csv").exists() and (src / "decoy.csv").exists()


def test_wrong_content_with_right_name_is_refused(tmp_path, monkeypatch, capsys):
    root = make(tmp_path, monkeypatch, {"EURUSD": b"a" * 2000})
    src = tmp_path / "d"; src.mkdir(); (src / "EURUSD_M15.csv").write_bytes(b"z" * 2000)
    assert sd.main(["--from", str(src)]) == 1
    assert not (root / "data" / "real" / "EURUSD_M15.csv").exists() and "INTROUVABLE" in capsys.readouterr().out


def test_already_in_place_is_left_alone(tmp_path, monkeypatch):
    root = make(tmp_path, monkeypatch, {"EURUSD": b"a" * 2000})
    (root / "data" / "real" / "EURUSD_M15.csv").write_bytes(b"a" * 2000)
    assert sd.main(["--from", str(tmp_path)]) == 0
