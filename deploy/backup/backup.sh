#!/bin/sh
set -eu

# Required: DATABASE_URL
# Optional:
#   FISORA_BACKUP_INTERVAL_SECONDS=86400
#   FISORA_BACKUP_DIR=/opt/fisora/data/backups
#   FISORA_DOCUMENT_STORAGE_PATH=/opt/fisora/data/documents
#   FISORA_PROTECTED_CORPUS_PATH=/opt/fisora/protected-corpus
#   FISORA_BACKUP_COPY_DIR=/mnt/fisora-backups
#   FISORA_BACKUP_AGE_RECIPIENT=age1...
#   FISORA_BACKUP_KEEP_DAYS=14

BACKUP_INTERVAL_SECONDS="${FISORA_BACKUP_INTERVAL_SECONDS:-86400}"
BACKUP_DIR="${FISORA_BACKUP_DIR:-/opt/fisora/data/backups}"
DOCUMENT_DIR="${FISORA_DOCUMENT_STORAGE_PATH:-/opt/fisora/data/documents}"
PROTECTED_CORPUS_DIR="${FISORA_PROTECTED_CORPUS_PATH:-/opt/fisora/protected-corpus}"
BACKUP_KEEP_DAYS="${FISORA_BACKUP_KEEP_DAYS:-14}"

mkdir -p "$BACKUP_DIR"

run_backup() {
  stamp="$(date -u +%Y%m%dT%H%M%SZ)"
  database_backup="$BACKUP_DIR/postgres-$stamp.sql"
  protected_archive="$BACKUP_DIR/protected-corpus-$stamp.tar.gz"
  protected_manifest="$BACKUP_DIR/protected-corpus-$stamp.sha256"
  pg_dump "$DATABASE_URL" > "$database_backup"
  if [ -d "$DOCUMENT_DIR" ]; then
    find "$DOCUMENT_DIR" -type f | while IFS= read -r file; do
      size="$(wc -c < "$file" | tr -d ' ')"
      rel="${file#$DOCUMENT_DIR/}"
      printf '%s\t%s\n' "$rel" "$size"
    done > "$BACKUP_DIR/documents-$stamp.manifest.tsv"
  fi
  if [ -d "$PROTECTED_CORPUS_DIR" ]; then
    (cd "$PROTECTED_CORPUS_DIR" && find . -type f -print0 | sort -z | xargs -0 -r sha256sum) > "$protected_manifest"
    tar -czf "$protected_archive" -C "$PROTECTED_CORPUS_DIR" .
  fi
  if [ -n "${FISORA_BACKUP_COPY_DIR:-}" ]; then
    if [ -z "${FISORA_BACKUP_AGE_RECIPIENT:-}" ]; then
      echo "FISORA_BACKUP_AGE_RECIPIENT is required for off-host backup" >&2
      return 1
    fi
    mkdir -p "$FISORA_BACKUP_COPY_DIR"
    bundle="$BACKUP_DIR/fisora-protected-backup-$stamp.tar.gz"
    tar_args="postgres-$stamp.sql"
    [ ! -f "$protected_archive" ] || tar_args="$tar_args protected-corpus-$stamp.tar.gz protected-corpus-$stamp.sha256"
    [ ! -f "$BACKUP_DIR/documents-$stamp.manifest.tsv" ] || tar_args="$tar_args documents-$stamp.manifest.tsv"
    # shellcheck disable=SC2086
    tar -czf "$bundle" -C "$BACKUP_DIR" $tar_args
    age -r "$FISORA_BACKUP_AGE_RECIPIENT" -o "$FISORA_BACKUP_COPY_DIR/fisora-protected-backup-$stamp.tar.gz.age" "$bundle"
    rm -f "$bundle"
  fi
  find "$BACKUP_DIR" -type f -name 'postgres-*.sql' -mtime +"$BACKUP_KEEP_DAYS" -delete
  find "$BACKUP_DIR" -type f -name 'documents-*.manifest.tsv' -mtime +"$BACKUP_KEEP_DAYS" -delete
  find "$BACKUP_DIR" -type f -name 'protected-corpus-*.tar.gz' -mtime +"$BACKUP_KEEP_DAYS" -delete
  find "$BACKUP_DIR" -type f -name 'protected-corpus-*.sha256' -mtime +"$BACKUP_KEEP_DAYS" -delete
}

if [ "${FISORA_BACKUP_RUN_ONCE:-}" = "1" ]; then
  run_backup
  exit 0
fi

while true; do
  run_backup
  sleep "$BACKUP_INTERVAL_SECONDS"
done
