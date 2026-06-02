#!/bin/sh
set -eu

BACKUP_INTERVAL_SECONDS="${FISORA_BACKUP_INTERVAL_SECONDS:-86400}"
BACKUP_DIR="${FISORA_BACKUP_DIR:-/opt/fisora/data/backups}"
DOCUMENT_DIR="${FISORA_DOCUMENT_STORAGE_PATH:-/opt/fisora/data/documents}"

mkdir -p "$BACKUP_DIR"

run_backup() {
  stamp="$(date -u +%Y%m%dT%H%M%SZ)"
  pg_dump "$DATABASE_URL" > "$BACKUP_DIR/postgres-$stamp.sql"
  if [ -d "$DOCUMENT_DIR" ]; then
    find "$DOCUMENT_DIR" -type f | while IFS= read -r file; do
      size="$(wc -c < "$file" | tr -d ' ')"
      rel="${file#$DOCUMENT_DIR/}"
      printf '%s\t%s\n' "$rel" "$size"
    done > "$BACKUP_DIR/documents-$stamp.manifest.tsv"
  fi
  find "$BACKUP_DIR" -type f -name 'postgres-*.sql' -mtime +14 -delete
  find "$BACKUP_DIR" -type f -name 'documents-*.manifest.tsv' -mtime +14 -delete
}

if [ "${FISORA_BACKUP_RUN_ONCE:-}" = "1" ]; then
  run_backup
  exit 0
fi

while true; do
  run_backup
  sleep "$BACKUP_INTERVAL_SECONDS"
done
