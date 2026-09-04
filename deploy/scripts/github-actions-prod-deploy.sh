#!/bin/sh
# File: deploy/scripts/github-actions-prod-deploy.sh
# Summary: Verifies and deploys an exact Fisora production commit invoked through GitHub Actions and SSM.

set -eu

ROOT_DIR="${FISORA_ROOT_DIR:-$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)}"
TARGET_SHA="${1:-}"
ENV_FILE="$ROOT_DIR/deploy/production.env"
COMPOSE_FILE="$ROOT_DIR/docker-compose.production.yml"
PROJECT_NAME="fisora"

if [ -z "$TARGET_SHA" ]; then
  echo "Target SHA is required." >&2
  exit 2
fi

cd "$ROOT_DIR"
actual_sha="$(git -c safe.directory="$ROOT_DIR" rev-parse HEAD)"
if [ "$actual_sha" != "$TARGET_SHA" ]; then
  echo "Checked out SHA does not match requested SHA." >&2
  exit 2
fi

if ! grep -q '^FISORA_WORKER_RETENTION_ENABLED=false$' "$ENV_FILE"; then
  echo "Production retention must remain disabled." >&2
  exit 2
fi
sh "$ROOT_DIR/deploy/scripts/fisora-prod.sh" check
sh "$ROOT_DIR/deploy/scripts/fisora-prod.sh" deploy
sh "$ROOT_DIR/deploy/scripts/fisora-prod.sh" smoke

actual_sha="$(git -c safe.directory="$ROOT_DIR" rev-parse HEAD)"
if [ "$actual_sha" != "$TARGET_SHA" ]; then
  echo "Production SHA changed during deploy." >&2
  exit 2
fi

compose() {
  docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" -p "$PROJECT_NAME" "$@"
}

compose ps
compose ps --services --status running | grep -qx backend
compose ps --services --status running | grep -qx frontend
compose ps --services --status running | grep -qx worker

worker_retention="$(compose exec -T worker sh -lc 'printf %s "${FISORA_WORKER_RETENTION_ENABLED:-}"')"
if [ "$worker_retention" != "false" ]; then
  echo "Worker retention runtime value is not false." >&2
  exit 2
fi

curl -fsS http://127.0.0.1/portal-next >/dev/null
printf 'FISORA_GITHUB_DEPLOY_OK sha=%s retention=%s\n' "$actual_sha" "$worker_retention"
