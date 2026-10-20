# NEXUS — socle local et Command Center v0.1

Projet distinct des 25 archives sources. **Aucun ordre de marché, message commercial ou contrat n'est envoyé par cette version** :
le seul chemin « d'envoi » (`agency.send_proposal`) enregistre l'approbation et s'arrête (`sent: false`).

```
Navigateur (PWA React/TS) ──► API FastAPI ──► PostgreSQL 16  (autorité : rôles, approbations, journal)
                                 │  └──► Ollama (inférence locale, propose seulement)
n8n ─ Baserow : services auto-hébergés, SANS droit d'action (voir docs/SECURITE_ET_LIMITES.md)
```

| Dossier | Contenu |
|---|---|
| `api/` | API, migrations SQL, CLI d'administration, **33 tests** sur un vrai PostgreSQL |
| `web/` | Dashboard PWA : Vue exécutive, Forge Quant, Agence, Mesh, Journal + Omni-Box |
| `deploy/` | `docker-compose.yml`, `.env.example` (sans secrets), `Makefile` |
| `scripts/` | `preflight.py`, `bench_ollama.py`, `backup.sh`, `restore.sh`, `fake_ollama.py` (démonstration) |
| `workflows/` | Exports n8n (lecture seule) |
| `docs/` | Guide de démarrage, exploitation, sécurité et limites, matériel/versions/licences, connecteurs, **rapport de validation** |

Commencer par `docs/GUIDE_DEMARRAGE.md`. L'état réel de ce qui est vérifié et de ce qui ne l'est pas : `docs/RAPPORT_VALIDATION.md`.
