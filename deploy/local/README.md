# Socle local Nexus (ticket #1)

PostgreSQL 16 dans Docker, joignable seulement depuis votre machine (127.0.0.1), puis schéma + migrations + vérification.

```
cd deploy/local
cp .env.example .env        # remplacer chaque CHANGER par un mot de passe distinct de 16+ caractères
pip install -r ../../nexus_core/requirements.txt
make init                   # démarre la base, crée rôles et base, applique schéma et migrations
make check                  # chaîne d'audit, migrations, droits des rôles (code 0 = sain)
make test                   # suite de tests (cluster temporaire, indépendant de cette base)
```

- `make init` est rejouable : il n'applique que ce qui manque. `make reset-danger` supprime toutes les données.
- Vérifié ici : `init_db.py` et `check.py` contre un vrai PostgreSQL temporaire (idempotence, refus des mots de passe faibles).
- **Non vérifié ici** (pas de démon Docker dans l'environnement de développement) : `docker-compose.yml`, `make up`, et l'authentification par mot de passe réelle. À confirmer sur votre PC avec `make init && make check`.
- Sauvegardes : non incluses. Avant de stocker de vrais leads, prévoir `pg_dump` régulier vers un disque chiffré.
