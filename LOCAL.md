# Running the whole thing locally

`scripts/deploy.sh` only ever targets the VM (see `CLAUDE.md`). Locally you
drive each stack with `docker compose` directly. Every stack is
self-contained — its own project `name:`, network, and volumes — so they
come up independently, in any order except where one joins another's
network (see *Bring-up order*).

Each stack's own README is the reference for what it does; this file is
only about running them all together on one machine.

## Prerequisites

- Docker with Compose v2 (`docker compose`, not `docker-compose`).
- ~8 GB RAM free for the full set. The minimal set (see below) needs far less.
- The host ports in the table below, unclaimed.

| Port | Stack | What |
| --- | --- | --- |
| 8080 | `.` (zabbix) | Zabbix web UI |
| 9090 / 9093 | `prometheus` | Prometheus / Alertmanager |
| 8090 | `eventsim` | event simulator (also runs Kafka, unpublished) |
| 8100 | `platform` | the monolith's API |
| 8091 | `frontend` | the dashboard |
| 8110 | `notifications` | notification service |
| 8120 | `trueconf-bot` | bot webhook target |
| 80 / 443 / 4307 | `trueconf` | TrueConf Server |
| 8443 / 8543 | `trueconf-tls` | HTTPS front for TrueConf / for the frontend |

## First: replace the hardcoded VM IP

`161.104.107.172` is written into committed config in several places. It is
**not** a variable, so a local run needs it changed.

Use your machine's **LAN IP**, not `localhost`. The same string has to work
in two places at once: your browser, and `httpx` running *inside* the
platform container — where `localhost` is the container itself, not your
machine. `TRUECONF_BASE_URL` is used for both the browser-facing
`/oauth2/authorize` redirect and the server-side token exchange, so one
value has to satisfy both.

```sh
HOST_IP=$(ip route get 1.1.1.1 | awk '{print $7; exit}')   # e.g. 192.168.1.42
echo "$HOST_IP"
```

On WSL2 this prints the WSL VM's address (`172.x.x.x`) rather than the
Windows machine's LAN address. That's the right one to use: it's reachable
both from the containers and from a browser on the Windows side.

What to change:

| File | Setting | Why it matters |
| --- | --- | --- |
| `platform/flags.env` | `TRUECONF_BASE_URL` | browser redirect *and* server-side token exchange |
| `platform/flags.env` | `TRUECONF_OAUTH_REDIRECT_URI` | must match the redirect_uri registered in TrueConf's control panel, exactly |
| `platform/flags.env` | `AUTH_RETURN_TO_ALLOWLIST` | exact-match allowlist; a stale entry silently drops `return_to` |
| `platform/flags.env` | `AUTH_DEFAULT_RETURN_TO` | must also appear in the allowlist above |
| `platform/flags.env` | `VLLM_BASE_URL` | only read when `AI_ENRICHMENT_MODE` isn't `off` |
| `trueconf-bot/flags.env` | `TRUECONF_SERVER` | only if you run the bot |
| `trueconf-tls/gen-cert.sh` | default `IP=` argument | or just pass the IP as `$1` |
| `platform/scripts/routing_from_corpus.py` | `DEFAULT_WEBHOOK` | offline analysis script; `--webhook` overrides it |

A blunt repo-wide swap works, as long as you don't commit it:

```sh
git grep -l 161.104.107.172 -- ':!artifacts' ':!*.md' | xargs sed -i "s/161\.104\.107\.172/$HOST_IP/g"
```

If you skip TrueConf entirely (see *Logging in*), only `AUTH_*` matter, and
only if you want the login flow at all.

## Bring-up order

`platform` joins four **external** networks (`eventsim_eventsim`,
`prometheus_prometheus`, `zabbix_zabbix`, `timescaledb_timescaledb`), and
`frontend` joins `platform_platform`. External means Compose won't create
them — it errors out if they don't exist yet. So those stacks come up
first, or you stub the networks (see *Minimal set*).

Every stack with a `gen-env.sh` needs it run once; it writes a gitignored
`.env` with generated secrets. Stacks without one need no secrets.

```sh
# 1. TimescaleDB — platform's identity + history store
cd timescaledb && ./gen-env.sh && set -a && . .env && . flags.env && set +a \
  && docker compose up -d && cd ..

# 2. eventsim — Kafka broker + the synthetic event source
cd eventsim && set -a && . flags.env && set +a && docker compose up -d --build && cd ..

# 3. prometheus + alertmanager
cd prometheus && set -a && . flags.env && set +a && docker compose up -d && cd ..

# 4. zabbix (this repo's root stack)
./scripts/gen-env.sh && set -a && . .env && . flags.env && set +a && docker compose up -d

# 5. platform — needs a .env of its own, see below
cd platform && set -a && . .env && . flags.env && set +a \
  && docker compose up -d --build && cd ..

# 6. frontend
cd frontend && set -a && . flags.env && set +a && docker compose up -d --build && cd ..
```

Order matters only for the network dependency; restarting any one stack
afterwards is safe and independent.

### platform's `.env`

