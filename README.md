# ftmo_algo — recherche algorithmique sélective, gros RR, anti-surapprentissage

Système de trading algorithmique pour passer et tenir des comptes prop firm (FTMO sur MT5, puis futures).
**Règle n°1 : on ne présente jamais un edge non validé.** Chaque résultat porte un statut :
`[VÉRIFIÉ]` (calculé sur données réelles), `[SYNTHÉTIQUE]`, `[HYPOTHÈSE]`.

> État honnête : le dépôt a été construit dans un environnement cloud **sans données réelles ni terminal MT5**.
> Tout ce qui est chiffré ci-dessous provient de données `[SYNTHÉTIQUE]`. Voir `ETAT_PROJET.md` pour les résultats
> et la liste de ce qui reste à vérifier sur votre machine.

Résultats publiés (synthétiques) : `reports/` ; journal de décisions, rejets et limites : `ETAT_PROJET.md`.

## Démarrage

```bash
pip install -r requirements.txt            # cœur : numpy, pandas, pyyaml (aucune autre dépendance)
python -m pytest tests -q                  # tests (le test de rejeu et la calibration prennent ~2 min)

# 1. données réelles (sur VOTRE machine, terminal MT5 ouvert) — 3 ans minimum, 5 recommandés
python -m ftmo_algo data-check --mt5 --instruments US500,US100,US30,GER40,XAUUSD,EURUSD,GBPUSD,USDJPY --start 2020-01-01
python -m ftmo_algo research   --mt5 --instruments US500,US100,US30,GER40,XAUUSD,EURUSD,GBPUSD,USDJPY --start 2020-01-01 --workers 4
python -m ftmo_algo target     # probabilité d'atteindre +5 %/mois, risque recommandé
```

Données CSV (Dukascopy, exports MT5) : `--data-dir dossier/` avec des fichiers `US500_M5.csv`, … (format, séparateur,
fuseau — `--tz Europe/Athens` si non UTC — et côté bid/ask détectés). Crypto via `ccxt` (`data.loaders.load_ccxt`).
Sans `--data-dir`/`--mt5`, les données sont **synthétiques** et étiquetées comme telles partout (CLI, JSON, dashboard).

| Commande | Rôle |
|---|---|
| `data-check` | rapport qualité par instrument (trous, doublons, bougies aberrantes, week-ends, heure d'été/hiver) |
| `research` | walk-forward + période verrouillée + 9 portes + test nul + DSR ; verdicts PASS/WATCH/FAIL (JSON + tableau) |
| `calibrate` | toute la recherche sur ≥ 20 marches aléatoires (et séries réelles mélangées) : **taux de faux PASS** |
| `target` | module « cible mensuelle » : Monte Carlo, risque recommandé sous P(violation) < 5 % |
| `paper` | rejeu multi-agents (mêmes décisions que le backtest), journal SQLite |
| `dashboard --port 8767` | terminal web (vortex, chandeliers, agents, cible mensuelle, jauges prop firm) |
| `demo` | connexion au compte DÉMO MT5 (ou diagnostic précis de ce qui manque) |
| `install` / `bench` | boîte à outils open source (venv séparé) / comparatifs mesurés |
| `gate` | affiche les conditions de passage au réel (jamais automatique) |

## Architecture

```
ftmo_algo/
  instruments.py        specs (lots, spreads, commissions, swaps, groupes corrélés) — défauts [HYPOTHÈSE] à écraser par MT5 symbol_info
  data/                 loaders (MT5, CSV auto-détecté, ccxt), synth (synthétique), quality (rapport + MTF sans fuite)
  engine/               sim.py (moteur pessimiste unique), market.py, guardian.py (règles prop firm), news.py
  algos/                context.py (séries causales partagées), library.py (8 algos), base.py (interface commune)
  research/             wf.py (variantes, walk-forward, surrogates), gates.py, stats.py, ml.py, split.py (verrou),
                        pipeline.py, calibrate.py
  target.py             cible mensuelle (mesure, jamais objectif d'optimisation)
  live/                 agent.py, runner.py (paper/replay/démo, kill switches), feed.py, mt5_bridge.py, gate.py, journal.py
  dashboard/            server.py (http.server) + static/index.html (canvas, sans CDN ni Node)
  toolbox/              registry.py (38 projets), install.py, bench.py — environnement SÉPARÉ du cœur
  profiles/             ftmo_2step.yaml, futures_trailing.yaml
legacy/                 ancien code (micro_scalping, fx_liquidity_bot) conservé pour mémoire, non utilisé
```

### Moteur de backtest pessimiste (`engine/sim.py`)
- Signal à la clôture de la barre *i*, exécution à l'**ouverture de i+1**. Barres supérieures (H1/H4/D1) utilisables **uniquement une fois closes**.
- Prix BID ; achat à l'ask (+spread variable selon l'heure, ×3 autour des annonces) ; slippage majoré autour des annonces ; commissions ; swaps (triple le mercredi).
- Stop et cible dans la même barre : **le stop gagne** (résolution sur M5 si disponible). Gap au-delà du stop : exécution à l'ouverture (**perte > 1 R possible**).
- Taille par risque fixe, arrondie au pas de lot réel, levier plafonné ; plafond de risque par groupe corrélé (US500/US100/US30 = un groupe) ; RR net < 2,5 refusé avant l'entrée.
- Gardien interne à 70 % des limites officielles, calculé sur l'**équité** (flottant inclus), reset à minuit **Prague** ; réserve de risque avant chaque entrée.
- Fermeture avant week-end : option `weekend_flat` (variantes de sortie testées).

