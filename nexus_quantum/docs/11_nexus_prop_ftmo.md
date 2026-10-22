# 11 — NEXUS PROP : FTMO 100k 2-Step (sprint 2)

## Règles utilisées [HYPOTHESE — sources tierces, site FTMO inaccessible ici]
Phase 1 : +10 % ; Phase 2 : +5 % ; perte journalière max 5 % (mesurée sur l'equity, reset minuit CE(S)T selon une source) ; perte max 10 % statique ; 4 jours de trading minimum par phase ; sans limite de temps. **À vérifier sur ftmo.com** (conditions, news, EA, swing) avant tout déploiement. Paramétrées dans `nexus/prop/rules.py`.

## Ce qui a été construit
- `rules.py` : `FtmoRules` + `Governor` (réduction linéaire de l'exposition dès 98 % d'equity, zéro à 93 % ; stop jour interne 3 % ; refuse d'être plus lâche que les règles FTMO).
- `strategy.py` : TSMOM multi-actifs, cible de volatilité (10 %/an par défaut), barres journalières, coûts forfaitaires. Test anti look-ahead par troncature.
- `challenge.py` : simulateur 2-step par bootstrap stationnaire (PASS / FAIL_DAILY / FAIL_MAX / TIMEOUT).
- `data.py` : chargeur CSV validé (dates, prix, hash de provenance), alignement multi-actifs.
- `scripts/prop_pipeline.py` : protocole 70 % sélection / 30 % **test final ouvert une seule fois**, tous les essais enregistrés (négatifs inclus), DSR avec N réel, portes, simulation FTMO.

## Résultats [SYNTHETIQUE] (`prop_pipeline_synthetic_output.txt`, un tirage chacun)
| Jeu | Meilleur IS | DSR | Test final (SR ann., IC95 %) | Décision |
|---|---|---|---|---|
| Sans edge | 0,07 | 0,37 | −0,39 [−1,15 ; 0,40] | rejeté (correct) |
| Momentum injecté (φ=0,08) | 0,77 | 0,865 | 0,31 [−0,50 ; 1,12] | rejeté |

Lecture honnête : même avec un edge **réel** injecté, ~4,5 ans de barres journalières ne permettent pas de le valider (IC trop large). Conséquence pratique : un edge modeste de trend daily ne sera pas démontrable sur 5 ans de données ; il faut soit un historique long (>15 ans), soit des stratégies à plus fort nombre d'observations (intraday), soit accepter un risque non prouvé — décision humaine, pas du système.
Le simulateur montre que sans edge la probabilité de passer est faible mais non nulle (phase 1 : 19 % sur 504 jours avec le bruit de l'échantillon) : **une réussite de challenge isolée ne prouve rien**.

## Ce qui manque avant toute démo FTMO
1. **Données réelles** : exports MT5 (D1 puis M1/M15) des instruments FTMO — je n'y ai pas accès (hôtes de données bloqués). Placez des CSV `date,close` dans un dossier et lancez `python scripts/prop_pipeline.py --csv-dir DIR`.
2. Intra-jour : la perte journalière FTMO se mesure sur l'equity flottante ; la simulation en barres D1 ne voit pas les pires points intra-jour → exiger M1/M15 avant live.
3. Swaps, spreads variables, news, week-ends, fuseau horaire du reset, coûts réels FTMO.
4. Pont MT5 (Windows) + `RiskGuardian` branché en ligne + réconciliation + shadow/démo (Phase 3, backlog X-1/X-2).
5. Validation indépendante et autorisation humaine ; le challenge réel est payant : ne pas le lancer sans passage des portes G0–G11.
