"""Signaux IGNORÉS : ce qu'aurait donné chaque signal que le moteur n'a pas pris (position déjà ouverte, arrêt de risque, hors séance, week-end, plan refusé...).

Registre « fantôme » en lecture seule : il ne touche ni au courtier, ni au risque, ni à la taille, et ne change AUCUNE décision du moteur (testé : mêmes trades avec et sans). Chaque signal ignoré est suivi sur les barres suivantes :
entrée à l'ouverture de la barre qui suit, stop prioritaire dans une barre, cible, sortie temporelle à `max_hold` barres, coûts déduits en R (`cost_frac` x entrée / distance du stop). Le résultat est un contrefactuel indicatif : les positions fantômes se superposent et la taille n'est pas simulée.
"""
from __future__ import annotations

from typing import Callable, Optional


class GhostBook:
    def __init__(self, max_hold: int, cost_frac: float, reward_risk: float, on_done: Optional[Callable[[dict], None]] = None, max_open: int = 50) -> None:
        self.max_hold, self.cost_frac, self.reward_risk, self.on_done, self.max_open = int(max_hold), float(cost_frac), float(reward_risk), on_done, int(max_open)
        self.open: list[dict] = []; self.done: list[dict] = []; self.dropped = 0

    def add(self, ts, side: str, stop: float, target: Optional[float], reason: str, ref_price: float, strategy: str = "") -> None:
        if len(self.open) >= self.max_open:
            self.dropped += 1
            return
        self.open.append({"ts": ts, "side": side, "stop": float(stop), "target": None if target is None else float(target), "reason": reason, "ref": float(ref_price), "strategy": strategy,
                          "entered": False, "entry": None, "held": 0})

    def step(self, ts, o: float, h: float, l: float, c: float) -> None:
        keep = []
        for g in self.open:
            if ts <= g["ts"]:
                keep.append(g); continue
            long = g["side"] == "long"
            if not g["entered"]:
                g["entered"] = True; g["entry"] = o; dist = (o - g["stop"]) if long else (g["stop"] - o)
                if dist <= 0:
                    self._finish(g, ts, o, "stop_du_mauvais_cote", None); continue
                g["dist"] = dist; g["tp"] = g["target"] if g["target"] is not None else (o + self.reward_risk * dist if long else o - self.reward_risk * dist)
            g["held"] += 1
            hit_s = (l <= g["stop"]) if long else (h >= g["stop"]); hit_t = (h >= g["tp"]) if long else (l <= g["tp"])
            if hit_s:
                self._finish(g, ts, g["stop"], "stop", None)
            elif hit_t:
                self._finish(g, ts, g["tp"], "cible", None)
            elif g["held"] >= self.max_hold:
                self._finish(g, ts, c, "temps", None)
            else:
                keep.append(g)
        self.open = keep

    def _finish(self, g: dict, ts, exit_price: float, outcome: str, _x) -> None:
        if outcome == "stop_du_mauvais_cote":
            return
        gross = ((exit_price - g["entry"]) if g["side"] == "long" else (g["entry"] - exit_price)) / g["dist"]
        r = gross - self.cost_frac * g["entry"] / g["dist"]
        rec = {"signal_ts": str(g["ts"]), "exit_ts": str(ts), "side": g["side"], "reason": g["reason"], "entry": g["entry"], "exit": float(exit_price), "stop": g["stop"], "tp": g["tp"],
               "outcome": outcome, "r": round(float(r), 4), "held": g["held"], "strategy": g["strategy"]}
        self.done.append(rec)
        if self.on_done is not None:
            self.on_done(rec)
