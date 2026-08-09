# Kafka protocol v1

Kafka is the asynchronous boundary between monitoring producers, the central
FastAPI monolith, and future heavyweight workers. It provides at-least-once
delivery; consumers must be idempotent by `message_id`.

## Topics

| Topic | Producer | Consumer | Purpose |
| --- | --- | --- | --- |
| `monitoring.events.v1` | eventsim; future Zabbix/Prometheus adapters | platform ingestion contour | Normalized source events, including non-alerting observations. |
| `monitoring.alerts.v1` | eventsim; future deterministic alert-core producers | platform alert contour | Alerts that have already fired. |
| `monitoring.ai.enrichment.v1` | platform alert core | parallel AI worker group | Optional enrichment jobs. |
| `monitoring.ai.results.v1` | AI workers | platform AI result contour | Enrichment results; they never block the deterministic path. |

## Envelope

Every message is UTF-8 JSON and has this envelope:

```json
{
  "schema_version": "1.0",
  "message_id": "b481c2e7-8228-4bcc-9d81-ff68c2733917",
  "message_type": "monitoring.event",
  "occurred_at": "2026-08-08T12:34:56Z",
  "producer": "eventsim",
  "correlation_id": "d8617c8d-9838-426f-a325-d2804b43a10d",
  "data": {}
}
```

Use `message_id` as the Kafka key. `correlation_id` is created for one source
event and preserved on every alert it produces. Add optional fields only; any
breaking payload change requires a new topic version.

Kafka is transport and replay, not the query store. The platform will persist
its operational timeline in TimescaleDB in a later increment.
