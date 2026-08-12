"""Happy-path tests for the core correlation/detection contour.

These tests run synthetic alert sequences through the CorrelationEngine and
verify the decision distribution against an oracle. The default engine runs
FlapAwareCorrelator (app/core/correlation_automaton.py), which is built to
satisfy exactly this oracle -- see that module for the state machine.
"""
from uuid import uuid4

import pytest

from app.core.pipeline import CorrelationEngine, PassThroughSequenceTransform
from tests.core.fixtures import (
    correlated_cascade,
    duplicate_storm,
    flapping_alerts,
    make_alert,
    multi_tenant_noise,
    second_incident_on_a_busy_key,
    severity_escalation,
)
from tests.core.oracle import ORACLE, CoreOracle


def _run_scenario(alerts: list) -> dict[str, int]:
    engine = CorrelationEngine()
    decisions = []
    for alert in alerts:
        decisions.extend(engine.process(alert))
    counts: dict[str, int] = {"route": 0, "dedup": 0, "suppress": 0}
    for decision in decisions:
        if decision.decision_type in counts:
            counts[decision.decision_type] += 1
    return counts


@pytest.mark.parametrize(
    "name, make_alerts, oracle",
    [
        ("duplicate_storm", duplicate_storm, ORACLE["duplicate_storm"]),
        ("correlated_cascade", correlated_cascade, ORACLE["correlated_cascade"]),
        ("severity_escalation", severity_escalation, ORACLE["severity_escalation"]),
        ("flapping_alerts", flapping_alerts, ORACLE["flapping_alerts"]),
        ("multi_tenant_noise", multi_tenant_noise, ORACLE["multi_tenant_noise"]),
    ],
)
def test_scenario_matches_oracle(name: str, make_alerts, oracle: CoreOracle):
    counts = _run_scenario(make_alerts())
    assert counts["route"] == oracle.route_count, f"{name}: route count mismatch"
    assert counts["dedup"] == oracle.dedup_count, f"{name}: dedup count mismatch"
    assert counts["suppress"] == oracle.suppress_count, f"{name}: suppress count mismatch"


def test_critical_on_an_already_open_key_still_pages():
    """The recall invariant: noise reduction may never swallow a critical.

    Asserted on decisions rather than on a corpus number so the property
    survives a corpus regeneration -- scenario/corpus.json measures how much
    this matters, this test states that it holds at all.
    """
    engine = CorrelationEngine()
    decisions = []
    for alert in second_incident_on_a_busy_key():
        decisions.extend(engine.process(alert))

    routes = [d for d in decisions if d.decision_type == "route"]
    assert [d.action for d in routes] == ["open_incident", "escalate_incident"]
    assert not any(d.decision_type == "suppress" for d in decisions)


def test_flapping_key_does_not_suppress_a_new_severity_peak():
    """ФТ7.2: auto-suppression of critical/high is forbidden, and an unstable
    key is exactly where a real fault is easiest to lose -- once anything on
    the key has flapped, plain FLAPPING would suppress everything after it.
    """
    base = make_alert(rule="service-up", source="zabbix", metric="up", labels={"service": "sessions"})
    engine = CorrelationEngine()
    decisions = []
    for severity, value in [("warning", 1.0), ("resolved", 1.0), ("critical", 0.0)]:
        alert = base.model_copy(update={"alert_id": uuid4(), "severity": severity, "value": value})
        decisions.extend(engine.process(alert))

    assert any(d.decision_type == "suppress" for d in decisions), "the resolved dip should flap"
    assert [d.action for d in decisions if d.decision_type == "route"] == [
        "open_incident",
        "escalate_incident",
    ]


def test_pass_through_transform_is_still_available_as_an_explicit_opt_out():
    engine = CorrelationEngine(sequence_transforms=[PassThroughSequenceTransform()])
    decisions = []
    for alert in duplicate_storm(5):
        decisions.extend(engine.process(alert))
    assert decisions == []
