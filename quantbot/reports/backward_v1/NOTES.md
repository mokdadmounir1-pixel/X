# backward_v1 — résultat complet (13 combinaisons, 2e exécution du 2026-10-25 18:01 UTC)

Stratégies FIGÉES de inst_strategies_v1, paramètres inchangés, sur 10 mois de M15 qui PRÉCÈDENT la période de recherche (or 2022-07-22 → 2023-05-29, EURUSD 2022-10-14 → 2023-08-03, USTEC 2022-07-06 → 2023-03-30).
La 1re exécution avait planté à l'affichage (cp1252) après un seul essai ; la 2e les a tous calculés (EURUSD amd recalculé : mêmes trades, seuls les seuils liés au nombre d'essais changent). Registre : 55 -> 67 essais.

**13 FAIL.** Un seul est proche : **USTEC orb** : 101 trades, +0,166 R, PF 1,44, tous les seuils passés sauf `null_test` (p = 0,026 contre un seuil corrigé de 0,0016) et `deflated_sharpe` (0,28).
Même signe que la recherche (284 trades, +0,075 R, p = 0,034). Autres positifs : or amd +0,037 R, or fvg_h4 +0,028 R, USTEC fvg_h4 +0,047 R (le dernier était négatif en recherche : instable). Tous les autres sont négatifs.

Lecture honnête : un candidat sur 13 avec p = 0,026 est environ ce que le hasard donne ; ce qui est notable est le MÊME signe positif sur deux périodes disjointes (p combinés ≈ 0,007 par Fisher, mais sélection parmi 13 : ≈ 0,09 corrigé).
Statut : à SURVEILLER, pas confirmé. Prochaine étape honnête : l'échantillon futur (specs/forward_eval_v1.json) ; l'ORB fait ~110 trades/an : 60 trades futurs = plusieurs mois.
Points ouverts : USTEC `trade_mode = 0` sur le compte démo (à vérifier en séance), horloge DST non vérifiée avant 2023 (l'ORB dépend de l'ouverture de 09:30 New York), segment court (0,73 an).
