# Forex Liquidity Sweep + Displacement + FVG bot

Bot de micro-scalping Forex (Smart Money Concepts) qui scanne plusieurs
paires en parallèle avec la **même** logique de setup et sélectionne au
maximum `max_trades_per_day` (10 par défaut) des meilleurs setups par jour
— jamais forcés.

Paires par défaut : EUR/USD, GBP/USD, USD/JPY, AUD/USD, USD/CAD, USD/CHF, NZD/USD.

## Pipeline

```
DATA -> REGIME -> LIQUIDITY -> SWEEP -> DISPLACEMENT -> FVG -> MOMENTUM -> SCORE -> RISK -> TRADE
```

Chaque paire est pilotée par une machine à états (`engine/pair_engine.py`,
classe `PairSignalEngine`) qui avance bougie par bougie :

`idle -> pending_sweep -> pending_displacement -> pending_fvg -> pending_retest -> (accepté ou rejeté) -> idle`

1. **Régime** (`core/regime.py`) : pente de l'EMA50 + ADX(14) ⇒ `up` / `down` / `range`.
2. **Liquidité** (`core/liquidity.py`) : pool de niveaux non "consommés" —
   swing highs/lows (fractals confirmés sans anticipation), plus haut/bas de
   la session précédente (Sydney/Tokyo/Londres/New York en UTC), plus
   haut/bas de la veille, et un plus haut/bas glissant sur N bougies comme
   source dynamique supplémentaire.
3. **Sweep** : détection d'un dépassement (`breach`) d'un niveau de
   liquidité, puis réintégration en dedans du niveau dans une fenêtre de
   confirmation configurable. Pas de réintégration = pas de signal, et le
   niveau reste "swept" (consommé) pour ne pas re-déclencher en boucle.
4. **Displacement** : bougie(s) qualifiées par taille de corps relative à
   l'ATR, ratio corps/range, et cassure d'une structure locale récente.
5. **FVG** : recherche du gap 3-bougies formé pendant le displacement, puis
   attente du retour du prix dans la zone (avec délai maximal configurable).
6. **Momentum** : filtre RSI + bougie de rejet à l'entrée dans la FVG.
7. **Score /100** : moyenne pondérée (poids configurables dans
   `ScoreWeights`) de la qualité du sweep, du displacement, de la FVG, de
   l'alignement au régime, de la volatilité, du momentum, de la distance à
   la prochaine liquidité, du RR et du spread. Seuil par défaut : 80.
8. **SL/TP** : SL = extrême du sweep ± tampon ATR. TP = prochaine liquidité
   opposée, sinon structure opposée, sinon un objectif RR minimum plafonné
   (jamais un TP fixe universel). Si aucun objectif ne satisfait le RR
   minimum, le trade est rejeté (`rr_unreachable`).

## Multi-devises et sélection quotidienne

`engine/scanner.py` (`PortfolioScanner`) fait tourner les 7 moteurs sur une
horloge chronologique commune. Quand plusieurs setups apparaissent au même
instant, ils sont classés par score et pris dans cet ordre tant que la
capacité du risk manager le permet. Le bot ne complète jamais artificiellement
jusqu'à 10 trades : s'il n'y a que 4 setups valides dans la journée, il ne
prend que 4 trades.

## Gestion du risque (`engine/risk_manager.py`)

Aucune martingale : le sizing est toujours un % fixe de l'équité **courante**,
jamais augmenté après une perte.

- `risk_per_trade_pct` : % du capital risqué par trade
- `max_daily_loss_pct` : coupe les nouvelles entrées pour le reste de la
  journée une fois la perte quotidienne atteinte
- `max_trades_per_day` : 10 par défaut
- `max_concurrent_trades` : positions simultanées max
- `max_consecutive_losses` : pause pour le reste de la journée après N pertes d'affilée
- `max_drawdown_pct` : coupe-circuit **permanent** sur le run si le drawdown
  depuis le plus haut d'équité est atteint (aucune tentative de "se refaire")
- `max_spread_pips` (par paire) : rejette le setup si le spread est trop élevé

## Utilisation

