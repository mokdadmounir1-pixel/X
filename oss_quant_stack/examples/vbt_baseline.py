"""vectorbt : plomberie de backtest vectorisé sur des barres CSV (démonstration, PAS une validation).

    python examples/vbt_baseline.py chemin/vers/XAUUSD_M15.csv [--fees 0.00005] [--slippage 0.00002]

Lit un CSV MT5 de quantbot (colonnes time, open, high, low, close) ; coupe les 12 derniers mois (jamais lus) ; compare achat-conservation et un croisement EMA FIGÉ (20/50) avec frais.
Les paramètres sont fixes à dessein : balayer une grille ici serait du sur-ajustement. Aucun résultat de ce script n'est une preuve d'avantage.
"""
import argparse, sys

import pandas as pd
import vectorbt as vbt


def load(path: str) -> pd.DataFrame:
    df = pd.read_csv(path); df["time"] = pd.to_datetime(df["time"], utc=True); df = df.set_index("time").sort_index()
    return df[df.index <= df.index[-1] - pd.DateOffset(months=12)]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__); ap.add_argument("csv"); ap.add_argument("--fees", type=float, default=0.00005); ap.add_argument("--slippage", type=float, default=0.00002)
    a = ap.parse_args(argv); df = load(a.csv); close = df["close"]
    if len(close) < 500:
        print("Historique trop court après retrait des 12 derniers mois (moins de 500 barres) : rien à faire.", file=sys.stderr); return 2
    fast, slow = vbt.MA.run(close, 20, ewm=True), vbt.MA.run(close, 50, ewm=True)
    entries, exits = fast.ma_crossed_above(slow), fast.ma_crossed_below(slow)
    pf = vbt.Portfolio.from_signals(close, entries, exits, fees=a.fees, slippage=a.slippage, freq="15min", init_cash=100_000)
    bh = vbt.Portfolio.from_holding(close, freq="15min", init_cash=100_000)
    for name, p in (("EMA 20/50 (figé, frais inclus)", pf), ("achat-conservation", bh)):
        s = p.stats()
        print(f"{name}: rendement {s['Total Return [%]']:.1f} % | DD max {s['Max Drawdown [%]']:.1f} % | trades {int(s['Total Trades'])} | Sharpe {s['Sharpe Ratio']:.2f}")
    print("Démonstration de plomberie uniquement : aucune conclusion de trading.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
