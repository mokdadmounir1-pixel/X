#!/bin/sh
# Restauration NEXUS dans une base VIDE puis vérification de la chaîne d'audit.
# Usage : NEXUS_RESTORE_URL=postgresql://.../base_vide sh scripts/restore.sh backups/nexus-XXXX.sql
# (en mode Docker : arrêter l'API, recréer la base « nexus » vide, puis rediriger le dump dans psql — voir docs/EXPLOITATION.md)
set -eu
FILE="${1:?fichier .sql requis}"; URL="${NEXUS_RESTORE_URL:?NEXUS_RESTORE_URL requis (base vide)}"
N=$(psql "$URL" -At -c "SELECT count(*) FROM information_schema.tables WHERE table_schema='public'")
[ "$N" = "0" ] || { echo "Base cible non vide ($N tables) : restauration refusée."; exit 2; }
CK=$(ls "$(dirname "$FILE")"/checksums-*.txt 2>/dev/null | tail -1 || true)
[ -z "$CK" ] || ( cd "$(dirname "$FILE")" && grep "$(basename "$FILE")" "$(basename "$CK")" | sha256sum -c - )
psql "$URL" -v ON_ERROR_STOP=1 -q -f "$FILE" > /dev/null
BAD=$(psql "$URL" -At -c "SELECT coalesce(verify_audit_chain()::text,'ok')")
[ "$BAD" = "ok" ] && echo "Restauration réussie, chaîne d'audit saine." || { echo "CHAÎNE D'AUDIT ALTÉRÉE à partir de l'événement $BAD"; exit 3; }
psql "$URL" -At -c "SELECT 'tâches: ' || (SELECT count(*) FROM tasks) || ', événements: ' || (SELECT count(*) FROM audit_events)"
