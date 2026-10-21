# ETAT_PROJET — journal de décisions, résultats, rejets

Dernière mise à jour : 2026-10-21. Environnement de construction : cloud Linux, **sans MT5, sans accès à ftmo.com, Dukascopy,
Binance** (proxy sortant restreint ; PyPI et GitHub accessibles). **Aucune donnée réelle n'a été utilisée.**
Statuts : `[VÉRIFIÉ]` = calculé sur données réelles · `[SYNTHÉTIQUE]` = calculé ici sur données générées · `[HYPOTHÈSE]`.

## 1. Point de départ et décisions de réécriture
Le dépôt contenait `micro_scalping/` (EMA/RSI/ATR 1 min, ~300 lignes) et `fx_liquidity_bot/` (sweep + displacement + FVG, ~1 500 lignes),
plus un stress-test sur marches aléatoires. Lus intégralement. **Aucun ETAT_PROJET.md n'existait.**

| Existant | Décision | Justification |
|---|---|---|
| `micro_scalping` (scalp 1 min, RR 1,67) | **remplacé**, déplacé dans `legacy/` | RR 1,67 < 2,5 requis ; coûts fixes ; pas de période verrouillée ni de tests de causalité ; scalping 1 min très sensible aux coûts |
| `fx_liquidity_bot` (machine à états barre par barre, pandas) | **remplacé**, déplacé dans `legacy/` ; l'idée « sweep de liquidité » est reprise dans `algos/library.py::SweepReversal` | boucle pandas barre par barre (lente), spreads/swaps/gaps non modélisés, un seul actif par moteur, pas de gardien sur l'équité |
| stress-test synthétique (`stress_test_results/`) | conservé dans `legacy/` | il validait des presets sur 10 marches aléatoires : exactement le type de preuve qu'on ne veut plus (sélection de presets sur du bruit) |
| `numpy/pandas/ccxt` en dépendances | cœur ramené à **numpy, pandas, pyyaml** | ccxt, MetaTrader5, etc. deviennent optionnels (import tardif) |

