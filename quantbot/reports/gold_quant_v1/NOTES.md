# gold_quant_v1 — 5 stratégies de scalping quantitatif sur l'or (XAUUSD M15, 07-17 UTC)
Spec préenregistrée (commit d155960) AVANT exécution. 5 essais comptés (registre : 84 / 120). Tranche verrouillée non lue.

| Stratégie | Trades | Espérance | PF | Verdict |
|---|---|---|---|---|
| gq_sweep (balayage de liquidité) | 704 | -0,028 R | 0,90 | FAIL |
| gq_asia_break (cassure range Asie) | 286 | -0,006 R | 0,99 | FAIL |
| gq_ema_pull (repli EMA20 en tendance) | 870 | +0,026 R | 1,08 | FAIL (nulle, DSR, Monte-Carlo) |
| gq_squeeze (compression -> cassure) | 132 | -0,033 R | 0,89 | FAIL |
| gq_zrev (retour à la moyenne) | 137 | -0,008 R | 0,97 | FAIL |

Seule gq_ema_pull est positive (+0,026 R, achats +0,045 R / ventes -0,005 R) : même profil que le bêta haussier de l'or, sous tous les seuils (espérance requise 0,15 R). Aucun avantage démontré.
Limites : M15 seulement (pas de vrai scalping M1/M5 : export requis), pas de delta de volume, coûts = spread mesuré + hypothèses.
