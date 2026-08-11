# Monitoring platform

Central FastAPI modular monolith for the alert-management architecture. It
consumes versioned Kafka event and alert topics and presents the central landing
page at `http://<host>:8100/`.

## Implemented contours

- **Integration**: consumes `monitoring.events.v1` and `monitoring.alerts.v1`.
  Eventsim is the synthetic producer. Alertmanager posts alert lifecycle
  transitions to the platform webhook; Zabbix can post action webhooks and is
  reconciled through its JSON-RPC API when the dedicated token is configured.
  Every real (non-eventsim) alert also gets a corresponding event published to
  `monitoring.events.v1` — see `to_event_data` in
  `app/integration/normalizers.py` and `MonitoringEvent`'s schema below —
  eventsim was, until this increment, the only real producer of that topic.
- **Event schema**: `MonitoringEvent` (`app/contracts/messages.py`) is
  deliberately minimal-but-open — only `source` and `status` are required
  (`timestamp` defaults to now if a normalizer doesn't have a better one);
  everything else, known (`metric`/`value`/`labels`) or not, is optional or
  free-form via Pydantic's `extra="allow"`. A normalizer attaches whatever
  fields its vendor has (see `to_event_data`); an LLM enrichment step can
  attach whatever it derives, later, the same way — no schema change either
  time. `MonitoringAlert` stays its own, stricter type (the deterministic
  core's `FlapAwareCorrelator` genuinely needs `rule`/`severity`/`metric`/
  `threshold` to be present, not optional).
- **Filtering**: pass-through service boundary for later noise/storm policy.
- **Alerts**: alert projection and query API.
- **Monitoring**: two deliberately separate stores, not one stretched to
  cover both jobs (see "Frontend query endpoints" below for the design
  reasoning) — a bounded in-memory live-tail cache (`MessageStore`, what
  `/v1/events`/`/v1/alerts`/`/v1/decisions` read from), and a persistent
  TimescaleDB projection (`app/monitoring/models.py`/`persistence.py`):
  every accepted event/alert/decision is also written to an
  `event_log`/`alert_log`/`decision_log` hypertable, partitioned on
  `occurred_at`, with a retention policy
  (`TIMESCALE_EVENT_RETENTION_DAYS`/`_ALERT_RETENTION_DAYS`/
  `_DECISION_RETENTION_DAYS`, defaults 90/90/400 — decisions default
  longer since they're the audit trail, АР-08's "at least a year"). Each
  table has a handful of known, indexed columns for what's actually
  filtered on, plus an `extra` JSONB column for the rest of the message
  body verbatim — so `MonitoringEvent`'s `extra="allow"` openness doesn't
  need a schema migration to persist here too. Nothing reads from these
  tables yet (no range-query API endpoint) — writing history is this
  increment; querying it is the next one. A write failure here is logged
  and swallowed, never raised into the Kafka handler — the same "must not
  block or break the deterministic path" principle already applied to
  plugins in `app/plugins/engine.py`, applied to this store too. Status
  visible at `GET /health`'s `monitoring_db` field.
- **Routing**: reserved notification-delivery boundary; no provider is called.
  Delivery itself, once routing publishes `notification.requested`, is
  handled by the separate `notifications` dispatcher stack (see
  `notifications/README.md`), not by code in this monolith.
- **AI**: reserved Kafka request/result topics for horizontally scalable worker
  groups; no model or worker is required for the deterministic path.
- **Core**: `app/core/` runs every consumed alert through a per-alert stage
  (identity by default), then a per-sequence stage over a `TimeBoundedWindow`
  keyed by correlation_id label, then service label, then `(source, metric)`
  (see `default_key` in `app/core/pipeline.py`). The per-sequence stage
  defaults to `FlapAwareCorrelator` — a small state machine per key (NEW →
  OPEN → FLAPPING) implementing АР-03's dedup/correlation/storm-suppression
  policy: the first alert for a key opens an incident (`route`); escalations
  and additional correlated signals fold in silently; an exact repeat dedups;
  and a signal recurring at a lower severity than before marks the key
  flapping, suppressing everything after. See
  `app/core/correlation_automaton.py` for the full state machine and
  `tests/core/oracle.py` for the scenarios it's built to satisfy.
  `PassThroughSequenceTransform` remains available as an explicit opt-out.
  Any `Decision` produced is published to `monitoring.decisions.v1` and
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
- `GET /v1/events` — query params: `source`, `status`, `since` (ISO 8601)
- `GET /v1/alerts` — query params: `severity`, `source`, `since`
- `GET /v1/alerts/{alert_id}` — 404 if the alert isn't in the retained
  window (see "Frontend query endpoints" below)
- `GET /v1/decisions` — output of `app/core/`; query param: `decision_type`
- `GET /v1/summary` — counts (alerts by severity, decisions by type) over
  the current retained window; the `frontend/` dashboard's header widget
- `GET /v1/incidents`, `GET /v1/incidents/{id}`,
  `POST /v1/incidents/{id}/ack` — **stubs**: always `501`, on purpose (see
  below), since incidents aren't implemented
- `POST /v1/integrations/{slug}/webhook` — generic dispatch to whichever
  `WebhookAlertSource` claims `slug`; built in today as `alertmanager` and
  `zabbix` (see "Monitoring client adapters" below)
- `GET /` — the monolith's own bundled landing page (see `frontend/` for
  the primary dashboard, which reverse-proxies to this API instead of
  duplicating it)
