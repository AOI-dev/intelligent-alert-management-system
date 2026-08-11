#!/usr/bin/env bash
# Installs tcs/xforwarded-ssl-vhost.conf into the *running* trueconf-server
# container and restarts only its apache front end.
#
# Run this on the VM (after `scripts/deploy.sh trueconf-tls trueconf-tls`
# has synced this directory there), not locally -- the container lives on
# the VM:
#
#     ssh vm 'cd ~/trueconf-tls && ./install-tcs-vhost.sh'
#
# Idempotent: re-running overwrites the same file and restarts apache
# again. It must be re-run whenever trueconf-server is recreated
# (trueconf/remove.sh + run.sh, an image update, ...) -- nothing here
# persists across container recreation, exactly like the manager.toml
# [proxy] change documented in README.md. Recreating the container to add
# a bind mount instead is what trueconf/README.md rules out (license
# risk), so this is a copy-in rather than a volume.
set -euo pipefail
cd "$(dirname "$0")"

CONTAINER="${TRUECONF_CONTAINER:-trueconf-server}"
DEST_DIR=/opt/trueconf/server/opt2
APACHECTL=/opt/trueconf/server/bin/webmanager/apachectl

docker exec "$CONTAINER" mkdir -p "$DEST_DIR"
docker cp tcs/xforwarded-ssl-vhost.conf "$CONTAINER:$DEST_DIR/xforwarded-ssl-vhost.conf"
docker exec "$CONTAINER" chown -R trueconf:trueconf "$DEST_DIR"

# Syntax-check before restarting: a bad drop-in would otherwise take the
# whole TrueConf control panel down with it, and this file is the only
# thing standing between a working config and that.
if ! docker exec "$CONTAINER" "$APACHECTL" -t; then
	echo "apache rejected the config -- removing the drop-in, leaving apache as it was." >&2
	docker exec "$CONTAINER" rm -f "$DEST_DIR/xforwarded-ssl-vhost.conf"
	exit 1
fi

# A full restart, not `-k graceful`: the drop-in adds a `Listen`, and
# apache only picks new listeners up on a hard restart. This restarts the
# trueconf-web supervisor program alone, not the container -- same
# license-safety property as trueconf/start.sh.
docker exec "$CONTAINER" supervisorctl restart trueconf-web

echo "Installed $DEST_DIR/xforwarded-ssl-vhost.conf and restarted apache in $CONTAINER."
