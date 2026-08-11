"""Wiring tests for the AI enrichment contour's place in handle_alert
(app/main.py) — the integration half of the contour, complementing
test_enrichment.py's service-level contract tests.

What's pinned here, because it's what the rest of the platform relies on:

- Decisions come back exactly as before with enrichment enabled — the AI
  path is fire-and-forget and cannot alter, delay, or drop them.
- A dead model (client raising AIClientError) leaves the alert flow
  untouched and still produces a *valid* fallback result envelope on the
  results topic — never an exception escaping into the Kafka consumer.
- AI_ENRICHMENT_MODE=off (the default) publishes nothing at all.

Like tests/test_main_routes.py, these call app.main's functions directly
rather than through TestClient: the lifespan's Kafka connections have no
broker to reach under pytest.
"""
from datetime import datetime, timezone
from uuid import uuid4

import pytest

import app.main as main_module
from app.ai.client import AIClientError
from app.contracts.messages import EnrichmentResult, MessageEnvelope
from tests.ai.fixtures import make_alert


class RecordingProducer:
    """Stands in for KafkaProducer; records (topic, envelope) pairs."""

    def __init__(self):
        self.published: list[tuple[str, MessageEnvelope]] = []

    async def publish(self, topic: str, envelope: MessageEnvelope) -> None:
        self.published.append((topic, envelope))


def _alert_message() -> MessageEnvelope:
    alert = make_alert()
    return MessageEnvelope(
        message_type="monitoring.alert",
        producer="test",
        correlation_id=uuid4(),
        occurred_at=datetime.now(timezone.utc),
        data=alert.model_dump(mode="json"),
    )


@pytest.fixture(autouse=True)
def _isolate_handle_alert(monkeypatch):
    """handle_alert is being tested for its *enrichment* wiring, not for
    storage or DB persistence (those have their own tests). Stub the stores
    to always accept and the TimescaleDB logging to a no-op so this test
    needs neither Kafka nor Postgres."""
    monkeypatch.setattr(main_module.alerts, "add", lambda message: True)
    monkeypatch.setattr(main_module.decisions, "add", lambda message: True)

    class _NullSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

    monkeypatch.setattr(main_module, "SessionLocal", lambda: _NullSession())

    async def _no_log(*args, **kwargs):
        return None

    monkeypatch.setattr(main_module, "log_alert", _no_log)
    monkeypatch.setattr(main_module, "log_decision", _no_log)


@pytest.mark.asyncio
async def test_alert_flow_ignores_enrichment_when_mode_is_off(monkeypatch):
    monkeypatch.setattr(main_module, "AI_ENRICHMENT_MODE", "off")
    producer = RecordingProducer()
    monkeypatch.setattr(main_module.app.state, "producer", producer, raising=False)

    await main_module.handle_alert(_alert_message())

    topics = [topic for topic, _ in producer.published]
    assert main_module.AI_REQUESTS_TOPIC not in topics
    assert main_module.AI_RESULTS_TOPIC not in topics


@pytest.mark.asyncio
async def test_enrichment_runs_detached_and_never_touches_decisions(monkeypatch):
    monkeypatch.setattr(main_module, "AI_ENRICHMENT_MODE", "shadow")
    producer = RecordingProducer()
    monkeypatch.setattr(main_module.app.state, "producer", producer, raising=False)

    created_tasks = []
    real_create_task = main_module.asyncio.create_task

    def capture(coro):
        task = real_create_task(coro)
        created_tasks.append(task)
        return task

    monkeypatch.setattr(main_module.asyncio, "create_task", capture)

    class ExplodingService:
        async def enrich(self, request):
            raise AIClientError("model is dead")

    monkeypatch.setattr(main_module, "enrichment_service", ExplodingService())

    await main_module.handle_alert(_alert_message())
    for task in created_tasks:
        await task  # must not raise, even with the model dead

    topics = [topic for topic, _ in producer.published]
    # Decisions still published (the deterministic path completed)...
    assert main_module.DECISIONS_TOPIC in topics
    # ...the enrichment request went out for audit/future workers...
    assert main_module.AI_REQUESTS_TOPIC in topics
    # ...and a valid fallback result was published despite the dead model.
    result_topics = [env for topic, env in producer.published if topic == main_module.AI_RESULTS_TOPIC]
    assert result_topics, "expected fallback enrichment results on the results topic"
    for envelope in result_topics:
        result = EnrichmentResult.model_validate(envelope.data)
        assert result.confidence == 0.0
        assert result.model_name == "unavailable"
        assert result.explanation  # names the failure, never empty
