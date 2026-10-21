"""Enveloppe d'une tâche : lance la commande, écrit son code retour, s'arrête si le fichier .stop apparaît.
Détachée du dashboard (survit à son redémarrage), sans dépendance externe, identique sous Windows/Linux."""
import os
import subprocess
import sys
import time
from pathlib import Path


def main():
    rc, stop, log = sys.argv[1:4]
    argv = sys.argv[5:]
    env = {**os.environ, "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8"}
    with open(log, "ab") as lf:
        p = subprocess.Popen(argv, stdout=lf, stderr=subprocess.STDOUT, env=env)
        while p.poll() is None:
            if os.path.exists(stop):
                p.terminate()
                try:
                    p.wait(8)
                except subprocess.TimeoutExpired:
                    p.kill()
                break
            time.sleep(0.5)
        Path(rc).write_text(str(p.returncode if p.returncode is not None else -1))


if __name__ == "__main__":
    main()
