"""Verrou de fichier inter-processus (un seul démon par dossier) ; relâché par l'OS même après un crash."""
from __future__ import annotations

import sys
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def exclusive_lock(path: str | Path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("a+b")
    locked = False
    try:
        if handle.seek(0, 2) == 0:
            handle.write(b"0"); handle.flush()
        handle.seek(0)
        try:
            if sys.platform == "win32":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            locked = True
        except OSError:
            raise RuntimeError(f"{path.name} : déjà utilisé par un autre processus") from None
        yield
    finally:
        if locked:
            handle.seek(0)
            if sys.platform == "win32":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()
