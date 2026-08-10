# Prometheus and Alertmanager stack

Prometheus scrapes itself, `eventsim-server`, and `monitoring-platform` over the
shared `prometheus_prometheus` Docker network. Alertmanager receives evaluated
Prometheus rule lifecycle transitions and POSTs them to the platform webhook.

## Flow

```text
Prometheus alert rule -> Alertmanager -> platform webhook
  -> monitoring.alerts.v1 -> platform alert projection
```

Prometheus retains raw metric samples. Only meaningful firing/resolved alert
transitions leave it; this deliberately avoids copying every high-cardinality
sample into Kafka.

## Configuration

`flags.env` is committed, contains all non-secret runtime settings, and is
synced on every `scripts/deploy.sh` run:

- `PROMETHEUS_VERSION`, `PROMETHEUS_PORT`, `PROMETHEUS_RETENTION`
- `ALERTMANAGER_VERSION`, `ALERTMANAGER_PORT`

There are no secrets in this stack.

`alert-rules.yml` carries the initial test rules. `alertmanager.yml` targets
`monitoring-platform:8100` through the shared Docker network; deploy platform
before Alertmanager sends a firing alert.

## Start

```sh
cd prometheus
docker compose --env-file flags.env up -d
```

Open Prometheus at <http://localhost:9090> and Alertmanager at
<http://localhost:9093>. Deploy the stack with:

```sh
scripts/deploy.sh prometheus prometheus http://localhost:9090/-/healthy
```
