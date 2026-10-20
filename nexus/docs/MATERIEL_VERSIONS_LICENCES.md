# Matériel, ports, versions épinglées et licences

## Contrôle de l'environnement de développement (celui où ce code a été écrit et testé)
Résultat réel de `scripts/preflight.py` : Linux x86_64, 4 cœurs, 15,7 Go de RAM, aucun GPU, 29 Go de disque libre, client Docker présent mais **démon inactif**, ports 11434/5678/8080/5173 libres (8000 occupé par l'API de test).
**Ce n'est pas votre PC.** Relancer `python scripts/preflight.py` sur la machine cible avant installation.

## Choix du modèle local
Non tranché : **Ollama n'est pas disponible ici**, donc aucune mesure de qualité ou de latence n'a pu être faite. La méthode est livrée (`scripts/bench_ollama.py`, 13 commandes dont 4 pièges, 2 passages) avec critères de décision écrits. Le banc d'essai a été vérifié contre un faux serveur : il fonctionne et **refuse** correctement un « modèle » à 69 % d'intentions exactes.
Candidats (licence d'après les fiches publiques, à vérifier au moment du téléchargement) :
| Mémoire libre | Candidat | Licence |
|---|---|---|
| ≥ 12 Go ou GPU | `qwen2.5:7b-instruct` | Apache-2.0 |
| 6–12 Go | `qwen2.5:7b-instruct` en 4 bits (si 8 Go libres), sinon `qwen2.5:1.5b-instruct` | Apache-2.0 |
| < 6 Go | `qwen2.5:1.5b-instruct` ou aucun | Apache-2.0 |
Éviter `qwen2.5:3b` (licence de recherche restreinte) pour un usage commercial. `qwen2.5:7b-instruct` est le défaut de la configuration : c'est un **candidat**, pas un modèle retenu.

## Ports (tous sur 127.0.0.1)
8000 API + Dashboard · 11434 Ollama · 5678 n8n · 8080 Baserow · 5173 Vite (développement). PostgreSQL n'est pas publié.

## Versions épinglées
| Composant | Version | Statut |
|---|---|---|
| Python | 3.13 | testé (3.13.16) |
| PostgreSQL | 16 (image `postgres:16.6-alpine`) | testé en 16 ; l'étiquette d'image **non vérifiée** |
| FastAPI / Uvicorn / Pydantic / psycopg | 0.156.1 / 0.53.0 / 2.13.5 / 3.3.6 | testés (`api/requirements.txt`) |
| React / TypeScript / Vite | 18.3.1 / 5.6.3 / 5.4.11 | compilés (`web/package-lock.json`) |
| Ollama | image `ollama/ollama:0.5.7` | **non vérifié** |
| n8n | image `n8nio/n8n:1.76.1` | **non vérifié** |
| Baserow | image `baserow/baserow:1.30.1` | **non vérifié** |
Les étiquettes d'images n'ont pas pu être tirées (pas de démon Docker). `docker compose pull` les confirmera ; remplacer toute étiquette introuvable par une version existante et **la réépingler**.

## Licences (à confirmer sur les dépôts officiels avant usage commercial)
- PostgreSQL : licence PostgreSQL (permissive). FastAPI, Pydantic, React, Vite, Ollama : MIT. Uvicorn, httpx : BSD.
- **psycopg 3 : LGPL-3.0** — usage comme bibliothèque sans modification : compatible, mais à noter si vous redistribuez.
- **n8n : Sustainable Use License** (code source disponible, **pas** open source OSI) : usage interne autorisé ; revendre n8n ou l'offrir comme service géré à des tiers est restreint.
- **Baserow** : cœur MIT ; fonctionnalités premium/entreprise sous licence propriétaire — n'utiliser que le cœur.
- Modèles : Apache-2.0 pour Qwen2.5 7B/1.5B ; les modèles Llama ont leur propre licence communautaire.
