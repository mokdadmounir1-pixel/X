# Socle local Nexus. Depuis le dossier deploy/local :  make init   puis   make check
# Prérequis : Docker, Python 3.11+, `pip install -r nexus_core/requirements.txt`, fichier .env (copie de .env.example).
ENVF := .env

.PHONY: up init check test down reset-danger
up:
	@test -f $(ENVF) || { echo "Créer .env (copie de .env.example) et remplacer chaque CHANGER."; exit 2; }
	docker compose --env-file $(ENVF) up -d --wait
init: up
	python3 init_db.py
check:
	python3 check.py
test:
	cd ../.. && python3 -m pytest -q
down:
	docker compose --env-file $(ENVF) down
# DESTRUCTIF : supprime le volume et donc toutes les données. À ne lancer que volontairement.
reset-danger:
	docker compose --env-file $(ENVF) down -v