## 2. Ce qui est construit
Voir README (architecture, commandes). Points structurants :
- **Un seul moteur** (`engine/sim.py`) pour backtest, paper et démo : `process_bar` est appelé par le backtest (barres utiles seulement) et par les agents live (chaque barre M15). Test `test_replay.py` : trades **identiques au 1e-9** entre backtest et rejeu M5 → agent.
- Pessimisme : exécution à l'ouverture suivante ; bid/ask ; stop prioritaire ; gaps à l'ouverture ; spread ×3 et slippage ×1,5 autour des annonces ; commissions, swaps ; RR net ≥ 2,5 exigé **avant** l'entrée ; lots arrondis ; levier plafonné ; plafond de risque par groupe corrélé ; gardien 70 % sur l'équité + réserve de risque pré-trade.
- Aucun look-ahead : `test_causality.py` vérifie, pour les 7 algos générateurs, que les signaux calculés sur un préfixe sont **identiques** à ceux de la série complète, qu'altérer le futur ne change pas le passé, et que toute barre H1/H4/D1 utilisée est déjà close.
- Test nul par surrogates (inversion de signe de blocs d'un jour, dérive retirée) : détruit toute structure directionnelle tout en gardant volatilité, saisonnalité, spreads.

## 3. Résultats
### 3.1 Recherche de référence `[SYNTHÉTIQUE]` (marche aléatoire, 6 instruments × 5 ans, graine 7)
Commande : `python -m ftmo_algo research --instruments US500,US100,GER40,XAUUSD,EURUSD,USDJPY --years 5 --seed 7 --tag ref_s7`
(hash des données `755e4623e5287b55`, graine 7, v0.1.0 ; fichier `reports/synthetic_reference/latest.json`). Verrou dès 2025-01-02, 11 plis walk-forward de 3 mois.

| algo | verdict | n OOS | E(R) OOS | PF | DSR | verrou : n / E(R) / PF |
|---|---|---|---|---|---|---|
| trend_pullback | FAIL | 96 | -0.022 | 0.97 | 0.044 | 41 / -0.222 / 0.7 |
| sweep_reversal | FAIL | 2834 | -0.095 | 0.86 | 0.0 | 1170 / -0.173 / 0.77 |
| squeeze_breakout | FAIL | 2731 | -0.125 | 0.83 | 0.0 | 1118 / -0.149 / 0.8 |
| session_orb | FAIL | 1799 | -0.114 | 0.81 | 0.0 | 669 / -0.004 / 0.99 |
| meanrev_z | FAIL | 296 | -0.157 | 0.8 | 0.0 | 110 / -0.005 / 0.99 |
| news_momentum | FAIL | 61 | -0.18 | 0.64 | 0.01 | 31 / -0.298 / 0.38 |
| regime_router | FAIL | 1922 | -0.165 | 0.72 | 0.0 | 703 / -0.106 / 0.8 |
| ml_filter | FAIL | 1085 | -0.135 | 0.79 | 0.0 | non évalué |

- **Aucun PASS, aucun WATCH** : attendu sur une marche aléatoire dont les coûts rongent l'espérance (≈ −0,1 à −0,2 R/trade) ; la période verrouillée confirme (espérances ≤ 0, publiées telles quelles). Portefeuille : AUCUN (aucun algo PASS : pas de portefeuille validé).
- Scoring A+/A/B : A+ -0.111 R, A -0.134 R, B -0.122 R → non monotone → **scoring supprimé** (décision automatique, tous les grades tradés).
- Étude des sorties (espérance OOS moyenne, toutes variantes de paramètres, sans sélection) : fixed3 -0.135 R, fixed4 -0.185 R, fixed3_wkflat -0.131 R, be3 -0.148 R, partial4 -0.174 R, trail_atr -0.229 R, trail_struct -0.22 R. Conservation du week-end vs fermeture forcée : écart non significatif sur données synthétiques (les gaps de week-end synthétiques sont symétriques, donc sans signification réelle : à retester sur réel).
- Un premier passage de la même recherche (avant ajout de la sortie week-end et avant correction du générateur de données) est conservé dans `reports/synthetic_baseline_pre_final/` : mêmes conclusions (aucun PASS). **La période verrouillée de cette ancienne exécution avait déjà été lue** ; les résultats finaux ci-dessus portent sur un jeu de données régénéré (hash différent) avec son propre marqueur de verrou.

### 3.2 Calibration des portes (faux PASS) `[SYNTHÉTIQUE]`
`python -m ftmo_algo calibrate` : toute la chaîne (walk-forward, 9 portes, test nul, DSR) rejouée sur des marches aléatoires indépendantes (3 instruments × 4 ans, graines différentes).
- **Faux PASS : 0/60 séries = 0.0%** (borne haute à 95 % ≈ 4.9%) ; faux WATCH : 0/60 ; espérance OOS moyenne -0.149 R (le biais négatif = coûts).
- Seuil de 5 % : respecté, mais la borne haute n'est qu'à peine sous 5 % avec 60 séries : **ne pas en déduire que le taux réel est nul**. Les portes n'ont donc pas été durcies. Le run 1 (20 séries) a tourné avant l'ajout de la sortie week-end ; le run 2 (40 séries) avant la correction du générateur de données (non-déterminisme de l'ordre des groupes, sans effet statistique). Séries réelles mélangées : non exécutées (pas de données réelles).
- Détail : `reports/synthetic_reference/calibration_run1.json`, `calibration_run2.json`.

### 3.3 Puissance : les portes peuvent-elles voir un vrai edge ? `[SYNTHÉTIQUE]`
Edge **planté** (dérive de tendance persistante dans le générateur) pour vérifier que les portes ne sont pas impossibles à franchir. `[SYNTHÉTIQUE]`, jeux de données générés avant la correction du déterminisme (hash enregistrés, non régénérables bit à bit).
- **Edge faible** (persistance 0,05) : squeeze_breakout FAIL (E=0.218R, PF=1.33, n=876), session_orb FAIL (E=0.238R, PF=1.43, n=597), regime_router FAIL (E=0.163R, PF=1.24, n=899), ml_filter FAIL (E=0.273R, PF=1.47, n=914). **Tous FAIL** : l'espérance OOS (≈ +0,2 R) est sous le seuil de 0,3 R et/ou la série de pertes p95 dépasse la marge ; la période verrouillée voit pourtant +0,18 à +0,32 R sur 3 algos. **Les portes sont donc conservatrices : un vrai edge modeste (< 0,3 R net) sera classé FAIL/WATCH.** C'est un choix (spécificité > sensibilité), à assumer ou à assouplir en connaissance de cause sur données réelles — pas un résultat.
- **Edge fort** (persistance 0,3, irréaliste : +2 à +3 R/trade) : PASS pour squeeze_breakout, session_orb, news_momentum, regime_router ; portefeuille **PASS** (9 portes + DSR au niveau portefeuille, simulation multi-instruments avec gardien et plafonds de groupe). Le module `target` donne alors P(mois ≥ 5 %) > 95 % : ce chiffre ne vaut que pour ce marché inventé.

### 3.4 Cible mensuelle
- Traduction en R : à 0,25 % → **+20 R/mois** ; 0,5 % → **+10 R/mois** ; 0,75 % → +6,7 R ; 1 % → **+5 R/mois**. Avec l'espérance minimale d'un PASS (+0,3 R), +10 R/mois à 0,5 % exige ≈ 33 trades/mois : incompatible avec « très peu de trades » sauf espérance bien supérieure.
- Données de référence (marche aléatoire) : **aucun algo PASS → aucune probabilité validée** ; `target --all` donne un calcul indicatif étiqueté NON VALIDÉ : espérance ≤ 0 pour tous → « ne pas trader », rendement mensuel médian négatif.
- **Probabilité mesurée d'atteindre +5 %/mois sur le marché réel : NON MESURABLE (pas de données réelles).**
- Le module rééchantillonne le nombre de trades par mois (distribution observée) et des blocs chronologiques de trades (regroupements de pertes conservés), applique le gardien (arrêt à 70 % des limites, réserve de risque) et cherche le risque (0,25–1,5 % par pas de 0,25) qui maximise P(mois ≥ 5 %) sous P(violation) < 5 % ; il ne modifie jamais les trades ni les paramètres des algos (test `test_target_module_never_uses_target_as_optimisation_objective`).

### 3.5 Boîte à outils
`python -m ftmo_algo install` (venv `toolbox_env/`, Python 3.13.16, linux) : **37/38 outils installés ET importés**. Échec : MetaTrader5 (paquet disponible uniquement sous Windows (terminal MT5) : à installer sur votre). Sources de référence clonées dans `vendor/` : 8/8. Détail : `reports/synthetic_reference/toolbox_status.json`.
Comparatifs mesurés (`bench`) : TA-Lib EMA 2.46× / ATR 6.8× plus rapide, écart numérique < 1e-12 ; la logistique maison est 2.4× plus rapide que scikit-learn avec des probabilités identiques à 1e-4. **Aucun outil intégré au cœur** : les gains de vitesse existent (TA-Lib) mais portent sur quelques millisecondes pour 200 000 barres, négligeables devant la simulation ; le cœur reste à 3 dépendances.

## 3bis. Amélioration continue (`ftmo_algo/evolve/`) — ajout du 2026-10-21
Boucle santé → recherche → ombre → promotion/probation/retour arrière → journal (voir README). Commande `evolve`, calibration `evolve-calibrate`, panneau dashboard, 6 tests (causalité, reprise d'état, pas de gain fabriqué sous le nul).
**Mesures [SYNTHÉTIQUE] — tables de trades simulées (`reports/evolution/evolve_calibration.json`), 40 séries par scénario :**
| scénario | gain évolutif − figé (R/mois) | promotions/série | verdict « UTILE » |
|---|---|---|---|
| nul (aucun avantage) | −0,03 (p5–p95 : −0,9 à +1,5) | 0,88 | **0/40** (aucun faux « utile ») |
| stable (un champion robuste) | +0,67 | 0,35 | 5/40 |
| dégradation (changement de régime) | +2,42 | 1,3 | 22/40 |
Lecture : sous le nul la boucle ne fabrique pas de gain (moyenne ≈ 0, bruit symétrique) ; sous changement de régime elle aide en moyenne mais pas à tout coup (22/40 « utile » à IC95).
Sur le marché synthétique complet (`evolve --years 4`, `reports/evolution/synthetic_example_*`) : un exemple de run et son évaluation unique sur la période verrouillée (non démontré, IC95 contient 0).
**Non vérifié / limites :** (a) aucune donnée réelle ; (b) les trades sont pré-calculés puis tranchés par date (sans fuite, comme le walk-forward) mais l'exclusion de zones est appliquée **a posteriori** sur la liste de trades (un trade retiré ne libère pas de créneau) ; (c) les seuils de la boucle (marges, 80 %, 2 mois d'ombre) sont des choix a priori non optimisés ; (d) le mode `--loop` n'a jamais tourné sur données fraîches MT5 ; (e) les exclusions promues ne sont pas encore appliquées par les agents live (seules la variante et la pause le sont).

## 3ter. Scalp / micro-scalp M1 (`ftmo_algo/scalp/`, voir `SCALP.md`) — ajout du 2026-10-21
4 algos M1, étude des coûts, portes scalp, 10ᵉ porte « retard d'une barre », mêmes moteur / walk-forward / verrou / DSR. **[SYNTHÉTIQUE]** : référence (marche aléatoire) 4 FAIL ; faux PASS 0/60 (borne 95 % ≈ 4,9 %) ; edge fort planté → PASS (+1,2 R), edge faible → FAIL.
**Défaut trouvé** : le test nul par blocs d'un jour conserve l'élan intrajournalier (nul moyen +1,07 R vs observé +1,20 R sur edge planté → vrai edge rejeté). Corrigé pour le scalp (`make_surrogate(block_bars=1)`) ; **non appliqué au pipeline M15** (mesures publiées inchangées) : décision à prendre.
Règles FTMO sur le scalping : sources tierces seulement (pas de durée minimale mentionnée, HFT / tick scalping / arbitrage de latence interdits, ~2 000 requêtes/jour évoquées) : **à confirmer sur ftmo.com**. Aucun edge réel mesuré.

## 4. Algos rejetés et pourquoi
Tous les algos échouent sur la marche aléatoire de référence — **ce n'est pas un rejet sur le fond** : sans edge à trouver, un FAIL est le bon résultat, et ce n'est pas une preuve contre les hypothèses sur marché réel. Ce que le dépôt prouve, c'est que le pipeline ne fabrique pas de faux edge. Rejets effectifs :
- `micro_scalping` et `fx_liquidity_bot` (code historique) : remplacés, voir §1.
- Scoring A+/A/B : **supprimé automatiquement** sur la référence (non monotone hors échantillon).
- Sorties trailing ATR/structure, partielle, break-even : aucune ne bat la cible fixe en moyenne OOS sur la référence (−0,22/−0,17/−0,15 vs −0,135 R) ; `session_orb` : aucune faveur, FAIL (cohérent avec son échec passé hors échantillon).
- Verdict réel de chaque algo : **à établir sur données MT5/CSV** (§6).

## 5. Ce qui n'est PAS vérifié (à faire sur votre machine)
1. **Tout edge sur le marché réel** : aucune donnée réelle ici. Les verdicts ci-dessus ne disent rien du marché.
2. **Pont MT5 / démo / MT5Feed** : le code est écrit mais n'a **jamais été exécuté contre un terminal** (package Windows-only). `python -m ftmo_algo demo` indique précisément ce qui manque, ou se connecte.
3. **Spécifications d'instruments** (`instruments.py`) : tailles de lot, valeur du point, commissions, swaps, spreads = `[HYPOTHÈSE]` ; utiliser `data.loaders.specs_from_mt5` pour les remplacer par `symbol_info()` du courtier. Conversion de devise JPY/GER40 approximative (taux figé).
4. **Spreads** : le moteur utilise la colonne `spread` des barres MT5 si disponible, sinon un profil horaire ; la mesure sur **ticks** (`copy_ticks_range`) n'est pas implémentée.
5. **Calendrier d'annonces** : règle NFP seulement (premier vendredi, 08:30 New York). CPI/FOMC/BCE exigent un CSV (`--news-csv time,name`). Sans lui, le filtre d'annonces et `news_momentum` sont incomplets.
6. **Règles FTMO** : valeurs recoupées par recherche web (sources tierces) le 2026-10-21 ; ftmo.com inaccessible ici. Un blog évoque un « 1-Step » 2026 (3 % journalier, drawdown suiveur) : non figé. Profil futures (Lucid-like) : blogs divergents. **Re-vérifier avant tout achat.**
7. **Filtre ML sur la période verrouillée** : non évalué (modèle gelé non persisté) ; il est évalué walk-forward sur la recherche.
8. **Calibration sur séries réelles mélangées** : implémentée (`calibrate --data-dir/--mt5`) mais non exécutée (pas de données réelles).
9. **Limites méthodologiques** : (a) le test nul est évalué sur la variante modale des plis, pas sur la procédure complète de sélection ; (b) la décision « scoring conservé/supprimé » est prise sur les fenêtres OOS (fuite légère, documentée) ; (c) la simulation de recherche est par instrument, sans compétition de capital (le portefeuille, lui, est simulé multi-instruments avec gardien) ; (d) 0 faux PASS observé ne prouve pas un taux < 5 % si peu de séries : voir la borne haute publiée.

## 6. Prochaines étapes (sur votre machine)
```bash
pip install -r requirements.txt MetaTrader5
python -m ftmo_algo data-check --mt5 --instruments US500,US100,US30,GER40,XAUUSD,EURUSD,GBPUSD,USDJPY --start 2020-01-01
python -m ftmo_algo research   --mt5 --instruments US500,US100,US30,GER40,XAUUSD,EURUSD,GBPUSD,USDJPY --start 2020-01-01 --workers 4 --news-csv calendrier.csv
python -m ftmo_algo calibrate  --mt5 --instruments ... --n 20     # séries réelles mélangées incluses
python -m ftmo_algo target
```
Puis : relire `results/latest.json`, **ne jamais relancer `research` pour « améliorer » le verdict de la période verrouillée** (le code refuse une 2ᵉ évaluation) ; si ≥ 1 algo PASS : `paper`, puis `demo` ≥ 4 semaines, puis `gate`.
