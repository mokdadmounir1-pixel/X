# quantbot

Bot de trading quantitatif **isolé** (aucun import de Nexus, de `ftmo_algo`, de `micro_scalping` ni de `fx_liquidity_bot`).
Principe : **un seul moteur** pour le backtest, le paper et la démo ; des setups à **logique floue** (scores continus, tolérances réglables) ;
une validation qui punit le nombre d'essais ; **aucune donnée ni aucun résultat inventé**.

## État réel (à jour)

| Élément | État |
|---|---|
| Moteur unique, risque, garde-fou FTMO 2-Step 100k | écrit et testé (216 tests) |
| Laboratoire de validation (DSR, test nul, Monte-Carlo, registre chaîné, tranche verrouillée) | écrit et testé |
| Données réelles MT5 (EURUSD, XAUUSD, USTEC en M15) | exportées par l'utilisateur ; empreintes dans `data/real/PROVENANCE.json` |
| **Edge de trading prouvé** | **AUCUN** : 73 essais préenregistrés, 0 PASS (voir `reports/`) |
| Tranche verrouillée de 12 mois | **jamais lue** |
| `quantbot/live/` (runtime MT5 : journal préalable, coupe-circuit, broker durci, approbations) | écrit ; **jamais exécuté d'ordre sur un terminal réel**. Seul un diagnostic en lecture seule (C1) a tourné sur un vrai terminal démo ; il a révélé des défauts, corrigés ensuite et testés uniquement sur un faux terminal de test |
| Contrôle de risque actif (`risk/active.py`) | perte journalière latente, freinage par drawdown, arrêt sur dérive / volatilité, Kelly plafonné ; câblé au moteur, **désactivé par défaut** |
| Orchestrateur IA (`ai/`), boucle d'amélioration (`improvement/`) | écrits, testés avec de faux adaptateurs, **non branchés** au runtime, jamais appelés avec de vraies clés |
| Crypto (Coinbase) | connecteur de **données et de simulation** en lecture seule (API publique, sans clé) ; spec `crypto_paper_v1` en PAPER ; aucun ordre vers Coinbase ; **aucune validation, coûts = hypothèses** |
| Synchronisation auto des données | `python -m quantbot ui` lance un thread (lecture seule) : Coinbase public -> `data/crypto/`, MT5 -> `data/live/` si un terminal démo est joignable ; état dans l'onglet Système (`data/sync_status.json`) ; `--no-sync` pour couper |
| Simulation PAPER (13 stratégies sur MT5) | `scripts/paper_all.py`, trades simulés sur prix réels, jamais d'approbation lue |

Le faux terminal MT5 (`tests/fake_mt5_live.py`) et le générateur synthétique (`tests/synthetic.py`) n'existent **que dans `tests/`** :
le produit ne génère aucune donnée de remplacement (le CLI exige une source explicite).

