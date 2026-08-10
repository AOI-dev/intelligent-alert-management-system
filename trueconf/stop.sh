#!/usr/bin/env bash
# Stop without removing the container (safe: license state is preserved).
set -euo pipefail
cd "$(dirname "$0")"
set -a; . ./flags.env; set +a
docker stop "$TRUECONF_CONTAINER_NAME"
