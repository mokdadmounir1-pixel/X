# portfolio_v1 — toutes les stratégies combinées (22 combinaisons stratégie x instrument)
Spec préenregistrée avant exécution. 2 essais comptés (registre : 86 / 120). Tranche verrouillée non lue. 490 jours ouvrés.

| Schéma | R/jour | Sharpe annualisé | Corrélation moyenne | Drawdown | p (test nul) | Verdict |
|---|---|---|---|---|---|---|
| parité de risque | -0,041 | -2,05 | +0,00 | 20,9 R | 0,996 | FAIL |
| parité de risque + tilt sur la performance passée | -0,030 | -0,81 | +0,00 | 25,7 R | 0,841 | FAIL |

La diversification fonctionne (corrélations ~0 entre les flux) mais elle ne crée pas d'espérance : 22 flux sans avantage donnent un portefeuille sans avantage, légèrement négatif net des coûts. Objectif repère 0,33 R/jour : non atteint (résultat négatif).
