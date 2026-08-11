"""Routing and notification-wording tests.

The through-line: a `route` decision must reach exactly one identified human,
and it must still reach them when the model is unavailable. Everything below
pins one of those two properties.
"""
import json
from datetime import datetime, timezone

import pytest

from app.ai.client import AIClientError
from app.ai.summarize import NotificationSummarizer, heuristic_summary
from app.contracts.messages import Decision, MonitoringAlert
from app.routing.registry import RoutingRegistry
from app.routing.service import NotificationRouter, incident_id_for

CONFIG = {
    "default_team": "platform_infra",
    "services": {"db_primary": "platform_infra", "checkout": "payments"},
    "teams": {
        "platform_infra": {
            "oncall": "alice",
            "shifts": [
                {"from": "08:00", "to": "20:00", "login": "alice"},
                {"from": "20:00", "to": "08:00", "login": "boris"},
            ],
        },
        "payments": {"oncall": "carmen"},
    },
    "targets": {
        "alice": {"trueconf_id": "alice@tc", "webhook_url": "http://bot/v1/notify"},
        "boris": {"trueconf_id": "boris@tc", "webhook_url": "http://bot/v1/notify"},
        "carmen": {"trueconf_id": "carmen@tc", "webhook_url": "http://bot/v1/notify"},
    },
}


def _alert(**overrides) -> MonitoringAlert:
    fields: dict = dict(
        rule="high_cpu",
        severity="critical",
        source="db-01",
        metric="cpu_percent",
        value=97.0,
        threshold=90.0,
        labels={"service": "db_primary"},
    )
    fields.update(overrides)
    return MonitoringAlert(**fields)


def _route(**overrides) -> Decision:
    fields: dict = dict(
        decision_type="route",
        alert_id=_alert().alert_id,
        action="open_incident",
        reason="first alert observed for correlation key",
    )
    fields.update(overrides)
    return Decision(**fields)


class StubClient:
    def __init__(self, reply=None, error: Exception | None = None) -> None:
        self._reply = reply
        self._error = error
        self.calls = 0

    async def chat_json(self, messages, max_tokens: int = 512):
        self.calls += 1
        if self._error is not None:
            raise self._error
        return self._reply, "qwen3.5-4b-int8"


# --- registry ---------------------------------------------------------------


def test_resolves_service_to_its_team_oncall():
    registry = RoutingRegistry(CONFIG)
    target = registry.resolve("checkout")
    assert target is not None
    assert (target.target_id, target.trueconf_id, target.team) == ("carmen", "carmen@tc", "payments")


def test_unknown_service_falls_back_to_default_team():
    registry = RoutingRegistry(CONFIG)
    target = registry.resolve("some-service-nobody-declared")
    assert target is not None and target.team == "platform_infra"


def test_shift_selects_by_time_of_day():
    registry = RoutingRegistry(CONFIG)
    day = registry.resolve("db_primary", at=datetime(2026, 8, 11, 12, 0, tzinfo=timezone.utc))
    assert day is not None and day.target_id == "alice"


def test_shift_crossing_midnight_covers_both_sides():
    """A 20:00->08:00 shift is two ranges, not one comparison. Getting this
    wrong drops the night shift -- when an unrouted page hurts most."""
    registry = RoutingRegistry(CONFIG)
    late = registry.resolve("db_primary", at=datetime(2026, 8, 11, 23, 30, tzinfo=timezone.utc))
    early = registry.resolve("db_primary", at=datetime(2026, 8, 11, 3, 0, tzinfo=timezone.utc))
    assert late is not None and late.target_id == "boris"
    assert early is not None and early.target_id == "boris"


def test_missing_config_file_yields_empty_registry_not_an_error(tmp_path):
    """A routing misconfiguration must degrade to 'nobody is notified', which
    is visible in metrics, rather than taking alert ingestion down."""
    registry = RoutingRegistry.from_file(tmp_path / "nope.json")
    assert registry.configured is False
    assert registry.resolve("db_primary") is None


def test_malformed_config_file_yields_empty_registry_not_an_error(tmp_path):
    path = tmp_path / "routing.json"
    path.write_text("{not json")
    assert RoutingRegistry.from_file(path).configured is False


