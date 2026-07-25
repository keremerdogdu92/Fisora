#!/bin/sh
set -eu

ROOT_DIR="${FISORA_ROOT_DIR:-$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)}"
ENV_FILE="${FISORA_ENV_FILE:-$ROOT_DIR/deploy/production.env}"
COMPOSE_FILE="${FISORA_COMPOSE_FILE:-$ROOT_DIR/docker-compose.production.yml}"
PROJECT_NAME="${FISORA_COMPOSE_PROJECT:-fisora}"

compose() {
  docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" -p "$PROJECT_NAME" "$@"
}

require_env_file() {
  if [ ! -f "$ENV_FILE" ]; then
    echo "Missing env file: $ENV_FILE" >&2
    echo "Create it from deploy/production.env.example and replace secrets." >&2
    exit 2
  fi
}

read_backup_mode() {
  backup_mode="$(sed -n 's/^FISORA_BACKUP_MODE=//p' "$ENV_FILE" | tail -n 1)"
  backup_mode="${backup_mode:-disabled}"
  case "$backup_mode" in
    disabled|checkpoint|scheduled) ;;
    *)
      echo "Invalid FISORA_BACKUP_MODE: $backup_mode" >&2
      exit 2
      ;;
  esac
}

cmd="${1:-help}"
case "$cmd" in
  check)
    require_env_file
    compose --profile backup config --quiet
    echo "compose config ok"
    ;;
  deploy)
    require_env_file
    read_backup_mode
    compose --profile backup pull --ignore-pull-failures
    compose --profile backup build
    if [ "$backup_mode" = "scheduled" ]; then
      compose --profile backup up -d
    else
      compose up -d
      compose stop backup >/dev/null 2>&1 || true
    fi
    compose --profile backup ps
    ;;
  migrate)
    require_env_file
    compose run --rm migrate
    ;;
  smoke)
    require_env_file
    compose run --rm backend python /app/backend/scripts/run_postgres_smoke.py
    ;;
  backup-once)
    require_env_file
    read_backup_mode
    if [ "$backup_mode" = "disabled" ]; then
      echo "backup-once requires FISORA_BACKUP_MODE=checkpoint or scheduled" >&2
      exit 2
    fi
    compose --profile backup run --rm -e FISORA_BACKUP_RUN_ONCE=1 backup
    ;;
  restore-protected-check)
    require_env_file
    encrypted_backup="${2:-}"
    age_identity="${3:-}"
    restore_dir="${4:-}"
    restored_dsn="${5:-}"
    if [ "$PROJECT_NAME" = "fisora" ] || [ "$PROJECT_NAME" = "production" ]; then
      echo "restore-protected-check refuses the production compose project" >&2
      exit 2
    fi
    if [ ! -f "$encrypted_backup" ] || [ ! -f "$age_identity" ] || [ -z "$restore_dir" ] || [ -z "$restored_dsn" ]; then
      echo "Usage: FISORA_COMPOSE_PROJECT=isolated $0 restore-protected-check <backup.age> <identity> <restore-dir> <restored-dsn>" >&2
      exit 2
    fi
    mkdir -p "$restore_dir"
    backup_dir="$(CDPATH= cd -- "$(dirname -- "$encrypted_backup")" && pwd)"
    identity_dir="$(CDPATH= cd -- "$(dirname -- "$age_identity")" && pwd)"
    restore_abs="$(CDPATH= cd -- "$restore_dir" && pwd)"
    docker run --rm --entrypoint /bin/sh \
      -v "$backup_dir:/proof/backup:ro" -v "$identity_dir:/proof/identity:ro" -v "$restore_abs:/proof/restore" \
      fisero-backup /usr/local/bin/fisora-verify-restore.sh \
      "/proof/backup/$(basename -- "$encrypted_backup")" "/proof/identity/$(basename -- "$age_identity")" /proof/restore
    docker run --rm --entrypoint /bin/sh --add-host host.docker.internal:host-gateway \
      -e DATABASE_URL="$restored_dsn" \
      -v "$restore_abs:/proof/restore:ro" fisero-backup \
      -c 'psql "$DATABASE_URL" < /proof/restore/postgres.sql'
    docker run --rm --entrypoint python3 --add-host host.docker.internal:host-gateway \
      -e DATABASE_URL="$restored_dsn" \
      -v "$restore_abs:/proof/restore:ro" fisero-backup \
      /usr/local/bin/fisora-verify-corpus.py /proof/restore
    verification_stamp="$(date -u +%Y%m%dT%H%M%SZ)"
    verification_time="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    generation_digest="$(sha256sum "$encrypted_backup" | awk '{print $1}')"
    printf '%s\n' \
      "{\"status\":\"verified\",\"verified_at\":\"$verification_time\",\"generation_file\":\"$(basename -- "$encrypted_backup")\",\"generation_digest\":\"$generation_digest\"}" \
      > "$restore_abs/restore-verification-$verification_stamp.json"
    echo "restore verification receipt: $restore_abs/restore-verification-$verification_stamp.json"
    ;;
  record-restore-verification)
    require_env_file
    receipt_file="${2:-}"
    if [ -z "$receipt_file" ] || [ ! -f "$receipt_file" ]; then
      echo "Usage: $0 record-restore-verification /path/to/restore-verification.json" >&2
      exit 2
    fi
    receipt_dir="$(CDPATH= cd -- "$(dirname -- "$receipt_file")" && pwd)"
    receipt_name="$(basename -- "$receipt_file")"
    compose --profile backup run --rm --no-deps \
      -v "$receipt_dir:/proof/receipt:ro" \
      -e FISORA_RESTORE_RECEIPT_FILE="/proof/receipt/$receipt_name" \
      --entrypoint python3 backup -c '
