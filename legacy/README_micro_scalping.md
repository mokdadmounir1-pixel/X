# Micro-Scalping Strategy

Stratégie de micro-scalping (timeframe 1 min) avec moteur de backtest, conçue
pour enchaîner une centaine de trades avec une gestion du risque stricte.

## Logique de la stratégie

- **Filtre de tendance** : EMA9 vs EMA21. On ne prend que des trades dans le
  sens de la tendance (long si EMA9 > EMA21, short si EMA9 < EMA21).
- **Déclencheur d'entrée** : repli (pullback) confirmé par le RSI(7) qui
  ressort de la zone survente/surachat (30/70), pendant que le prix est
  encore du côté "pullback" de la bande de Bollinger médiane (20, 2σ). On
  entre donc sur un retour dans le sens de la tendance, pas sur un simple
  croisement brut.
- **Filtre de volatilité** : les bougies dont l'ATR relatif est trop faible
  sont ignorées (marché plat = pas de trade, pour éviter le bruit).
- **Gestion du risque** : stop-loss et take-profit dynamiques basés sur
  l'ATR (SL = 1.2×ATR, TP = 2×ATR, ratio gain/risque ≈ 1.67:1), taille de
  position calculée pour risquer un % fixe du capital par trade, cooldown
  entre deux trades, limite de trades/jour, frais + slippage modélisés.

Tous les paramètres sont centralisés dans `micro_scalping/config.py`
(`ScalpingConfig`).

## Structure du code

```
micro_scalping/
  indicators.py    # EMA, RSI, ATR, Bollinger Bands
  config.py        # ScalpingConfig (tous les paramètres réglables)
  strategy.py       # ajout des indicateurs + génération du signal d'entrée
  backtester.py     # moteur : ouverture/fermeture de position, équité, trades
  stats.py          # win rate, profit factor, drawdown, etc.
  data_loader.py    # données Binance via ccxt, ou données synthétiques
run_backtest.py      # point d'entrée CLI
```

## Utilisation

```bash
pip install -r requirements.txt

# Backtest sur données synthétiques (aucune clé API requise)
python run_backtest.py --bars 60000 --trades 100

# Backtest sur données réelles Binance (BTC/USDT, 1 minute)
python run_backtest.py --live-data --symbol BTC/USDT --timeframe 1m --bars 5000 --trades 100
```

Le script s'arrête dès que `--trades` trades ont été clôturés (100 par
défaut) et affiche : win rate, profit factor, PnL net, drawdown max, et le
détail des 10 derniers trades.

## Avertissement important

- Les données synthétiques (`generate_synthetic_ohlcv`) sont une marche
  aléatoire pure : **aucune stratégie technique n'a d'edge réel dessus**.
  Elles servent uniquement à valider que le moteur (signaux, SL/TP, frais,
  stats) fonctionne correctement, pas à prouver la rentabilité de la
  stratégie. Testez avec `--live-data` sur de l'historique réel pour évaluer
  la performance.
- Avant tout passage en réel : backtestez sur plusieurs mois de données
  réelles multi-actifs, faites du forward-testing en paper trading, et ne
  risquez jamais plus que ce que vous pouvez perdre. Le micro-scalping est
  très sensible aux frais/slippage — vérifiez que votre exchange/courtier
  offre des frais assez bas pour que la stratégie reste rentable après coûts.
