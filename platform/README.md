# Monitoring platform

Central FastAPI modular monolith for the alert-management architecture. It
consumes versioned Kafka event and alert topics and presents the central landing
page at `http://<host>:8100/`.

## Implemented contours

- **Integration**: consumes `monitoring.events.v1` and `monitoring.alerts.v1`.
  Eventsim is the first producer. Alertmanager posts alert lifecycle transitions
  to the platform webhook; Zabbix can post action webhooks and is reconciled
  through its JSON-RPC API when the dedicated token is configured.
- **Filtering**: pass-through service boundary for later noise/storm policy.
- **Alerts**: alert projection and query API.
- **Monitoring**: bounded in-memory event/alert history. TimescaleDB replaces
  this projection in a later increment.
- **Routing**: reserved notification-delivery boundary; no provider is called.
  Delivery itself, once routing publishes `notification.requested`, is
  handled by the separate `notifications` dispatcher stack (see
  `notifications/README.md`), not by code in this monolith.
- **AI**: reserved Kafka request/result topics for horizontally scalable worker
  groups; no model or worker is required for the deterministic path.
- **Core**: `app/core/` runs every consumed alert through a per-alert stage,
  then a per-sequence stage over a `TimeBoundedWindow` keyed by
  `(source, metric)` (see `app/core/pipeline.py`). This is real plumbing
  wired to the live Kafka flow, but both stages default to pass-through —
  no dedup/correlation/storm-suppression policy or windowing algorithm has
  been chosen yet; that's deliberately left open (АР-03). Any `Decision`
  the transforms do produce is published to `monitoring.decisions.v1` and
  queryable at `/v1/decisions`.
- **Incidents**: `monitoring.incident-events.v1` is a defined contract (see
  `artifacts/kafka-protocol.md`); nothing publishes to it yet, so treat it
  as reserved until that increment lands.
- **Identity**: TrueConf Server OAuth2 (Authorization Code flow) is the auth
  path; roles are an open-ended table seeded with `viewer`/`engineer`/`admin`
  rather than a fixed enum, so new roles are an insert, not a deploy. A
  synthetic Active Directory link (`ad_login`/`department`/`team`) is a
  nominal attribute source only — see `platform/app/identity/`. `/v1/events`
  and `/v1/alerts` now require an authenticated session; the admin-only
  `/v1/identities/*` endpoints manage roles and AD links.

## API

- `GET /health`
- `GET /v1/contours`
- `GET /v1/events`
- `GET /v1/alerts`
- `POST /v1/integrations/{slug}/webhook` — generic dispatch to whichever
  `WebhookAlertSource` claims `slug`; built in today as `alertmanager` and
  `zabbix` (see "Monitoring client adapters" below)
- `GET /` — polling alert landing page
- `GET /metrics`
- `GET /v1/auth/login`, `GET /v1/auth/callback`, `POST /v1/auth/logout`,
  `GET /v1/auth/me`
- `GET /v1/identities`, `POST /v1/identities/{id}/roles`,
  `PUT /v1/identities/{id}/ad-link` — admin role only
- `GET /v1/decisions` — output of `app/core/`, empty until a real transform
  is implemented

## Monitoring client adapters

Real deployments talk to wildly different monitoring stacks — Alertmanager,
Zabbix, and whatever a given customer already runs — so ingestion is a
plugin port, not a hardcoded branch. Two shapes cover it, both in
`app/plugins/ports.py`:

- **`WebhookAlertSource`** — the vendor calls us. `POST
  /v1/integrations/{slug}/webhook` looks up the adapter registered for
  `slug` and calls `adapter.parse(payload) -> Sequence[ParsedAlert]`. The
  route never branches on vendor identity; each adapter owns its own
  payload shape entirely (Alertmanager's `{"alerts": [...]}`, Zabbix's flat
  `eventid` object, or anything else) and raises `ValueError` on a
  malformed payload, which the route turns into HTTP 422.
- **`AlertSource`** — we call the vendor (poll an API, subscribe to a
  queue). The engine drains it via `async def events()` /
  `async def alerts()` async iterators; see `app/plugins/ports.py` and the
  example in `app/plugins/builtins/sources.py`.

`AlertmanagerWebhookSource` and `ZabbixWebhookSource`
(`app/plugins/builtins/webhooks.py`) are the two adapters wired in by
default. A third monitoring client is a new class implementing one of
these Protocols plus an entry in `PLUGIN_PATHS` — no changes to `app/main.py`
or the route. `PluginRegistry` rejects two webhook adapters that claim the
same `slug` at startup rather than letting one silently shadow the other.
See `platform/tests/plugins/test_webhook_sources.py` for a worked example
of a from-scratch adapter with a payload shape unrelated to either builtin.

