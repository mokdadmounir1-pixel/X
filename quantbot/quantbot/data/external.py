"""Données externes GRATUITES et publiques, en lecture seule : positionnement COT de l'or (CFTC) et calendrier macro.

COT (CFTC, rapport « Disaggregated Futures Only », COMEX Gold, code 088691) : « Managed Money » long/short. Publié le VENDREDI pour la photo du MARDI : `available_from` = mardi + 3 jours,
jamais avant (aucune fuite). Le schéma de l'API publique (Socrata 72hh-3qpy) n'a PAS pu être vérifié en direct depuis le serveur de développement (réseau fermé) : le parseur échoue
bruyamment si un champ manque, il ne devine pas.
Calendrier macro : fichier data/external/macro_events.csv (colonnes : time_utc, name, importance) à fournir ou à télécharger avec une clé FRED GRATUITE (variable FRED_API_KEY, jamais stockée dans le dépôt) ;
sans fichier, seules les règles régulières (NFP : 1er vendredi du mois 12:30/13:30 UTC) sont connues. Les dates FOMC/CPI ne sont JAMAIS devinées.
"""
from __future__ import annotations

import json
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Callable, Optional

import numpy as np
import pandas as pd

COT_URL = "https://publicreporting.cftc.gov/resource/72hh-3qpy.json"
COT_GOLD_CODE = "088691"
COT_FIELDS = ("report_date_as_yyyy_mm_dd", "m_money_positions_long_all", "m_money_positions_short_all")


def _get(url: str, timeout: float = 20.0) -> str:
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return r.read().decode("utf-8")


def fetch_cot(get: Callable[[str], str] = _get, limit: int = 2000) -> pd.DataFrame:
    q = urllib.parse.urlencode({"cftc_contract_market_code": COT_GOLD_CODE, "$order": "report_date_as_yyyy_mm_dd", "$limit": limit})
    return cot_frame(json.loads(get(f"{COT_URL}?{q}")))


def cot_frame(rows: list[dict]) -> pd.DataFrame:
    """Lignes JSON -> DataFrame indexé par la date de DISPONIBILITÉ (mardi + 3 jours) avec net_mm = long - short du Managed Money. Champ absent : ValueError explicite."""
    if not rows:
        raise ValueError("COT : réponse vide")
    missing = [f for f in COT_FIELDS if f not in rows[0]]
    if missing:
        raise ValueError(f"COT : champs attendus absents {missing} (schéma de l'API modifié ?) : rien n'est deviné")
    df = pd.DataFrame(rows); d = pd.to_datetime(df["report_date_as_yyyy_mm_dd"]).dt.tz_localize(None).dt.normalize()
    out = pd.DataFrame({"report_date": d, "net_mm": pd.to_numeric(df["m_money_positions_long_all"]) - pd.to_numeric(df["m_money_positions_short_all"])})
    out["available_from"] = out["report_date"] + pd.Timedelta(days=3)
    return out.drop_duplicates("report_date").sort_values("report_date").set_index("available_from")


def cot_percentile(cot: pd.DataFrame, window: int = 156) -> pd.Series:
    """Rang percentile [0, 100] de net_mm parmi les `window` dernières semaines (courante incluse), à la date de disponibilité. Causal."""
    x = cot["net_mm"]
    return x.rolling(window, min_periods=max(26, window // 4)).apply(lambda w: 100.0 * (w <= w[-1]).mean(), raw=True)


def cot_extremity(pct: float, lo: float = 5.0, hi: float = 95.0) -> float:
    """Score continu [0, 1] d'extrémité du positionnement (0 en zone neutre, 1 au-delà des seuils) : aucune coupure binaire."""
    if not np.isfinite(pct):
        return 0.0
    return float(np.clip(max((lo * 3 - pct) / (lo * 2), (pct - (100 - lo * 3)) / (lo * 2)) if (pct < lo * 3 or pct > 100 - lo * 3) else 0.0, 0.0, 1.0))


def nfp_times(start: pd.Timestamp, end: pd.Timestamp) -> list[pd.Timestamp]:
    """Règle régulière : 1er vendredi du mois, 13:30 UTC (12:30 en heure d'hiver américaine). Approximation : l'heure exacte suit l'heure d'été américaine ; un décalage d'une heure est possible."""
    out = []
    for m in pd.period_range(start, end, freq="M"):
        d = pd.Timestamp(m.start_time); first_fri = d + pd.Timedelta(days=(4 - d.weekday()) % 7)
        t = first_fri + pd.Timedelta(hours=13, minutes=30)
        if start <= t <= end:
            out.append(t)
    return out


def load_events(root: Path, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    """Événements connus : fichier macro_events.csv (si présent) + NFP régulier. Colonnes : time (UTC naïf), name."""
    rows = [{"time": t, "name": "NFP (règle)"} for t in nfp_times(start, end)]
    f = Path(root) / "data" / "external" / "macro_events.csv"
    if f.exists():
        df = pd.read_csv(f); t = pd.to_datetime(df["time_utc"], utc=True).dt.tz_localize(None)
        rows += [{"time": a, "name": b} for a, b in zip(t, df.get("name", ["événement"] * len(df)))]
    return pd.DataFrame(rows).sort_values("time").reset_index(drop=True) if rows else pd.DataFrame(columns=["time", "name"])


def fetch_fred_releases(api_key: str, start: str, end: str, get: Callable[[str], str] = _get) -> pd.DataFrame:
    """Dates de publication FRED (clé GRATUITE fournie par l'utilisateur, passée en argument, jamais journalisée). Heures non fournies : 12:30 UTC par défaut pour les publications US du matin, MARQUÉ comme hypothèse."""
    q = urllib.parse.urlencode({"api_key": api_key, "file_type": "json", "realtime_start": start, "realtime_end": end, "include_release_dates_with_no_data": "true", "limit": 1000})
    data = json.loads(get(f"https://api.stlouisfed.org/fred/releases/dates?{q}"))
    if "release_dates" not in data:
        raise ValueError("FRED : réponse inattendue (clé invalide ?)")
    return pd.DataFrame({"time_utc": [f"{r['date']}T12:30:00Z" for r in data["release_dates"]], "name": [r.get("release_name", "FRED") for r in data["release_dates"]], "importance": "à vérifier"})
