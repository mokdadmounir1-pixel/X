# Cahier des 3 stratégies + 2 règles d'accompagnement : état dans quantbot (2026-11-01)

PAPER uniquement, 0 essai consommé (sauf `trend_multi_v1` : 1 essai à l'exécution du script). Aucune valeur démontrée. Les écarts avec le cahier sont listés ci-dessous sans les cacher.

| Cahier | Module / spec | Écarts déclarés |
|---|---|---|
| 1. IBS + RSI(2) + MM200, séance cash, long seulement | `strategies/ibs_rsi2_trend.py`, `specs/ibs_rsi2_v1.json` (US : `ibs_rsi2_trend` sur USTEC/US500/US30 ; GER40 : variante `ibs_rsi2_trend__de` sur DE40, séance 09:00-17:30 Paris) | Décision à la CLÔTURE de la dernière barre M15 de la séance (pas 5 min avant : les barres M15 ne le permettent pas). Sortie « 1re clôture de séance > clôture de la séance d'entrée » ou 3 séances : règle `exit_rule` (nouveau crochet moteur, causal). Fermeture du vendredi : coupure week-end du moteur (`weekend_cutoff_hour` 21 Paris) à l'heure près, pas 21h50 exact. Il faut >= 200 séances d'historique : fenêtre élargie (`history_bars` 24000 en direct, `min_bars` 36000 dans le banc d'essai). |
| Bloc corrélé US500/US100/US30 = un seul pari | `exclusive_group: US_BLOCK` ; fichiers-témoins entre lanceurs (`live/runner._group_blocked`) | Appliqué en PAPER (lanceurs en parallèle) ; non appliqué dans un backtest d'un seul instrument. |
| 2. Noise Area | `strategies/noise_area.py`, `specs/noise_area_v1.json` (USTEC, US500) | Adaptation M15 du M1 (décisions aux demi-heures : le prix à 10:00, 10:30... est la clôture de la barre M15 qui finit à cette heure). VWAP pondéré par les ticks. Stop suiveur évalué aux demi-heures ; stop dur initial entre-temps. Test de coûts 10 ans M1 avec le vrai spread FTMO : IMPOSSIBLE ici (données absentes) ; filtre `max_cost_r` 0,3 actif. |
| 3. Trend following multi-actifs (compte financé) | `stat/trend_multi.py`, `scripts/run_trend_multi.py`, `specs/trend_multi_v1.json` | Script de recherche (1 essai) : >= 8 marchés avec >= 1500 jours de H1 dans `data/live`. Swaps NON CONNUS (exclus, déclarés). Commission = hypothèse. Non exécuté ici (historique H1 sur le PC de l'utilisateur seulement). |
| Filtre fin de mois (x1,25) | dans `ibs_rsi2_trend` (`eom_factor`) | Jours fériés boursiers non modélisés (dernier jour OUVRÉ lundi-vendredi). |
| Ciblage de volatilité (plafond 1,5), perte du jour -2 %, drawdown -5 % | taille : `size_factor` (base 0,4 % / plafond 0,75 %) ; `risk.max_daily_loss` 0,02 ; `active_risk` (frein linéaire dès -5 %, plancher x0,5, arrêt à -8 %) | Le frein de drawdown est linéaire (pas un simple « divisé par deux »). |

## Nouveautés d'infrastructure (aucun effet sur les stratégies existantes)
- `exit_rule` : une stratégie peut fournir une règle de sortie causale appelée sur le passé (`TradingEngine`, branche PAPER/backtest).
- `external_halt` + `exclusive_group` : blocage inter-lanceurs.
- `history_bars` / `min_bars` : fenêtre de données propre à une stratégie.

## Jugement
>= 4 semaines ET >= 60 trades PAPER sans toucher aux paramètres ; espérance > 0,15 R ; comparaison à l'achat-conservation (bêta des indices). Le cahier annonce un taux de réussite de 60-70 % avec un R:R < 1 pour l'IBS : le seuil d'équilibre doit être lu avec lui (voir `win_profile`).
