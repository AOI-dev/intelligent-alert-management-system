# eventsim stack

Dead-simple event simulation server: ingest (synthetic, for now) events,
evaluate them against a small set of hardcoded trigger rules, and publish
whatever fires as an **alert** (never the raw event) onto a Kafka topic — the
"distributed queue" the rest of the pipeline will eventually consume from.

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
  Returns the list of alerts fired (empty if none). Any that fire are
  published to the `alerts` Kafka topic as JSON.
- `GET /rules` — the currently loaded trigger rules.
- `GET /alerts` — the last 200 alerts consumed off the `alerts` Kafka topic,
  newest first, as JSON. Backs the viewer page below.
- `GET /` — a single-page viewer: polls `/alerts` every 3s and renders them
  as a table. Open `http://<host>:8090/` in a browser.
- `GET /health` — liveness check, used by `scripts/deploy.sh`.
- `GET /metrics` — Prometheus exposition format.

The server both produces to and consumes from the `alerts` topic — the
consumer (`app/kafka_consumer.py`) just keeps an in-memory ring buffer
(`app/store.py`, last 200) for the viewer page. It joins the topic with a
fixed consumer group (`KAFKA_CONSUMER_GROUP`, default `eventsim-viewer`)
starting from the earliest offset, so restarting the server doesn't lose
history already sitting in Kafka — a real downstream consumer would use its
own group and isn't affected by this one.

Trigger rules live in `app/rules.py` as a flat, hardcoded list for now —
`(metric, operator, threshold) -> severity`. No config file or DB yet; add
rules there until there's a reason not to.

## Autogenerate mode

Set `EVENTSIM_AUTOGENERATE=true` (see `.env.example`) to have the server
generate a synthetic event every `EVENTSIM_AUTOGENERATE_INTERVAL` seconds on
its own, so there's traffic to watch in Kafka/Prometheus before any real
monitoring-system integration exists. Off by default.

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
cp .env.example .env   # optional, only if overriding defaults
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
