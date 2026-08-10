#!/usr/bin/env bash
# Resume an existing stopped container (safe: does not recreate it).
set -euo pipefail
cd "$(dirname "$0")"
set -a; . ./flags.env; set +a

# Import shared helpers.
. ./helpers.sh

docker start "$TRUECONF_CONTAINER_NAME"
sleep 5
# Re-apply admin ACL patch; configs inside the container are ephemeral, so the
# default RFC1918-only restriction would return after a restart.
_patch_admin_acl "$TRUECONF_CONTAINER_NAME"
