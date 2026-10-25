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
| Orchestrateur IA (`ai/`), boucle d'amélioration (`improvement/`) | écrits, testés avec de faux adaptateurs, **non branchés** au runtime, jamais appelés avec de vraies clés |
| Crypto (Coinbase) | connecteur de **données et de simulation** en lecture seule (API publique, sans clé) ; spec `crypto_paper_v1` en PAPER ; aucun ordre vers Coinbase ; **aucune validation, coûts = hypothèses** |
| Simulation PAPER (13 stratégies sur MT5) | `scripts/paper_all.py`, trades simulés sur prix réels, jamais d'approbation lue |

Le faux terminal MT5 (`tests/fake_mt5_live.py`) et le générateur synthétique (`tests/synthetic.py`) n'existent **que dans `tests/`** :
le produit ne génère aucune donnée de remplacement (le CLI exige une source explicite).

## Résultats de recherche (tous négatifs jusqu'ici)
- `baseline_v0/v1`, `v2_calibrated`, `mtf_v3` : aucun PASS ; le positif de l'or est le bêta haussier du marché.
- `battery_v1` : aucun survivant (Reality Check p = 0,076).
- `inst_strategies_v1` (13 essais) : tous FAIL. Meilleur : USTEC orb +0,075 R, PF 1,31, échoue à l'espérance, au test nul et au DSR.
- `battery_backward_v1` (6 essais, 13 ans d'H1) : tous REJETÉS (p = 0,93). `backward_v1` (13 stratégies figées sur 10 mois antérieurs) : 13 FAIL ; USTEC orb le plus proche (+0,166 R, p = 0,026, même signe qu'en recherche) : à surveiller, non confirmé.
- `smc_v1b` (SMC OB+FVG H1, cible structurelle >= 3 R, 3 essais ; la 1re exécution smc_v1 est invalide : bug du FVG baissier) : 3 FAIL (EURUSD -0,114 R, USTEC -0,075 R, or +0,098 R dont les achats +0,22 R = bêta de l'or). Les réglages stricts donnent 4 à 8 trades en 2,5 ans : non testables.
- Budget d'essais déclaré : 80 ; consommés : 73.
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
  ui/          interface locale 127.0.0.1, LECTURE SEULE : résultats, rejeu, onglet « En direct » (état du runtime via QUANTBOT_STATE)
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
IA (optionnelle, non branchée) : `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GEMINI_API_KEY`.
