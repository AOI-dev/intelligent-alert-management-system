#!/usr/bin/env bash
# Create the secrets-only .env with a freshly generated database password.
set -euo pipefail

cd "$(dirname "$0")"

if [ -e .env ]; then
	echo ".env already exists — refusing to overwrite it." >&2
	exit 1
fi

gen() { LC_ALL=C tr -dc 'A-Za-z0-9' </dev/urandom | head -c 32; }

sed \
	-e "s|^POSTGRES_PASSWORD=.*|POSTGRES_PASSWORD=$(gen)|" \
	.env.example >.env

chmod 600 .env
echo "Wrote .env with a generated database password."
