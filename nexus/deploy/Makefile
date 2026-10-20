# Usage (depuis nexus/deploy) : make help
COMPOSE = docker compose
.PHONY: help preflight up up-full down logs create-founder create-user import-repos backup restore upgrade test
help:
	@echo "preflight | up | up-full | down | logs | create-founder | create-user | import-repos F=... | backup | restore F=... | upgrade | test"
preflight:      ; python ../scripts/preflight.py
up:             ; $(COMPOSE) up -d --build
up-full:        ; $(COMPOSE) --profile full up -d --build
down:           ; $(COMPOSE) down
logs:           ; $(COMPOSE) logs -f --tail=100
create-founder: ; $(COMPOSE) exec api python -m app.cli create-user --username $${NEXUS_USER:-fondateur} --role fondateur
create-user:    ; $(COMPOSE) exec api python -m app.cli create-user --username $(U) --role $(R)
import-repos:   ; $(COMPOSE) cp $(F) api:/tmp/inventaire.json && $(COMPOSE) exec api python -m app.cli import-repos /tmp/inventaire.json
backup:         ; sh ../scripts/backup.sh
restore:        ; sh ../scripts/restore.sh $(F)
upgrade:        ; sh ../scripts/backup.sh && $(COMPOSE) up -d --build
test:           ; cd ../api && python -m pytest tests -q
