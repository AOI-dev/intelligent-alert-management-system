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
from uuid import uuid4

import pytest
from fastapi import HTTPException

import app.main as main_module
from app.identity.models import Identity

FAKE_IDENTITY = Identity(id=uuid4(), trueconf_subject="test-subject", display_label="Test User")


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


@pytest.mark.asyncio
async def test_incidents_are_an_honest_501_not_a_fake_empty_list():
    """Deliberately not testing for [] here -- an empty list would look
    identical to "no incidents right now", which is a lie when the truth
    is "incidents aren't implemented". See main.py's INCIDENTS_NOT_IMPLEMENTED.
    """
    with pytest.raises(HTTPException) as excinfo:
        await main_module.list_incidents(_=FAKE_IDENTITY)

    assert excinfo.value.status_code == 501
    assert "not implemented" in excinfo.value.detail


@pytest.mark.asyncio
async def test_incident_detail_is_also_a_501():
    with pytest.raises(HTTPException) as excinfo:
        await main_module.get_incident(uuid4(), _=FAKE_IDENTITY)

    assert excinfo.value.status_code == 501


@pytest.mark.asyncio
async def test_incident_ack_is_also_a_501():
    with pytest.raises(HTTPException) as excinfo:
        await main_module.acknowledge_incident(uuid4(), _=FAKE_IDENTITY)

    assert excinfo.value.status_code == 501
