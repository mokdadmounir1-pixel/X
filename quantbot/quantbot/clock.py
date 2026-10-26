"""Contrôle de l'horloge : décalage de la machine par rapport à un serveur NTP (SNTP, UDP/123, bibliothèque standard). Tous les horodatages du projet sont en UTC.

Un décalage supérieur à quelques centaines de ms fausse la mesure de latence et le rapprochement ordre/cotation ; au-delà de plusieurs secondes il fausse la clôture de barre.
"""
from __future__ import annotations

import socket
import struct
import time
from typing import Callable, Optional

NTP_EPOCH = 2208988800          # secondes entre 1900 et 1970
SERVERS = ("time.google.com", "pool.ntp.org")


def _query(server: str, timeout: float) -> tuple[float, float, float, float]:
    """(t1 envoi, t2 réception serveur, t3 émission serveur, t4 réception locale) en secondes Unix."""
    pkt = b"\x1b" + 47 * b"\0"
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.settimeout(timeout); t1 = time.time(); s.sendto(pkt, (server, 123)); data, _ = s.recvfrom(48); t4 = time.time()
    f = struct.unpack("!12I", data[:48])
    ts = lambda sec, frac: sec - NTP_EPOCH + frac / 2 ** 32
    return t1, ts(f[8], f[9]), ts(f[10], f[11]), t4


def clock_offset(servers=SERVERS, timeout: float = 2.0, query: Optional[Callable] = None) -> dict:
    """Décalage local - serveur en secondes (positif = machine en avance) = ((t2-t1)+(t3-t4))/2 inversé ; aller-retour réseau en secondes. Échec = rapporté, jamais inventé."""
    q = query or _query; errors = []
    for srv in servers:
        try:
            t1, t2, t3, t4 = q(srv, timeout)
            return {"status": "ok", "server": srv, "offset_s": -(((t2 - t1) + (t3 - t4)) / 2.0), "round_trip_s": (t4 - t1) - (t3 - t2)}
        except Exception as exc:
            errors.append(f"{srv}: {type(exc).__name__}")
    return {"status": "injoignable", "errors": errors}


def clock_health(res: dict, warn_s: float = 0.25, bad_s: float = 2.0) -> str:
    if res.get("status") != "ok":
        return "inconnue"
    a = abs(res["offset_s"])
    return "ok" if a < warn_s else ("a_corriger" if a < bad_s else "mauvaise")
