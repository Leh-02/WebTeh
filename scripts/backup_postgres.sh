#!/bin/sh
set -eu
: "${POSTGRES_PASSWORD:?POSTGRES_PASSWORD is required}"
BACKUP_DIR="${BACKUP_DIR:-./backups}"
CONTAINER="${POSTGRES_CONTAINER:-topbearing-db-1}"
DB="${POSTGRES_DB:-topbearing}"
USER="${POSTGRES_USER:-topbearing}"
STAMP="$(date +%Y%m%d_%H%M%S)"
mkdir -p "$BACKUP_DIR"
docker exec -e PGPASSWORD="$POSTGRES_PASSWORD" "$CONTAINER" pg_dump -U "$USER" -d "$DB" -Fc > "$BACKUP_DIR/topbearing_${STAMP}.dump"
find "$BACKUP_DIR" -type f -name 'topbearing_*.dump' -mtime +${BACKUP_RETENTION_DAYS:-14} -delete
echo "Backup created: $BACKUP_DIR/topbearing_${STAMP}.dump"
