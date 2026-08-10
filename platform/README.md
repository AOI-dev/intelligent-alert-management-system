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
- **AI**: reserved Kafka request/result topics for horizontally scalable worker
  groups; no model or worker is required for the deterministic path.

## API

- `GET /health`
- `GET /v1/contours`
- `GET /v1/events`
- `GET /v1/alerts`
- `POST /v1/integrations/alertmanager/webhook`
- `POST /v1/integrations/zabbix/webhook`
- `GET /` — polling alert landing page
- `GET /metrics`

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

The platform requires the `eventsim`, `prometheus`, and `zabbix` Compose stacks
first, because it joins their Docker networks.

```sh
cd platform
docker compose --env-file flags.env --env-file .env up -d --build
```

See `artifacts/kafka-protocol.md` for the v1 topic contract. The consumer group
is independent from eventsim, so Kafka retains one stream for each application.
