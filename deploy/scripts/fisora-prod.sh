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

cmd="${1:-help}"
case "$cmd" in
  check)
    require_env_file
    compose config --quiet
    echo "compose config ok"
    ;;
  deploy)
    require_env_file
    compose pull --ignore-pull-failures
    compose build
    compose up -d
    compose ps
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
    compose run --rm -e FISORA_BACKUP_RUN_ONCE=1 backup
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
    docker run --rm --entrypoint python3 --add-host host.docker.internal:host-gateway \
      -e DATABASE_URL="$restored_dsn" \
      -v "$restore_abs:/proof/restore:ro" fisero-backup \
      /usr/local/bin/fisora-verify-corpus.py /proof/restore
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
  backup-once        Run one database/document manifest backup.
  restore-protected-check  Verify encrypted protected backup against an isolated restored DB.
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
