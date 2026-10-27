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
| Synchronisation auto des données | `python -m quantbot ui` (ou `lancer_terminal.bat`) lance un thread (lecture seule) : Coinbase public -> `data/crypto/` ; MT5 (terminal démo ouvert et connecté sur le PC) -> `data/live/` en M1/M5/M15/H1 sur XAUUSD, XAGUSD, EURUSD, USTEC, DXY si disponibles (historique initial jusqu à 50 000 barres) + instantanés de PROFONDEUR du carnet XAUUSD toutes les 2 s (`data/live/depth/`, si le courtier les expose) pour un vrai OFI ; état dans l'onglet Système (`data/sync_status.json`) ; `--no-sync` pour couper |
| Microstructure (`order_flow_ofi.py`) | OFI de Cont-Kukanov-Stoikov sur VRAIES tailles bid/ask (aucune sur MT5 CFD : non utilisable en l'état) ; proxys de flux par ticks et d'absorption par barres, nommés comme tels ; un iceberg est invisible par construction |
| GEX / gamma des teneurs de marché (`strategies/dealer_gex.py`) | calcul réel (gamma de Black-76, niveau de gamma nul, score G, fusion avec APEX) **sur une chaîne d'options RÉELLE à fournir** (open interest par strike : `data/options/GC_chain_<date>.csv`) ; sans fichier, aucun signal, aucun GEX inventé ; **jamais backtesté** (aucun historique d'OI) |
| Données externes gratuites + surcouche de risque | `data/external.py` (COT or de la CFTC avec disponibilité décalée de 3 jours, calendrier macro FRED si clé gratuite `FRED_API_KEY`, sinon NFP régulier ; aucune date FOMC/CPI devinée) collectées par la synchronisation ; `risk/overlay.py` : multiplicateur CONTINU qui ne fait que RÉDUIRE la taille (abstention douce ±15 min autour des annonces, réduction quand la queue de pertes récente s'élargit), actif dans la simulation PAPER (`--no-overlay` pour couper), désactivé dans les backtests/specs (identités d'essais inchangées) ; schéma de l'API COT non vérifié en direct (réseau fermé côté développement) |
| Simulation PAPER (toutes les stratégies à règles figées sur MT5 : 13 + SMC + 5 scalping or + APEX + stop-hunt) | `scripts/paper_all.py --spec <plusieurs specs>`, trades simulés sur prix réels, jamais d'approbation lue |

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
- `apex_pullback_v1` (APEX PULLBACK ALPHA : score de similarité S >= 0,75, taille continue, stop 1,5 ATR, cible 2,6 R, or M15) : FAIL, +0,024 R (achats +0,08 R, ventes -0,05 R : bêta de l'or).
- `stop_hunt_v1` (balayage de réservoir de liquidité + retour, or M15) : FAIL, +0,06 R (achats +0,13 R, ventes -0,03 R : bêta de l'or). Lead-lag EURUSD->or mesuré (sans essai) : corrélation simultanée 0,32, à un lag de 15 min 0,007 : aucune avance exploitable.
- `apex_levels_v1` (APEX pondéré par la proximité aux chiffres ronds et aux nœuds de volume, proxy qui n'est PAS un GEX) : FAIL, +0,016 R.
- `mtf_confluence_v1` (analyse descendante D1/H4/H1/M15, confluence continue par moyenne géométrique, or) : FAIL mais le meilleur de la série or : +0,113 R, PF 1,25, 301 trades (achats +0,116 R, ventes +0,093 R) ; sous le seuil de 0,15 R, test nul non rejeté. Suivi en simulation PAPER.
- `alpha_miner_v1` (extraction rétrospective : 4 314 trades de l'or, jeu de données causal avec MFE/MAE, LightGBM + importance par permutation + test nul + règles à seuil corrigées Bonferroni, jugées sur la période la plus récente) : verdict RIEN (AUC hors-échantillon 0,527 < 0,53 préenregistré ; la seule règle « retenue », écarter les trades contre une forte tendance H1 baissière, ne tenait pas dans la période d'apprentissage : à ne pas appliquer). Aucune règle n'est jamais appliquée automatiquement.
- `stop_hunt_v2` (asymétrie achat/vente corrigée + variantes VENTES SEULES et INVERSÉE) : 3 FAIL ; sur 2,5 ans les achats gagnent (+0,11 R) et les ventes perdent (-0,06 R). Les 3 variantes tournent séparément en simulation PAPER.
- `stop_hunt_v3` : variante ACHATS SEULS du stop-hunt corrigé, post-hoc, **simulation PAPER uniquement** (aucun essai de recherche : rejouer sur les mêmes données répéterait +0,106 R sans indépendance) ; jugée sur >= 60 trades futurs contre l'achat-conservation de l'or.
- `il_svr_v1` (IL-SVR : balayage de la première heure + épuisement sur la bande ±2σ du VWAP + divergence de flux proxy, fenêtres UTC 08h-10h30 / 13h30-16h, indice Nasdaq M15) : FAIL, +0,002 R sur 89 trades. Registre de portefeuille FTMO simulé (compte unique 100 000 $, coupe-circuit global, `/api/ledger`, `/metrics`) ajouté.
- `cta_donchian_v1` (suivi de tendance : Donchian 20 barres H4 + tendance D1, or) : FAIL sur UNE seule porte (test nul) : 61 trades, +0,223 R, PF 1,86, 93 % d'achats dans un marché haussier = profil de bêta ; suivi en simulation PAPER. Corrections : verrous/état séparés par source (simulation MT5 et Coinbase en parallèle), `QUANTBOT_MT5_TERMINAL`, `lightgbm` dans requirements.
- Budget d'essais déclaré : 120 (relevé de 80 le 2026-10-25, avant les essais stat-arb/ML/VWAP ; le DSR compte tous les essais) ; consommés : 114.
Les rapports sont dans `reports/` (JSON + logs) et l'interface locale les affiche.

## Audit
Audit de performance sur les journaux réels : `python scripts/audit_performance.py` (espérance, facteur de profit, réussite vs seuil d'équilibre, Sharpe/Sortino par trade, drawdown, latence/glissement, ticks ; chaque condition de passage est OK / ÉCHEC / NON MESURÉ).
Voir `docs/AUDIT_2026-10-26.md` (défauts corrigés, demandes impossibles et pourquoi) et `docs/prompts/chatgpt_finalisation.md` (tâches PC).

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

## Lancer et vérifier (Windows)
**`lancer_terminal.bat` ou `lancer_tout.bat` : le terminal lance et RELANCE TOUT SEUL la simulation PAPER (MT5 + crypto) et la synchronisation des données** (`supervisor.py`, journaux `runtime/logs/`, état dans l'onglet Système > Processus automatiques ; `--no-workers` pour couper). `lancer_tout.bat` ajoute le pré-vol : pré-vol en clair de la connexion MT5 (`scripts/preflight.py` : [OK]/[ATTENTION]/[BLOQUANT] + quoi faire), puis simulation PAPER de toutes les stratégies sur les prix réels + interface. Aucun ordre n'est envoyé à MT5. Au premier lancement, `scripts/broker_profile.py` relève le profil de TON courtier (nom de l'or chez lui : GOLD, XAUUSD.a... ; contrat ; spread réel ; commission à fournir avec `--commission-per-lot-side`, jamais supposée nulle) dans `config/broker_profile.json`, et tout le reste s'y adapte (`live/symbols.py`).

## Banc d'essai (onglet Backtests)
Toutes les stratégies à règles (28) se rejouent sur TOUS les instruments qui ont un CSV M15 : `data/real`, `data/live` (synchronisé depuis MT5 : or, argent, EURUSD, USTEC, DXY, GBPUSD, USDJPY, USDCHF, AUDUSD, USDCAD, US500, US30, DE40, UK100, JP225, USOIL quand le courtier les propose ; noms du courtier détectés automatiquement) et `data/crypto`. Un instrument hors de la spec préenregistrée est rejoué en **EXPLORATION** (règles figées, coûts mesurés ou hypothèses déclarées, aucun essai compté, aucune validité statistique, bannière affichée).

## Utilisation
```bash
pip install -r requirements.txt && python -m pytest -q
python -m quantbot ui                                    # interface locale (lecture seule)
python -m quantbot audit-data --mt5-csv data/real/EURUSD_M15.csv
python scripts/run_strategies.py specs/inst_strategies_v1.json
```
IA (optionnelle, non branchée) : exclusivement Claude (`ANTHROPIC_API_KEY`) et ChatGPT (`OPENAI_API_KEY`). Hermes est supprimé : son rôle (routage d'automatisation) est tenu par Claude ; l'exécution locale sur le PC est faite par ChatGPT via le protocole de liaison.
