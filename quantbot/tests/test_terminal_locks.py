import importlib.util
import json
import threading
from pathlib import Path

import pytest

from quantbot.filelock import exclusive_lock
from quantbot.live.terminal import mt5_initialize, resolve_terminal
from tests.fake_mt5_live import FakeMT5Live


def test_terminal_path_priority_explicit_env_default_only_if_it_exists(tmp_path, monkeypatch):
    exe = tmp_path / "terminal64.exe"; exe.write_text("x"); monkeypatch.delenv("QUANTBOT_MT5_TERMINAL", raising=False)
    assert resolve_terminal("C:/faux/chemin.exe", str(exe)) == "C:/faux/chemin.exe"                  # explicite : transmis tel quel
    assert resolve_terminal(None, str(exe)) == str(exe) and resolve_terminal(None, str(tmp_path / "absent.exe")) is None   # défaut inexistant : ignoré
    monkeypatch.setenv("QUANTBOT_MT5_TERMINAL", str(exe)); assert resolve_terminal(None, "autre") == str(exe)
    m = FakeMT5Live(); assert mt5_initialize(m) and m.init_args[0] == (str(exe),); monkeypatch.delenv("QUANTBOT_MT5_TERMINAL")
    m2 = FakeMT5Live(); assert mt5_initialize(m2, None, str(tmp_path / "absent.exe")) and m2.init_args[0] == ()


def test_mt5_and_coinbase_paper_workers_use_separate_locks_and_status_files(tmp_path):
    out = tmp_path / "runtime" / "paper"
    with exclusive_lock(out / "paper_mt5.lock"):
        with exclusive_lock(out / "paper_coinbase.lock"):              # ne doit PAS lever « déjà utilisé »
            pass
        with pytest.raises(RuntimeError):
            with exclusive_lock(out / "paper_mt5.lock"):               # le même verrou, lui, protège bien contre un doublon
                pass
    src = (Path(__file__).resolve().parents[1] / "scripts" / "paper_all.py").read_text(encoding="utf-8")
    assert 'f"paper_{args.source}.lock"' in src and 'f"STATUS_{args.source}.json"' in src and '"paper.lock"' not in src


def test_requirements_list_lightgbm_for_the_ml_scripts():
    assert "lightgbm" in (Path(__file__).resolve().parents[1] / "requirements.txt").read_text(encoding="utf-8")
