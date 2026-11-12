#!/bin/bash
# Backs up retail_db from the running postgres container. No local
# pg_dump is assumed — the dump runs inside the container, where the
# matching Postgres version always lives, then gets copied out.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_ROOT"

set -a
source .env
set +a

CONTAINER="$(docker compose ps -q postgres)"
if [[ -z "$CONTAINER" ]]; then
    echo "postgres container is not running. Start it with: docker compose up -d postgres" >&2
    exit 1
fi

BACKUP_DIR="$PROJECT_ROOT/backups"
mkdir -p "$BACKUP_DIR"
TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
BACKUP_FILE="$BACKUP_DIR/retail_db_${TIMESTAMP}.dump"

echo "Backing up ${POSTGRES_DB} to ${BACKUP_FILE}..."
docker exec -e PGPASSWORD="$POSTGRES_PASSWORD" "$CONTAINER" \
    pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -F c -f /tmp/retail_db_backup.dump
docker cp "$CONTAINER:/tmp/retail_db_backup.dump" "$BACKUP_FILE"
docker exec "$CONTAINER" rm -f /tmp/retail_db_backup.dump

if [[ -s "$BACKUP_FILE" ]]; then
    echo "Backup complete: $BACKUP_FILE ($(du -h "$BACKUP_FILE" | cut -f1))"
else
    echo "Backup failed: output file is empty or missing" >&2
    exit 1
fi
