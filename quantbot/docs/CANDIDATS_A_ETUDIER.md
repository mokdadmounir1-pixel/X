# Stratégies candidates intégrées à quantbot (2026-10-31)

Toutes en simulation PAPER uniquement, 0 essai consommé (plafond d'essais : 500, décision écrite de l'utilisateur, `config/trial_budget.json`). Aucune n'est validée. Les références académiques sont citées de mémoire : **à vérifier avant de s'y fier**. Les paramètres ont été fixés en comptant le nombre d'événements seulement (jamais leur performance).

## Les deux candidats de l'utilisateur
| Candidat | État dans quantbot |
|---|---|
| **Attention Factors** (arbitrage statistique, 500 actions US, apprentissage profond) | NON exécutable : données absentes (univers d'actions, facteurs), code original non vérifié. Formules (coût de portefeuille, exposition brute, résidu) dans `quantbot/stat/equity_formulas.py`, testées. Catalogué dans « Autres modules ». |
| **ORB cinq minutes sur actions à volume inhabituel** | Module `orb_stocks_in_play` (code `ORB_STOCKS_IN_PLAY`), adaptation DÉCLARÉE : barres M15 (pas 5 min), volume = ticks du courtier, seuil absolu de RVOL (pas le classement des 20 meilleurs d'un univers). Spec `stocks_orb_v1` sans instrument tant que le courtier n'expose pas d'actions (`broker_profile.py`). Filtre de coût en R (le stop à 10 % de l'ATR rend les frais très lourds). |

## Cinq autres candidats (études + code)
| # | Module | Hypothèse (qui paie ?) | Règle figée | Limites |
|---|---|---|---|---|
| A | `gap_fade` | Les écarts d'ouverture modérés des indices se comblent (déséquilibres d'ordres nocturnes, liquidité) | Écart 09:30 NY vs clôture de la veille entre 0,25 et 1,5 x amplitude moyenne ; entrée à la clôture de la 1re barre contre l'écart ; cible = clôture de la veille | Un grand écart vient d'une nouvelle (ignoré) ; frais et spread du courtier |
| B | `ibs_reversion` | Une séance qui clôture près de son extrême est suivie d'un rebond (réversion de court terme) | IBS = (clôture-bas)/(haut-bas) <= 0,2 achat, >= 0,8 vente ; maintien ~1 jour | Pas de valeur démontrée ici ; bêta haussier possible |
| C | `rsi2_reversion` | Réversion de très court terme (Connors et Alvarez, à vérifier) | RSI(2) sur clôtures de séance <= 20 / >= 80 avec filtre de tendance 10 séances | Filtre court = adaptation du filtre classique à 200 jours (flux de ~1 mois) ; ~14 signaux en 2,5 ans sur USTEC : très peu de puissance |
| D | `turn_of_month` | Flux de fin/début de mois (salaires, rééquilibrages) (Lakonishok et Smidt 1988, à vérifier) | Achat à la clôture du dernier jour ouvré du mois, maintien ~4 séances | ~12 signaux/an ; jours fériés non modélisés ; surtout du bêta |
| E | `london_breakout` | Continuation après la cassure de la plage asiatique à l'arrivée de la liquidité de Londres | Cassure en clôture à +0,1 ATR entre 07h et 10h UTC, stop au bord opposé, cible 2 R ; une tentative par jour | Différent d'AMD (retour après balayage) ; heures UTC fixes (DST non modélisé) |

## Jugement (identique pour toutes)
>= 4 semaines ET >= 60 trades PAPER sans toucher aux paramètres ; espérance > 0,15 R ; comparaison obligatoire à l'achat-conservation de l'actif. Aucun backtest de recherche n'est lancé sans décision écrite : chaque exécution consomme un essai.

## Fichiers
`quantbot/strategies/{sessions,gap_fade,ibs_reversion,rsi2_reversion,turn_of_month,london_breakout,orb_stocks_in_play}.py`, `specs/{candidates_v1,london_breakout_v1,stocks_orb_v1}.json`, `tests/test_candidates.py`, `tests/test_equity_formulas.py`.
