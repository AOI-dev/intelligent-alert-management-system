# notifications stack

Generic webhook dispatcher: consumes `notification.requested` messages,
POSTs the notification `payload` to the request's `webhook_url`, and
publishes a `notification.delivered`/`notification.failed` outcome. It is a
standalone external consumer per `artifacts/kafka-protocol.md`'s "External
consumers" model — it does not register with the `platform` stack at
runtime, it just reads Kafka under its own consumer group.

No target/routing registry exists yet (that's a later increment): today the
`webhook_url` must already be resolved by whatever publishes the request.
Once file-backed routing config lands in `platform`, its routing module
resolves `target_id -> webhook_url` before publishing; this dispatcher's
contract and delivery logic don't need to change.

| Service  | Image                        | Exposed  |
| -------- | ----------------------------- | -------- |
| `server` | built from `./Dockerfile`     | `8110/tcp` |

## API

- `GET /v1/results` — recent delivery outcomes (bounded in-memory history).
- `GET /health` — liveness + Kafka connection status, used by
  `scripts/deploy.sh`.
- `GET /metrics` — Prometheus exposition format.

Delivery is single-attempt in this increment — no retry loop. Retry policy
is target-config behavior (see `artifacts/kafka-protocol.md`), deferred
until routing/target registration exists.

## Start (local)

Requires the `eventsim` stack's Kafka broker to already be running.

```sh
cd eventsim && docker compose up -d --build   # Kafka, if not already up
cd ../notifications
set -a; . flags.env; set +a
docker compose up -d --build
```

Hand-publish a `notification.requested` envelope to
`monitoring.notification-requests.v1` to exercise it end to end — there is
no producer of this topic yet since routing hasn't landed.

## Deploy

Deploy the `eventsim` and `prometheus` stacks first, then:

```sh
scripts/deploy.sh notifications notifications http://localhost:8110/health
```

## Data

Stateless — results are an in-memory bounded projection only, lost on
restart. Kafka retains the actual `monitoring.notification-results.v1` log.
