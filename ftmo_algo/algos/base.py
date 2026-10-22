"""Interface commune des algos + structure de signaux."""
from __future__ import annotations
from dataclasses import dataclass, field
import itertools
import numpy as np
import pandas as pd


@dataclass(frozen=True)
class ExitCfg:
    mode: str = "fixed"      # fixed | be | partial | trail_atr | trail_struct | lock
    rr: float = 3.0          # multiple de risque de la cible (cible absolue si le signal n'en fournit pas)
    time_stop: int = 96      # barres
    be_at: float = 1.0
    partial_at: float = 1.5
    partial_frac: float = 0.5
    atr_k: float = 2.5
    trail_after: float = 1.0
    max_rr: float = 8.0
    weekend_flat: bool = False
    lock_steps: tuple = ((1.5, 0.0), (2.5, 1.0))   # mode « lock » : (MFE atteint en R, gain verrouillé en R)
    # --- sorties « natives » (algos importés d'EA MT5) ; toutes inactives par défaut : comportement inchangé
    flat_srv_min: int = -1          # clôture forcée à cette minute du jour (HEURE SERVEUR) ; -1 = désactivée
    flat_fri_srv_min: int = -1      # idem le vendredi si >= 0 (sinon flat_srv_min)
    px_be_trig: float = 0.0         # break-even : gain (unités de prix) qui déclenche le verrou ; 0 = off
    px_be_lock: float = 0.0         # gain verrouillé au-delà de l'entrée (unités de prix)
    px_trail_start: float = 0.0     # trailing : gain minimal avant activation (unités de prix)
    px_trail_dist: float = 0.0      # trailing : distance du stop au prix (unités de prix) ; 0 = off
    px_trail_step: float = 0.0      # trailing : pas minimal de resserrement (unités de prix)
    px_trail_above_entry: bool = False   # le stop suiveur ne peut être posé qu'au-delà du prix d'entrée


@dataclass
class Signals:
    algo: str
    sym: str
    side: np.ndarray            # int8 : +1 long, -1 short, 0 rien (signal constaté À LA CLÔTURE de la barre i)
    stop: np.ndarray            # prix de stop absolu
    target: np.ndarray          # prix de cible absolu (nan -> exit.rr)
    grade: np.ndarray           # 2 = A+, 1 = A, 0 = B
    exit: ExitCfg = field(default_factory=ExitCfg)
    feat: np.ndarray | None = None      # (n, k) features du setup (pour le filtre ML)
    feat_names: tuple = ()
    allow_news: bool = False
    max_per_day: int = 2
    params: dict = field(default_factory=dict)
    min_rr_net: float | None = None     # plancher de RR net propre à l'algo (None = celui de SimConfig) ; RR natif d'un EA importé
    risk_mult: np.ndarray | None = None # multiplicateur de risque par signal (None = 1) ; paliers « core/expérimental »
    xs: np.ndarray | None = None        # int8 : bit 1 = fermer les LONGS à l'ouverture suivante, bit 2 = fermer les SHORTS

    def idx(self):
        return np.flatnonzero(self.side != 0)


def empty_signals(algo, sym, n, exit=None, **kw) -> Signals:
    return Signals(algo, sym, np.zeros(n, np.int8), np.full(n, np.nan), np.full(n, np.nan),
                   np.zeros(n, np.int8), exit or ExitCfg(), **kw)


class Algo:
    """Chaque algo : hypothèse économique, invalidation, grille de paramètres, génération causale."""
    name = "base"
    hypothesis = ""
    invalidation = ""
    grid: dict = {}            # nom -> liste de valeurs (la grille entière est comptée dans le DSR)
    default: dict = {}
    timeframes = ("M15", "H1", "H4", "D1")
    family = "base"            # « leo » pour les algos portés des EA de Leo
    exits = None               # None = toutes les sorties testées ; sinon tuple de noms (ex. ("native",))
    default_exit = "fixed3"    # sortie utilisée par défaut (filtre ML, agents live sans variante choisie)
    native_symbols = ()        # instruments pour lesquels la source a été conçue (indicatif)

    def combos(self):
        keys = list(self.grid)
        return [dict(zip(keys, v)) for v in itertools.product(*[self.grid[k] for k in keys])]

    def neighbors(self, params: dict):
        """Voisins immédiats (±1 cran sur une dimension) pour le test de plateau."""
        out = []
        for k, vals in self.grid.items():
            i = vals.index(params[k])
            for d in (-1, 1):
                if 0 <= i + d < len(vals):
                    out.append({**params, k: vals[i + d]})
        return out

    def generate(self, ctx, params: dict) -> Signals:  # pragma: no cover
        raise NotImplementedError
