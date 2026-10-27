# twelve_v1 — résultats (3 essais, registre : 117/120)
Or M15, tranche verrouillée non lue. Aucune stratégie ne passe.
| Stratégie | Trades | Espérance | PF | Verdict |
|---|---|---|---|---|
| kalman_ou (t_max −2,0) | 271 | −0,019 R | 0,94 | FAIL |
| orderflow_iceberg (proxy volume/range) | 964 | +0,006 R | 1,01 | FAIL |
| fixing_seasonality | 923 | −0,022 R | 0,92 | FAIL |
Constats : l'effet « achats > ventes » de l'or se retrouve (iceberg : achats +0,094 R, ventes −0,103 R) = bêta haussier, pas d'alpha. `t_max` fixé en comptant les événements, pas la performance.
