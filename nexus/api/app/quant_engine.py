"""Backtest de démonstration, Python pur. Données SYNTHÉTIQUES : aucune valeur de marché,
aucun edge attendu. Sert à prouver la chaîne (données versionnées → stratégie → frais → rapport)."""
from __future__ import annotations
import math, random
from .canon import sha256_hex

DRIFT, VOL = 0.0, 0.01


def make_prices(seed: int, bars: int) -> list[float]:
    rng = random.Random(seed)
    p, out = 100.0, []
    for _ in range(bars):
        p *= math.exp(DRIFT - 0.5 * VOL * VOL + VOL * rng.gauss(0, 1))
        out.append(round(p, 6))
    return out


def dataset_csv(prices: list[float]) -> str:
    return "bar,close\n" + "\n".join(f"{i},{c}" for i, c in enumerate(prices)) + "\n"


def dataset_sha(prices: list[float]) -> str:
    return sha256_hex(dataset_csv(prices))


def _sma(prices, n):
    out, s = [None] * len(prices), 0.0
    for i, p in enumerate(prices):
        s += p
        if i >= n:
            s -= prices[i - n]
        if i >= n - 1:
            out[i] = s / n
    return out


def backtest(prices: list[float], fast: int, slow: int, fee_bps: float, slippage_bps: float) -> dict:
    """Long seul. Signal calculé à la clôture de la barre t, position tenue sur la barre t+1 (pas d'anticipation).
    Coût par changement de position : (frais + glissement) en points de base, à l'entrée et à la sortie."""
    f, s = _sma(prices, fast), _sma(prices, slow)
    cost = (fee_bps + slippage_bps) / 10_000.0
    equity, peak, max_dd = 1.0, 1.0, 0.0
    pos, trades, cur, fees_paid = 0, [], None, 0.0
    curve = [1.0]
    for t in range(1, len(prices)):
        sig = 1 if (f[t - 1] is not None and s[t - 1] is not None and f[t - 1] > s[t - 1]) else 0
        r = prices[t] / prices[t - 1] - 1.0
        if sig != pos:
            equity *= (1 - cost)
            fees_paid += cost
            if sig == 1:
                cur = equity
            else:
                trades.append(equity / cur - 1.0)
                cur = None
            pos = sig
        if pos == 1:
            equity *= (1 + r)
        curve.append(equity)
        peak = max(peak, equity)
        max_dd = max(max_dd, 1 - equity / peak)
    if pos == 1 and cur is not None:
        trades.append(equity / cur - 1.0)
    wins = [x for x in trades if x > 0]
    losses = [x for x in trades if x <= 0]
    gross_w, gross_l = sum(wins), -sum(losses)
    return {
        "net_return_pct": round((equity - 1) * 100, 3),
        "buy_hold_pct": round((prices[-1] / prices[0] - 1) * 100, 3),
        "trades": len(trades),
        "win_rate_pct": round(100 * len(wins) / len(trades), 2) if trades else None,
        "profit_factor": round(gross_w / gross_l, 3) if gross_l > 0 else None,
        "expectancy_pct_per_trade": round(100 * sum(trades) / len(trades), 4) if trades else None,
        "max_drawdown_pct": round(max_dd * 100, 3),
        "cost_drag_pct_of_equity": round(fees_paid * 100, 3),
    }


def split_backtests(prices, fast, slow, fee_bps, slippage_bps, ratio=0.7) -> dict:
    cut = int(len(prices) * ratio)
    return {
        "full": backtest(prices, fast, slow, fee_bps, slippage_bps),
        "first_70pct": backtest(prices[:cut], fast, slow, fee_bps, slippage_bps),
        "last_30pct": backtest(prices[cut:], fast, slow, fee_bps, slippage_bps),
    }


def report_markdown(meta: dict, metrics: dict) -> str:
    m = metrics["full"]
    rows = "\n".join(
        f"| {k} | {metrics[k]['net_return_pct']} % | {metrics[k]['trades']} | {metrics[k]['profit_factor']} | "
        f"{metrics[k]['max_drawdown_pct']} % |" for k in ("full", "first_70pct", "last_30pct"))
    return f"""# Rapport de backtest de démonstration — MODE SIMULATION

> **Ceci n'est pas une stratégie validée.** Données synthétiques générées par un tirage aléatoire sans tendance :
> aucun résultat positif ne peut être attribué à un avantage réel. Cette exécution prouve la chaîne, pas un rendement.

## Provenance
- Jeu de données : `{meta['dataset_name']}` version `{meta['dataset_version']}` — SHA-256 `{meta['sha256']}`
- Génération : mouvement brownien géométrique, graine {meta['seed']}, {meta['bars']} barres, dérive {DRIFT}, volatilité {VOL}/barre
- Stratégie : croisement de moyennes mobiles simples {meta['fast']}/{meta['slow']}, long seul

## Hypothèses
- Frais : {meta['fee_bps']} pb et glissement : {meta['slippage_bps']} pb, appliqués à chaque entrée et chaque sortie
- Signal à la clôture de t, position tenue sur t+1 ; une seule position ; pas d'effet de levier ni de swap
- Aucun paramètre n'a été optimisé : les 30 % finaux ne sont pas utilisés pour choisir quoi que ce soit

## Résultats
| Période | Rendement net | Trades | Facteur de profit | Drawdown max |
|---|---|---|---|---|
{rows}

- Achat-conservation sur la période complète : {m['buy_hold_pct']} %
- Coûts cumulés (part de l'équité) : {m['cost_drag_pct_of_equity']} %
- Taux de réussite : {m['win_rate_pct']} % — espérance par trade : {m['expectancy_pct_per_trade']} %

## Lecture
Sur une marche aléatoire sans dérive, l'espérance avant frais est nulle ; après frais elle est négative en moyenne.
Un facteur de profit supérieur à 1 ici serait du hasard. Utiliser de vraies données historiques versionnées,
une période hors échantillon et plusieurs graines avant toute conclusion.
"""
