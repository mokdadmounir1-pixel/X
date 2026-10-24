# quantbot

Bot de trading **autonome et isolé** (aucun lien avec le projet « Nexus », ni avec `micro_scalping/` / `fx_liquidity_bot/`).
Détection de patterns **tolérante** (heuristiques, scores de similarité), boucle d'**auto-amélioration contrôlée**,
paper trading et trading réel MT5 sous règles **FTMO 2-Step 100k**.

## Architecture (d'après les schémas fournis)

| Bloc du schéma | Module |
|---|---|
| Market Data (MT5, CSV, ccxt, synthétique) | `data/` |
| Features / indicateurs | `indicators/` |
| Reconnaissance de patterns (tolérance) | `patterns/` (candles, chart, harmonic, `tolerance.py`) |
| Signal Logic | `signals/engine.py` |
| Risk Management (+ règles FTMO) | `risk/manager.py`, `risk/ftmo.py` |
| Execution Layer (Broker Adapter paper / MT5) | `execution/broker.py` |
| Backtest | `backtest/` |
| Validation & Testing (60/20/20, coûts, walk-forward, robustesse) | `validation/validator.py` |
| Memory & Observability | `memory/store.py` (SQLite : expériences, trades, leçons) |
| Error Analysis + Reasoning Engine | `improvement/diagnosis.py` |
| Strategy Update (versions, approve/reject) | `improvement/loop.py` |
| Journal du trader / runner continu | `improvement/journal.py`, `improvement/runner.py` |
| AI Orchestrator (Claude, ChatGPT, Hermes) | `ai/` |

### IA : qui fait quoi
- **Claude** : raisonnement, hypothèses d'amélioration. **ChatGPT** : relecture critique. **Hermes** (local, API compatible OpenAI) : leçons du journal, repli hors-ligne. Repli automatique d'un modèle à l'autre ; sans IA, des règles déterministes prennent le relais.
- Les IA **ne proposent que des changements de paramètres** d'une liste blanche bornée (`PARAM_SPACE`). Aucun code généré n'est exécuté. Elles ne contournent ni la validation ni le risque.
- Gemini pourrait s'ajouter avec le même patron d'adaptateur ; non inclus.

### Patterns : tolérance
Chaque détecteur renvoie un **score 0..1**. `tolerance.tolerance_percentage` (écart accepté sans pénalité),
`deviation_threshold` (écart où le score tombe à 0) et `min_score` sont réglables. Les versions baissières viennent du miroir des prix.
Implémentés : 10 familles de chandeliers, double top/bottom, tête-épaules (+inversé), triangles, Gartley/Bat/Butterfly/Crab.
**Non implémentés** : wedges, pennants, scallop, diamond, cup & handle, island, rectangles, corridors.

## Utilisation
```bash
pip install -r requirements.txt && python -m pytest -q          # 102 tests
python -m quantbot init-config config/default.json
python -m quantbot scan|backtest|validate [--csv f.csv | --exchange binance | --mt5 EURUSD]
python -m quantbot improve --db bot.db [--use-ai]             # un cycle d'amélioration
python -m quantbot run-paper --db bot.db --improve-every 30   # trader paper qui apprend
python -m quantbot history --db bot.db
```
Clés IA via variables d'environnement : `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `HERMES_BASE_URL`/`HERMES_MODEL`.

## Règles FTMO 2-Step 100k (`ftmo` dans la config)
Objectif 10 % (Challenge) / 5 % (Vérification) · perte journalière max 5 % (reset minuit CE(S)T, flottant inclus) ·
perte totale max 10 % statique (equity ≥ 90 000 $) · 4 jours de trading minimum · pas de limite de temps.
**Ces valeurs viennent de sources secondaires : vérifiez-les sur ftmo.com, elles peuvent changer** (tout est configurable).

Le `FtmoGuard` agit **avant** les limites : tampons internes à 4 % (jour) et 8 % (total) → clôture + arrêt des entrées ;
limite dure atteinte → arrêt définitif ; risque par trade plafonné (0,5 % par défaut et marge restante) ;
flat avant le week-end (vendredi 20h Prague) ; fenêtres news configurables ; arrêt une fois l'objectif atteint et 4 jours faits.

## Passer en réel (MT5 / FTMO) — procédure
1. Windows + terminal MT5 connecté au compte FTMO (essai gratuit ou démo d'abord) ; `pip install MetaTrader5`.
2. Config : `execution.mode="live"`, `execution.allow_live=true`, `ftmo.enabled=true`, `ftmo.expected_login=<n° de compte>`,
   `execution.mt5_symbol` (coté en USD, ex. EURUSD), `execution.mt5_server_utc_offset_hours` (heure serveur → UTC).
3. `set QUANTBOT_ALLOW_LIVE=1` puis `python -m quantbot run-live --config live.json --db bot.db`.
4. En réel, une version validée par la boucle **n'est pas adoptée seule** : `python -m quantbot approve <version> --db bot.db`.

## Limites à connaître
- `MT5Broker` n'a été testé que contre un **faux module MT5** : aucun test sur un vrai terminal. Essayez-le d'abord sur un compte d'essai.
- Une seule position à la fois, un seul symbole, devise de cotation = devise du compte.
- Sur marché aléatoire (données synthétiques) la boucle rejette tout candidat : c'est attendu. Aucune performance n'est garantie ;
  « s'améliorer en continu » signifie ici *ne promouvoir que ce qui passe la validation*, pas une croissance exponentielle.
- La limite journalière FTMO utilise `max(balance, equity)` en début de jour (hypothèse prudente) ; le décalage horaire/DST du serveur MT5 doit être réglé à la main.
