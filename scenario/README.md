# scenario

Offline corpus generator. **Not a deployed stack** — no `docker-compose.yml`,
nothing on the VM, no compose project name. It runs locally, writes a JSON
file, and stops.

It exists because the platform has no data. As of writing, `event_log`,
`alert_log` and `decision_log` all hold **0 rows** and both Kafka topics sit at
**offset 0** — nothing has ever flowed through the pipeline. The CMDB is empty.
Zabbix reconciliation fails every 60s on `problem.get` rejecting `selectHosts`
(`platform/app/integration/zabbix.py:34`), so the one real integration path is
down.

And the pre-existing generator could not have helped: `eventsim/app/simulator.py`
draws i.i.d. random values over 3 metrics × 4 hosts. There are no incidents in
that data, no cascades, no repeats that mean anything. On i.i.d. input the
optimal filter is a constant threshold, so no adaptive algorithm can demonstrate
a benefit and any filtering metric computed on it is meaningless.

## Why Prolog

The corpus needs a dependency graph walked transitively, ground truth derived
from that walk rather than hand-labelled, and the whole thing recomputed
whenever the topology changes. That is a set of rules over facts, and
backtracking enumerates every consequence of a root cause without anyone
writing the enumeration loop.

The split matters more than the language:

- **`topology.pl` — facts only.** Services, hosts, sites, environments,
  configuration items, dependencies, teams, users, on-call rota, contacts,
  escalation, trigger rules, incident catalogue, noise profiles, maintenance
  windows, timeline.
- **`cascade.pl` — rules only.** Impact closure, symptom propagation, incident
  expansion, noise expansion, maintenance demotion, page resolution, ground
  truth, validation, JSON output.

A second scenario is a second facts file against the same rules.

## Run

```sh
swipl -g run -t halt cascade.pl -- --seed 42 --out corpus.json
```

Seed plus `topology.pl` fully determine the output, so a scoring run is
reproducible and two runs are diffable.

Current output:

```
1053 alerts (545 actionable, 508 noise), 8 incidents, seed 42
```

## What comes out

```jsonc
{
  "seed": 42,
  "duration_seconds": 7200,
  "alert_count": 1053, "actionable_count": 545, "noise_count": 508,
  "incidents": [
    { "incident_id": "db_saturation@120", "kind": "db_saturation",
      "root_service": "db_primary", "owner_team": "platform_infra",
      "expected_page": "alice", "escalates_to": "galina",
      "started_at": 120, "ends_at": 1020 }
  ],
  "alerts": [
    { "t": 120, "source": "db-01", "service": "db_primary",
      "ci": "db-01/cpu", "metric": "cpu_percent", "value": 97.0,
      "severity": "critical", "rule": "high_cpu",
      "gt": "actionable", "gt_reason": "root_cause",
      "incident_id": "db_saturation@120", "hops": 0,
      "owner_team": "platform_infra", "environment": "prod", "site": "dc-a" }
  ],
  "cmdb": {
    "teams": [ /* id, name, escalates_to */ ],
    "users": [ /* login, team, role, contacts[{channel,address}] */ ],
    "on_call": [ /* team, login, from, to */ ],
    "services": [ /* id, tier, criticality, owner_team, environment */ ],
    "hosts": [ /* hostname, service, site */ ],
    "cis": [ /* id, type, hostname, service */ ],
    "depends_on": [ /* dependent, dependency */ ],
    "maintenance": [ /* service, from, to */ ]
  }
}
```

Three consumers, one file — a generator and a scorer that disagreed about the
topology would silently produce meaningless numbers:

1. **Generator** — replay `alerts` into eventsim by `t`.
2. **CMDB seed** — the `cmdb` block, which is where the empty CMDB gets filled:
   3 teams, 9 users with contact channels, a 6-shift rota, 9 services, 11 hosts
   across 2 sites, **29 configuration items**, 11 dependency edges, 2
   maintenance windows.
3. **Scorer** — `gt` / `gt_reason` / `incident_id` / `expected_page` are the
   ground truth.

`gt` and `incident_id` ride in `MonitoringAlert.labels`, which already exists
and is already free-form (`MonitoringEvent` is `extra="allow"`), so replaying a
corpus needs **no contract change**. The platform ignores those keys; only the
scorer reads them.

