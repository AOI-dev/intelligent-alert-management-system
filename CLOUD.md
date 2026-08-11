# Scaling model

This is a decision record, not a built feature: how this system scales when
it needs to, and what that choice costs. Nothing here is implemented yet —
`scripts/deploy.sh` targets exactly one VM (`vm`) today.

## The decision

Scale by running more VMs/Docker containers of the monolith and the
services around it. **Kafka is not what gets scaled.** It stays a single
broker, same as today — see the bottleneck discussion this doc formalizes:
TimescaleDB and the AI/LLM service are the real capacity limits, Kafka is
the buffer between them, not a limit itself. Scaling Kafka (partitions,
multi-broker cluster) is a different, separate problem from this one and is
explicitly out of scope here.

What actually scales, and how, per stack:

- **`platform` (the monolith)**: run N containers/VMs of it, each its own
  Kafka consumer group member on `monitoring.events.v1`/`.alerts.v1`. This
  already works mechanically — Kafka consumer groups exist specifically to
  split partitions across instances — but two things are NOT ready for it
  yet (see "What breaks first" below).
- **`notifications`, `trueconf-bot`, AI workers (once they exist)**: same
  story — stateless Kafka consumers, N replicas share the load via consumer
  group partitioning. This is the cheapest thing to scale in the whole
  system because it needed nothing new to be built for it.
- **`trueconf-server`, `active-directory`**: do **not** scale this way.
  TrueConf Server's license is bound to a single container (see
  `trueconf/README.md` — recreating it via Compose risks invalidating the
  license, which is exactly the kind of thing this scaling model would do).
  The AD DC is a single directory; running two disagreeing ones is a
  correctness problem, not a capacity one. Both stay singletons regardless
  of how everything else scales.
- **TimescaleDB, the AI/LLM service**: also not scaled by this decision —
  they're the bottlenecks this model doesn't touch. Scaling either is a
  separate decision (read replicas/sharding for the DB, provider-side
  quota/multi-provider for the LLM) with its own tradeoffs, not "add more
  VMs."

## The cost: availability drops when a VM goes down

This is VM/Docker scaling, not orchestrated scaling — there's no
scheduler re-placing work off a dead node the way Kubernetes or a managed
container platform would. A VM is the unit of failure as much as it's the
unit of scale: if a VM goes down, every container that happened to be
running on it goes down with it, and stays down until someone manually
redeploys to a replacement host. More VMs means more capacity *and* more
independent things that can individually fail — this model trades
automatic failover for simplicity. That's an accepted tradeoff for where
this system is now, not an oversight, but it means "scaled" here reads as
"more throughput," not "more available." If uptime through a VM loss
becomes a real requirement, that needs a scheduler/orchestrator
underneath this (Kubernetes, Nomad, a managed platform) — a different,
larger decision than this one.

## What breaks first if you actually add a second `platform` instance

Two things this repo already built assume exactly one instance, and need
to change before "N containers of the monolith" is actually safe:

1. **Rate limiting** (`app/core/rate_limit.py`) uses an in-memory
   `InMemoryBucketStore` — per-process state. Run two replicas today and
   each enforces its own budget independently, so the *effective* limit
   silently becomes (configured limit × replica count) instead of staying
   fixed. The module was written with this in mind — `BucketStore` is a
   `Protocol` specifically so a shared backend (Redis) can drop in without
   touching the middleware — but nothing implements that backend yet. Do
   that before scaling `platform` past one instance, not after.
2. **No load balancer** sits in front of `platform` today —
   `scripts/deploy.sh` publishes one container's port directly
   (`PLATFORM_PORT`). N instances need something in front of them (even a
   plain nginx/HAProxy) to actually distribute the unauthenticated webhook
   and authenticated API traffic across replicas; right now there's
   nowhere for a second instance's traffic to come from.

Both are small, known gaps — called out here so "just start a second
container" doesn't get tried before they're closed.
