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