Not every declared CI is currently alerted on (16 of 29 appear in the corpus).
That is intended — a CMDB describes the estate, not just the parts currently on
fire, and the spare objects are there for new metrics to attach to.

## CMDB ↔ simulation sync, enforced

The CMDB is a **projection of the same facts the generator reads**, never a
parallel list. Drift would corrupt every ownership- and CI-scoped metric while
the run still reported success, so `validate/0` fails the run before anything is
written when:

- a `(host, metric)` pair the generator could emit has **no CI** of the matching
  type — CIs are never synthesised on demand, precisely so this surfaces
- a metric maps to no CI type, or a CI names an unknown host
- a service has no owner or no environment; a host has no site
- a team's on-call shifts do not **exactly partition** `0..corpus_duration` —
  a gap means nobody carries the pager, an overlap means two people do, and
  either silently wrecks per-user precision
- an engineer has no `webhook` contact to notify
- a team has no escalation contact
- an incident does not resolve to exactly one on-call engineer
- a maintenance window falls outside the corpus or is inverted
- a `root_cause` value breaches no trigger

All verified by negative test — deleting `ci('worker-03/archive', ...)`, shifting
a rota boundary, or dropping a contact each fail the run with a named error and
no corpus written.

## Data only the CMDB can supply

Two signals in the corpus are **unavailable from the alert stream at any
volume**, which is what separates a CMDB-aware filter from a purely statistical
one:

- **Maintenance windows.** Anything a service emits inside its own window is
  ground-truth `noise` however genuine the breach — planned work is not an
  incident. 21 alerts in the current corpus are demoted this way, and their
  `incident_id` is cleared so a scorer cannot credit them toward recall.
- **The on-call rota.** Pages resolve by incident *time*, not by a static role:
  `checkout_errors@3800` pages dmitri rather than carmen purely because it
  crossed the 3600s shift boundary. Move a boundary and the expected pages move
  with it.

`gt_reason` (`root_cause` / `cascade` / `noise_profile` / `maintenance`) lets
the scorer report *which* kind of noise got filtered. "Filtered 80%" is much
less useful than knowing whether the 80% was duplicate cascade or planned work.

## Ground truth is derived, not asserted

An alert is `actionable` because a cascade rule produced it from a declared root
cause — nothing is labelled by hand, so labels cannot drift from what was
emitted. Incident alerts come from `incident_alert/1` walking the dependency
graph; noise comes from `noise_profile/4` and is `noise` by construction.

**This measures the pipeline, not real-world efficacy.** The same file defines
both the noise and what counts as noise, so it is a harness for ranking
variants honestly against a fixed corpus — not evidence that filtering works on
real traffic. That needs working Zabbix ingestion and a human feedback channel.
Worth saying plainly to anyone shown the number.

## Metrics this makes computable

- **noise reduction** — `1 − notifications / alerts`
- **incident recall** — % of `incidents` with ≥1 notification. The safety
  metric; must stay at 100%, and it is the one that catches a filter that
  scores well by dropping everything.
- **per-user precision** — fraction of a user's pages belonging to incidents
  they own, scored against `expected_page`
- **time to first notification** per incident

Run three arms over the identical corpus: no filtering → `FlapAwareCorrelator`
only → + LLM enricher. **The first two need no LLM at all**, so the first real
number does not depend on the model being wired up.

The discriminating case is already in the corpus: `db_saturation` lights up 8
services across all 3 teams, but only `alice` should be paged. A filter that
pages every team whose dashboard turned red scores badly on per-user precision
while looking fine on noise reduction.

## Scoring

`platform/scripts/score_corpus.py` runs the corpus through the real pipeline
**in process** — no Kafka, no HTTP, no eventsim, no deployment:

```sh
cd platform && python3 -m scripts.score_corpus ../scenario/corpus.json
```

```
arm           alerts   pages  noise red    recall  precision    ttfn
--------------------------------------------------------------------
unfiltered      1053    1053      0.0%       8/8     20.5%      0s
correlator      1053      36     96.6%       7/8     27.8%      0s
```

It works without infrastructure because `TimeBoundedWindow` takes an injectable
`now_fn`, so the corpus `t` drives the clock: two hours of corpus scores in
milliseconds, exactly reproducibly.