## Résultats de recherche (tous négatifs jusqu'ici)
- `baseline_v0/v1`, `v2_calibrated`, `mtf_v3` : aucun PASS ; le positif de l'or est le bêta haussier du marché.
- `battery_v1` : aucun survivant (Reality Check p = 0,076).
- `inst_strategies_v1` (13 essais) : tous FAIL. Meilleur : USTEC orb +0,075 R, PF 1,31, échoue à l'espérance, au test nul et au DSR.
- `battery_backward_v1` (6 essais, 13 ans d'H1) : tous REJETÉS (p = 0,93). `backward_v1` (13 stratégies figées sur 10 mois antérieurs) : 13 FAIL ; USTEC orb le plus proche (+0,166 R, p = 0,026, même signe qu'en recherche) : à surveiller, non confirmé.
- `smc_v1b` (SMC OB+FVG H1, cible structurelle >= 3 R, 3 essais ; la 1re exécution smc_v1 est invalide : bug du FVG baissier) : 3 FAIL (EURUSD -0,114 R, USTEC -0,075 R, or +0,098 R dont les achats +0,22 R = bêta de l'or). Les réglages stricts donnent 4 à 8 trades en 2,5 ans : non testables.
- `ml_v1` / `ml_v1b` (LightGBM walk-forward purgé, features fracdiff/GK/entropie/Amihud, seuil P >= 0,65, M15 à 8 barres) : 6 FAIL. AUC hors-échantillon 0,51-0,53 (signal minuscule), espérance nette ~0 : EURUSD -0,001 R, XAUUSD -0,041 R, USTEC +0,035 R (p = 0,23). `ml_v1` USTEC (-2,29 R) venait d'un défaut du simulateur (marché figé, risque quasi nul), amendé avant relance.
- `pairs_v1` (stat-arb BTC/ETH) : écrit et préenregistré, **pas encore exécuté** (données Coinbase à récupérer ; le terminal les synchronise désormais seul).
- `gold_quant_v1` (5 stratégies de scalping sur l'or, M15, 07-17 UTC : balayage de liquidité, cassure d'Asie, repli EMA, compression, retour à la moyenne) : 5 FAIL ; la seule positive (repli EMA, +0,026 R) est un profil de bêta haussier.
- `portfolio_v1` (les 22 combinaisons stratégie x instrument combinées, poids causaux, ciblage de volatilité) : 2 FAIL, R/jour -0,04 et -0,03 ; corrélations ~0 mais aucune espérance à diversifier.
- `gold_winrate_v1b` (9 variantes à cible rapprochée / stop éloigné sur l'or) : 9 FAIL ; des taux de réussite de 62-63 % existent mais avec un R:R réalisé de 0,5 (seuil d'équilibre 66-67 %) donc perdants. Meilleur : +0,05 R. (`gold_winrate_v1` invalide : réglage min_reward_risk, 0 trade.)
- Budget d'essais déclaré : 120 (relevé de 80 le 2026-10-25, avant les essais stat-arb/ML/VWAP ; le DSR compte tous les essais) ; consommés : 104.
Les rapports sont dans `reports/` (JSON + logs) et l'interface locale les affiche.

## Arborescence
```
quantbot/
  core/        MOTEUR UNIQUE (on_bar), labels, calibration
  data/        validation OHLCV, CSV, mt5.py (horloge courtier, trous, coûts), mtf.py
  indicators/  patterns/  signals/  strategies/     détection floue et stratégies à événements causaux
  risk/        sizing, limites, garde-fou FTMO, calendrier
  execution/   interface Broker + PaperBroker (aucun envoi d'ordre)
  live/        runtime MT5 : état (SQLite), coupe-circuit, flux de barres, HardenedMT5Broker, approbations, runner
  lab/         statistiques, registre d'essais, tranche verrouillée, portes, pipeline
  ai/ improvement/ memory/                          non branchés (voir ci-dessus)
  ui/          couche de données de l'interface (état, simulations, rejeu)
  gui/         terminal FastAPI + interface sombre (127.0.0.1, LECTURE SEULE) : trades & attribution, marché (zones OB/FVG), backtests, risque, recherche, système
specs/         spécifications PRÉENREGISTRÉES, commitées AVANT chaque exécution
scripts/       exécution des specs, diagnostics, export MT5 en lecture seule
docs/prompts/  prompts pour ChatGPT (export MT5, connexion au terminal réel, protocole de liaison)
```

## Garanties et limites
- **Un moteur.** Signal à la clôture de t, exécution à l'ouverture de t+1, stop prioritaire, gap exécuté à l'ouverture, trous de données gérés.
- **Pas de look-ahead** : testé en altérant le futur.
- **Horloge MT5** : reconstruite depuis `time_broker_epoch` (UTC+2 hiver / UTC+3 été, calendrier européen). Les 1-2 h autour des changements d'heure restent ambiguës.
- **Coûts** : un spread nul n'est jamais pris pour un coût nul ; hypothèses déclarées dans les specs, à re-mesurer sur le compte cible.
- **Statistiques** : le DSR compte tous les essais (registre chaîné par hachage) ; lire la tranche verrouillée est un essai de plus, une fois par spec.
- **Live** : OBSERVATION (paper sur barres réelles, aucun ordre) par défaut ; DEMO_ACTIF exige une approbation humaine liée au hachage de la spec et un coupe-circuit inactif ; le réel / FTMO est une décision humaine, jamais automatique.
- Limites connues non mesurées : fuseau et fraîcheur des ticks en séance ouverte, remplissages réels, glissement, swaps.

## Utilisation
```bash
pip install -r requirements.txt && python -m pytest -q
python -m quantbot ui                                    # interface locale (lecture seule)
python -m quantbot audit-data --mt5-csv data/real/EURUSD_M15.csv
python scripts/run_strategies.py specs/inst_strategies_v1.json
```
IA (optionnelle, non branchée) : exclusivement Claude (`ANTHROPIC_API_KEY`), ChatGPT (`OPENAI_API_KEY`) et Hermes (modèle LOCAL via un serveur Ollama-compatible sur 127.0.0.1, sans clé).