`platform` has no `gen-env.sh` — copy the example and fill it in:

```sh
cp platform/.env.example platform/.env
```

- `IDENTITY_DATABASE_URL` — the password must match `timescaledb/.env`'s
  `POSTGRES_PASSWORD`. Everything else in that URL
  (`platform:…@timescaledb:5432/platform`) is already right, since both
  containers share the `timescaledb_timescaledb` network.
- `SESSION_SECRET_KEY` — any random string (`openssl rand -hex 32`). It
  signs session cookies; leaving it empty falls back to a hardcoded
  insecure default.
- `ZABBIX_API_TOKEN` — optional. Without it the Zabbix reconcile loop logs
  a traceback every `ZABBIX_RECONCILE_INTERVAL` seconds and nothing else
  breaks. See the platform README's "Zabbix API token".
- `TRUECONF_OAUTH_CLIENT_SECRET` — only for the login flow.
- `VLLM_API_KEY` — only when `AI_ENRICHMENT_MODE` isn't `off`.

### Minimal set

`platform` degrades rather than failing when its dependencies are missing:
a Kafka or identity-DB failure at startup is caught, recorded in
`app.state`, and reported by `/health` — the API still serves. So the
smallest useful local run is TimescaleDB + platform + frontend, with the
other three networks stubbed:

```sh
docker network create eventsim_eventsim
docker network create prometheus_prometheus
docker network create zabbix_zabbix
```

You get the UI, login, and the admin panel, but no events or alerts —
nothing is producing them. Add `eventsim` (step 2) as soon as you want data
flowing.

## Logging in

The dashboard shows nothing until you're authenticated: there is no
development bypass in `get_current_identity`.

### Option A — the shortcut, no TrueConf

Insert an identity directly and mint a session token for it. Both roles
below exist already: `ensure_seed_roles` seeds `viewer`/`engineer`/`admin`
at platform startup.

```sh
docker exec timescaledb psql -U platform -d platform -c "
  insert into identities (id, trueconf_subject, display_label, created_at, last_login_at)
  values (gen_random_uuid(), 'local-dev', 'Local Dev', now(), now());
  insert into identity_roles (identity_id, role_id, assigned_at)
  select id, 'admin', now() from identities where trueconf_subject = 'local-dev';"

ID=$(docker exec timescaledb psql -U platform -d platform -tAc \
  "select id from identities where trueconf_subject = 'local-dev'")
docker exec monitoring-platform python -c "
import sys
from uuid import UUID
from app.identity.session import issue_session_cookie
print(issue_session_cookie(UUID(sys.argv[1])))" "$ID"
```

That token is what the frontend keeps in `sessionStorage` after a real
login, so paste it there and reload:

```js
sessionStorage.setItem('platform_session_token', '<token>')
```

It's also usable directly: `curl -H "Authorization: Bearer <token>"
http://localhost:8100/v1/auth/me`.

### Option B — the real TrueConf flow

Only worth it when you're working on login itself. `trueconf/` runs locally
exactly as it does on the VM, but read `trueconf/README.md` first — that
container is license-sensitive and must never be `docker run` twice or
managed by Compose.

Then `trueconf-tls/`, whose README covers the parts that aren't obvious:
TrueConf refuses OAuth over plain HTTP, its API needs `X-Forwarded-SSL` via
an apache drop-in installed into the running container, the callback has to
be served from TrueConf's own origin, and the frontend has to be reached
over `:8543` so the whole flow shares one scheme. Generate the cert for
your LAN IP (`./gen-cert.sh "$HOST_IP"`), and register the same
`redirect_uri` in TrueConf's control panel under *API → OAuth2*.

The first identity to log in gets `admin` while
`AUTH_BOOTSTRAP_FIRST_ADMIN=true` (`platform/flags.env`), because
`/v1/identities` requires `admin` and nothing else can grant it.

## Verify

```sh
curl -s localhost:8100/health   # kafka / identity / monitoring_db / auth statuses
curl -s localhost:8091/health   # frontend -> platform passthrough
curl -s localhost:8090/health   # eventsim
curl -s localhost:9090/-/healthy
curl -s localhost:8080          # zabbix web
```

`/health` reporting `unavailable: …` for a contour you didn't start is
expected, not a failure — that's the degradation described above.

## What doesn't run locally

- **vLLM** — no stack in this repo; it's a GPU service on the VM. Leave
  `AI_ENRICHMENT_MODE=off` (the default) and nothing reads it.
- **`active-directory`** — a Samba AD DC. It runs, but wants privileges and
  its own DNS setup; `platform/scripts/seed_synthetic_ad.py` covers the AD
  linkage without it.
- **`trueconf-tls`'s apache drop-in** — needs a running `trueconf-server`
  container to install into, so it's meaningless without Option B.

## Teardown

```sh
for d in frontend platform prometheus eventsim timescaledb; do (cd $d && docker compose down); done
docker compose down          # zabbix, at the root
```

Add `-v` to drop volumes too — for `timescaledb` that means identities and
history, and you'd redo *Logging in*.
