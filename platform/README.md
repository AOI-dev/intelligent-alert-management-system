# Monitoring platform

Central FastAPI modular monolith for the alert-management architecture. It
consumes versioned Kafka event and alert topics and presents the central landing
page at `http://<host>:8100/`.

## Implemented contours

- **Integration**: Kafka consumers for `monitoring.events.v1` and
  `monitoring.alerts.v1`. Zabbix and Prometheus adapter ports are intentionally
  deferred; eventsim is the current producer.
- **Filtering**: pass-through service boundary for later noise/storm policy.
- **Alerts**: alert projection and query API.
- **Monitoring**: bounded in-memory event/alert history. TimescaleDB replaces
  this projection in a later increment.
- **Routing**: reserved notification-delivery boundary; no provider is called.
- **AI**: reserved Kafka request/result topics for horizontally scalable worker
  groups; no model or worker is required for the deterministic path.

## API

- `GET /health`
- `GET /v1/contours`
- `GET /v1/events`
- `GET /v1/alerts`
- `GET /` — polling alert landing page
- `GET /metrics`

## Run

The platform requires the `eventsim` and `prometheus` Compose stacks first,
because it joins their Docker networks.

```sh
cd platform
docker compose --env-file flags.env up -d --build
```

See `artifacts/kafka-protocol.md` for the v1 topic contract. The consumer group
is independent from eventsim, so Kafka retains one stream for each application.