## Rate limiting

Rate limiting sits at the HTTP entrance (`app/core/rate_limit.py`,
wired into `app/main.py` as `RateLimitMiddleware`), not between internal
modules — this is a monolith, so a call from filtering to correlation is a
function call, not a network hop, and there's nothing to rate-limit there.
Two token-bucket rules apply today, matched by longest path prefix so the
narrower one wins:

- `/v1/integrations/*` (webhooks — unauthenticated, machine-to-machine,
  bursty by nature): `RATE_LIMIT_WEBHOOK_CAPACITY` /
  `RATE_LIMIT_WEBHOOK_REFILL_PER_SECOND` (default 60 burst, 5/s refill).
- `/v1/*` (everything else): `RATE_LIMIT_API_CAPACITY` /
  `RATE_LIMIT_API_REFILL_PER_SECOND` (default 120 burst, 20/s refill).

`/health` and `/metrics` match neither prefix and stay unlimited. Clients
are keyed by `X-Forwarded-For` (falling back to the socket peer), so a
reverse proxy in front of this service must set that header for the limit
to track real clients rather than the proxy itself. The bucket store is an
in-memory dict, correct for the current single-replica deployment; if this
ever runs as more than one replica, swap `InMemoryBucketStore` for a
shared (e.g. Redis-backed) implementation of the same `BucketStore`
protocol — the middleware doesn't change. See
`platform/tests/core/test_rate_limit.py` for the request-level behavior.

The other place traffic crosses a real network boundary is this process's
own outbound calls (Zabbix API reconciliation, TrueConf OAuth); those get
client-side timeouts at their call sites rather than a shared limiter,
since each has a different failure mode.

## TrueConf OAuth2 and identity database

1. In the TrueConf Server control panel: **API -> OAuth2**, create an app,
   note the generated `client_id`/`client_secret`.
2. Set `TRUECONF_OAUTH_CLIENT_ID` and `TRUECONF_OAUTH_REDIRECT_URI` in
   `flags.env`; put `TRUECONF_OAUTH_CLIENT_SECRET` in the deployment host's
   private `platform/.env`.
3. Verify `TRUECONF_USERINFO_PATH` and the subject/display claim field names
   against the deployed server's own `/api/v4/docs/` — TrueConf doesn't
   publish a fixed schema across versions.
4. The `timescaledb` stack must be up first (see `timescaledb/README.md`);
   set `IDENTITY_DATABASE_URL` and `SESSION_SECRET_KEY` in `platform/.env`.

First login for any TrueConf account auto-provisions an identity with the
`viewer` role (JIT provisioning); an existing admin promotes it via
`POST /v1/identities/{id}/roles`. `platform/scripts/seed_synthetic_ad.py`
backfills synthetic department/team data for identities that have logged in
at least once — see the script's docstring.

## Zabbix API token

Create a dedicated API token in Zabbix for a service account limited to read
access for the monitored hosts. Put it in the deployment host's private
`platform/.env`:

```env
ZABBIX_API_TOKEN=<token>
```

The platform loads open `problem.get` records every
`ZABBIX_RECONCILE_INTERVAL` seconds (60 by default). Webhooks are the fast path;
API polling reconciles missed delivery after outages. Do not use the `Admin`
password as an application credential.

For a Zabbix action, post this minimum JSON payload to
`http://monitoring-platform:8100/v1/integrations/zabbix/webhook`:

```json
{
  "eventid": "{EVENT.ID}",
  "name": "{EVENT.NAME}",
  "severity": "{EVENT.NSEVERITY}",
  "clock": "{EVENT.DATE} {EVENT.TIME}",
  "hosts": [{"host": "{HOST.HOST}"}],
  "tags": [{"tag": "service", "value": "payments"}]
}
```

The exact action macro/template must be configured in the Zabbix UI because it
lives in the Zabbix database; the platform endpoint is ready for it.

## Run

The platform requires the `eventsim`, `prometheus`, `zabbix`, and
`timescaledb` Compose stacks first, because it joins their Docker networks.

```sh
cd platform
docker compose --env-file flags.env --env-file .env up -d --build
```

See `artifacts/kafka-protocol.md` for the v1 topic contract. The consumer group
is independent from eventsim, so Kafka retains one stream for each application.
