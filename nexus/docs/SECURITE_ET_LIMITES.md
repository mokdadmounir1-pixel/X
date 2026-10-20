# Sécurité, permissions et limites connues

## Qui décide
L'**API NEXUS** est la seule autorité. Une modification dans Baserow, un workflow n8n ou une réponse d'Ollama ne donne **aucun** droit. Le modèle de langage propose une intention ; le serveur la valide contre un catalogue fermé (`omnibox.INTENTS`, `kinds.KINDS`), des schémas stricts (champs inconnus refusés), le rôle de l'appelant, puis exige un aperçu et une confirmation. Aucune commande système ni code n'est exécutable : il n'existe aucun type de tâche qui en lance.

## Rôles
| Rôle | Peut |
|---|---|
| Lecture | consulter toutes les vues, interpréter une commande (aperçu), `show_status` |
| Opérateur | + créer des tâches, lancer les démonstrations, modifier des paramètres, **déclencher** l'arrêt d'urgence, sonder les services, saisir engagements et incidents |
| Fondateur | + **approuver/refuser**, **réarmer** après arrêt d'urgence, écrire dans le registre financier |

## Approbations
Liées à une action précise, à ses paramètres (empreinte SHA-256 de `type + paramètres`) et à une expiration (24 h par défaut, 72 h maximum). Usage unique. Toute modification des paramètres invalide l'approbation et en redemande une. Vérifiées **au moment du départ**, pas seulement au moment de l'approbation : une approbation expirée ou une tâche modifiée hors API (hash différent) est refusée.

## Journal d'audit
Table append-only : `UPDATE`, `DELETE` et `TRUNCATE` sont refusés par déclencheurs ; chaque ligne porte l'empreinte de la précédente (calculée dans la base). `GET /api/audit/verify` ou `python -m app.cli verify-audit` détecte l'altération. Les refus d'accès sont journalisés dans une transaction séparée.
**Limite** : un administrateur de la base (superutilisateur) peut désactiver les déclencheurs et réécrire la chaîne entière. Le système le **détecte** s'il n'a pas tout recalculé, mais ne l'**empêche** pas. L'ancrage hors machine (`audit-anchors.txt`) est la parade ; il n'est pas automatique.

## Secrets et accès
Aucun secret dans le dépôt (`.env.example` ne contient que des `CHANGER_*`, `.env` est ignoré). Aucun compte par défaut ; politique de mot de passe (12+ caractères, liste de faibles). Mots de passe hachés (scrypt), jetons de session stockés hachés, expiration 12 h. Les journaux masquent jetons, mots de passe et URL de base de données. Tous les ports Docker sont liés à `127.0.0.1`.

## Arrêt d'urgence
Persistant (en base, survit aux redémarrages), bloque création de tâches, départs, approbations. Le rapport sépare : **annulées** (jamais démarrées), **encore en cours** (arrêt *demandé* seulement), **actions externes déjà effectuées** (registre `external_actions`, vide en v0.1). Réarmement : Fondateur, avec saisie de `REARMER`.
**Limite** : les tâches déjà en cours ne sont pas interrompues de force ; en v0.1 elles sont courtes et finissent, sauf appel d'Ollama (jusqu'à 180 s). Le rapport le dit.

## Limites connues (v0.1)
- Pas de MFA, pas de TLS (usage local en HTTP sur 127.0.0.1 ; ne pas exposer sur Internet sans reverse proxy TLS et revue de sécurité).
- Limitation des tentatives de connexion **en mémoire**, par processus.
- Un seul processus d'API avec un exécuteur interne (claim atomique `SKIP LOCKED`, testé à 4 exécuteurs concurrents sur le même PostgreSQL) ; pas de file distribuée.
- Le registre financier est saisi à la main : « dépenses documentées » = lignes avec référence de pièce, rien de plus. Aucune connexion bancaire.
- Prospects : seuls les **fictifs** sont acceptés. Le traitement de données personnelles réelles (RGPD : base légale, durée, droits) n'est pas conçu.
- Le contrôle du brouillon d'agence est un filtre simple (problèmes cités, pas de prix ni de garantie, pas de marqueurs vides), pas une relecture humaine.
- Le Conseil s'appuie sur le modèle local ; un désaccord affiché n'est pas une vérité, et le consensus ne donne aucun droit (contrainte en base : `grants_rights = false`).