- `GET /metrics`
- `GET /v1/auth/login` (accepts `?return_to=<origin>` for cross-origin
  login — see "Cross-origin login" below), `GET /v1/auth/callback`,
  `POST /v1/auth/logout`, `GET /v1/auth/me`
- `GET /v1/identities`, `POST /v1/identities/{id}/roles`,
  `PUT /v1/identities/{id}/ad-link`, `GET /v1/auth/roles` — admin role
  only. `PUT .../ad-link` writes only to this platform's own
  `ad_account_links` table — it never creates, modifies, or otherwise
  reaches a real Active Directory account; see АР-07 and
  `active-directory/README.md`. `frontend/public/index.html`'s Admin tab
  is the UI for all four.

## Frontend query endpoints

`/v1/events`, `/v1/alerts`, `/v1/decisions`, and the new `/v1/alerts/{id}`
and `/v1/summary` all read from the same bounded in-memory
`MessageStore` (`app/monitoring/store.py`, `PLATFORM_HISTORY_LIMIT` items,
default 500) they always have — none of this is a new data source, just
query/filter/lookup logic (`app/monitoring/query.py`, unit-tested
independent of FastAPI/auth/Kafka) added on top of what was already a
plain unfiltered `.list()`. This is deliberately the *live-tail* cache,
not a general-purpose history API — see the design discussion this
increment came out of: a bounded, in-process cache is right for "what's
happening now" (which is what a polling dashboard needs), wrong for
time-range/audit queries once volume or retention needs exceed the
window, which is what the still-pending TimescaleDB projection is for
instead of stretching this cache to cover both jobs.

`/v1/incidents*` are real endpoints that always return `501`, not stubs
that fake success with an empty list — an empty list would look
identical to "no incidents right now," which isn't true; the honest
answer is "this isn't implemented yet." See `INCIDENTS_NOT_IMPLEMENTED`
in `app/main.py`.

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
`POST /v1/identities/{id}/roles`. To get a batch of test accounts without
logging in by hand, `scripts/create_trueconf_users.py` provisions real
TrueConf Server accounts for a synthetic org chart (see the script's
docstring for the required `TRUECONF_ADMIN_API_TOKEN`); the matching
`active-directory/scripts/create_synthetic_users.sh` creates the same
accounts in the `active-directory` stack's AD DC. Once those users have
each logged in once via `/v1/auth/login`,
`platform/scripts/seed_synthetic_ad.py` backfills synthetic department/team
data onto their identities — see the script's docstring.

## Cross-origin login

The identity model (`identities`/`identity_roles`/`ad_account_links`) is
the actual auth authority here, not TrueConf's session mechanics — TrueConf
only ever answers "who is this" once, at login. That distinction matters
because TrueConf's OAuth2 `redirect_uri` is fixed to one pre-registered
host (a real OAuth2 constraint, not a choice made here), so the
`httponly` session cookie `/v1/auth/callback` sets is only ever valid for
that same host. A frontend on any other origin — a developer's own
machine, a second deployment — would never see it.

`GET /v1/auth/login?return_to=<origin>` (`app/identity/return_to.py`)
covers that case: if `origin` exactly matches one in
`AUTH_RETURN_TO_ALLOWLIST` (`platform/flags.env`, comma-separated exact
origins, no path), `/v1/auth/callback` redirects to
`{origin}/#session=<token>` instead of `/` — the same signed token the
cookie carries, delivered via URL *fragment* specifically because
fragments are never transmitted to any server, only readable by JS already
running on that origin. The frontend (`frontend/public/index.html`) picks
it up once, stores it, and sends `Authorization: Bearer <token>` on
API calls instead of relying on the cookie.
`app/identity/dependencies.py:get_current_identity` accepts either —
cookie first, header as the fallback — so this is purely additive; the
plain same-host cookie flow (deployed frontend + platform on one host)
is unchanged.

An unrecognized or absent `return_to` isn't an error — it's silently
ignored and the flow falls back to the cookie-only default it always had.

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