```bash
pip install -r requirements.txt

# Backtest sur données synthétiques (aucune donnée réelle requise, sert à valider le moteur)
python run_fx_backtest.py --bars 60000

# Backtest sur données réelles : un CSV par paire (colonnes time,open,high,low,close[,volume,spread_pips])
python run_fx_backtest.py --data-dir ./historical_data

# Avec walk-forward chronologique et Monte-Carlo sur la séquence de trades
python run_fx_backtest.py --data-dir ./historical_data --walk-forward --monte-carlo

# Export du journal complet (tous les signaux, y compris rejetés) et des trades
python run_fx_backtest.py --journal-csv journal.csv --trades-csv trades.csv
```

Le journal (`fx_liquidity_bot/journal.py`) trace **chaque** étape franchie ou
échouée pour chaque paire (`breach_detected`, `no_reintegration`,
`no_displacement`, `no_fvg`, `fvg_not_retested`, `momentum_filter_failed`,
`counter_trend_*`, `spread_too_high`, `rr_unreachable`,
`score_below_threshold`, `daily_trade_cap_reached`, etc.), pour comprendre
précisément pourquoi le bot entre ou n'entre pas.

## Backtest : ce qui est implémenté

- Coûts inclus : spread (typique par paire, ou colonne `spread_pips` fournie
  dans le CSV), commission par lot, slippage à l'entrée et à la sortie.
- Métriques (`backtest/metrics.py`) : win rate, profit factor, expectancy,
  rendement, drawdown max, Sharpe (annualisé sur PnL quotidien), nombre de
  trades, gain/perte moyens, plus longue série de pertes.
- Breakdown (`backtest/breakdown.py`) : par paire, par heure, par session,
  par jour de semaine, par régime, par direction.
- Walk-forward (`backtest/walkforward.py`) : découpage chronologique en
  folds successifs, réévalués indépendamment avec la même config — vérifie
  que la performance ne dépend pas d'une seule fenêtre. **Ce n'est pas un
  ré-optimiseur de paramètres** : c'est un point d'extension pour en brancher un.
- Monte-Carlo (`backtest/montecarlo.py`) : rééchantillonnage (bootstrap) de
  la séquence de PnL des trades pour estimer la distribution du rendement
  final et du drawdown max.

## Performance

Le moteur traite les bougies une par une (nécessaire pour la machine à états
sweep→displacement→FVG→retest et pour appliquer les limites de risque sans
biais d'anticipation), pas de façon vectorisée. À titre indicatif : environ
200 secondes pour 60 000 bougies M1 × 7 paires sur cette machine. Un backtest
multi-années sur M1 peut donc prendre plusieurs dizaines de minutes — pour
itérer plus vite pendant le réglage des paramètres, testez d'abord sur une
fenêtre plus courte ou un timeframe plus grand (M5/M15 via votre propre
rééchantillonnage), puis validez la version finale sur l'historique complet.

## Limites connues / avertissements

- **Aucune donnée de marché réelle n'est fournie.** `--bars` sans
  `--data-dir` génère une marche aléatoire synthétique avec des ruptures
  injectées périodiquement, uniquement pour vérifier que tout le pipeline
  (sweep → displacement → FVG → retest → score → risk → trade) fonctionne
  de bout en bout. **Aucune conclusion de rentabilité ne doit être tirée de
  ces résultats.** Fournissez vos propres CSV M1 (ou autre timeframe) réels
  via `--data-dir` pour un vrai backtest.
- Le pipeline travaille sur OHLCV, pas sur des données tick : le spread est
  approximé par une valeur typique par paire (ou une colonne `spread_pips`
  si vous la fournissez), pas par un vrai bid/ask tick par tick. Le
  paramètre `spread_pips` dans les CSV est le point d'extension prévu si
  vous disposez de données tick.
- Une seule "recherche de setup" active à la fois par paire (le moteur ne
  traque pas plusieurs sweeps candidats en parallèle sur la même paire).
- **Jamais de passage en réel automatique.** Backtestez, validez en walk
  forward / Monte-Carlo, puis passez en paper trading avant tout capital réel.
