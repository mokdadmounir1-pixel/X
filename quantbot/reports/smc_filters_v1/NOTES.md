# smc_filters_v1 — corriger les SMC H4/M15 en comparant GAGNANTS ET PERDANTS (2026-11-01)

Méthode : six filtres prédéclarés, seuil = médiane de la PREMIÈRE moitié chronologique de la période de recherche, au plus un filtre par stratégie (permutation p < 0,10, >= 60 trades gardés, 3 instruments regroupés). Tranche verrouillée jamais lue. Spec commitée AVANT la lecture de la seconde moitié.

## Entraînement (1re moitié) — `TRAIN.json`
| Stratégie | n | E | Filtre retenu |
|---|---|---|---|
| smc_h4 | 49 | -0,240 R | aucun (trop peu de trades) |
| smc_h4_free | 108 | -0,154 R | aucun |
| smc_m15 | 443 | -0,333 R | session 07-20 UTC |
| smc_m15_free | 992 | -0,183 R | stop large (>= 1,37 ATR M15) |
Observation NON exploitée : en H4, « tendance D1 alignée » sépare nettement (garde +0,84 R sur 18 trades ; +0,56 R sur 39) mais n < 60 : règle prédéclarée non remplie, hypothèse à tester en PAPER, pas de filtre ajouté après coup.

## Test confirmatoire (2e moitié) — `TEST.json`, 2 essais (registre : 120)
| Variante | Filtrée | Non filtrée | Verdict |
|---|---|---|---|
| smc_m15_f (session) | 242 trades, -0,042 R, PF 0,84 | 404 trades, -0,038 R | NON CONFIRMÉ (p = 0,86) |
| smc_m15_free_f (stop large) | 474 trades, -0,054 R, PF 0,86 | 930 trades, -0,058 R | NON CONFIRMÉ (p = 0,89) |

Conclusion : l'amélioration vue sur la 1re moitié ne se retrouve pas sur la 2e : elle réduit le nombre de trades (donc la perte totale) sans changer l'espérance par trade (≈ -0,04 à -0,06 R). Aucune correction démontrée.
