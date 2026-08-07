#!/usr/bin/env bash
# Create .env from .env.example with freshly generated database passwords.
set -euo pipefail

cd "$(dirname "$0")/.."

if [ -e .env ]; then
	echo ".env already exists — refusing to overwrite it." >&2
	exit 1
fi

gen() { LC_ALL=C tr -dc 'A-Za-z0-9' </dev/urandom | head -c 32; }

sed \
	-e "s|^MYSQL_ROOT_PASSWORD=.*|MYSQL_ROOT_PASSWORD=$(gen)|" \
	-e "s|^MYSQL_PASSWORD=.*|MYSQL_PASSWORD=$(gen)|" \
	.env.example >.env

chmod 600 .env
echo "Wrote .env with generated passwords."