import json
import os
import re
from datetime import datetime
from pathlib import Path

source = Path(os.environ["FISORA_RESTORE_RECEIPT_FILE"])
payload = json.loads(source.read_text(encoding="utf-8"))
verified_at = str(payload.get("verified_at", ""))
generation_file = Path(str(payload.get("generation_file", ""))).name
generation_digest = str(payload.get("generation_digest", ""))
if payload.get("status") != "verified":
    raise SystemExit("restore receipt status is not verified")
if not generation_file.endswith(".tar.gz.age"):
    raise SystemExit("restore receipt generation file is invalid")
if not re.fullmatch(r"[0-9a-f]{64}", generation_digest):
    raise SystemExit("restore receipt digest is invalid")
parsed = datetime.fromisoformat(verified_at.replace("Z", "+00:00"))
stamp = parsed.strftime("%Y%m%dT%H%M%SZ")
target = Path("/opt/fisora/data/backups") / f"restore-verified-{stamp}.json"
temporary = target.with_suffix(".json.tmp")
safe = {
    "status": "verified",
    "verified_at": verified_at,
    "generation_file": generation_file,
    "generation_digest": generation_digest,
}
temporary.write_text(json.dumps(safe, separators=(",", ":")) + "\n", encoding="utf-8")
temporary.replace(target)
print(target.name)
'
    ;;
  logs)
    require_env_file
    service="${2:-backend}"
    compose logs --tail="${FISORA_LOG_TAIL:-200}" "$service"
    ;;
  ps)
    require_env_file
    compose ps
    ;;
  down)
    require_env_file
    compose down
    ;;
  restore-postgres)
    require_env_file
    backup_file="${2:-}"
    if [ -z "$backup_file" ] || [ ! -f "$backup_file" ]; then
      echo "Usage: $0 restore-postgres /path/to/postgres-backup.sql" >&2
      exit 2
    fi
    echo "Restoring PostgreSQL from $backup_file"
    echo "This overwrites database content. Press Ctrl+C within 5 seconds to cancel."
    sleep 5
    compose exec -T postgres sh -c 'psql "$POSTGRES_DB" "$POSTGRES_USER"' < "$backup_file"
    ;;
  help|*)
    cat <<EOF
Usage: $0 <command>

Commands:
  check              Validate production compose config.
  deploy             Pull/build/start production stack.
  migrate            Run database migrations once.
  smoke              Run Postgres-backed workflow smoke test.
  backup-once        Run one checkpoint or scheduled backup generation.
  restore-protected-check  Verify encrypted protected backup against an isolated restored DB.
  record-restore-verification  Record a successful isolated restore receipt for readiness.
  logs [service]     Show logs for backend, worker, frontend, nginx, postgres, backup.
  ps                 Show compose service status.
  down               Stop stack without deleting volumes.
  restore-postgres   Restore a postgres-*.sql dump into the database.

Environment:
  FISORA_ENV_FILE defaults to deploy/production.env.
  FISORA_COMPOSE_PROJECT defaults to fisora.
EOF
    ;;
esac