### Les 8 algos (`algos/library.py` : hypothèse économique et invalidation écrites dans chaque classe)
`trend_pullback`, `sweep_reversal`, `squeeze_breakout`, `session_orb` (le breakout d'ouverture n'a droit à aucune faveur),
`meanrev_z`, `news_momentum`, `regime_router`, `ml_filter` (logistique walk-forward, labels triple-barrière, purge + embargo, qui FILTRE les autres).
Chaque algo passe par la grille de paramètres × 6 sorties testées (cible fixe, break-even, partielle, trailing ATR, trailing structure) :
la sortie est choisie sur l'entraînement uniquement, jamais supposée.

### Protocole anti-surapprentissage (`research/`)
1. **Période verrouillée** (≥ 12 derniers mois et ≥ 20 %) : physiquement retirée des données de recherche (`split.py`), évaluée **une seule fois** (marqueur disque), publiée telle quelle.
2. Walk-forward ancré (plis de 3 mois, embargo 5 j) ; la variante est choisie sur l'entraînement, évaluée sur le pli suivant.
3. **PASS = 9 portes** : ≥ 60 trades OOS · espérance ≥ +0,3 R · PF > 1,3 · bat un marché nul (block-bootstrap à inversion de signe aléatoire, p corrigé de Šidák pour le nombre d'algos) · survit à des coûts ×2 · Monte Carlo p5 de l'équité finale > capital · < 50 % du profit dans les 3 meilleurs trades · plateau de paramètres · séries de pertes / drawdown p95 compatibles avec le profil prop firm (marge 40 %). S'ajoute le **Deflated Sharpe** (tous les essais comptés) ≥ 0,5.
4. Moins de 3 ans de données ⇒ verdicts plafonnés à **WATCH** (raison affichée).
5. **Calibration** : `calibrate` rejoue toute la chaîne sur des séries sans edge et publie le taux de faux PASS.
6. Scoring A+/A/B conservé **seulement** si A+ > A > B est prouvé hors échantillon ; sinon supprimé (et le dit).
7. Reproductibilité : hash des données + version du code + graine dans chaque résultat.

### Profils prop firm (`profiles/*.yaml`)
FTMO 2 étapes : perte jour 5 %, perte max 10 %, objectif 10 %, 4 jours min, reset minuit Prague, mesurés sur l'équité.
**Vérification du 2026-10-21 via recherche web (sources tierces) : le site ftmo.com est inaccessible depuis le cloud. Re-vérifiez les valeurs sur ftmo.com avant tout achat** (un blog évoque un « 1-Step » 2026 à 3 % journalier / drawdown suiveur, non figé ici). Le profil futures (drawdown suiveur fin de journée) repose sur des blogs qui divergent : à confirmer.

## Lecture honnête des résultats

- **+5 %/mois en unités de risque.** À 0,5 % de risque par trade, +5 % = **+10 R nets/mois** ; à 1 % = +5 R ; à 0,25 % = +20 R. Avec une espérance nette de +0,3 R par trade (seuil de la porte 2), il faut ~33 trades/mois à 0,5 % pour atteindre 10 R : c'est incompatible avec « très peu de trades très sélectifs » sauf espérance ≫ 0,3 R. La cible est une **mesure**, jamais une fonction objectif : `target` rééchantillonne le nombre de trades par mois et leurs résultats, puis dit si +5 % est atteignable avec P(violation) < 5 %, sinon donne le rendement mensuel réaliste.
- **Les séries de pertes existent.** Avec un taux de réussite de 25–35 % (RR 1:3), 8–12 pertes consécutives sont normales ; à 0,5 % de risque c'est −4 à −6 % : c'est exactement pourquoi la porte 9 compare la série max p95 aux limites prop firm.
- **La période verrouillée compte plus que tout le reste.** Les 9 portes et le walk-forward réduisent le surapprentissage mais ne l'éliminent pas (de nombreuses variantes sont essayées) ; seule une évaluation unique sur des données jamais vues, publiée même si mauvaise, est une preuve. Relancer la recherche après avoir vu le verrou le détruit : le code refuse une 2ᵉ évaluation (`--force-relock` la trace comme infraction).
- Un résultat `[SYNTHÉTIQUE]` ne prouve **rien** sur le marché réel : il valide la mécanique (portes, absence de look-ahead, faux PASS) et rien d'autre.
- Les limites connues (conversion de devise approximative, calendrier d'annonces réduit à la règle NFP sauf CSV fourni, test nul évalué sur la variante modale, spreads synthétiques) sont listées dans `ETAT_PROJET.md`.

## Amélioration continue des stratégies (`evolve`)

Les stratégies ne sont pas jugées une fois pour toutes : une boucle les surveille et les fait évoluer **sur preuve**.
Chaque mois (pas configurable), pour chaque algo, avec uniquement les données antérieures à la date :
1. **Santé** : l'espérance récente du champion est comparée à sa référence (z-score + CUSUM) → SAIN / DÉGRADÉ / **PAUSE** (l'algo cesse de trader tant qu'il ne redevient pas positif).
2. **Recherche** : déclenchée par une dégradation ; sur un champion qui gagne, seulement tous les 3 pas et avec une avance d'entraînement nette (« peut-on gagner plus ? »). Candidats : autre variante, et/ou **exclusion de zones perdantes** (sessions, jours, instruments) trouvées par `insights` (permutation + correction Šidák).
3. **Ombre** : le candidat est suivi **sans être tradé** pendant 2 mois ; il n'est promu que s'il bat le champion sur ces données neuves (avance ≥ 0,10 R/trade, probabilité bootstrap ≥ 80 %, espérance > 0, ≥ 12 trades), avec carence et ≤ 3 promotions/an.
4. **Probation** : après promotion, retour arrière automatique si le nouveau fait pire que l'ancien.
5. **Journal** (`evolution_journal.jsonl`) : chaque décision, ses chiffres et son statut ; les trouvailles d'`insights` sont des `[HYPOTHÈSE]` jamais appliquées sans passer l'ombre.

Le compromis, simplement : plus la boucle bouge souvent, plus elle risque de coller au bruit (surapprentissage) ; les garde-fous ci-dessus la rendent lente et exigeante exprès. **Preuve de valeur** : la boucle est comparée à la configuration initiale figée sur les mêmes mois (gain en R/mois avec IC95) ; elle est jugée « utile » seulement si l'IC95 est > 0.

```bash
python -m ftmo_algo evolve --mt5 --instruments US500,EURUSD,XAUUSD --start 2020-01-01 --out results           # un passage
python -m ftmo_algo evolve --mt5 ... --loop --every-hours 24 --resume                                          # en continu sur votre machine
python -m ftmo_algo evolve --mt5 ... --locked --tag v1                                                         # évalue UNE fois la procédure sur la période verrouillée
python -m ftmo_algo evolve-calibrate --n 40                                                                    # comportement sur scénarios nul / stable / dégradation
```
`paper`/`dashboard` utilisent automatiquement `results/evolved_config.json` (champions promus, algos en pause exclus). Le dashboard affiche le panneau « amélioration continue ».
**Réel** : les promotions s'appliquent automatiquement en paper/démo ; un compte réel reste soumis à `gate` (décision humaine).

## Scalp / micro-scalp (M1)
`python -m ftmo_algo scalp-costs | scalp-research | scalp-calibrate` : même chaîne (moteur pessimiste, walk-forward, période verrouillée, portes, test nul, DSR) sur barres M1,
avec étude des coûts et stress de retard d'exécution. Règles FTMO, résultats `[SYNTHÉTIQUE]`, limites et lancement sur votre machine : voir `SCALP.md`.

## Démo MT5 et passage au réel
`python -m ftmo_algo demo` (sur votre machine Windows, terminal MT5 ouvert, **compte démo**) : mêmes agents, ordres réels avec SL/TP côté courtier,
réconciliation prix demandé/exécuté/slippage, kill switch (gardien, flux coupé, écart d'exécution anormal, performance hors intervalle Monte Carlo → pause de l'agent).
Le pont **refuse tout compte non démo**. Le passage à un réel/challenge payant est une décision humaine : conditions affichées par `python -m ftmo_algo gate`
(verdict PASS + période verrouillée positive + ≥ 4 semaines de démo avec assez de trades + écart démo/backtest dans la norme).

## Boîte à outils open source
`python -m ftmo_algo install` crée `toolbox_env/`, installe 38 projets un par un, vérifie chacun par un **vrai import**, clone les sources de référence dans `vendor/`,
tente des corrections (roue binaire seule, sans dépendances) et écrit `results/toolbox_status.json` (ok/failed + raison). Un échec n'affecte jamais le cœur.
`python -m ftmo_algo bench` publie les comparatifs mesurés ; un outil n'entre dans le cœur que s'il apporte un gain mesuré (aucun ne l'a fait pour l'instant).
