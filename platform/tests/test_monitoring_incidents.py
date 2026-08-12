"""IncidentProjection behaviour, independent of FastAPI and Kafka.

The route tests in tests/test_main_routes.py cover wiring and status codes;
these cover the two judgement calls the projection makes that a reader would
otherwise have to take on faith.
"""
from uuid import UUID

import pytest

from app.contracts.messages import Decision, MonitoringAlert
from app.monitoring.incidents import IncidentProjection


def alert(severity: str = "critical", service: str = "db_primary", rule: str = "high_cpu") -> MonitoringAlert:
    return MonitoringAlert(
        rule=rule, severity=severity, source="db-01", metric="cpu_percent",
        value=97.0, threshold=90.0, labels={"service": service},
    )


def decision(kind: str, target: MonitoringAlert, action: str) -> Decision:
    return Decision(decision_type=kind, alert_id=target.alert_id, action=action, reason="because", policy_id="p/v1")


@pytest.fixture
def projection() -> IncidentProjection:
    return IncidentProjection(limit=10)


def test_a_suppressed_alert_does_not_open_an_incident(projection):
    """Otherwise every flapping key would manufacture an incident nobody was
    told about, and the Инциденты screen would stop meaning "we paged"."""
    noisy = alert(severity="warning")

    assert projection.observe(noisy, [decision("suppress", noisy, "suppress_flap")]) is None
    assert projection.list() == []


def test_alerts_on_an_open_key_are_counted_without_opening_a_second_incident(projection):
    first = alert()
    projection.observe(first, [decision("route", first, "open_incident")])
    repeat = alert()
    projection.observe(repeat, [decision("dedup", repeat, "dedup")])

    assert len(projection.list()) == 1
    incident = projection.list()[0]
    assert incident["alert_count"] == 2
    assert incident["notification_count"] == 1
    assert incident["decisions_by_type"] == {"route": 1, "dedup": 1}


def test_severity_is_the_peak_not_the_latest(projection):
    opening = alert(severity="critical")
    projection.observe(opening, [decision("route", opening, "open_incident")])
    later = alert(severity="warning")
    projection.observe(later, [decision("dedup", later, "dedup")])

    assert projection.list()[0]["severity"] == "critical"


def test_a_new_page_invalidates_an_earlier_acknowledgement(projection):
    """Acking "the database is slow" cannot also ack "the database is now
    critical" -- being paged again means the incident outgrew the ack."""
    opening = alert(severity="warning")
    incident = projection.observe(opening, [decision("route", opening, "open_incident")])
    projection.acknowledge(UUID(incident["incident_id"]), by="user-1", display_label="Дежурный")
    assert projection.list()[0]["status"] == "acknowledged"

    escalation = alert(severity="critical")
    projection.observe(escalation, [decision("route", escalation, "escalate_incident")])

    reopened = projection.list()[0]
    assert reopened["status"] == "open"
    assert reopened["acknowledged_by"] is None
    assert reopened["severity"] == "critical"


def test_the_projection_is_bounded_like_the_rest_of_the_live_tail():
    projection = IncidentProjection(limit=2)
    for service in ("a", "b", "c"):
        opening = alert(service=service)
        projection.observe(opening, [decision("route", opening, "open_incident")])

    assert [i["correlation_key"] for i in projection.list()] == ["c", "b"]
