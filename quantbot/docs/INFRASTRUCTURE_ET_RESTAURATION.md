# quantbot — infrastructure complète et restauration à l'identique

Version figée le 2026-10-28. Dépôt GitHub : `mokdadmounir1-pixel/X`, dossier `quantbot/`. Branche de travail : `claude/eager-davinci-8i7zsd` ; branche d'intégration : `claude/micro-scalping-strategy-fp4bly`. Le commit exact est dans `backup/COMMIT.txt` ; l'empreinte SHA-256 de chaque fichier est dans `backup/MANIFEST_sha256.txt`.

## 0. Où est « le code intégral » ?
Le code source complet (≈ 146 modules Python, ≈ 12 000 lignes de code produit, 62 fichiers de tests, 38 specs, 34 scripts) est dans le dépôt Git. Le coller dans un message serait illisible et sujet aux erreurs de copie : la sauvegarde exacte est faite par TROIS copies vérifiables par empreinte :
1. **Dépôt GitHub** (historique complet, toutes les versions).
2. **`backup/quantbot_full_history_2026-10-28.bundle`** : fichier Git unique contenant tout l'historique (se restaure sans internet).
3. **`backup/quantbot_source_2026-10-28.zip`** : instantané des fichiers du dossier `quantbot/` à ce commit.
Garde le .bundle ET le .zip dans un second endroit (disque externe, cloud personnel). Les données de marché (`data/`) ne sont PAS dans Git : voir §6.

## 1. Principe général
- **Un seul moteur** (`quantbot/backtest/engine.py`, `TradingEngine.on_bar`) pour backtest, PAPER et démo : signal calculé à la clôture de barre, exécution à l'ouverture suivante, priorité au stop.
- **Stratégies à événements causaux** (`quantbot/strategies/*`) : chaque module renvoie une liste d'`Event` (horodatage, sens, stop, cible, méta-confiance) calculée sans regarder l'avenir ; `EventSignalEngine` les sert au moteur. `strategies/build.py::events_for` est partagé par la recherche et le live.
- **Validation stricte** (`quantbot/lab/`) : spec préenregistrée AVANT toute exécution, registre d'essais chaîné par hachage (`reports/registry.jsonl`), portes (espérance, facteur de profit, test nul par inversion de signes, DSR sur tous les essais, Monte-Carlo, folds), tranche verrouillée de 12 mois jamais lue, échantillon avant-coup ≥ 60 trades.
- **Aucune donnée inventée.** Sans fichier réel, les modules de données externes ne produisent aucun signal.
- **Aucun ordre réel.** Mode PAPER par défaut ; l'envoi d'ordres démo exige une phrase d'autorisation écrite et une approbation signée (`docs/EXPLOITATION.md`).

## 2. Arborescence
```
quantbot/                      racine du projet (pyproject.toml, requirements*.txt, README.md)
  quantbot/                    package Python
    core/ indicators/ patterns/ signals/   détection floue (tolérances, scores continus)
    backtest/                  moteur unique, courbes, métriques
    risk/                      manager, active (garde-fou), overlay, ledger FTMO, var/EVT, tail_dependence
    lab/                       registre d'essais, portes, stats (DSR, sign-flip), tranche verrouillée
    strategies/                toutes les stratégies à événements + build.py + events.py
    stat/ ml/                  paires (Kalman), Avellaneda, vol_arb ; LightGBM walk-forward, RL tabulaire
    data/                      mt5 (CSV/horloge courtier), live_store (journal chaîné), autosync, coinbase, external
    live/                      runner, feed, broker durci MT5, état SQLite write-ahead, symboles/alias, terminal
    gui/ ui/                   serveur FastAPI lecture seule + interface web (modules JS), replay, catalogue
    ai/ improvement/           orchestrateur Claude/ChatGPT (non branché), boucle d'amélioration
    supervisor.py clock.py audit.py ...
  scripts/                     run_strategies, paper_all, run_ml, run_rl, run_pairs, run_portfolio, preflight, broker_profile...
  specs/                       38 specs préenregistrées (*.json) = définition + portes de chaque essai
  reports/                     résultats de chaque essai + registry.jsonl (chaîné)
  config/                      default.json, broker_profile.json (créé sur le PC)
  data/                        real/ live/ crypto/ external/ options/ (JAMAIS dans Git : voir §6)
  runtime/                     état d'exécution propre à chaque PC (ignoré par Git)
  tests/                       62 fichiers (≈ 457 tests)
  docs/                        EXPLOITATION, AUDIT, REVUE_MODULES, OMEGA, prompts/
  lancer_terminal.bat lancer_tout.bat scripts/start_all.bat quantbot_terminal.py build_windows.bat
```
Autres dossiers du dépôt sans lien (non importés par quantbot) : `fx_liquidity_bot/`, `micro_scalping/`, `oss_quant_stack/`.

