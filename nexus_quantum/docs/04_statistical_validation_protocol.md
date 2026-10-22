# 04 — Statistical Validation Protocol

Chaque stratégie → une **carte de validation** ; une porte échouée = rejet consigné au registre (jamais supprimé).

| Porte | Test | Seuil (à figer AVANT d'observer) | Outil |
|---|---|---|---|
| G0 | Provenance données + hash + disponibilité temporelle des features | 100 % traçable | Data Auditor |
| G1 | Enregistrement de l'hypothèse **avant** backtest | présent au registre | `registry.record` |
| G2 | Walk-forward + purge (horizon du label) + embargo | pas de fuite | `purged_kfold` |
| G3 | Coûts centraux **et** ×2 + latence stressée | espérance nette > 0 aux deux | `costs.py` |
| G4 | PSR(0) | ≥ 0,95 | `stats.psr` |
| G5 | **DSR** avec N = `registry.n_trials(famille)` | ≥ 0,95 | `stats.dsr` |
| G6 | IC bootstrap stationnaire de l'espérance nette | borne basse > 0 | `stationary_bootstrap_ci` |
| G7 | Nul spécifique (permutation de signes / décalage temporel / surrogates) | p < 0,05 corrigé | à implémenter |
| G8 | White RC / SPA contre baselines et toutes variantes essayées | p < 0,05 | à implémenter (Phase 2) |
| G9 | Stabilité param. (voisinage plat, pas un pic isolé) ; inter-instruments ; concentration des profits (top 5 % trades < 50 % du PnL) | — | à implémenter |
| G10 | Test final verrouillé (ouvert **une fois**) | passe | processus |
| G11 | Prospectif (shadow→paper), écart simulation/exécution | slippage réel ≤ hypothèse pessimiste | Phase 6 |

**Métriques jointes** (jamais isolées) : espérance nette, distribution des R, profit factor, drawdown, Sharpe/Sortino, CVaR, turnover, coût/trade, performance par régime, corrélation entre stratégies, P(perte extrême).

**Taille d'échantillon** : `required_sample_size(SR_par_période)` (iid, optimiste). Exemple [SYNTHETIQUE/calcul] : détecter SR=0,1 par période exige **619** observations (α=5 %, puissance 80 %) ; avec dépendance/queues épaisses, davantage. 100 trades rentables ≠ robustesse.

**Preuve que le garde-fou fonctionne** (`docs/sprint1_demo_output.txt`, [SYNTHETIQUE], une graine) : sur 1000 stratégies de bruit pur, le meilleur a un SR annualisé de 1,95 et un PSR=1,000 (faux positif certain) ; le DSR le ramène à 0,522 ⇒ non validé. Cette démonstration est un tirage unique, pas une distribution.

**Critère d'arrêt scientifique** : si aucune stratégie ne passe G0–G10 après coûts, conclusion = « aucun déploiement justifié ».
