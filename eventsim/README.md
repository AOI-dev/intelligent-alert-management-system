# eventsim stack

Dead-simple event simulation server: ingest (synthetic, for now) events,
evaluate them against a small set of hardcoded trigger rules, then publish both
the normalized source event and any fired alert onto versioned Kafka topics for
the central monitoring platform to consume.

The real problem this repo is meant to solve is integration with actual
monitoring systems (Zabbix, Prometheus), so the app is intentionally thin
right now: no real API polling yet, just a `/events` endpoint shaped so that
a future poller can call it the same way a human curl would.

| Service  | Image                        | Exposed              |
| -------- | ----------------------------- | --------------------- |
| `kafka`  | `confluentinc/cp-kafka:7.6.1` | internal only (`9092`) |
| `server` | built from `./Dockerfile`     | `8090/tcp`             |

## API

- `POST /events` — `{"source": "web-01", "metric": "cpu_percent", "value": 95, "labels": {}}`.
  Publishes every normalized input to `monitoring.events.v1`; any fired alert
  goes to `monitoring.alerts.v1` with the same correlation ID. Returns the
  alerts that fired (empty if none).
- `GET /rules` — the currently loaded trigger rules.
- `GET /health` — liveness check, used by `scripts/deploy.sh`.
- `GET /metrics` — Prometheus exposition format.

The central viewer moved to the `platform` stack at port `8100`. Eventsim is a
producer only, which leaves the monolith as the canonical alert consumer and
landing page. The JSON envelope/topic compatibility rules are in
`artifacts/kafka-protocol.md`.

Trigger rules live in `app/rules.py` as a flat, hardcoded list for now —
`(metric, operator, threshold) -> severity`. No config file or DB yet; add
rules there until there's a reason not to.

## Autogenerate mode

The committed `flags.env` controls autogeneration and is deployed on every
`scripts/deploy.sh` run. It currently enables generation every 10 seconds, so
there is traffic to watch in Kafka/Prometheus before real monitoring-system
integration exists. Change `EVENTSIM_AUTOGENERATE` or
`EVENTSIM_AUTOGENERATE_INTERVAL` in `flags.env`, commit, and deploy; do not
manually edit VM configuration for ordinary flags.

## Monitoring the sensor itself

- **Prometheus**: `server` joins the already-deployed `prometheus` stack's
  docker network (`prometheus_prometheus`, declared `external: true` in
  `docker-compose.yml`) so it can be scraped by container name. Deploy the
  `prometheus` stack first. The scrape job is already added to
  `prometheus/prometheus.yml` — after editing that file, the prometheus
  container needs a manual restart to pick it up (`docker compose up -d`
  won't recreate it on its own since only the mounted config changed, not
  the compose file):
  ```sh
  ssh vm "cd prometheus && docker compose restart prometheus"
  ```
- **Zabbix**: point a "Simple check" or HTTP agent item at
  `http://<vm-host>:8090/health` from the Zabbix web UI (*Data collection →
  Hosts → Items*) — same as the DB-only fixup documented in the root
  README, this lives in the Zabbix database, not in this repo.

## Start (local)

```sh
cd eventsim
set -a; . flags.env; set +a
docker compose up -d --build
curl -X POST localhost:8090/events -H 'content-type: application/json' \
  -d '{"source":"web-01","metric":"cpu_percent","value":95}'
```

## Deploy

Deploy the `prometheus` stack first if it isn't already up, then:

```sh
scripts/deploy.sh eventsim eventsim http://localhost:8090/health
```

## Data

Kafka's log lives in the `kafka-data` named volume. `docker compose down`
keeps it; `docker compose down -v` destroys it along with all queued alerts.
