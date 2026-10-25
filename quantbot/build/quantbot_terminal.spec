# -*- mode: python ; coding: utf-8 -*-
# Compilation PyInstaller du terminal quantbot (Windows). Lancé par build_windows.bat depuis la racine du projet.
import os
from PyInstaller.utils.hooks import collect_submodules

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))
ICON = os.path.join(ROOT, "assets", "fennec_diamond.ico")
hidden = collect_submodules("uvicorn") + collect_submodules("quantbot") + ["webview", "pandas._libs.tslibs.timedeltas", "sqlite3"]

a = Analysis(
    [os.path.join(ROOT, "quantbot_terminal.py")],
    pathex=[ROOT],
    datas=[(os.path.join(ROOT, "quantbot", "gui", "static"), os.path.join("quantbot", "gui", "static"))],
    hiddenimports=hidden,
    excludes=["tkinter", "matplotlib", "pytest"],
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="quantbot-terminal", console=False, icon=ICON if os.path.exists(ICON) else None)
coll = COLLECT(exe, a.binaries, a.datas, name="quantbot-terminal")
