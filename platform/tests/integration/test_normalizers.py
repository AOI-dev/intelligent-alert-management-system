"""Corresponding-event derivation: every real alert normalized from
Zabbix/Alertmanager should also produce a matching raw event via
to_event_data, reusing the same already-computed fields rather than
recomputing anything.
"""
from app.contracts.messages import MonitoringAlert, MonitoringEvent
from app.integration.normalizers import normalize_alertmanager, normalize_zabbix_problem, to_event_data


def test_to_event_data_renames_state_to_status():
    event_data = to_event_data({"source": "zabbix", "state": "firing", "severity": "critical"})

    assert event_data["status"] == "firing"
    assert "state" not in event_data
    assert event_data["severity"] == "critical"


def test_to_event_data_prefers_occurred_at_over_starts_at():
    event_data = to_event_data({"occurred_at": "2026-01-01T00:00:00+00:00", "starts_at": "2025-01-01T00:00:00+00:00"})

    assert event_data["timestamp"] == "2026-01-01T00:00:00+00:00"


def test_to_event_data_falls_back_to_starts_at():
    event_data = to_event_data({"starts_at": "2025-06-01T00:00:00+00:00"})

    assert event_data["timestamp"] == "2025-06-01T00:00:00+00:00"


def test_to_event_data_renames_a_stray_event_id_to_avoid_colliding_with_the_record_id():
    """Defensive: MonitoringEvent.event_id is a generated UUID identity, so
    a vendor's own non-UUID event id landing under that exact key would
    blow up validation. (normalize_zabbix_problem itself now avoids this
    by using vendor_event_id directly -- this covers any future normalizer
    that doesn't.)
    """
    event_data = to_event_data({"event_id": "42", "source": "zabbix"})

    assert event_data["vendor_event_id"] == "42"
    assert "event_id" not in event_data


def test_zabbix_problem_normalizes_into_both_alert_and_event():
    problem = {
        "eventid": "42",
        "name": "Disk full",
        "severity": "4",
        "clock": "1710000000",
        "hosts": [{"host": "db-01"}],
        "tags": [{"tag": "service", "value": "payments"}],
    }
    _message_id, _correlation_id, alert_data = normalize_zabbix_problem(problem)

    alert = MonitoringAlert.model_validate(alert_data)
    event = MonitoringEvent.model_validate(to_event_data(alert_data))

    assert alert.source == "zabbix"
    assert alert.severity == "high"
    assert event.source == "zabbix"
    assert event.status == "firing"
    assert event.vendor_event_id == "42"
    # the event carries everything the alert has -- summary, description,
    # labels -- via MonitoringEvent's open schema, not just the required core.
    assert event.summary == "Disk full"
    assert event.labels == {"host": "db-01", "service": "payments"}


def test_alertmanager_alert_normalizes_into_both_alert_and_event():
    alertmanager_alert = {
        "status": "resolved",
        "labels": {"alertname": "HighCPU", "severity": "warning"},
        "annotations": {"summary": "CPU pegged"},
        "startsAt": "2026-08-11T10:00:00Z",
        "endsAt": "2026-08-11T10:05:00Z",
        "fingerprint": "abc123",
    }
    _message_id, _correlation_id, alert_data = normalize_alertmanager(alertmanager_alert)

    alert = MonitoringAlert.model_validate(alert_data)
    event = MonitoringEvent.model_validate(to_event_data(alert_data))

    assert alert.source == "prometheus"
    assert event.status == "resolved"
    assert event.timestamp.isoformat().startswith("2026-08-11T10:00:00")
    assert event.summary == "CPU pegged"
