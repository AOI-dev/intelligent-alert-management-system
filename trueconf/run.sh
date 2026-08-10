#!/usr/bin/env bash
# One-time launch of TrueConf Server. Deliberately NOT a `docker compose up`
# and NOT wired into scripts/deploy.sh: TrueConf's own docs warn that
# recreating the container via Compose up/down invalidates the license.
# Run this once; afterwards use stop.sh/start.sh, never re-run this script
# while a container of the same name already exists.
set -euo pipefail

cd "$(dirname "$0")"
set -a
. ./flags.env
[ -f .env ] && . ./.env
set +a

: "${TRUECONF_ADMIN_PASSWORD:?run gen-env.sh first to create .env, or set TRUECONF_ADMIN_PASSWORD manually}"

if docker ps -a --format '{{.Names}}' | grep -qx "$TRUECONF_CONTAINER_NAME"; then
	echo "container '$TRUECONF_CONTAINER_NAME' already exists — refusing to re-run." >&2
	echo "use ./start.sh / ./stop.sh, or ./remove.sh first if you really want to recreate it." >&2
	exit 1
fi

mkdir -p "$TRUECONF_DATA_DIR" "$TRUECONF_LOG_DIR"

# Import shared helpers.
. ./helpers.sh

args=(
	-d
	--name "$TRUECONF_CONTAINER_NAME"
	--restart unless-stopped
	-p "${TRUECONF_HTTP_PORT}:80"
	-p "${TRUECONF_HTTPS_PORT}:443"
	-p "${TRUECONF_PROTOCOL_PORT}:4307"
	-e "ADMIN_USER=${TRUECONF_ADMIN_USER}"
	-e "ADMIN_PASSWORD=${TRUECONF_ADMIN_PASSWORD}"
	-v "$(pwd)/${TRUECONF_DATA_DIR}:/opt/trueconf/server/var/lib"
	-v "$(pwd)/${TRUECONF_LOG_DIR}:/opt/trueconf/server/var/log"
)

[ -n "${TRUECONF_SERIAL:-}" ] && args+=(-e "Serial=${TRUECONF_SERIAL}")
[ -n "${TRUECONF_SERVER_ID:-}" ] && args+=(-e "ServerID=${TRUECONF_SERVER_ID}")
[ -n "${TRUECONF_SERVER_NAME:-}" ] && args+=(-e "ServerName=${TRUECONF_SERVER_NAME}")

echo "==> starting $TRUECONF_CONTAINER_NAME from $TRUECONF_IMAGE"
docker run "${args[@]}" "$TRUECONF_IMAGE"

# Allow admin panel access from any IP (default restricts to RFC1918/local).
# This is applied after first boot so the container has generated its configs.
_patch_admin_acl "$TRUECONF_CONTAINER_NAME"

echo "==> control panel: http://localhost:${TRUECONF_HTTP_PORT}"
echo "==> logs: docker logs -f $TRUECONF_CONTAINER_NAME"
