#!/usr/bin/env bash
# Sync a stack to the VM, bring it up, and verify it's actually healthy —
# so you don't have to `ssh vm docker compose logs` after every push.
#
# Usage: scripts/deploy.sh <local-dir> <remote-dir> [health-url]
#   scripts/deploy.sh prometheus prometheus http://localhost:9090/-/healthy
#   scripts/deploy.sh . zabbix http://localhost:8080
set -euo pipefail

LOCAL="${1:?usage: deploy.sh <local-dir> <remote-dir> [health-url]}"
REMOTE_NAME="${2:?usage: deploy.sh <local-dir> <remote-dir> [health-url]}"
HEALTH_URL="${3:-}"
VM_HOST="vm"
REMOTE_DIR="~/${REMOTE_NAME}"

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOCAL_DIR="${ROOT}/${LOCAL}"
[ -d "$LOCAL_DIR" ] || { echo "no such local dir: $LOCAL_DIR" >&2; exit 1; }

echo "==> syncing ${LOCAL} -> ${VM_HOST}:${REMOTE_NAME}"
ssh "$VM_HOST" "mkdir -p $REMOTE_DIR"
# flags.env is committed and always replaces remote runtime flags. .env stays
# private to the deployment host, so credentials never cross the wire.
rsync -az --exclude '.env' --exclude '.git' "$LOCAL_DIR"/ "$VM_HOST:$REMOTE_DIR"/

if [ -f "$LOCAL_DIR/.env.example" ]; then
  echo "==> ensuring secrets .env exists (never overwritten if already present)"
  ssh "$VM_HOST" "cd $REMOTE_DIR && [ -f .env ] || cp .env.example .env"
fi

# Later --env-file values win. This makes flags reproducible on every
# deployment even while an older remote .env still has stale non-secret keys.
COMPOSE="docker compose --env-file flags.env"
if ssh "$VM_HOST" "test -f $REMOTE_DIR/.env"; then
  COMPOSE="docker compose --env-file .env --env-file flags.env"
fi

echo "==> docker compose up -d --build"
ssh "$VM_HOST" "cd $REMOTE_DIR && $COMPOSE up -d --quiet-pull --build"

echo "==> waiting for containers to settle"
sleep 5

STATUS="$(ssh "$VM_HOST" "cd $REMOTE_DIR && $COMPOSE ps --format '{{.Name}}: {{.Status}}'")"
echo "$STATUS"

FAIL=0
if echo "$STATUS" | grep -qiE 'restarting|exited|unhealthy'; then
  echo "==> FAIL: unhealthy/restarting/exited container(s)"
  FAIL=1
fi

if [ -n "$HEALTH_URL" ] && [ "$FAIL" -eq 0 ]; then
  CODE="$(ssh "$VM_HOST" "curl -s -o /dev/null -w '%{http_code}' '$HEALTH_URL'" || echo 000)"
  if [ "$CODE" != "200" ]; then
    echo "==> FAIL: health check $HEALTH_URL returned $CODE"
    FAIL=1
  fi
fi

if [ "$FAIL" -ne 0 ]; then
  echo "==> dumping last 50 lines per service"
  ssh "$VM_HOST" "cd $REMOTE_DIR && $COMPOSE logs --tail=50"
  exit 1
fi

echo "==> OK: ${REMOTE_NAME} deployed and healthy"
