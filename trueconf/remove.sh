#!/usr/bin/env bash
# Remove the container (data in $TRUECONF_DATA_DIR survives; the license
# tied to this container instance does not — re-registration will be
# needed after run.sh next launches). Confirms before acting.
set -euo pipefail
cd "$(dirname "$0")"
set -a; . ./flags.env; set +a

read -r -p "Remove container '$TRUECONF_CONTAINER_NAME'? This may require re-licensing. [y/N] " reply
case "$reply" in
	[yY]*) docker rm -f "$TRUECONF_CONTAINER_NAME" ;;
	*) echo "aborted"; exit 1 ;;
esac
