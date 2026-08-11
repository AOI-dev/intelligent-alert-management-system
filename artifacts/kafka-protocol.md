# Kafka protocol v1

Kafka is the asynchronous boundary between monitoring producers, the central
FastAPI monolith, and future heavyweight workers. It provides at-least-once
delivery; consumers must be idempotent by `message_id`.

## Topics

| Topic | Producer | Consumer | Purpose |
| --- | --- | --- | --- |
| `monitoring.events.v1` | eventsim; future Zabbix/Prometheus adapters | `platform-ingestion-v1-events` | Normalized operational state transitions/events. |
| `monitoring.observations.v1` | future curated Zabbix/Prometheus adapters | `platform-observations-v1` | Selected aggregates/forecasts, never all raw metric samples. |
| `monitoring.alerts.v1` | eventsim; Alertmanager webhook; Zabbix webhook/API reconciliation | `platform-ingestion-v1-alerts` | Fired/resolved alert lifecycle records. |
| `monitoring.ai.enrichment.v1` | platform alert core | parallel AI worker group | Optional enrichment jobs. |
| `monitoring.ai.results.v1` | AI workers | platform AI result contour | Enrichment results; they never block the deterministic path. |
| `monitoring.incident-events.v1` | platform alert core (dedup logic, not yet implemented) | `platform-incidents-v1`, and any external consumer group (ticketing, analytics, AI enrichment, stress-test verifiers) | Durable incident lifecycle facts: `incident.created` / `incident.updated` / `incident.resolved`. |
| `monitoring.decisions.v1` | platform alert core (`app/core/pipeline.py`; pipeline wired to live alerts, dedup/routing policy not yet chosen — see `platform/README.md`) | `platform-decisions-v1`, and any external consumer group | Audit trail of every dedup/routing/suppression decision: `decision.dedup` / `decision.route` / `decision.suppress`. |
| `monitoring.notification-requests.v1` | platform routing module (not yet implemented) | `notification-dispatcher-v1` (see `notifications/`) | `notification.requested` — a resolved delivery: `target_id`, already-resolved `webhook_url`, `priority`, `reason`, `payload`. |
| `monitoring.notification-results.v1` | `notifications` dispatcher | `platform-notification-results-v1`, and any external consumer group | Delivery outcome: `notification.delivered` / `notification.failed`. |

## External consumers

Any system that wants the incident/decision stream (ticketing, analytics, an
AI worker, a stress-test verifier) reads `monitoring.incident-events.v1` /
`monitoring.decisions.v1` directly under its own consumer group — it does not
register with the platform at runtime. It needs only: the Kafka bootstrap
address, a unique consumer-group name, read ACL on the topic, this contract,
and an offset/replay policy. A consumer being down never affects another
consumer; Kafka retains the backlog until it catches up.

Notification delivery (a target that the platform should route to and track
delivery for, as opposed to a passive reader of the stream) is a separate,
declarative registration concept — not yet implemented; tracked as a later
increment.

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

## Monitoring-system ingestion

- **Alertmanager webhook** is Prometheus's lifecycle fast path. It publishes
  `firing` and `resolved` records to the platform, which normalizes them and
  publishes `monitoring.alerts.v1`.
- **Zabbix action webhook** is Zabbix's lifecycle fast path. **Zabbix JSON-RPC
  `problem.get`** is the repair path; the platform polls open problems with a
  dedicated read-only token and republishes idempotently by vendor event ID.
- Prometheus and Zabbix remain their systems of record for raw metric history.
  Do not export every sample/item update into Kafka. Publish only selected
  forecasts or meaningful state transitions to `monitoring.observations.v1`.

Kafka is transport and replay, not the query store. The platform will persist
its operational timeline in TimescaleDB in a later increment.
