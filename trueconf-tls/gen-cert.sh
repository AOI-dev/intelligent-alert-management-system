#!/usr/bin/env bash
# Self-signed cert for the bare IP this VM is reachable at -- no domain
# name means Let's Encrypt (or any public CA) can't issue a real one.
# Modern clients require the IP in subjectAltName, not just the CN, or
# they reject the cert outright regardless of trust -- that's what -addext
# below is for.
#
# Every visitor sees a one-time browser warning to click through (expected
# with any self-signed cert); this only exists to satisfy TrueConf
# Server's own "authorization requires HTTPS" check on the /oauth/authorize
# step, not to make the connection trusted end to end.
set -euo pipefail
cd "$(dirname "$0")"

IP="${1:-161.104.107.172}"

if [ -e certs/tls.crt ]; then
	echo "certs/tls.crt already exists -- refusing to overwrite it." >&2
	exit 1
fi

mkdir -p certs
openssl req -x509 -nodes -newkey rsa:2048 \
	-keyout certs/tls.key -out certs/tls.crt \
	-days 3650 \
	-subj "/CN=${IP}" \
	-addext "subjectAltName=IP:${IP}"

chmod 600 certs/tls.key
echo "Wrote certs/tls.crt and certs/tls.key for IP ${IP} (valid 10 years)."
