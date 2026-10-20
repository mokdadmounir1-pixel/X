#!/bin/sh
# Sauvegarde NEXUS : (1) dump PostgreSQL complet, (2) export séparé du journal d'audit + empreinte d'ancrage.
# Mode direct : NEXUS_DATABASE_URL défini (psql/pg_dump installés).  Sinon : docker compose exec postgres.
# Usage : sh scripts/backup.sh [dossier]   (défaut : ./backups)
set -eu
OUT="${1:-./backups}"; TS=$(date -u +%Y%m%dT%H%M%SZ)
mkdir -p "$OUT"
run_dump()  { if [ -n "${NEXUS_DATABASE_URL:-}" ]; then pg_dump "$NEXUS_DATABASE_URL"; else docker compose -f "$(dirname "$0")/../deploy/docker-compose.yml" exec -T postgres pg_dump -U nexus nexus; fi; }
run_query() { if [ -n "${NEXUS_DATABASE_URL:-}" ]; then psql "$NEXUS_DATABASE_URL" -At -c "$1"; else docker compose -f "$(dirname "$0")/../deploy/docker-compose.yml" exec -T postgres psql -U nexus -d nexus -At -c "$1"; fi; }
run_dump > "$OUT/nexus-$TS.sql"
run_query "SELECT row_to_json(a) FROM (SELECT seq, ts, actor, action, entity_type, entity_id, correlation_id, outcome, details, prev_hash, hash FROM audit_events ORDER BY seq) a" > "$OUT/audit-$TS.jsonl"
LAST=$(run_query "SELECT coalesce(max(seq),0) || ' ' || coalesce((SELECT hash FROM audit_events ORDER BY seq DESC LIMIT 1),'-') FROM audit_events")
echo "$TS $LAST" >> "$OUT/audit-anchors.txt"
( cd "$OUT" && sha256sum "nexus-$TS.sql" "audit-$TS.jsonl" > "checksums-$TS.txt" )
echo "Sauvegarde : $OUT/nexus-$TS.sql, audit-$TS.jsonl, checksums-$TS.txt"
echo "Dernière empreinte du journal : $LAST (copier audit-anchors.txt HORS de cette machine)."
