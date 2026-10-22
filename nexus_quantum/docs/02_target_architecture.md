# 02 — Institutional Target Architecture

## Principe directeur
Monolithe modulaire Python (un dépôt, un processus de trading + un processus gardien séparé). Pas de microservices tant qu'une mesure ne les justifie pas. Rust/C++ seulement après profilage montrant qu'un edge dépend de la latence.

## Composants (raison d'être · interface · échec · récupération · contrôleur)
| # | Composant | Interface | Échec détecté par | Récupération | Contrôleur | Statut |
|---|---|---|---|---|---|---|
| 1 | Ingestion | `Source → RawEvent` (horodatage réception + source) | séquence/gap, fraîcheur | resync snapshot | Data Auditor | à faire |
| 2 | Stockage brut immuable | append-only + hash (parquet/JSONL) | hash mismatch | restauration sauvegarde | Data Auditor | à faire |
| 3 | Registre d'expériences | `ExperimentRegistry.record/verify/n_trials` | `verify()` | restauration + ancrage hash externe | Validator | **FAIT** (`nexus/registry.py`) |
| 4 | Stats/validation | `psr, dsr, purged_kfold, bootstrap` | tests unitaires | — | Skeptic | **FAIT** (`nexus/stats.py`) |
| 5 | Modèle de coûts | `CostModel.round_trip/breakeven` | test arithmétique | — | Execution | **FAIT** (`nexus/costs.py`) |
| 6 | Risk Guardian | `check(Order)→Decision`, `halt`, `reconcile`, `request_*`/`confirm` | tests + fault injection | restart autorisé seulement | CRO | **FAIT noyau** (`nexus/risk.py`) |
| 7 | Moteur événementiel + simulateur de file | `on_event` | calibration vs journaux réels | — | Execution Scientist | Phase 1/5 |
| 8 | Strategy engine | `Strategy.on_event → Intent` (jamais d'ordre direct) | — | désactivation | Strategy Eng. | Phase 2 |
| 9 | Allocator | `Intent → Order proposé` | — | — | CQO | Phase 2 |
| 10 | OMS/EMS + adaptateurs | idempotence par `order_id`, ack, fills = vérité | écart de position | réconciliation | Exec | Phase 3 |
| 11 | Monitoring/alerting/audit | métriques P50–P99.9, journal | watchdog externe | — | Infra | Phase 3 |
| 12 | Dashboard | lecture seule | — | trading indépendant | Infra | tardif |

Chemin d'ordre unique : `Strategy → Allocator → Risk Guardian → OMS → Broker`. Le Guardian tourne dans un processus séparé avec **son propre** flux de positions broker ; la perte du dashboard n'affecte rien.

## Environnements
Research (sans clés d'ordre) → Backtest → Simulation événementielle → Shadow → Paper → Live minimal → Live. Promotion = enregistrement signé dans le registre + `authorize_*` humain. Clés live uniquement dans l'environnement live (gestionnaire de secrets, droits minimaux, pas de retrait).

## Alternatives écartées
- *Microservices/Kafka dès le départ* : latence, surface d'attaque, complexité sans besoin mesuré → écarté.
- *Réutiliser ftmo_algo comme base* : inaccessible, et la consigne impose l'indépendance → écarté ; seuls des **comportements validés** pourront être réimplémentés comme tests de non-régression après audit.
- *Deep learning par défaut* : écarté (voir 03).
- *Stdlib-only pour le noyau* : choisi (auditabilité, zéro supply-chain) ; numpy/pandas admis en recherche, jamais dans le Guardian.
