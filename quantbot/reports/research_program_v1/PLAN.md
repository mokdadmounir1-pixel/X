# Programme de recherche v1 — 28 essais préenregistrés sur un plafond autorisé de 50 (2026-11-03)

Autorisation écrite de l'utilisateur : « utilise 50 essais pour de la recherche ». Plafond global : 500 (120 consommés avant ce programme). Ce programme n'en dépense que 28 ; les 22 restants ne sont pas utilisés.

Règle : chaque ligne = UN essai (stratégie x instrument), spécifications figées et DÉJÀ commitées (aucun paramètre modifié), tranche verrouillée de 12 mois jamais lue, portes de validation habituelles (espérance >= 0,15 R, PF, test nul, DSR sur TOUS les essais, Monte-Carlo, folds), pipeline `scripts/run_strategies.py`. Données disponibles ici : EURUSD, XAUUSD, USTEC (M15). Les autres instruments des specs (US500, US30, DE40, GBPUSD, USDJPY) ne sont pas dans ce jeu : non testés.
Aucun résultat n'est utilisé pour régler une stratégie : un échec est publié tel quel.

| # | Spec | Stratégie | Instruments |
|---|---|---|---|
| 1-4 | candidates_v1 | gap_fade, ibs_reversion, rsi2_reversion, turn_of_month | USTEC |
| 5-6 | institutional60_v1 | overnight_premium, intraday_momentum | USTEC |
| 7-8 | london_breakout_v1 | london_breakout | EURUSD, XAUUSD |
| 9 | ibs_rsi2_v1 | ibs_rsi2_trend | USTEC |
| 10 | noise_area_v1 | noise_area | USTEC |
| 11-13 | omega_v2 | omega | EURUSD, XAUUSD, USTEC |
| 14-19 | smc_orig_v1 | smc_h4, smc_m15 | EURUSD, XAUUSD, USTEC |
| 20-28 | smc_free_v1 | smc_h1_free, smc_h4_free, smc_m15_free | EURUSD, XAUUSD, USTEC |

Hors programme (non exécutables ici) : sig_tda, hawk_tox, leadlag_k (données/ticks absents), trend_multi (historique H1 sur le PC), stratégies sur indices absents du jeu.

## Addendum (2026-11-03, avant les essais suivants)
Essai n°2 (`candidates_v1` ibs_reversion, USTEC) : 309 signaux, 0 trade — le filtre R:R minimum du moteur (1,3) refuse les réversions dont la cible est plus proche que le stop. Défaut de conception, aucune performance vue. Amendement `specs/candidates_v1b.json` (seul changement : min_reward_risk 0,3), commité avant exécution ; ibs_reversion et rsi2_reversion y sont (ré)évalués : +2 essais (1 déjà gaspillé). Total du programme : 29 essais sur 50 autorisés.
