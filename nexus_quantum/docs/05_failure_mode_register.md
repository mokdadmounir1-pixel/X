# 05 — Failure Mode Register

Les scénarios 1–18 de la directive sont couverts ; colonnes : Signal · Prévention · Détection · Réaction auto · Réaction humaine · Détection max visée (TTD) · Récupération max (TTR) · Test d'injection · Retour en prod. Cibles TTD/TTR = **[HYPOTHESE]** à mesurer. « Test » = existant (✔ `tests/test_risk.py` etc.) ou à faire (☐).

| # | Scénario | Signal | Prévention / réaction auto | Humain | TTD / TTR | Test | Retour prod |
|---|---|---|---|---|---|---|---|
| 1 | Broker déconnecté | heartbeat manquant | gel entrées, `reduce_only`, réconciliation | contacter broker | 5 s / 15 min | ☐ adaptateur | `reconcile`+`authorize_restart` |
| 2 | Exécution sans confirmation | ordre « inconnu » | état = fills broker uniquement (`on_fill`), `reconcile` | vérifier compte | 10 s / 5 min | ✔ mismatch→REDUCE_ONLY | réconcilié |
| 3 | Ordre dupliqué | même `order_id` | déduplication `check` | — | 0 s / — | ✔ | — |
| 4 | Données retardées | âge > `max_data_age_s` | entrées refusées | enquête feed | 1 s / 5 min | ✔ | tick frais |
| 5 | Spread ×10 | spread/ATR, coût > edge | filtre de coût (`breakeven_ticks`) | — | 1 s / auto | ☐ filtre | spread normal N min |
| 6 | Flash crash | gap, perte jour | limites dures, halt | décider liquidation | 1 s / variable | ✔ halt perte (gap non simulé ☐) | `authorize_restart` |
| 7 | ML dégradé | dérive, perf shadow | désactivation, retour champion | revue | 1 jour / 1 h | ☐ | validation |
| 8 | Bug de sizing | qty/notionnel/risque hors limite | `max_order_notional`, `max_risk_per_trade` | — | 0 s | ✔ | correctif + tests |
| 9 | Position inconnue après restart | `reconciled=False` au démarrage | entrées bloquées | — | 0 s | ✔ | `reconcile` |
| 10 | Dashboard perdu | — | gardien indépendant | — | — | ☐ | — |
| 11 | Horloge désynchronisée | écart NTP, ts futurs | contrôle horodatages (à coder) | — | 10 s | ☐ | resync |
| 12 | Déploiement défectueux | smoke tests, erreurs | rollback, arrêt des entrées | — | 1 min / 10 min | ☐ CI | canary vert |
| 13 | Compromission d'identifiants | accès inhabituel | révocation, clés sans retrait | confinement | 1 min / 1 h | ☐ | rotation |
| 14 | Fausse amélioration | DSR/SPA | registre, test final verrouillé, audit | — | n/a | ✔ DSR | — |
| 15 | Hausse brutale des frais | grille tarifaire | recalcul `breakeven`, suspension | contrat broker | 1 jour | ✔ stress ×2 | edge recalculé |
| 16 | Changement de contrat/roll | expiration, spec | validation du roll, specs versionnées | — | 1 jour | ☐ | spec vérifiée |
| 17 | Arrêt de cotation | pas de ticks | donnée périmée⇒gel; ordres pendants à gérer | décision | 2 s | ✔ (péremption) | reprise cotation |
| 18 | Limites API | 429 / rejets | throttling, backoff, gel | — | 1 s | ☐ | débit ok |
| + | Défaillances simultanées / cause commune (ex. réseau+horloge+broker) | multi-alertes | **politique fail-safe unique : tout doute ⇒ pas d'entrée** | — | — | ☐ scénarios composés | — |

**Processus permanent** : revue post-incident et pré-mortem à chaque phase ; tout incident ou quasi-incident ajoute une ligne ici et un test. Aucune matrice n'est exhaustive. Les défauts de `ftmo_algo` seront ajoutés après audit (code non fourni).
