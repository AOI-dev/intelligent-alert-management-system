"""Happy-path tests for the core correlation/detection contour.

These tests run synthetic alert sequences through the CorrelationEngine and
verify the decision distribution against an oracle. The default engine runs
FlapAwareCorrelator (app/core/correlation_automaton.py), which is built to
satisfy exactly this oracle -- see that module for the state machine.
"""
import pytest

from app.core.pipeline import CorrelationEngine, PassThroughSequenceTransform
from tests.core.fixtures import (
    correlated_cascade,
    duplicate_storm,
    flapping_alerts,
    multi_tenant_noise,
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


def test_pass_through_transform_is_still_available_as_an_explicit_opt_out():
    engine = CorrelationEngine(sequence_transforms=[PassThroughSequenceTransform()])
    decisions = []
    for alert in duplicate_storm(5):
        decisions.extend(engine.process(alert))
    assert decisions == []