## 3. Flux de données
MT5 (démo, terminal ouvert sur le PC Windows) → `data/autosync.py` + `live_store.py` → `data/live/<SYMBOLE>_<TF>.csv` (M1/M5/M15/H1, journal `MANIFEST.jsonl` chaîné par hachage, un seul écrivain via `daemon.lock`) ; profondeur du carnet et ticks échantillonnés → `data/live/depth|ticks`.
Coinbase public → `data/crypto/*.csv` (historique 800 j, complété vers le passé). COT/FRED → `data/external/`.
**Horloge courtier** : l'heure du serveur est UTC+2 (hiver) / UTC+3 (été, calendrier européen). Les chargeurs reconstruisent l'UTC depuis `time_broker_epoch` (`data/mt5.py::load_mt5_csv`, règle `eu_dst`) : ne jamais se fier à la colonne `time` des CSV.

## 4. Flux d'exécution (simulation)
`supervisor.py` lance et relance `scripts/paper_all.py` (workers MT5 + Coinbase, backoff, un verrou par source) → pour chaque spec et instrument, un lanceur : `live/feed` lit la dernière barre close → `live/strategies.generate` (même `events_for`) → `EventSignalEngine` → `TradingEngine` + `RiskManager` (risque par trade 0,5 %, levier ≤ 3, garde-fou actif, surcouche de risque, spread) → `PaperBroker` → journal SQLite `runtime/paper/*.db`. `risk/ledger.py` (LedgerMonitor) additionne tout sur UN compte FTMO simulé de 100 000 $ et pose le fichier `runtime/paper/KILL` aux tampons 4 % / 8 % (jamais levé automatiquement).
Interface : `python -m quantbot ui` → http://127.0.0.1:3214, lecture seule : Live trades & attribution, Marché, Stratégies (catalogue), Backtests (banc d'essai), Risque, Recherche, Système.

## 5. Stratégies présentes (ids)
amd, vwap, orb, fvg_h1/h4, smc_h1/h4, gq_sweep/asia_break/ema_pull/squeeze/zrev, apex_pullback, apex_levels, stop_hunt (+ variantes sell/buy/flip), mtf_confluence, il_svr, cta_donchian, kalman_ou, orderflow_iceberg, fixing_seasonality, cot_extremes*, macro_tips*, ofi_depth*, **omega** (confluence FVG H1 + AMD + VWAP). (*) exigent des données réelles absentes : aucun signal sans elles. Aucune n'est validée (118/120 essais consommés, 0 PASS). Les résultats sont dans `reports/*/NOTES.md`.

## 6. Ce qui N'EST PAS dans Git (à sauvegarder à part)
- `data/real/*.csv` : exports MT5 de recherche (ancien jeu, empreintes dans `data/real/PROVENANCE.json` et dans les specs `data_sha256`). **Sans eux, les essais déjà comptés ne sont pas rejouables à l'identique.** Sur le PC de l'utilisateur ils sont dans le stash Git `avant-pull-27oct` (ne jamais `stash pop` global : en extraire les fichiers un par un).
- `data/live/`, `data/crypto/`, `data/external/` : régénérés par la synchronisation (mais l'historique passé ancien ne l'est que partiellement).
- `config/broker_profile.json` (créé par `scripts/broker_profile.py` sur le PC), `runtime/` (bases SQLite, KILL, ports), variables d'environnement (`QUANTBOT_MT5_TERMINAL`, `FRED_API_KEY`, éventuelles clés IA) : **les clés ne sont jamais versionnées**.
- `reports/registry.jsonl` : EST versionné (registre chaîné) ; ne jamais le réécrire.

