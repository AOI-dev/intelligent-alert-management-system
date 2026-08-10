#!/usr/bin/env bash
# Resume an existing stopped container (safe: does not recreate it).
set -euo pipefail
cd "$(dirname "$0")"
set -a; . ./flags.env; set +a
docker start "$TRUECONF_CONTAINER_NAME"
