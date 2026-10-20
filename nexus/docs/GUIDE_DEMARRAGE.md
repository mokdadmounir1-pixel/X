# Guide de démarrage

## 0. Prérequis et contrôle
Docker Desktop (ou Docker Engine + Compose v2), Python 3.11+ pour les scripts. Puis :
```
python scripts/preflight.py        # mémoire, GPU, Docker, ports 8000/11434/5678/8080
```

## 1. Configuration (sans secret dans le dépôt)
```
cd deploy
cp .env.example .env               # remplacer chaque CHANGER_* ; .env est ignoré par git
```
Générer chaque valeur : `python -c "import secrets; print(secrets.token_urlsafe(32))"`.

## 2. Démarrage minimal (PostgreSQL + API + Dashboard)
```
docker compose up -d --build       # ou : make up
docker compose ps                  # postgres et api doivent être « healthy »
```
L'API applique les migrations au démarrage. Dashboard : http://127.0.0.1:8000 (accès local uniquement).

## 3. Premier compte — il n'existe aucun compte par défaut
```
make create-founder                # demande un mot de passe de 12+ caractères, refuse les mots de passe faibles
make create-user U=operateur1 R=operateur    # rôles : fondateur | operateur | lecture
```
Le mot de passe se saisit au clavier (ou `NEXUS_NEW_USER_PASSWORD` pour un script). Il n'est jamais écrit dans un journal.

## 4. Pile complète (Ollama, n8n, Baserow)
```
docker compose --profile full up -d
docker compose exec ollama ollama pull qwen2.5:7b-instruct     # candidat, voir ci-dessous
python scripts/bench_ollama.py --models qwen2.5:7b-instruct qwen2.5:1.5b-instruct
```
**Ne retenir un modèle que si le banc d'essai dit RETENIR** (JSON valide 100 %, intention exacte ≥ 90 %, p95 ≤ 20 s). Sinon changer `NEXUS_OLLAMA_MODEL` dans `.env` et `docker compose up -d api`.
Sans Ollama, l'Omni-Box répond « llm_unavailable » (échec explicite) ; le reste du système fonctionne.

## 5. Importer les 25 dépôts
```
make import-repos F=chemin/vers/outputs/trading-github/inventaire.json
```
Ils s'affichent « téléchargé, non audité » dans la Forge Quant. Accepte une liste d'objets (`name`/`nom`, `url`) ou un objet contenant `depots`/`repositories`/`repos`.

## 6. Parcours de démonstration
- **Quant** : Forge Quant → « Lancer une expérience de démonstration » (ou dans l'Omni-Box : « lance une expérience de démonstration »). Données **synthétiques** versionnées → backtest avec frais → rapport. Mode SIMULATION, jamais une stratégie validée.
- **Agence** : onglet Agence → prospect **fictif** + problèmes documentés → analyse → brouillon → contrôle → demande d'approbation (Vue exécutive, compte Fondateur). Aucun envoi.
- **Conseil** et **Engagements du jour** : Vue exécutive.

## 7. Arrêt
`docker compose down` (les données restent dans les volumes). Arrêt d'urgence applicatif : bouton rouge du Dashboard.

## Développement sans Docker
```
pip install -r api/requirements.txt pytest
cd api && NEXUS_DATABASE_URL=postgresql://... python -m app.cli migrate && uvicorn app.main:app --port 8000
cd web && npm install && npm run dev         # http://127.0.0.1:5173, proxy vers l'API
cd api && python -m pytest tests -q          # démarre un PostgreSQL jetable (PG_BIN, runuser/postgres sous Linux)
```
