# TimescaleDB stack

Central relational/time-series store for the platform (АР-08). First tenant is
the `platform` identity schema (roles, TrueConf-linked identities, synthetic
AD account links); incident state, subscriptions, policies, and audit land
here in later increments, followed by hypertables for event/alert history.

No host port is published — only the `platform` monolith, on the
`timescaledb_timescaledb` network, can reach it (АР-14, defense in depth).

## Start

```sh
./gen-env.sh     # writes secret-only .env with a random DB password
set -a; . .env; . flags.env; set +a
docker compose up -d
```

## Configuration

- `flags.env` — committed: image version, DB name, DB user.
- `.env` — gitignored, secret-only: `POSTGRES_PASSWORD`. Generate with
  `./gen-env.sh`; `scripts/deploy.sh` creates it from `.env.example` only
  when absent and never overwrites it.

## Schema

The `platform` app owns its schema via `SQLAlchemy` `metadata.create_all` at
startup — there is no migrations tool yet, matching this repo's
build-the-thin-slice-first approach elsewhere. Revisit with a real migration
tool (e.g. Alembic) once the schema needs to evolve without a full recreate.

## Data

`timescaledb-data` named volume. `docker compose down` keeps it; `docker
compose down -v` destroys it along with all history. Back up with:

```sh
docker compose exec timescaledb pg_dump -U platform platform > platform-backup.sql
```
