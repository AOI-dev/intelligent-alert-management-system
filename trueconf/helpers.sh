#!/usr/bin/env bash
# Shared helpers for TrueConf lifecycle scripts.
# Sourced by run.sh and start.sh; do not execute directly.

# Patch Apache <Location /admin> ACL inside the container to allow remote IPs.
# TrueConf's default restricts the admin panel to RFC1918/local IPs, which
# blocks access from the public internet. This updates both the frontend
# webmanager and backend Apache configs, then graceful-reloads them.
_patch_admin_acl() {
	local container="$1"
	echo "==> patching admin ACL to allow remote IPs"
	local conf='<Location /admin>\n    Require all granted\n</Location>\n'
	docker exec "$container" sh -c "printf '$conf' > /opt/trueconf/server/etc/webmanager/opt/local_only_admin_24.conf" || true
	docker exec "$container" sh -c "printf '$conf' > /opt/trueconf/server/etc/backend/opt/local_only_admin_24.conf" || true
	docker exec "$container" /opt/trueconf/server/bin/webmanager/httpd -f /opt/trueconf/server/etc/webmanager/httpd.conf -k graceful >/dev/null 2>&1 || true
	docker exec "$container" /opt/trueconf/server/bin/webmanager/httpd -f /opt/trueconf/server/etc/backend/httpd.conf -k graceful >/dev/null 2>&1 || true
}
