"""MonitoringEvent's minimal-but-open contract: only source/status are
required, everything else -- known fields or ones an LLM enrichment step
invents -- rides along free-form. See app/contracts/messages.py.
"""
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from uuid import uuid4

from app.contracts.messages import MonitoringAlert, MonitoringEvent


def test_minimal_event_needs_only_source_and_status():
    event = MonitoringEvent(source="zabbix", status="firing")

    assert event.source == "zabbix"
    assert event.status == "firing"
    assert event.metric is None
    assert event.value is None
    assert event.labels == {}


def test_timestamp_defaults_to_now_when_omitted():
    before = datetime.now(timezone.utc)
    event = MonitoringEvent(source="zabbix", status="firing")
    after = datetime.now(timezone.utc)

    assert before <= event.timestamp <= after


@pytest.mark.parametrize("missing", ["source", "status"])
def test_missing_required_field_is_rejected(missing: str):
    fields = {"source": "zabbix", "status": "firing"}
    del fields[missing]

    with pytest.raises(ValidationError):
        MonitoringEvent(**fields)


def test_arbitrary_extra_fields_attach_without_a_schema_change():
    """Stand-in for an LLM enrichment step (or a vendor normalizer)
    attaching fields nobody declared on the model -- exactly the "as big
    as it wants" requirement.
    """
    event = MonitoringEvent(
        source="zabbix",
        status="firing",
        root_cause="disk queue depth on the primary database",
        confidence=0.87,
        recommended_team="db-oncall",
        nested={"anything": ["goes", 1, True]},
    )

    assert event.root_cause == "disk queue depth on the primary database"
    assert event.confidence == 0.87
    assert event.recommended_team == "db-oncall"
    assert event.nested == {"anything": ["goes", 1, True]}

    dumped = event.model_dump(mode="json")
    assert dumped["root_cause"] == "disk queue depth on the primary database"


def test_extra_fields_round_trip_through_model_validate():
    """The Kafka path: model_validate(message.data) must not drop or
    reject fields it doesn't know about.
    """
    payload = {
        "source": "prometheus",
        "status": "resolved",
        "severity": "warning",
        "rule": "HighCPU",
        "summary": "CPU pegged",
        "runbook": "https://runbooks.example/high-cpu",
    }

    event = MonitoringEvent.model_validate(payload)

    assert event.severity == "warning"
    assert event.rule == "HighCPU"
    assert event.summary == "CPU pegged"
    assert event.runbook == "https://runbooks.example/high-cpu"


def _alert(**overrides) -> MonitoringAlert:
    fields: dict = dict(rule="cpu-high", severity="critical", source="zabbix", metric="cpu", value=99.0, threshold=90.0)
    fields.update(overrides)
    return MonitoringAlert(**fields)


def test_alert_source_event_id_defaults_to_none():
    assert _alert().source_event_id is None


def test_alert_source_event_id_links_to_its_causing_event():
    """The FK app/main.py's publish_alert sets: the same id publish_event
    used as MonitoringEvent.event_id for the occurrence this alert came
    from. Explicit and queryable, unlike the implicit link via a shared
    correlation_id (which groups things across time, not one occurrence to
    its one causing event).
    """
    event_id = uuid4()
    alert = _alert(source_event_id=event_id)

    assert alert.source_event_id == event_id