## 7. Restauration à l'identique (pas à pas)
**A. Depuis GitHub**
```
git clone https://github.com/mokdadmounir1-pixel/X.git
cd X
git checkout claude/micro-scalping-strategy-fp4bly     # ou la branche voulue
git log -1                                             # comparer avec backup/COMMIT.txt
```
**B. Depuis le .bundle (sans internet)**
```
git clone quantbot_full_history_2026-10-28.bundle X
cd X && git branch -a
git checkout <branche>      # puis git log -1 et comparer à COMMIT.txt
```
**C. Depuis le .zip** : le dézipper dans un dossier VIDE (le zip contient `quantbot/...`).
**D. Vérifier l'intégrité** (depuis la racine qui contient le dossier `quantbot/`) :
```
sha256sum -c quantbot/backup/MANIFEST_sha256.txt         # Linux/Mac/Git Bash
```
Windows PowerShell : `Get-FileHash <fichier> -Algorithm SHA256` et comparer à la ligne du manifeste. Tout écart = fichier modifié.
**E. Installer (Windows, Python 3.13 documenté)**
```
cd quantbot
python -m pip install -r requirements.txt
python -m pip install -r requirements-gui.txt   # interface de bureau (optionnel)
python -m pytest -q                              # attendu : tout passe (≈ 457 tests, 1 désélectionné)
```
**F. Remettre les données et la config**
1. Copier les anciens CSV dans `quantbot/data/real/` (jeu d'origine sauvegardé) ; vérifier `python scripts/check_data.py`.
2. Ouvrir MetaTrader 5 (compte DÉMO), définir `QUANTBOT_MT5_TERMINAL` si plusieurs terminaux.
3. `python scripts/preflight.py`, puis `python scripts/broker_profile.py --seconds 120` en pleine séance (jamais pendant la pause 21h–22h UTC).
4. Variables d'environnement : `FRED_API_KEY` (gratuite) ; aucune clé de trading.
**G. Lancer** : `lancer_tout.bat` (superviseur + simulations + interface), ou `python -m quantbot ui` pour l'interface seule.

## 8. Contrôles de fidélité après restauration
- `python -m pytest -q` passe en entier.
- `python -c "from quantbot.lab.registry import TrialRegistry as R; r=R('reports/registry.jsonl'); print(r.verify(), r.n_trials())"` → `True 118`.
- Le nombre de specs : 38 fichiers dans `specs/` ; les stratégies de §5 apparaissent dans l'onglet Stratégies.
- Le capital affiché est 100 000 $ (un seul compte FTMO simulé).

## 9. Index des modules (généré depuis le code : fichier, lignes, rôle)
| Fichier | Lignes | Rôle (première ligne de la docstring) |
|---|---|---|
| `quantbot/__main__.py` | 4 |  |
| `quantbot/ai/adapters.py` | 99 | Adaptateurs LLM : Claude et ChatGPT (exclusivement). Aucun autre modèle. |
| `quantbot/ai/orchestrator.py` | 131 | Orchestrateur IA : routage par rôle, repli entre modèles, sorties JSON bornées. |
| `quantbot/alpha_miner/dataset.py` | 54 | Jeu de données de trades : un vecteur de caractéristiques CAUSALES à la barre du signal + l'issue (R net, MFE, MAE). |
| `quantbot/alpha_miner/miner.py` | 102 | Analyse rétrospective AVEC GARDE-FOUS : partage chronologique purgé, importance par permutation hors-échantillon, test nul par étiquettes mélangées, r |
| `quantbot/audit.py` | 64 | Audit de performance sur les journaux RÉELS (trades simulés PAPER, journal d'exécution, ticks). Aucune valeur par défaut inventée : ce qui n'est pas m |
| `quantbot/backtest/engine.py` | 51 | Backtest = rejeu barre par barre du moteur unique `core.sim.TradingEngine` (sans look-ahead). |
| `quantbot/backtest/metrics.py` | 30 | Métriques de performance (après coûts). |
| `quantbot/cli.py` | 106 | Interface en ligne de commande : python -m quantbot <commande>. |
| `quantbot/clock.py` | 42 | Contrôle de l'horloge : décalage de la machine par rapport à un serveur NTP (SNTP, UDP/123, bibliothèque standard). Tous les horodatages du projet son |
| `quantbot/config.py` | 355 | Configuration typée et validée. |
| `quantbot/console.py` | 19 | Console Windows (cp1252) : ne jamais perdre un résultat à cause d'un caractère d'affichage. |
| `quantbot/core/calibration.py` | 144 | Calibration score -> espérance nette (en R nominal) par régression isotone (PAV). |
| `quantbot/core/labels.py` | 117 | Labels : résultat NET (en R nominal) du trade standard si on avait pris chaque côté à chaque barre. |
| `quantbot/core/scores.py` | 28 | Scores de direction pour TOUTES les barres (entraînement de la calibration). |
| `quantbot/core/sim.py` | 220 | Moteur de trading UNIQUE : backtest, paper et démo exécutent exactement ce code. |
| `quantbot/data/autosync.py` | 228 | Synchronisation AUTOMATIQUE des données du terminal, en lecture seule, sans clé : |
| `quantbot/data/coinbase.py` | 139 | Coinbase (API publique Exchange) : barres OHLCV de crypto en LECTURE SEULE. Aucune clé, aucun ordre, aucun compte. |
| `quantbot/data/external.py` | 88 | Données externes GRATUITES et publiques, en lecture seule : positionnement COT de l'or (CFTC) et calendrier macro. |
| `quantbot/data/live_store.py` | 140 | Magasin incrémental de barres MT5 CLÔTURÉES, alimenté en continu en LECTURE SEULE (aucun appel d'ordre). |
| `quantbot/data/loaders.py` | 90 | Sources de données : CSV, synthétique, ccxt, MetaTrader 5 (optionnels). |
| `quantbot/data/mt5.py` | 122 | Export MetaTrader 5 (CSV) : horloge du courtier -> UTC, spreads, trous. |
| `quantbot/data/mtf.py` | 66 | Multi-timeframe SANS fuite : une barre H4/D1 n'est utilisable qu'une fois TERMINÉE. |
| `quantbot/data/validation.py` | 63 | Validation / nettoyage des données OHLCV. |
| `quantbot/exceptions.py` | 33 | Exceptions propres au projet quantbot. |
| `quantbot/execution/broker.py` | 141 | Couche d'exécution : interface broker et paper trading. |
| `quantbot/filelock.py` | 39 | Verrou de fichier inter-processus (un seul démon par dossier) ; relâché par l'OS même après un crash. |
| `quantbot/gui/app.py` | 111 | Application web locale (FastAPI) : API en LECTURE SEULE + interface terminal. Écoute uniquement sur 127.0.0.1 ; aucune route n'envoie d'ordre ni n'écr |
| `quantbot/gui/book.py` | 185 | Livre de trades et attribution par stratégie : agrège les bases d'état des simulations PAPER (runtime/paper/*.db) et du lanceur (QUANTBOT_STATE). LECT |
| `quantbot/gui/chart.py` | 56 | Charge utile des graphiques temps réel : bougies clôturées publiées par le lanceur, position / ordre en attente, trades clos et zones Order Block / FV |
| `quantbot/gui/paths.py` | 17 | Racine des données de l'application : le dossier du projet, ou le dossier de l'exécutable une fois compilé (PyInstaller). |
| `quantbot/gui/server.py` | 101 | Lancement du terminal : uvicorn lié à 127.0.0.1 UNIQUEMENT (jamais 0.0.0.0). |
| `quantbot/improvement/apex_loop.py` | 39 | Boucle d'apprentissage d'APEX PULLBACK : isole les échecs à score ÉLEVÉ causés par une expansion de volatilité et propose une variante resserrée. |
| `quantbot/improvement/diagnosis.py` | 156 | Analyse d'erreurs (OBSERVE / DIAGNOSE) et hypothèses d'amélioration (HYPOTHESIZE). |
| `quantbot/improvement/journal.py` | 35 | Journal de trading : chaque trade clôturé produit une leçon mémorisée. |
| `quantbot/indicators/core.py` | 53 | Moteur de calcul des indicateurs (pandas / numpy). |
| `quantbot/indicators/structure.py` | 69 | Structure de marché : pivots confirmés, niveaux S/R, tendance HH/HL. |
| `quantbot/lab/battery.py` | 157 | Batterie d'hypothèses documentées, évaluées en rendements JOURNALIERS nets de coûts. |
| `quantbot/lab/forward.py` | 31 | Évaluation sur l'échantillon FUTUR (barres postérieures au gel, specs/forward_freeze.json). |
| `quantbot/lab/gates.py` | 109 | Portes de validation sur les résultats en R. Seuils PRÉENREGISTRÉS : changer un seuil change le hachage de la spec. |
| `quantbot/lab/locked.py` | 52 | Période verrouillée : séparée dès le départ, lisible une seule fois par spécification. |
| `quantbot/lab/pipeline.py` | 119 | Évaluation d'une spécification : recherche (répétable) puis période verrouillée (une seule fois). |
| `quantbot/lab/registry.py` | 83 | Registre d'essais append-only, chaîné par hachage. |
| `quantbot/lab/specs.py` | 20 | Construction des réglages d'une spec préenregistrée (partagée par les scripts et l'interface). |
| `quantbot/lab/stats.py` | 171 | Statistiques de validation sur des résultats en R (multiples du risque). |
| `quantbot/lab/walkforward.py` | 106 | Optimisation en marche avant (walk-forward) : on choisit les paramètres sur une fenêtre d'ENTRAÎNEMENT puis on ne retient |
| `quantbot/live/approvals.py` | 37 | Approbation HUMAINE : le programme ne l'écrit jamais. Sans approbation valide, le bot reste en OBSERVATION (aucun ordre). |
| `quantbot/live/feed.py` | 74 | Flux de barres MT5 : barres CLÔTURÉES uniquement, chacune émise une seule fois, trous et flux figés détectés. |
| `quantbot/live/killswitch.py` | 44 | Arrêt d'urgence : tant qu'il est actif, AUCUNE nouvelle entrée n'est possible. |
| `quantbot/live/mt5_exec.py` | 294 | Broker MT5 DURCI pour le bot en direct. |
| `quantbot/live/runner.py` | 145 | Boucle du bot en direct : flux de barres -> moteur UNIQUE -> broker (observation ou démo durci). |
| `quantbot/live/state.py` | 114 | État persistant du bot en direct (SQLite) : intentions d'ordres, événements, clé/valeur. |
| `quantbot/live/strategies.py` | 50 | Stratégies exécutables en direct : mêmes générateurs causaux que la recherche, appliqués sur la fenêtre récente. |
| `quantbot/live/symbols.py` | 96 | Noms de symboles propres à CHAQUE courtier : quantbot raisonne en noms canoniques (XAUUSD, EURUSD, USTEC...) ; le courtier peut les appeler GOLD, XAUU |
| `quantbot/live/terminal.py` | 25 | Chemin du terminal MetaTrader 5 : paramètre explicite > variable d'environnement QUANTBOT_MT5_TERMINAL > chemin par défaut SI le fichier existe > aucu |
| `quantbot/logging_utils.py` | 36 | Logs structurés : une seule configuration pour tout le package. |
| `quantbot/memory/store.py` | 144 | Mémoire & observabilité : toutes les expériences, versions et trades (SQLite). |
| `quantbot/ml/cv.py` | 25 | Validation croisée purgée avec embargo (López de Prado, AFML ch. 7). |
| `quantbot/ml/features.py` | 74 | Features strictement causales (la valeur à la barre t n'utilise que les barres <= t). |
| `quantbot/ml/model.py` | 108 | Walk-forward LightGBM : réentraînement périodique sur le passé purgé, prédiction hors-échantillon barre par barre, puis simulation de trades. |
| `quantbot/ml/rl_agent.py` | 50 | Apprentissage par renforcement (stratégie n°10) : Q-learning TABULAIRE avec contrainte de perte journalière de type FTMO, évalué en WALK-FORWARD hors- |
| `quantbot/patterns/base.py` | 85 | Contexte de marché (numpy), résultat de détection et classe de base. |
| `quantbot/patterns/candles.py` | 228 | Chandeliers (photo « Candlesticks Signals »), version haussière + miroir. |
| `quantbot/patterns/chart.py` | 110 | Figures chartistes sur pivots confirmés (version haussière + miroir). |
| `quantbot/patterns/harmonic.py` | 50 | Patterns harmoniques XABCD (Gartley, Bat, Butterfly, Crab). |
| `quantbot/patterns/scanner.py` | 47 | Orchestration des détecteurs : un seul passage, erreurs isolées et loggées. |
| `quantbot/patterns/tolerance.py` | 72 | Logique floue : scores de similarité plutôt que correspondance binaire. |
| `quantbot/portfolio/combine.py` | 59 | Combinaison causale de flux de résultats journaliers (en R) de plusieurs stratégies. |
| `quantbot/risk/active.py` | 128 | Contrôle ACTIF du risque : limite de perte journalière (latent inclus), freinage par drawdown, arrêt sur dérive, arrêt sur volatilité anormale, dimens |
| `quantbot/risk/calendar.py` | 15 | Calendrier de risque : fenêtre de week-end (les plus gros gaps sont les réouvertures du dimanche soir). |
| `quantbot/risk/ftmo.py` | 120 | Garde-fou FTMO 2-Step : le bot s'arrête AVANT les limites du challenge. |
| `quantbot/risk/ledger.py` | 95 | Registre de portefeuille FTMO SIMULÉ : toutes les stratégies en simulation PAPER sont comptées comme si elles tradaient UN SEUL compte de 100 000 $ (c |
| `quantbot/risk/manager.py` | 125 | Gestion du risque : plan de trade, limites journalières, VaR. |
| `quantbot/risk/overlay.py` | 49 | Surcouche de risque CONTINUE (jamais un oui/non) : multiplicateur de taille dans [0, 1] qui ne peut QUE réduire le risque. |
| `quantbot/risk/tail_dependence.py` | 17 | Dépendance de queue empirique entre deux séries de rendements (stratégie/outil n°11 : défense contre la contagion). |
| `quantbot/risk/var.py` | 58 | VaR / Expected Shortfall paramétriques et historiques, et Kelly fractionnaire. Fonctions pures, mesures descriptives (aucune garantie de perte maximal |
| `quantbot/signals/calibrated.py` | 36 | Moteur de signaux v2 : détecteurs flous -> scores de direction -> espérance CALIBRÉE -> décision. |
| `quantbot/signals/engine.py` | 93 | Agrégation des patterns en un signal unique (direction + confiance). |
| `quantbot/signals/mtf_calibrated.py` | 33 | Moteur de signaux v3 : scores flous x contexte multi-timeframe -> espérance calibrée PAR ÉTAT de tendance HTF. |
| `quantbot/signals/scoring.py` | 37 | Scores de direction partagés par l'ENTRAÎNEMENT (calibration) et l'EXÉCUTION : une seule définition. |
| `quantbot/stat/avellaneda.py` | 35 | Teneur de marché d'Avellaneda-Stoikov : prix de réserve et spread optimaux selon l'inventaire, puis SIMULATION de cotation sur barres (outil de recher |
| `quantbot/stat/pairs.py` | 151 | Arbitrage statistique sur paire : test de cointégration (Engle-Granger/ADF), bêta dynamique (filtre de Kalman), z-score, simulation causale. |
| `quantbot/stat/vol_arb.py` | 31 | Arbitrage de volatilité : volatilité RÉALISÉE (Garman-Klass) contre volatilité IMPLICITE de la chaîne d'options (ATM, échéance la plus proche), en éca |
| `quantbot/strategies/amd.py` | 56 | #1 AMD / Power of 3 — règles mécaniques FIGÉES (la description d'origine est qualitative). |
| `quantbot/strategies/apex.py` | 65 | THE APEX PULLBACK ALPHA — repli dans une tendance saine, score de similarité continu S dans [0, 1]. |
| `quantbot/strategies/apex_composite.py` | 25 | Score composite Ω des piliers DISPONIBLES, sans jamais remplacer une donnée absente par une valeur. |
| `quantbot/strategies/build.py` | 88 | Construction des événements d'une stratégie à règles explicites depuis sa définition de spec (partagé par l'interface ; les scripts ont leur copie). |
| `quantbot/strategies/cot_extremes.py` | 35 | Positionnement COT (stratégie n°9) : extrêmes de la position nette « Managed Money » sur l'or (CFTC), approche CONTRARIENNE fixée à l'avance. |
| `quantbot/strategies/cta_donchian.py` | 32 | Suivi de tendance (CTA) : cassure de canal de Donchian sur H4 (barres TERMINÉES) filtrée par la tendance D1 continue. |
| `quantbot/strategies/dealer_gex.py` | 119 | Exposition gamma des teneurs de marché (GEX) sur l'or, calculée sur de VRAIES données d'options, fusionnée avec le repli APEX. |
| `quantbot/strategies/events.py` | 56 | Stratégies à règles explicites : événements causaux datés -> signaux pour le moteur unique. |
| `quantbot/strategies/external_data.py` | 56 | Chargement des données externes pour les stratégies qui en dépendent (COT, FRED, profondeur du carnet). Sans fichier : liste vide et raison explicite, |
| `quantbot/strategies/fixing_seasonality.py` | 29 | Saisonnalité des fixings LBMA (stratégie n°12) : fenêtres de liquidité autour des fixings de Londres (10h30 et 15h00, HEURE DE LONDRES : l'heure UTC v |
| `quantbot/strategies/fvg.py` | 69 | #6 FVG mitigation (H1/H4) — règles FIGÉES. |
| `quantbot/strategies/goldq.py` | 135 | Cinq stratégies de scalping quantitatif pour l'OR (XAUUSD), règles FIGÉES, événements causaux (barre t = données <= t). |
| `quantbot/strategies/il_svr.py` | 63 | IL-SVR — Institutional Liquidity Sweep & VWAP Reversion, pour INDICES (barres M15 ; M1/M5 dès qu'elles seront exportées). |
| `quantbot/strategies/intermarket_telemetry.py` | 22 | Télémétrie inter-marchés : lead-lag mesuré entre l'or et des séries de référence (EURUSD, USTEC, et DXY / argent / cuivre / taux réels SI exportés). |
| `quantbot/strategies/kalman_ou.py` | 52 | Réversion à la moyenne : résidu du filtre de Kalman 1D + demi-vie d'Ornstein-Uhlenbeck (stratégie n°2). |
| `quantbot/strategies/level_proximity.py` | 62 | Proximité aux niveaux structurels (chiffres ronds + nœuds de volume récents) fusionnée avec le repli APEX. |
| `quantbot/strategies/macro_tips.py` | 36 | Global macro / taux réels (stratégies n°3 et n°7) : l'or contre les taux réels américains à 10 ans (TIPS, série FRED DFII10), signal LENT. |
| `quantbot/strategies/mtf_confluence.py` | 60 | Analyse multi-temporelle descendante (D1 -> H4 -> H1 -> M15) : confluence continue, sans fuite, sans règle binaire. |
| `quantbot/strategies/ofi_depth.py` | 32 | Microstructure (stratégie n°5) : déséquilibre RÉEL du carnet (profondeur enregistrée par le terminal dans data/live/depth) en CONFIRMATION de la direc |
| `quantbot/strategies/orb.py` | 52 | #9 Opening Range Breakout 15 min (ouverture cash New York 09:30) — règles FIGÉES. |
| `quantbot/strategies/order_flow_ofi.py` | 71 | Flux d'ordres : OFI (Cont-Kukanov-Stoikov) sur des cotations RÉELLES de carnet, proxy de flux par ticks, proxy d'absorption par barres. |
| `quantbot/strategies/orderflow_iceberg.py` | 36 | Flux d'ordres et absorption (stratégie n°8) : CVD par barre + absorption volume/déplacement, puis CONTINUATION dans le sens de la sortie. |
| `quantbot/strategies/smc.py` | 177 | SMC_OB_FVG — Order Block + Fair Value Gap en confluence, règles FIGÉES, détection MATRICIELLE et causale. |
| `quantbot/strategies/stop_hunt_engine.py` | 61 | Topologie des stops : réservoirs de liquidité (plus hauts/bas égaux), balayage, puis validation de retour (reclaim) — entrée APRÈS la purge. |
| `quantbot/strategies/vwap.py` | 48 | #5 VWAP à bandes — retour à la moyenne ; règles FIGÉES. |
| `quantbot/supervisor.py` | 131 | Superviseur des processus automatiques : lance, surveille et RELANCE les scripts (simulation PAPER MT5, simulation crypto) sans intervention. |
| `quantbot/ui/catalog.py` | 68 | Catalogue de TOUTES les stratégies de quantbot : ce qui existe, son résultat de recherche (verdict préenregistré), si la simulation PAPER la fait tour |
| `quantbot/ui/replay.py` | 224 | Rejeu visuel d'une stratégie : chaque trade avec entrée, stop (SL), objectif (TP), sortie, motif et R, pour LIRE ce que fait le moteur. |
| `quantbot/ui/server.py` | 257 | Couche de DONNÉES de l'interface (état, résultats, simulations, rejeu) ; le serveur et l'interface sont dans quantbot/gui. |
| `quantbot_terminal.py` | 31 | Point d'entrée du terminal de bureau (fenêtre native si pywebview est installé, sinon navigateur par défaut). Lecture seule : aucun ordre. |
| `scripts/audit_performance.py` | 49 | Audit de performance à partir des journaux RÉELS du terminal (trades PAPER, journal d'exécution, ticks). Lecture seule. |
| `scripts/baseline_real.py` | 63 | Première évaluation RÉELLE d'une spec préenregistrée (specs/*.json) sur la partie RECHERCHE des données. |
| `scripts/broker_profile.py` | 82 | Profil du courtier, en LECTURE SEULE : nom des symboles chez ce courtier, spécifications de contrat, spread réellement observé, coûts de départ pour l |
| `scripts/c3_quote_gate.py` | 56 | Précontrôle local de disponibilité pour C3 ; aucune API d'ordres. |
| `scripts/calibrate_gates.py` | 60 | Calibre les portes sur des marchés SANS edge (le « tell » ne prédit rien) et mesure la puissance sur un edge planté. |
| `scripts/check_data.py` | 17 | Vérifie que data/real/*.csv sont présents et identiques (SHA-256) à ceux de data/real/PROVENANCE.json. Aucune écriture. |
| `scripts/data_daemon.py` | 72 | Démon d'extraction MT5 : met à jour data/live/<SYMBOLE>_<TF>.csv en continu, en LECTURE SEULE (aucun appel d'ordre). |
| `scripts/diagnose_beta.py` | 44 | DIAGNOSTIC (pas un essai) : les scores flous apportent-ils de l'information AU-DELÀ du simple biais directionnel du marché ? |
| `scripts/diagnose_costs.py` | 31 | DIAGNOSTIC (pas un essai) : espérance brute vs nette de coûts de la spec préenregistrée. |
| `scripts/export_coinbase.py` | 49 | Export d'historique crypto depuis Coinbase (API publique, LECTURE SEULE, sans clé) vers data/crypto/<PRODUIT>_<TF>.csv. |
| `scripts/export_mt5.py` | 101 | Export de l'historique MetaTrader 5 au format attendu par quantbot (à lancer sur la machine Windows où tourne MT5). |
| `scripts/export_mt5_deep.py` | 94 | Export PROFOND de l'historique MT5 par tranches de dates (copy_rates_range) : remonte aussi loin que le serveur a des données. |
| `scripts/export_symbol_specs.py` | 41 | Spécifications de contrat des symboles (swaps, taille de contrat, pas de prix, marge...) en LECTURE SEULE. |
| `scripts/forward_eval.py` | 67 | Évaluation des stratégies FIGÉES sur l'échantillon futur collecté par le démon (data/live), selon specs/forward_eval_v1.json. |
| `scripts/optimize.py` | 71 | Optimisation en MARCHE AVANT d'une stratégie à règles explicites (specs/wf_*.json). Période de RECHERCHE seulement. |
| `scripts/paper_all.py` | 103 | Simulation PAPER permanente : toutes les stratégies préenregistrées tournent sur les barres RÉELLES, avec des trades SIMULÉS. |
| `scripts/preflight.py` | 97 | Pré-vol : vérifie en clair, point par point, que quantbot est CONNECTÉ à MetaTrader 5 et prêt à prendre des trades SIMULÉS sur les prix réels. |
| `scripts/registry_merge.py` | 30 | Reprend un registre d'essais produit sur un AUTRE ordinateur, uniquement s'il PROLONGE le registre du dépôt. |
| `scripts/research_queue.py` | 82 | File de recherche 24 h/24 : exécute, une fois chacune, les specs PRÉENREGISTRÉES listées dans specs/queue.json. |
| `scripts/run_alpha_miner.py` | 63 | Exécute specs/alpha_miner_v1.json : rejoue les trades de l'or (recherche seulement), construit le jeu de données, juge hors-échantillon. Un essai comp |
| `scripts/run_backward.py` | 71 | Backtest en ARRIÈRE : les stratégies FIGÉES (specs/inst_strategies_v1.json, paramètres inchangés) sur les années qui PRÉCÈDENT |
| `scripts/run_battery.py` | 74 | Batterie d'hypothèses documentées (specs/battery_v1.json) sur la période de RECHERCHE : verdict après correction de multiplicité. |
| `scripts/run_battery_backward.py` | 70 | Batterie journalière EN ARRIÈRE : hypothèses à paramètres FIGÉS (specs/battery_v1.json) sur les années d'H1 qui PRÉCÈDENT la période de recherche. |
| `scripts/run_c8.py` | 110 | C8 en UNE commande, sans assistant : export profond MT5 (lecture seule), contrôle d'identité avec data/real, backtests en arrière, dossier de livraiso |
| `scripts/run_live.py` | 371 | Lanceur Windows MT5 : observation par défaut, approbation humaine inchangée. |
| `scripts/run_ml.py` | 49 | Exécute specs/ml_v1.json : LightGBM walk-forward purgé sur les exports MT5. Un essai compté par instrument (registre chaîné). |
| `scripts/run_mtf.py` | 105 | v3 : scores flous x contexte multi-timeframe (H4+D1, causal) -> calibration par (côté, état) -> évaluation hors échantillon. |
| `scripts/run_pairs.py` | 69 | Exécute specs/pairs_v1.json sur les CSV exportés (scripts/export_coinbase.py). Un essai compté par variante de coûts (registre chaîné). |
| `scripts/run_portfolio.py` | 65 | Exécute specs/portfolio_v1.json : toutes les stratégies à règles figées combinées par des poids causaux. Un essai compté par schéma. |
| `scripts/run_rl.py` | 31 | Exécute specs/rl_v1.json : Q-learning tabulaire en walk-forward strict (entraînement passé, test suivant, jamais l'inverse). UN essai compté. Verdict  |
| `scripts/run_strategies.py` | 59 | Stratégies à règles explicites (specs/inst_strategies_v1.json) : événements causaux -> moteur unique -> portes. Période de RECHERCHE seulement. |
| `scripts/run_v2.py` | 105 | Phase 2 : calibration score -> espérance nette (apprentissage) puis évaluation sur la validation (hors échantillon). |
| `scripts/setup_data.py` | 77 | Prépare data/real automatiquement : cherche sur le disque les exports dont le SHA-256 correspond à data/real/PROVENANCE.json |

## 10. Règles du projet (à ne jamais perdre)
Aucun ordre sans autorisation écrite ; aucun résultat ni donnée inventés ; spec commitée AVANT chaque essai ; tranche verrouillée jamais lue ; coûts réels du courtier jamais supposés nuls ; résultats négatifs publiés tels quels ; aucun rendement garanti (pas de 7 %/mois ni 65 % de réussite comme objectif).
