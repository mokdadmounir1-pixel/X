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

---
# Addendum — données réelles FTMO M5 (5 instruments, 2022-01 → 2026-09)

## Provenance et qualité [VERIFIE sur les fichiers fournis]
US100, US500, XAUUSD, GBPUSD, GER40 en M5 avec spread par barre. Audit (`nexus/prop/mdata.py`) : 0 doublon, 0 retour arrière, 0 OHLC incohérent, 0 prix ≤ 0 ; ~250 interruptions >6 h par symbole (week-ends/fêtes) ; spreads nuls : 17–82 barres, **2 888 pour GER40** (artefact, planché au P10 des spreads positifs). SHA-256 enregistrés dans le registre. Le contenu des fichiers n'a pas pu être confronté à une source externe : on suppose qu'il est exact.
**Heure serveur = EET/EEST (GMT+2/+3), pas CET** : pics de volume à 10:00 (GER40) et 16:30 (US), identiques en hiver et en été. Donc ouverture 10:00 (GER40/GBPUSD/XAUUSD) et 16:30 (US), fermetures 18:30 / 23:00 ; minuit CET = 01:00 serveur [HYPOTHESE: reset FTMO].

## Protocole (figé avant exécution) et résultat [VERIFIE données, SIMULE performance]
IS jusqu'au 2024-12-31 (935 jours), test final verrouillé 2025-01-01→2026-09 (540 jours), ouvert **une seule fois**. 13 variantes pré-enregistrées : 6 ORB (range 15/30/60 min × sortie fin de session/2R, 5 instruments), 1 momentum intraday (30 premières/dernières minutes, 3 indices), 6 TSMOM journaliers. Coûts : spread réel de chaque barre + slippage 0,25×spread médian par côté [HYPOTHESE], fill à l'ouverture de la barre suivante, stop prioritaire sur cible, gaps au prix d'ouverture.

| | |
|---|---|
| Retenue (meilleur Sharpe IS) | ORB 30 min, sortie fin de session : SR 0,78, PSR 0,939 |
| **DSR (N=13)** | **0,548** → < 0,95 |
| Test final | SR annualisé **0,33**, IC95 % **[−0,90 ; 1,53]**, PSR 0,688, PnL +8,9 % à 0,25 %/trade |
| Pire jour / pire intra-jour (test) | −1,26 % / −2,59 % |
| **Décision** | **REJETÉ : aucun edge démontré. Ne pas acheter le challenge sur cette base.** |

Autres faits : 12 variantes sur 13 ont un SR IS positif (0,28–0,78) et le momentum intraday −0,92 ; l'accord entre variantes ressemble à un facteur commun (marché haussier 2022-2026 sur les indices), pas à des edges indépendants [HYPOTHESE, non testée]. Je n'ai **pas** regardé le test final des variantes non retenues : le faire serait du data snooping.
La simulation FTMO (bootstrap des jours, perte intra-jour réelle) donne pour ce candidat rejeté 31 % de réussite des deux phases à 0,25 %/trade (OOS) ; elle baisse quand le risque monte (faillites quotidiennes dès 0,5 %/trade). Ce chiffre est celui d'une stratégie **non validée** : il n'a pas valeur de promesse.

## Suite recommandée
(1) Plus d'historique (≥10 ans, y compris 2018-2021) pour le même protocole ; (2) nouvelles hypothèses enregistrées **avant** test (chaque essai augmente N) ; (3) mesurer les spreads/slippage réels en démo FTMO ; (4) tester l'hypothèse « facteur commun » (régression sur un benchmark long) ; (5) aucune mise à l'échelle du risque tant que le DSR n'est pas ≥ 0,95. Sortie complète : `prop_m5_pipeline_output.txt`.
