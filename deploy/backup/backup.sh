#!/bin/sh
set -eu

# Required: DATABASE_URL
# Optional:
#   FISORA_BACKUP_INTERVAL_SECONDS=86400
#   FISORA_BACKUP_DIR=/opt/fisora/data/backups
#   FISORA_DOCUMENT_STORAGE_PATH=/opt/fisora/data/documents
#   FISORA_BACKUP_COPY_DIR=/mnt/fisora-backups
#   FISORA_BACKUP_KEEP_DAYS=14

BACKUP_INTERVAL_SECONDS="${FISORA_BACKUP_INTERVAL_SECONDS:-86400}"
BACKUP_DIR="${FISORA_BACKUP_DIR:-/opt/fisora/data/backups}"
DOCUMENT_DIR="${FISORA_DOCUMENT_STORAGE_PATH:-/opt/fisora/data/documents}"
BACKUP_KEEP_DAYS="${FISORA_BACKUP_KEEP_DAYS:-14}"

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
  if [ -n "${FISORA_BACKUP_COPY_DIR:-}" ]; then
    mkdir -p "$FISORA_BACKUP_COPY_DIR"
    cp "$BACKUP_DIR/postgres-$stamp.sql" "$FISORA_BACKUP_COPY_DIR/postgres-$stamp.sql"
    if [ -f "$BACKUP_DIR/documents-$stamp.manifest.tsv" ]; then
      cp "$BACKUP_DIR/documents-$stamp.manifest.tsv" "$FISORA_BACKUP_COPY_DIR/documents-$stamp.manifest.tsv"
    fi
  fi
  find "$BACKUP_DIR" -type f -name 'postgres-*.sql' -mtime +"$BACKUP_KEEP_DAYS" -delete
  find "$BACKUP_DIR" -type f -name 'documents-*.manifest.tsv' -mtime +"$BACKUP_KEEP_DAYS" -delete
}

if [ "${FISORA_BACKUP_RUN_ONCE:-}" = "1" ]; then
  run_backup
  exit 0
fi

while true; do
  run_backup
  sleep "$BACKUP_INTERVAL_SECONDS"
done
