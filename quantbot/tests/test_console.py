import io
import subprocess
import sys
from pathlib import Path

from quantbot.console import safe_console

ROOT = Path(__file__).resolve().parents[1]


def test_safe_console_never_raises_on_cp1252(monkeypatch):
    raw = io.BytesIO()
    cp = io.TextIOWrapper(raw, encoding="cp1252", errors="strict", write_through=True)
    monkeypatch.setattr(sys, "stdout", cp); monkeypatch.setattr(sys, "stderr", cp)
    safe_console()
    print("2022-10-14 → 2023-08-03 ≥ échec")       # lèverait UnicodeEncodeError en cp1252 strict
    assert b"2023-08-03" in raw.getvalue()


def test_every_script_that_prints_makes_the_console_safe_first():
    """Régression C8 : un « \u2192 » dans un print a fait planter run_backward sous cp1252 après le 1er essai. Tout script qui affiche protège la console."""
    import re
    missing = []
    for f in sorted((ROOT / "scripts").glob("*.py")):
        src = f.read_text(encoding="utf-8")
        if "print(" in src and "errors=\"replace\"" not in src:
            missing.append(f.name)
    assert not missing, missing


def test_scripts_still_start_with_help(tmp_path):
    for name in ("run_backward.py", "run_battery_backward.py", "forward_eval.py", "run_c8.py", "export_mt5.py", "export_mt5_deep.py"):
        r = subprocess.run([sys.executable, str(ROOT / "scripts" / name), "--help"], capture_output=True, text=True, cwd=tmp_path)
        assert r.returncode == 0, (name, r.stderr[-300:])
