# Prometheus stack

Prometheus scrapes itself and the `eventsim-server` sensor over the shared
`prometheus_prometheus` Docker network.

## Configuration

`flags.env` is committed, contains all non-secret runtime settings, and is
synced on every `scripts/deploy.sh` run:

- `PROMETHEUS_VERSION`
- `PROMETHEUS_PORT`
- `PROMETHEUS_RETENTION`

There are no Prometheus secrets in this stack, so it intentionally has no
private `.env` file.

## Start

```sh
cd prometheus
set -a; . flags.env; set +a
docker compose up -d
```

Open <http://localhost:9090>. Deploy it with:

```sh
scripts/deploy.sh prometheus prometheus http://localhost:9090/-/healthy
```
