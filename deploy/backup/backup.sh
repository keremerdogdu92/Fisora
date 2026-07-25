#!/bin/sh
set -eu

# Required for checkpoint/scheduled modes:
#   DATABASE_URL
#   FISORA_BACKUP_COPY_DIR
#   FISORA_BACKUP_AGE_RECIPIENT
# Optional:
#   FISORA_BACKUP_MODE=disabled|checkpoint|scheduled
#   FISORA_BACKUP_INTERVAL_SECONDS=86400
#   FISORA_BACKUP_DIR=/opt/fisora/data/backups
#   FISORA_DOCUMENT_STORAGE_PATH=/opt/fisora/data/documents
#   FISORA_PROTECTED_CORPUS_PATH=/opt/fisora/protected-corpus
#   FISORA_BACKUP_KEEP_DAYS=14
#   FISORA_BACKUP_OFFHOST_KEEP_DAYS=30

BACKUP_MODE="${FISORA_BACKUP_MODE:-disabled}"
BACKUP_INTERVAL_SECONDS="${FISORA_BACKUP_INTERVAL_SECONDS:-86400}"
BACKUP_DIR="${FISORA_BACKUP_DIR:-/opt/fisora/data/backups}"
DOCUMENT_DIR="${FISORA_DOCUMENT_STORAGE_PATH:-/opt/fisora/data/documents}"
PROTECTED_CORPUS_DIR="${FISORA_PROTECTED_CORPUS_PATH:-/opt/fisora/protected-corpus}"
BACKUP_KEEP_DAYS="${FISORA_BACKUP_KEEP_DAYS:-14}"
BACKUP_OFFHOST_KEEP_DAYS="${FISORA_BACKUP_OFFHOST_KEEP_DAYS:-30}"

case "$BACKUP_MODE" in
  disabled)
    echo "backup mode disabled; no generation created"
    exit 0
    ;;
  checkpoint|scheduled) ;;
  *)
    echo "invalid FISORA_BACKUP_MODE: $BACKUP_MODE" >&2
    exit 2
    ;;
esac

: "${DATABASE_URL:?DATABASE_URL is required}"
: "${FISORA_BACKUP_COPY_DIR:?FISORA_BACKUP_COPY_DIR is required}"
: "${FISORA_BACKUP_AGE_RECIPIENT:?FISORA_BACKUP_AGE_RECIPIENT is required}"

mkdir -p "$BACKUP_DIR" "$FISORA_BACKUP_COPY_DIR"

stage=""
bundle=""
local_encrypted=""
offhost_encrypted=""
receipt=""
cleanup() {
  if [ -n "$bundle" ] && [ -f "$bundle" ]; then
    rm -f -- "$bundle"
  fi
  if [ -n "$local_encrypted" ]; then
    rm -f -- "$local_encrypted.tmp"
  fi
  if [ -n "$offhost_encrypted" ]; then
    rm -f -- "$offhost_encrypted.tmp"
  fi
  if [ -n "$receipt" ]; then
    rm -f -- "$receipt.tmp"
  fi
  case "$stage" in
    "$BACKUP_DIR"/.backup-stage.*)
      rm -rf -- "$stage"
      ;;
  esac
}
trap cleanup EXIT HUP INT TERM

run_backup() {
  stamp="$(date -u +%Y%m%dT%H%M%SZ)"
  timestamp="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  stage="$(mktemp -d "$BACKUP_DIR/.backup-stage.XXXXXX")"
  bundle="$BACKUP_DIR/.fisora-backup-$stamp.tar.gz.tmp"
  local_encrypted="$BACKUP_DIR/fisora-backup-$stamp.tar.gz.age"
  offhost_encrypted="$FISORA_BACKUP_COPY_DIR/fisora-backup-$stamp.tar.gz.age"
  receipt="$BACKUP_DIR/backup-success-$stamp.json"

  pg_dump "$DATABASE_URL" > "$stage/postgres.sql"

  if [ ! -d "$PROTECTED_CORPUS_DIR" ]; then
    echo "protected corpus directory is missing: $PROTECTED_CORPUS_DIR" >&2
    return 1
  fi
  tar -cf "$stage/protected-corpus.tar" -C "$PROTECTED_CORPUS_DIR" .

  if [ "$BACKUP_MODE" = "scheduled" ]; then
    if [ ! -d "$DOCUMENT_DIR" ]; then
      echo "document directory is missing: $DOCUMENT_DIR" >&2
      return 1
    fi
    (
      cd "$DOCUMENT_DIR"
      find . -type f \( -iname '*.pdf' -o -iname '*.xml' \) -print > "$stage/documents.list"
      tar -cf "$stage/documents.tar" -T "$stage/documents.list"
    )
    rm -f -- "$stage/documents.list"
  fi

  printf '{"format_version":1,"mode":"%s","created_at":"%s"}\n' \
    "$BACKUP_MODE" "$timestamp" > "$stage/metadata.json"

  (
    cd "$stage"
    if [ "$BACKUP_MODE" = "scheduled" ]; then
      sha256sum postgres.sql protected-corpus.tar documents.tar metadata.json > SHA256SUMS
    else
      sha256sum postgres.sql protected-corpus.tar metadata.json > SHA256SUMS
    fi
  )

  tar -czf "$bundle" -C "$stage" .
  age -r "$FISORA_BACKUP_AGE_RECIPIENT" -o "$local_encrypted.tmp" "$bundle"
  mv "$local_encrypted.tmp" "$local_encrypted"
  cp "$local_encrypted" "$offhost_encrypted.tmp"
  mv "$offhost_encrypted.tmp" "$offhost_encrypted"
  digest="$(sha256sum "$local_encrypted" | awk '{print $1}')"

  receipt_tmp="$receipt.tmp"
  printf '%s\n' \
    "{\"mode\":\"$BACKUP_MODE\",\"latest_attempt_at\":\"$timestamp\",\"latest_success_at\":\"$timestamp\",\"generation_file\":\"$(basename "$local_encrypted")\",\"generation_digest\":\"$digest\",\"offhost_copy_status\":\"complete\"}" \
    > "$receipt_tmp"
  mv "$receipt_tmp" "$receipt"

  if [ "$BACKUP_MODE" = "scheduled" ]; then
    find "$BACKUP_DIR" -type f -name 'fisora-backup-*.tar.gz.age' -mtime +"$BACKUP_KEEP_DAYS" -delete
    find "$BACKUP_DIR" -type f -name 'backup-success-*.json' -mtime +"$BACKUP_KEEP_DAYS" -delete
    find "$FISORA_BACKUP_COPY_DIR" -type f -name 'fisora-backup-*.tar.gz.age' \
      -mtime +"$BACKUP_OFFHOST_KEEP_DAYS" -delete
  fi

  rm -f -- "$bundle"
  bundle=""
  case "$stage" in
    "$BACKUP_DIR"/.backup-stage.*)
      rm -rf -- "$stage"
      ;;
  esac
  stage=""
  echo "backup generation completed: $(basename "$local_encrypted")"
}

if [ "${FISORA_BACKUP_RUN_ONCE:-}" = "1" ]; then
  run_backup
  exit 0
fi

if [ "$BACKUP_MODE" = "checkpoint" ]; then
  echo "checkpoint mode requires FISORA_BACKUP_RUN_ONCE=1" >&2
  exit 2
fi

while true; do
  run_backup
  sleep "$BACKUP_INTERVAL_SECONDS"
done
