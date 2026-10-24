# quantbot

Bot de trading quantitatif **isolé** (aucun import de Nexus, de `ftmo_algo`, de `micro_scalping` ni de `fx_liquidity_bot`).
Principe directeur : **un seul cœur de vérité**, des setups à **logique floue** (scores continus, tolérances réglables),
une validation qui punit le nombre d'essais, et **aucun ordre réel** tant que les portes de décision humaines ne sont pas franchies.

## État réel (phases 0-1 du plan terminées, phase 3-4 en cours)

| Phase | Contenu | État |
|---|---|---|
| 0 | Hygiène : projet isolé, ancienne validation/boucle supprimées | fait |
| 1 | Moteur unique, statistiques, registre d'essais, période verrouillée, portes calibrées | fait, testé |
| 2 | Couche floue v2 : specs déclaratives, calibration score → proba, agrégation par familles | **à faire** |
| 3 | Données réelles MT5 : horloge, trous, coûts | fait pour 3 instruments (voir `reports/`) |
| 4 | Première recherche réelle préenregistrée (`specs/baseline_v0.json`) | en cours / voir `reports/baseline_v0/` |
| 5 | Boucle d'amélioration : IA propose des specs, suivi en ombre, probation, retour arrière | à faire |
| 6 | Exécution MT5 démo durcie (`order_check`, filling, rapprochement) | à faire |
| 7 | Réel / FTMO | **décision humaine** ; jamais automatique |

`execution/broker.py::MT5Broker` existe mais **n'a été testé que contre un faux module MT5** et n'est branché sur aucune commande.

## Arborescence (réelle)
```
quantbot/
  core/sim.py            MOTEUR UNIQUE (backtest = paper = démo) : on_bar, trous de données, garde-fou
  backtest/              rejeu du moteur + métriques
  data/                  validation OHLCV, CSV/ccxt, mt5.py (horloge courtier -> UTC, trous, coûts)
  indicators/            EMA/RSI/ATR/pivots confirmés
  patterns/              détecteurs flous (chandeliers, figures, harmoniques) + tolérance
  signals/               agrégation en un signal (confiance, confluence, filtre de tendance)
  risk/                  sizing ATR, limites journalières, garde-fou FTMO (limites internes avant les limites dures)
  execution/             PaperBroker ; MT5Broker (triple verrou, non éprouvé en réel)
  lab/                   stats (DSR, MinTRL, Monte-Carlo par blocs, test nul, Reality Check), registre d'essais
                         chaîné par hachage, période verrouillée, portes, pipeline d'évaluation
  ai/                    adaptateurs Claude / ChatGPT / Gemini (opt-in), orchestrateur à sorties JSON bornées
  improvement/           diagnostic + liste blanche de paramètres + journal des leçons
  memory/                SQLite (expériences, trades, leçons)
specs/                   spécifications PRÉENREGISTRÉES (hypothèse, coûts, seuils, hachages des données)
scripts/                 calibrate_gates.py, baseline_real.py
data/real/               exports MT5 (CSV ignorés par git ; empreintes dans PROVENANCE.json)
```

## Garanties et leurs limites
- **Un moteur.** `Backtester` rejoue `TradingEngine.on_bar` ; un test vérifie qu'alimenter le moteur barre après barre
  (avec barres répétées) donne exactement les mêmes trades. Signal à la clôture de t, exécution à l'ouverture de t+1,
  stop prioritaire si stop et cible dans la même barre, gap au-delà du stop exécuté à l'ouverture.
- **Pas de look-ahead** : testé en altérant le futur. Pivots confirmés par `order` barres.
- **Trous de données** (> `backtest.max_gap_hours`) : position clôturée, ordre annulé, contexte et ré-échauffement réinitialisés.
- **Horloge MT5** : la colonne `time` du CSV fourni (courtier − 3 h fixe) est **fausse d'1 h en hiver**. `load_mt5_csv` reconstruit
  l'UTC depuis `time_broker_epoch` (UTC+3 en heure d'été US, UTC+2 sinon) ; contrôle : ouverture hebdo 21:00 UTC l'été / 22:00 l'hiver.
  Les 1-2 heures autour de chaque changement d'heure restent ambiguës.
- **Coûts** : un spread nul n'est jamais pris pour un coût nul. Le spread EURUSD de l'export est inutilisable (44-83 % de zéros) :
  une hypothèse déclarée est utilisée. Commission et slippage ne sont pas fournis : hypothèses déclarées, à re-mesurer sur le compte cible.
- **Statistiques** : le DSR compte tous les essais du registre (chaîné par hachage : toute altération est détectée) ;
  lire la période verrouillée est un essai de plus, une seule fois par spec, enregistré avant exécution (même en cas de crash).
- **Calibration des portes** (`scripts/calibrate_gates.py`) : marchés synthétiques sans edge + signal oracle, 120 séries x 5000 barres :
  **1 faux PASS (borne haute 95 % = 3,9 %)** ; 24/24 PASS sur edge planté fort. Avec ~3000 barres (moins de trades) le taux mesuré
  montait à 4/60 : la puissance dépend du nombre de trades. **Ce n'est pas une preuve de puissance sur marché réel.**

## Logique floue (phase 2 à venir)
Aujourd'hui : chaque détecteur renvoie un score 0..1 (rampe avec plateau : plein score sous `tolerance_percentage`, zéro au-delà de
`deviation_threshold`), seuil `min_score`. Les contrôles de sécurité restent des rejets stricts. Ces scores ne sont **pas** des probabilités.

## Utilisation
```bash
pip install -r requirements.txt && python -m pytest -q          # tests rapides ; python -m pytest -m slow pour la calibration
python -m quantbot audit-data --mt5-csv data/real/EURUSD_M15.csv
python scripts/baseline_real.py specs/baseline_v0.json           # recherche (jamais la période verrouillée)
python scripts/baseline_real.py specs/baseline_v0.json --locked  # lecture UNIQUE de la période verrouillée, une fois par spec
```
IA (optionnelle) : `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GEMINI_API_KEY`. Gemini n'est utilisé que si sa clé est présente.
