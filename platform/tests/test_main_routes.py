"""Route-handler tests calling app.main's functions directly rather than
through TestClient -- confirms the new endpoints are actually wired
correctly (status codes, HTTPException behavior), not just that
app.monitoring.query's logic is correct in isolation (see
tests/test_monitoring_query.py for that).

Deliberately not using FastAPI's TestClient: app.main's lifespan calls
KafkaProducer.start()/KafkaTopicConsumer.start(), which try to actually
reach a broker and can hang for a long time with no broker present rather
than failing fast -- exactly this sandbox's situation. Calling the route
functions directly (they're plain async functions FastAPI's decorators
register but don't wrap) exercises the same code with none of that.
"""
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException

import app.main as main_module
from app.contracts.messages import Decision, MonitoringAlert
from app.identity.models import Identity
from app.monitoring.incidents import IncidentProjection

FAKE_IDENTITY = Identity(id=uuid4(), trueconf_subject="test-subject", display_label="Test User")


@pytest.fixture(autouse=True)
def _health_state(monkeypatch):
    monkeypatch.setattr(main_module.app.state, "kafka_status", "connected", raising=False)
    monkeypatch.setattr(main_module.app.state, "identity_status", "connected", raising=False)
    monkeypatch.setattr(main_module.app.state, "monitoring_db_status", "connected", raising=False)


@pytest.mark.asyncio
async def test_health_reports_when_oauth_login_is_configured(monkeypatch):
    for name in (
        "TRUECONF_BASE_URL",
        "TRUECONF_OAUTH_CLIENT_ID",
        "TRUECONF_OAUTH_CLIENT_SECRET",
        "TRUECONF_OAUTH_REDIRECT_URI",
    ):
        monkeypatch.setenv(name, "configured")

    assert (await main_module.health())["auth"] == "configured"


@pytest.mark.asyncio
async def test_health_reports_when_oauth_login_is_not_configured(monkeypatch):
    monkeypatch.delenv("TRUECONF_OAUTH_CLIENT_SECRET", raising=False)

    assert (await main_module.health())["auth"] == "not_configured"


@pytest.mark.asyncio
async def test_summary_reflects_the_empty_window_when_nothing_has_been_ingested():
    result = await main_module.summary(_=FAKE_IDENTITY)

    assert result == {
        "events_in_window": 0,
        "alerts_in_window": 0,
        "alerts_by_severity": {},
        "decisions_by_type": {},
        "window_limit": main_module.HISTORY_LIMIT,
    }


@pytest.mark.asyncio
async def test_alerts_accepts_filter_query_params_without_error():
    result = await main_module.list_alerts(severity="critical", source="zabbix", since=None, _=FAKE_IDENTITY)

    assert result == []


@pytest.mark.asyncio
async def test_get_alert_404s_when_not_in_the_retained_window():
    with pytest.raises(HTTPException) as excinfo:
        await main_module.get_alert(uuid4(), _=FAKE_IDENTITY)

    assert excinfo.value.status_code == 404


def _routed(alert):
    return Decision(
        decision_type="route",
        alert_id=alert.alert_id,
        action="open_incident",
        reason="first alert observed for correlation key",
        policy_id="flap-aware-correlator/v1",
    )


@pytest.fixture
def one_open_incident(monkeypatch):
    """A projection holding exactly one incident, swapped in for the module's."""
    projection = IncidentProjection(limit=10)
    alert = MonitoringAlert(
        rule="high_cpu", severity="critical", source="db-01", metric="cpu_percent",
        value=97.0, threshold=90.0, labels={"service": "db_primary"},
    )
    projection.observe(alert, [_routed(alert)])
    monkeypatch.setattr(main_module, "incidents", projection)
    return projection.list()[0]


@pytest.mark.asyncio
async def test_incidents_list_reports_what_the_correlator_decided(one_open_incident):
    listed = await main_module.list_incidents(_=FAKE_IDENTITY)

    assert [i["incident_id"] for i in listed] == [one_open_incident["incident_id"]]
    assert listed[0]["status"] == "open"
    assert listed[0]["service"] == "db_primary"
    # The screen has to be able to say *why* this paged, not just that it did.
    assert listed[0]["policy_id"] == "flap-aware-correlator/v1"


@pytest.mark.asyncio
async def test_incidents_list_filters_by_status(one_open_incident):
    assert await main_module.list_incidents(status="acknowledged", _=FAKE_IDENTITY) == []
    assert len(await main_module.list_incidents(status="open", _=FAKE_IDENTITY)) == 1


@pytest.mark.asyncio
async def test_unknown_incident_is_a_404_not_an_empty_object(one_open_incident):
    with pytest.raises(HTTPException) as excinfo:
        await main_module.get_incident(uuid4(), _=FAKE_IDENTITY)

    assert excinfo.value.status_code == 404


@pytest.mark.asyncio
async def test_ack_records_the_authenticated_session_not_a_client_supplied_name(one_open_incident):
    """The acknowledger is taken from the session. An ack whose author the
    caller can choose proves nothing about who actually responded."""
    incident_id = UUID(one_open_incident["incident_id"])

    acked = await main_module.acknowledge_incident(
        incident_id, body=main_module.AcknowledgementBody(note="проверяю реплику"), identity=FAKE_IDENTITY
    )

    assert acked["status"] == "acknowledged"
    assert acked["acknowledged_by"] == str(FAKE_IDENTITY.id)
    assert acked["acknowledged_by_label"] == "Test User"
    assert acked["acknowledgement_note"] == "проверяю реплику"


@pytest.mark.asyncio
async def test_ack_of_an_unknown_incident_is_a_404(one_open_incident):
    with pytest.raises(HTTPException) as excinfo:
        await main_module.acknowledge_incident(uuid4(), body=None, identity=FAKE_IDENTITY)

    assert excinfo.value.status_code == 404