def test_target_without_webhook_url_does_not_resolve():
    config = json.loads(json.dumps(CONFIG))
    del config["targets"]["carmen"]["webhook_url"]
    assert RoutingRegistry(config).resolve("checkout") is None


# --- summarizer -------------------------------------------------------------


@pytest.mark.asyncio
async def test_model_wording_is_used_when_the_model_answers():
    client = StubClient({"headline": "DB primary CPU saturated", "priority": "p1", "next_step": "Check queries."})
    summary = await NotificationSummarizer(client=client).summarize(_alert())
    assert summary.headline == "DB primary CPU saturated"
    assert summary.priority == "p1"
    assert summary.source == "model"


@pytest.mark.asyncio
async def test_model_failure_falls_back_to_heuristic_wording():
    client = StubClient(error=AIClientError("vLLM is down"))
    summary = await NotificationSummarizer(client=client).summarize(_alert())
    assert summary.source == "heuristic"
    assert "high_cpu" in summary.headline
    assert summary.priority == "p1"  # critical -> p1, without asking anyone


@pytest.mark.asyncio
async def test_out_of_vocabulary_priority_falls_back_but_keeps_the_headline():
    """Partial credit: a good headline is not thrown away because the model
    invented a priority."""
    client = StubClient({"headline": "Disk nearly full on worker-03", "priority": "URGENT!!", "next_step": "Rotate logs."})
    summary = await NotificationSummarizer(client=client).summarize(_alert(severity="warning"))
    assert summary.headline == "Disk nearly full on worker-03"
    assert summary.priority == "p3"


@pytest.mark.asyncio
async def test_summarizer_times_out_into_the_heuristic():
    import asyncio

    class SlowClient:
        async def chat_json(self, messages, max_tokens: int = 512):
            await asyncio.sleep(10)

    summary = await NotificationSummarizer(client=SlowClient(), timeout_seconds=0.01).summarize(_alert())
    assert summary.source == "heuristic"


def test_heuristic_summary_never_needs_the_model():
    summary = heuristic_summary(_alert(severity="info"))
    assert summary.source == "heuristic"
    assert summary.priority == "p4"


def test_heuristic_priority_defaults_for_unknown_severity():
    assert heuristic_summary(_alert(severity="wat")).priority == "p3"


# --- router -----------------------------------------------------------------


@pytest.mark.asyncio
async def test_route_decision_becomes_a_notification_request():
    router = NotificationRouter(RoutingRegistry(CONFIG), NotificationSummarizer(client=StubClient(error=AIClientError("down"))))
    request = await router.build(_route(), _alert())

    assert request is not None
    assert request.target_id == "alice"
    assert request.webhook_url == "http://bot/v1/notify"
    # What trueconf-bot needs, and nothing it must guess at.
    assert request.payload["trueconf_id"] == "alice@tc"
    assert "high_cpu" in request.payload["text"]
    assert request.payload["summary_source"] == "heuristic"


@pytest.mark.asyncio
async def test_non_route_decisions_produce_nothing():
    router = NotificationRouter(RoutingRegistry(CONFIG))
    for decision_type in ("dedup", "suppress"):
        assert await router.build(_route(decision_type=decision_type), _alert()) is None


@pytest.mark.asyncio
async def test_unroutable_alert_does_not_call_the_model():
    """Ordering matters: an alert nobody owns must not spend a vLLM slot. At
    storm time that is the difference between a queue that drains and one
    that does not."""
    client = StubClient({"headline": "x", "priority": "p1", "next_step": "y"})
    router = NotificationRouter(RoutingRegistry({}), NotificationSummarizer(client=client))
    assert await router.build(_route(), _alert()) is None
    assert client.calls == 0


def test_incident_id_is_stable_across_alerts_in_one_correlation_key():
    """The notifications dispatcher dedups on incident_id, so two alerts for
    the same correlation key must agree on it -- including across restarts."""
    first = _alert(value=97.0)
    second = _alert(value=98.5)
    assert incident_id_for(first) == incident_id_for(second)
    assert incident_id_for(_alert(labels={"service": "checkout"})) != incident_id_for(first)
