# Rapport de validation — NEXUS v0.1 (ordre d'exécution 001)

Date : 20 octobre 2026. Environnement : Linux, 4 cœurs, 15,7 Go, PostgreSQL 16 réel (cluster jetable), Python 3.13, Node 22, Chromium. **Pas de démon Docker, pas d'Ollama, pas de n8n ni de Baserow.**

## Résultat des critères d'acceptation (§8)
| # | Critère | Verdict | Preuve |
|---|---|---|---|
| 1 | Les services démarrent selon une procédure documentée | **Partiel** | PostgreSQL + API + Dashboard démarrés à la main selon `GUIDE_DEMARRAGE.md` (« développement sans Docker »), migrations et création de comptes par la CLI. **`docker-compose.yml` jamais exécuté** (pas de démon). Ollama : faux serveur seulement. n8n, Baserow : non lancés. |
| 2 | Les données persistent après redémarrage | **Validé** | `test_data_persists_after_database_restart` (arrêt/relance de PostgreSQL) ; l'API de test a aussi été relancée avec les mêmes données. |
| 3 | Une sauvegarde a été restaurée | **Validé** | `test_backup_restore_roundtrip` (comptes de lignes identiques, chaîne d'audit saine, immuabilité conservée) **et** `scripts/backup.sh` + `restore.sh` exécutés sur la base de test : somme de contrôle OK, « Restauration réussie, chaîne d'audit saine », refus sur base non vide (code 2). |
| 4 | Une tâche se suit de bout en bout (journal + Dashboard) | **Validé** | `test_task_end_to_end_in_journal_and_dashboard` : `task.draft → queued → running → succeeded`, même identifiant de corrélation, nœud dans le Mesh, compteurs de la Vue exécutive. Parcours refait dans Chromium (Omni-Box → tâches exécutées par l'exécuteur réel → Journal → « Chaîne saine »). |
| 5 | Une commande interdite est refusée côté serveur | **Validé** | `test_forbidden_commands_refused_server_side` : `run_shell`/`rm -rf /` (403, `intent_not_allowed`), paramètre inconnu (422), rôle Lecture (403), type de tâche non créable (403), sans jeton (401) ; aucune tâche créée ; refus journalisés (`outcome=denied`). |
| 6 | Une approbation expirée ou modifiée est refusée | **Validé** | 5 tests : expirée à la décision ; expirée entre approbation et départ (`approval_expired`) ; modifiée via l'API (invalidée, nouvelle demande) ; modifiée **directement en base** (`approval_params_changed`) ; usage unique ; seul le Fondateur décide. |
| 7 | Une répétition de requête ne duplique pas l'action | **Validé** | `test_repeated_request_does_not_duplicate` (`Idempotency-Key`, même clé + autre corps = 422) ; `test_two_runners_never_execute_the_same_task_twice` (4 exécuteurs concurrents, 6 tâches, chacune exécutée une fois). |
| 8 | L'arrêt d'urgence bloque les nouveaux départs | **Validé** | `test_emergency_stop_blocks_new_starts_and_reports_categories` : rapport en trois catégories (annulées / en cours / actions externes déjà effectuées), création de tâches refusée (423), exécuteur inactif, état persistant pour un nouveau processus, réarmement Fondateur + `REARMER` seulement. |
| 9 | Une panne d'Ollama produit un état d'échec explicite | **Validé** (avec réserve) | `test_ollama_outage_gives_explicit_failure` : tâche `failed` / `llm_unavailable`, 2 tentatives (reprises limitées), Omni-Box 503 journalisée. **Réserve** : le client Ollama a été exercé contre un faux serveur écrit par nous, jamais contre un vrai Ollama. |
| 10 | Les deux parcours de démonstration fonctionnent sans action externe | **Validé** | Agence : `test_agency_demo_journey_no_external_action` (`sent: false`, `external_actions` vide) et `test_agency_review_blocks_prices_and_guarantees`. Quant : `test_quant_demo_journey_is_simulation_with_provenance` (SHA-256, graine, hypothèses, « n'est pas une stratégie validée », frais). Aussi Council et CEO. |

**Suite automatisée : 33 tests, 33 réussis (≈ 32 s)** sur PostgreSQL réel. Dashboard : `tsc --noEmit` sans erreur, build Vite OK, 0 erreur de console dans Chromium sur le parcours complet.

## Ce que le Dashboard a réellement montré (Chromium, 1280 px)
Connexion → Omni-Box (intention validée par le serveur, aperçu, confirmation, 3 tâches créées) → parcours Agence jusqu'à une approbation en attente → Forge Quant (expérience `reported`, mode SIMULATION) → Mesh (graphe issu des lignes réelles) → Journal (vérification de chaîne) → approbation par le Fondateur. Services : `api`, `postgres`, `ollama` (faux) **up** ; `n8n`, `baserow` **down** (non lancés) ; `mt5` **disabled** — l'état affiché est l'état réel, pas un état supposé.
Cache PWA après rechargement : uniquement `/assets/*.js`, `/assets/*.css`, `/icon.svg`. Aucune entrée `/api`. Journal de l'API : aucun mot de passe ni jeton.

## Ce qui n'est PAS validé (à faire sur votre machine)
1. **`docker compose up`** : fichier écrit, jamais exécuté. Étiquettes d'images (postgres, ollama, n8n, baserow) **non vérifiées**.
2. **Choix du modèle local** : non fait (pas d'Ollama). Exécuter `scripts/bench_ollama.py`.
3. **Import des 25 dépôts** : `outputs/trading-github/inventaire.json` n'existe pas dans cet environnement. L'import est testé sur un inventaire de 3 entrées d'essai (idempotent, statut « téléchargé, non audité »). Les 25 ne sont **pas** importés ni affichés.
4. **n8n** : deux workflows exportés (lecture seule), jamais importés dans n8n. **Baserow** : déclaré comme service, **aucune synchronisation de données** livrée : à ce stade il n'est qu'une interface vide à côté de l'API.
5. **Vrai Ollama** : format `/api/chat` utilisé d'après la documentation, non éprouvé.
6. **Mobile / PWA installée** : seule la mise en page 1280 px a été regardée ; l'installation PWA et l'affichage téléphone ne sont pas testés. Pas d'audit d'accessibilité.
7. **MT5** : aucun terminal ici ; connecteur seulement préparé, désactivé.
8. **Windows** : rien n'a été exécuté sous Windows (les tests lancent PostgreSQL via `runuser`, spécifique Linux).

## Écarts et décisions à connaître
- Les tâches déjà en cours ne sont pas interrompues de force lors d'un arrêt d'urgence (seulement signalées) ; une tâche orpheline après panne devient `failed/interrupted`, jamais relancée seule (test dédié).
- Les chiffres du backtest de démonstration portent sur des **données synthétiques sans tendance** : ils ne prouvent aucun rendement et n'ont aucune valeur pour TriEdgeLucid ni pour les robots MT5.
- Le journal d'audit détecte l'altération mais ne l'empêche pas face à un administrateur de la base (voir `SECURITE_ET_LIMITES.md`).
- Le dépôt contient d'autres projets sur d'autres branches (dont un « nexus_core » antérieur sur `claude/pensive-planck-kd52v1`) : celui-ci est un projet neuf et distinct, sans les reprendre.

## Reproduire
```
cd nexus/api && pip install -r requirements.txt pytest && NEXUS_TEST_TMP=/var/tmp python -m pytest tests -q
cd ../web && npm ci && npm run build
```