**Ground truth never reaches the pipeline.** Only `service`, `environment`,
`site`, `ci` and `owner_team` are passed as alert labels; `gt`, `gt_reason` and
`incident_id` stay in a side table keyed by `alert_id`. Since
`MonitoringAlert.labels` is free-form and `default_key()` groups on it, leaking
the incident id would let the correlator group by incident and score perfectly
for entirely the wrong reason.

Scope: this measures filtering quality, not the deployed system — Kafka, the
TimescaleDB projection and delivery are all out of the loop. A "page" is a
`route` decision, since no `target_id -> webhook_url` registry exists yet
(`notifications/README.md`).

## What the first run found

**The correlator drops one incident in eight.** `catalog_degraded@900` starts
while `db_saturation@120` (which runs to t=1020) is still cascading through the
same two services, `catalog` and `storefront_web`. The correlation key is the
service, so the second incident lands on an already-open key and is folded in
as more evidence for the first — deduped, suppressed, or silently absorbed, but
never routed.

**Two concurrent incidents sharing a service are indistinguishable to a
service-keyed correlator.** That is a real limitation of the shipped policy, not
a corpus artifact, and it is exactly the case root-cause or CMDB awareness would
have to fix. It is deliberately left in: a corpus whose baseline scores 100%
recall teaches nothing. De-overlapping the timeline would hide it.

Precision is low in both arms for a related reason — a cascade alert pages the
on-call of the service that is *alerting*, not of the service that is *broken*,
so 10 of the correlator's 36 pages go to the wrong person and 16 are noise it
did not filter.

The decision mix behind the correlator arm: 660 dedup, 329 suppress, 36 route,
28 alerts folded silently.

## The opinionated call

**One page per incident, to whoever is on call for the team owning the _root_
service at the moment the incident starts.** Teams owning merely impacted
services are not paged.

A cascade from `db_primary` genuinely does degrade storefront and payments, so
there is a defensible argument for notifying them too. It is rejected here
because waking three on-calls for one database problem is the exact failure this
platform exists to prevent — and because loosening it would make per-user
precision easier to score well on without the system having improved. If that
call changes, change `expected_page/7` in `cascade.pl`, not the scorer.

Current expected pages spread across five engineers — alice 3, boris 2, carmen,
dmitri, elena 1 each — so "never page the wrong person" cannot be satisfied by
always paging one team.

## Known coupling: trigger tiers

`fires/5` in `topology.pl` mirrors `eventsim/app/rules.py`, duplicated because
the generator must know which values fire a trigger *before* emitting them. If
the two drift, the corpus stops firing and every metric reads as perfect
filtering.

`rules.py` only matters if a corpus is replayed *through eventsim's evaluator*.
The in-process scorer and the `/v1/integrations/{slug}/webhook` replay both
inject alerts directly, and the corpus already carries `severity` — so this is
**not a blocker** for scoring. It matters for making eventsim's live
autogenerate produce realistic data.

When you do: **`rules.py` needs severity tiers on its existing three rules, not
three additional rules.** `FlapAwareCorrelator` defines flapping as a signal
recurring at a *lower severity*, and signal identity is `(rule, metric, source)`
(`platform/app/core/correlation_automaton.py`). Tier-specific rule names
(`high_cpu_warn` vs `high_cpu`) split one metric into two separate signals, each
with a constant severity — so a regression is never seen *within* a signal and
flap detection still cannot fire, while a genuine escalation reads as an
unrelated new signal. Severity is a property of the reading, not of the rule;
`MonitoringAlert` carries the two as separate fields for exactly this reason.

This was a live bug in an earlier version of `topology.pl` — the tiers had
distinct rule names and produced zero suppress decisions. Fixing it to shared
rule names turned on 329 of them.

Longer term `rules.py` should be generated from `fires/5`. Until then, edit
both.

## Validation

`validate/0` runs before anything is written — see the enforced-sync list
above. Every check exists because its failure mode is *silent*: a `root_cause`
that breaches no trigger, a rota gap, or a missing CI all yield a quietly
degraded corpus that still "succeeds", and a metric computed on it looks
perfectly plausible.
