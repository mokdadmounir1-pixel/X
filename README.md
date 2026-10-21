# QuantLab — recherche, paper-trading et dashboard de scalping

```bash
pip install -r requirements.txt
python -m quantlab install                 # installe + smoke-teste ~30 projets open source (pip + clones git dans vendor/)
python -m quantlab research --ccxt BTC/USDT --bars 30000   # données réelles ; sans --ccxt : synthétique (signalé)
python -m quantlab dashboard --port 8767 --ccxt BTC/USDT   # http://127.0.0.1:8767
python -m pytest -q tests
```

## Ce qui est construit
- `quantlab/engine.py` : backtest pessimiste (signal à la clôture -> fill à l'ouverture suivante, stop prioritaire si stop+cible dans la même bougie, frais+spread+slippage, levier plafonné, plafond de trades/jour, arrêt sur perte journalière).
- `quantlab/strategies/` : 8 algos (ema_pullback, bb_reversion, vwap_reversion, squeeze_breakout, momentum_burst, liquidity_sweep, regime_router, ml_direction walk-forward). Un test vérifie que chacun est causal (pas de look-ahead).
- `quantlab/research.py` : protocole anti-illusion. Un algo n'est **PASS** que s'il passe 7 portes : >=60 trades OOS, espérance OOS>0, PF>1.15, bat un marché nul (block-bootstrap, p<0.10), survit à 2x les frais, Monte-Carlo p5>capital, pas porté par 3 trades.
- `quantlab/live.py` + `dashboard/` : paper-trading multi-agents (1 algo = 1 agent) rejouant le même moteur, vortex animé piloté par les métriques réelles (ω = vol courte/longue, étirement = force de tendance, ordre = accord des agents, couleur = direction), chandeliers + entrées, tape, verdicts de recherche, état des outils installés, suivi d'objectif de session.
- `quantlab/tools/` : registre de 31 projets (ccxt, vectorbt, backtesting.py, hftbacktest, freqtrade, nautilus_trader, py-clob-client Polymarket, quantstats, optuna, hmmlearn, lightgbm, arch, ...).
- Les anciens dossiers `micro_scalping/` et `fx_liquidity_bot/` sont conservés intacts.

## Lecture honnête des résultats
Sur données synthétiques, **tous les algos sont FAIL** : c'est normal (le coût aller-retour ~0.12 % est de l'ordre de la taille d'un stop de 1 minute). Seule une exécution `research` sur vos vraies données (`--ccxt` ou `--csv`) dit quelque chose d'exploitable. Ce conteneur n'a pas accès aux exchanges, donc rien n'y a été validé sur marché réel. Ne passez en réel qu'après PASS/WATCH stables sur plusieurs mois et plusieurs actifs, puis du paper trading.

---

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
