#!/bin/bash
# Restores a backup produced by backup.sh into the running postgres
# container's retail_db, then verifies the restore actually landed data
# rather than trusting pg_restore's exit code alone.
set -euo pipefail

if [[ $# -ne 1 ]]; then
    echo "Usage: $0 <path-to-backup.dump>" >&2
    exit 1
fi

BACKUP_FILE="$1"
if [[ ! -f "$BACKUP_FILE" ]]; then
    echo "Backup file not found: $BACKUP_FILE" >&2
    exit 1
fi

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

echo "Restoring ${BACKUP_FILE} into ${POSTGRES_DB}..."
docker cp "$BACKUP_FILE" "$CONTAINER:/tmp/retail_db_restore.dump"
docker exec -e PGPASSWORD="$POSTGRES_PASSWORD" "$CONTAINER" \
    pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists -F c /tmp/retail_db_restore.dump
docker exec "$CONTAINER" rm -f /tmp/retail_db_restore.dump

echo "Verifying restore..."
ROW_COUNT="$(docker exec -e PGPASSWORD="$POSTGRES_PASSWORD" "$CONTAINER" \
    psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -t -c "SELECT COUNT(*) FROM invoice_items" | xargs)"
echo "invoice_items row count after restore: $ROW_COUNT"

if [[ "$ROW_COUNT" -eq 0 ]]; then
    echo "Restore verification failed: invoice_items is empty." >&2
    exit 1
fi
echo "Restore verified."
