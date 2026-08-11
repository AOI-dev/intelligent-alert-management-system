#!/usr/bin/env bash
# Create the secrets-only .env with a freshly generated admin password.
set -euo pipefail

cd "$(dirname "$0")"

if [ -e .env ]; then
	echo ".env already exists — refusing to overwrite it." >&2
	exit 1
fi

# `|| true` matters here: under `set -o pipefail` above, `head -c 32`
# closing the pipe early can send `tr` a SIGPIPE, which pipefail then
# reports as the pipeline failing (exit 141) even though head already
# captured the bytes it needed -- an intermittent race, not a real error.
gen() { LC_ALL=C tr -dc 'A-Za-z0-9' </dev/urandom | head -c 32 || true; }

sed \
	-e "s|^TRUECONF_ADMIN_PASSWORD=.*|TRUECONF_ADMIN_PASSWORD=$(gen)|" \
	.env.example >.env

chmod 600 .env
echo "Wrote .env with a generated admin password."
