#!/usr/bin/env bash
# Safe deploy for TrueConf Server.
#
# TrueConf's own docs warn that recreating the container via docker compose
# up/down invalidates the server's license. This script therefore does NOT use
# Compose and does NOT recreate an existing container.
#
# Behaviour:
#   1. rsync trueconf/ to the VM (excluding .env and any local data/ dir).
#   2. Ensure a remote .env exists from .env.example if missing (never overwrite).
#   3. If the TrueConf container does not exist on the VM, run ./run.sh once.
#   4. If the container already exists, run ./start.sh instead (safe restart).
#
# Usage: scripts/deploy-trueconf.sh

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOCAL_DIR="${ROOT}/trueconf"
VM_HOST="vm"
REMOTE_DIR="~/trueconf"
CONTAINER_NAME="trueconf-server"

[ -d "$LOCAL_DIR" ] || { echo "no such local dir: $LOCAL_DIR" >&2; exit 1; }

echo "==> syncing trueconf -> ${VM_HOST}:${REMOTE_DIR}"
ssh "$VM_HOST" "mkdir -p $REMOTE_DIR"
# Keep .env private to the VM; never overwrite it. Keep local data/ out too.
rsync -az --exclude '.env' --exclude '.git' --exclude 'data' \
  "${LOCAL_DIR}/" "$VM_HOST:$REMOTE_DIR/"

# Ensure remote secrets exist, but never clobber an existing deployment's .env.
echo "==> ensuring secrets .env exists (never overwritten if already present)"
ssh "$VM_HOST" "cd $REMOTE_DIR && [ -f .env ] || ./gen-env.sh"

# Detect whether the container already exists on the VM.
EXISTS="$(ssh "$VM_HOST" "docker ps -a --format '{{.Names}}' | grep -qx '$CONTAINER_NAME' && echo yes || echo no")"

if [ "$EXISTS" = "no" ]; then
  echo "==> container '$CONTAINER_NAME' not found; running ./run.sh (one-time launch)"
  ssh "$VM_HOST" "cd $REMOTE_DIR && ./run.sh"
else
  echo "==> container '$CONTAINER_NAME' already exists; running ./start.sh (preserve license)"
  ssh "$VM_HOST" "cd $REMOTE_DIR && ./start.sh"
fi

echo "==> waiting for container to settle (first boot initializes the database)"
for i in {1..60}; do
  STATUS="$(ssh "$VM_HOST" "docker ps --format '{{.Names}}: {{.Status}}' | grep '$CONTAINER_NAME' || echo 'NOT RUNNING'")"
  if echo "$STATUS" | grep -qi 'NOT RUNNING'; then
    echo "==> FAIL: $CONTAINER_NAME is not running"
    ssh "$VM_HOST" "cd $REMOTE_DIR && docker logs --tail=50 $CONTAINER_NAME" || true
    exit 1
  fi
  # TrueConf exposes HTTP on port 80 inside the container, mapped to the host
  # port configured in flags.env (default 80).
  HTTP_CODE="$(ssh "$VM_HOST" "curl -s -o /dev/null -w '%{http_code}' --max-time 10 http://localhost/ || echo 000")"
  if [ "$HTTP_CODE" = "200" ]; then
    echo "==> OK: TrueConf deployed and control panel is up (HTTP $HTTP_CODE after ${i}0s)"
    exit 0
  fi
  echo "    ... not ready yet (HTTP $HTTP_CODE), retrying"
  sleep 10
done

echo "==> FAIL: control panel did not become ready within 10 minutes"
ssh "$VM_HOST" "cd $REMOTE_DIR && docker logs --tail=50 $CONTAINER_NAME" || true
exit 1
