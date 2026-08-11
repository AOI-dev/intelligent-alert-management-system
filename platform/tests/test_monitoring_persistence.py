"""Row-building tests for the TimescaleDB projection (app/monitoring/
persistence.py): what lands in known columns vs. the `extra` JSONB catch-
all. This is the part that's testable without a live TimescaleDB -- the
actual DB calls (log_event/log_alert/log_decision, init_monitoring_models)
aren't covered here; see the module docstring for why (failures there are
swallowed by design) and the README for how this was verified against a
real instance.
"""
from datetime import datetime, timezone
from uuid import uuid4

from app.monitoring.persistence import build_alert_row, build_decision_row, build_event_row

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def test_build_event_row_known_fields_land_in_columns():
    message_id = uuid4()
    correlation_id = uuid4()
    row = build_event_row(
        message_id, NOW, correlation_id, {"source": "zabbix", "status": "firing", "metric": "cpu", "value": 99.0}
    )

    assert row.event_id == message_id
    assert row.occurred_at == NOW
    assert row.correlation_id == correlation_id
    assert row.source == "zabbix"
    assert row.status == "firing"
    assert row.metric == "cpu"
    assert row.value == 99.0
    assert row.extra == {}


def test_build_event_row_uses_domain_event_id_over_message_id_when_present():
    domain_event_id = uuid4()
    row = build_event_row(uuid4(), NOW, uuid4(), {"event_id": str(domain_event_id), "source": "zabbix", "status": "firing"})

    assert row.event_id == domain_event_id


def test_build_event_row_unknown_fields_land_in_extra():
    row = build_event_row(
        uuid4(),
        NOW,
        uuid4(),
        {
            "source": "zabbix",
            "status": "firing",
            "severity": "critical",
            "summary": "Disk full",
            "labels": {"host": "db-01"},
        },
    )

    assert row.extra == {"severity": "critical", "summary": "Disk full", "labels": {"host": "db-01"}}


def test_build_event_row_defaults_missing_required_text_fields():
    row = build_event_row(uuid4(), NOW, uuid4(), {})

    assert row.source == "unknown"
    assert row.status == "unknown"
    assert row.metric is None
    assert row.value is None


def test_build_alert_row_known_fields_land_in_columns():
    message_id = uuid4()
    source_event_id = uuid4()
    row = build_alert_row(
        message_id,
        NOW,
        uuid4(),
        {
            "rule": "disk-full",
            "severity": "critical",
            "source": "zabbix",
            "metric": "disk",
            "value": 98.0,
            "threshold": 90.0,
            "source_event_id": str(source_event_id),
        },
    )

    assert row.alert_id == message_id
    assert row.rule == "disk-full"
    assert row.severity == "critical"
    assert row.source_event_id == source_event_id
    assert row.value == 98.0
    assert row.threshold == 90.0
    assert row.extra == {}


def test_build_alert_row_uses_domain_alert_id_over_message_id_when_present():
    domain_alert_id = uuid4()
    row = build_alert_row(uuid4(), NOW, uuid4(), {"alert_id": str(domain_alert_id)})

    assert row.alert_id == domain_alert_id


def test_build_alert_row_unknown_fields_land_in_extra():
    row = build_alert_row(uuid4(), NOW, uuid4(), {"summary": "Disk full", "state": "firing"})

    assert row.extra == {"summary": "Disk full", "state": "firing"}


def test_build_alert_row_without_source_event_id_is_none():
    row = build_alert_row(uuid4(), NOW, uuid4(), {})

    assert row.source_event_id is None


def test_build_decision_row_known_fields_land_in_columns():
    decision_id = uuid4()
    alert_id = uuid4()
    incident_id = uuid4()
    row = build_decision_row(
        NOW,
        uuid4(),
        {
            "decision_id": str(decision_id),
            "decision_type": "route",
            "alert_id": str(alert_id),
            "incident_id": str(incident_id),
            "action": "notify",
            "reason": "first alert observed for correlation key",
            "policy_id": "flap-aware-correlator/v1",
        },
    )

    assert row.decision_id == decision_id
    assert row.decision_type == "route"
    assert row.alert_id == alert_id
    assert row.incident_id == incident_id
    assert row.action == "notify"
    assert row.policy_id == "flap-aware-correlator/v1"


def test_build_decision_row_without_incident_id_is_none():
    row = build_decision_row(NOW, uuid4(), {"decision_id": str(uuid4()), "alert_id": str(uuid4())})

    assert row.incident_id is None
