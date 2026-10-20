# Workflows n8n exportés (v0.1)

| Fichier | Rôle | Écrit dans NEXUS ? |
|---|---|---|
| `nexus-sante.json` | Interroge `/api/health` toutes les 5 min | Non |
| `nexus-resume-quotidien.json` | Lit la vue exécutive chaque matin (jeton du compte **Lecture**) | Non |

- Les deux sont livrés **inactifs** (`active: false`) et **ne peuvent rien engager** : aucun nœud d'envoi, aucun appel d'écriture.
- **Non testés dans n8n** : n8n n'est pas disponible dans l'environnement de développement. Les fichiers suivent le format d'export n8n 1.x ; l'import doit être vérifié sur votre machine (n8n → Workflows → Import from file). Si un nœud est refusé, corriger dans l'éditeur et réexporter.
- Pour le second, créer l'identifiant « Header Auth » : nom `Authorization`, valeur `Bearer <jeton d'un compte Lecture>` (jeton obtenu par `POST /api/auth/login`). Ne jamais donner à n8n un compte Fondateur.
- n8n n'est jamais une autorité : une action engageante passe par l'API NEXUS (rôle, approbation liée aux paramètres, journal). Modifier un workflow ne donne aucun droit supplémentaire.
