"""Score a scenario corpus (scenario/README.md) against the alert pipeline,
in process -- no Kafka, no HTTP, no eventsim, no deployment.

    cd platform && python -m scripts.score_corpus ../scenario/corpus.json

Two properties make this work without any infrastructure:

- TimeBoundedWindow takes an injectable `now_fn`, so the corpus `t` field
  drives the clock directly. A two-hour corpus scores in milliseconds rather
  than two hours of wall time, and the result is exactly reproducible.
- PluginEngine.process() is a plain coroutine returning Decisions, so the
  filtering policy can be exercised directly.

SCOPE, stated plainly: this measures *filtering quality*, not the deployed
system. Kafka, the TimescaleDB projection, and notification delivery are all
out of the loop. A good number here does not mean the VM works end to end --
that needs the HTTP replay against /v1/integrations/{slug}/webhook.

Delivery is likewise not measured: no target registry resolving
target_id -> webhook_url exists yet (notifications/README.md), so a
"notification" here is a `route` decision, which is what the platform would
hand to that registry once it exists.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from app.contracts.messages import MonitoringAlert
from app.core.window import TimeBoundedWindow
from app.plugins.builtins.correlation import FlapAwareCorrelatorPlugin
from app.plugins.engine import PluginEngine
from app.plugins.registry import PluginRegistry

WINDOW_SECONDS = 300

# Alert keys the pipeline is allowed to see. Everything else in a corpus alert
# is ground truth or scoring bookkeeping.
#
# This split is the integrity of the whole measurement: `gt`, `gt_reason` and
# `incident_id` describe the answer, and MonitoringAlert.labels is free-form,
# so leaking them into the alert would let default_key() group by incident and
# score a perfect result for the wrong reason. The scorer keeps them in a
# side table keyed by alert_id instead.
OPERATIONAL_LABELS = ("service", "environment", "site", "ci", "owner_team")


@dataclass(frozen=True)
class Truth:
    """Ground truth for one alert. Never visible to the pipeline."""

    t: int
    gt: str
    gt_reason: str
    incident_id: str | None
    service: str
    owner_team: str


@dataclass(frozen=True)
class Notification:
    t: int
    alert_id: UUID
    recipient: str | None


class Rota:
    """Who carries the pager for a team at a given corpus second.

    Read from the corpus's own cmdb block rather than re-derived, so the
    scorer cannot disagree with the generator about the roster -- the sync
    that scenario/cascade.pl's validate/0 enforces on the way out.
    """

    def __init__(self, corpus: dict) -> None:
        self._shifts = corpus["cmdb"]["on_call"]
        self._team_of_service = {s["id"]: s["owner_team"] for s in corpus["cmdb"]["services"]}

    def team_for(self, service: str) -> str | None:
        return self._team_of_service.get(service)

    def on_call(self, team: str | None, t: int) -> str | None:
        for shift in self._shifts:
            if shift["team"] == team and shift["from"] <= t < shift["to"]:
                return shift["login"]
        return None


def load_corpus(path: Path) -> dict:
    with path.open() as handle:
        return json.load(handle)


def build_alerts(corpus: dict) -> tuple[list[tuple[int, MonitoringAlert]], dict[UUID, Truth]]:
    """Turn corpus records into what a monitoring system would actually send,
    plus the side table of ground truth."""
    alerts: list[tuple[int, MonitoringAlert]] = []
    truth: dict[UUID, Truth] = {}
    for record in corpus["alerts"]:
        labels = {key: str(record[key]) for key in OPERATIONAL_LABELS if key in record}
        alert = MonitoringAlert(
            rule=record["rule"],
            severity=record["severity"],
            source=record["source"],
            metric=record["metric"],
            value=float(record["value"]),
            threshold=0.0,
            labels=labels,
        )
        alerts.append((record["t"], alert))
        truth[alert.alert_id] = Truth(
            t=record["t"],
            gt=record["gt"],
            gt_reason=record["gt_reason"],
            incident_id=record["incident_id"],
            service=record["service"],
            owner_team=record["owner_team"],
        )
    return alerts, truth


# ---------------------------------------------------------------------------
# Arms
# ---------------------------------------------------------------------------

Arm = Callable[[Sequence[tuple[int, MonitoringAlert]], Rota], list[Notification]]


def arm_unfiltered(alerts: Sequence[tuple[int, MonitoringAlert]], rota: Rota) -> list[Notification]:
    """Baseline: every alert pages someone. The number every other arm has to
    beat, and the one that makes 'noise reduction' meaningful as a ratio."""
    return [
        Notification(t, alert.alert_id, rota.on_call(rota.team_for(alert.labels.get("service", "")), t))
        for t, alert in alerts
    ]


def _engine_arm(plugins: Sequence[object]) -> Arm:
    def run(alerts: Sequence[tuple[int, MonitoringAlert]], rota: Rota) -> list[Notification]:
        clock = {"now": 0.0}
        engine = PluginEngine(
            registry=PluginRegistry(list(plugins)),
            window=TimeBoundedWindow(WINDOW_SECONDS, now_fn=lambda: clock["now"]),
        )

        async def drive() -> list[Notification]:
            out: list[Notification] = []
            for t, alert in alerts:
                clock["now"] = float(t)
                for decision in await engine.process(alert):
                    if decision.decision_type != "route":
                        continue
                    team = rota.team_for(alert.labels.get("service", ""))
                    out.append(Notification(t, decision.alert_id, rota.on_call(team, t)))
            return out

        return asyncio.run(drive())

    return run


ARMS: dict[str, Arm] = {
    "unfiltered": arm_unfiltered,
    "correlator": _engine_arm([FlapAwareCorrelatorPlugin()]),
}


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


@dataclass
class Score:
    alerts_in: int
    notifications: int
    incidents_total: int
    incidents_caught: int
    correct_pages: int
    pages_for_noise: int
    pages_to_wrong_person: int
    ttfn: list[int]
    noise_by_reason: dict[str, int]

    @property
    def noise_reduction(self) -> float:
        if not self.alerts_in:
            return 0.0
        return 1.0 - self.notifications / self.alerts_in

    @property
    def incident_recall(self) -> float:
        if not self.incidents_total:
            return 0.0
        return self.incidents_caught / self.incidents_total

    @property
    def page_precision(self) -> float:
        if not self.notifications:
            return 0.0
        return self.correct_pages / self.notifications

    @property
    def median_ttfn(self) -> float | None:
        return statistics.median(self.ttfn) if self.ttfn else None


def score(corpus: dict, truth: dict[UUID, Truth], notifications: Sequence[Notification]) -> Score:
    incidents = {i["incident_id"]: i for i in corpus["incidents"]}
    caught: dict[str, int] = {}
    correct = noise_pages = wrong_person = 0
    noise_by_reason: dict[str, int] = {}

    for note in notifications:
        fact = truth[note.alert_id]
        if fact.gt == "noise":
            noise_pages += 1
            noise_by_reason[fact.gt_reason] = noise_by_reason.get(fact.gt_reason, 0) + 1
            continue
        incident_id = fact.incident_id
        incident = incidents.get(incident_id) if incident_id is not None else None
        if incident_id is None or incident is None:
            # Actionable, but its incident expects no page at all -- e.g. one
            # opening inside its own service's maintenance window.
            wrong_person += 1
            continue
        if note.t < caught.get(incident_id, 1 << 30):
            caught[incident_id] = note.t
        if note.recipient == incident["expected_page"]:
            correct += 1
        else:
            wrong_person += 1

    ttfn = [t - incidents[iid]["started_at"] for iid, t in caught.items()]
    return Score(
        alerts_in=len(corpus["alerts"]),
        notifications=len(notifications),
        incidents_total=len(incidents),
        incidents_caught=len(caught),
        correct_pages=correct,
        pages_for_noise=noise_pages,
        pages_to_wrong_person=wrong_person,
        ttfn=ttfn,
        noise_by_reason=noise_by_reason,
    )


def report(results: dict[str, Score]) -> None:
    header = f"{'arm':<12} {'alerts':>7} {'pages':>7} {'noise red':>10} {'recall':>9} {'precision':>10} {'ttfn':>7}"
    print(header)
    print("-" * len(header))
    for name, s in results.items():
        recall = f"{s.incidents_caught}/{s.incidents_total}"
        ttfn = "-" if s.median_ttfn is None else f"{s.median_ttfn:.0f}s"
        print(
            f"{name:<12} {s.alerts_in:>7} {s.notifications:>7} "
            f"{s.noise_reduction:>9.1%} {recall:>9} {s.page_precision:>9.1%} {ttfn:>7}"
        )

    print("\nwhere the pages went:")
    for name, s in results.items():
        print(
            f"  {name:<12} correct={s.correct_pages:<6} "
            f"noise={s.pages_for_noise:<6} wrong-person={s.pages_to_wrong_person}"
        )
        if s.noise_by_reason:
            detail = ", ".join(f"{k}={v}" for k, v in sorted(s.noise_by_reason.items()))
            print(f"  {'':<12} noise pages by cause: {detail}")

    print(
        "\nrecall is the safety metric: anything below 100% means the filter "
        "lost an incident,\nwhich no amount of noise reduction compensates for."
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("corpus", type=Path, help="corpus.json from scenario/cascade.pl")
    parser.add_argument("--arms", default=",".join(ARMS), help=f"comma-separated: {', '.join(ARMS)}")
    args = parser.parse_args()

    corpus = load_corpus(args.corpus)
    alerts, truth = build_alerts(corpus)
    rota = Rota(corpus)

    print(
        f"corpus: {len(alerts)} alerts, {len(corpus['incidents'])} incidents, "
        f"{corpus['duration_seconds']}s, seed {corpus['seed']}\n"
    )

    results: dict[str, Score] = {}
    for name in (a.strip() for a in args.arms.split(",") if a.strip()):
        if name not in ARMS:
            print(f"unknown arm '{name}'; known: {', '.join(ARMS)}", file=sys.stderr)
            return 2
        results[name] = score(corpus, truth, ARMS[name](alerts, rota))

    report(results)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
