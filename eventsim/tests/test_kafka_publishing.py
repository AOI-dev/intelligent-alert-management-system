"""Verify POST /events actually reaches Kafka -- both the raw event and,
when a rule fires, its derived alert -- without needing a real broker: the
module-level `producer` singleton in app.main is swapped for a fake that
just records what it was asked to publish. `ingest` is a plain async
function under FastAPI's decorator (the decorator registers a route but
returns the function unchanged), so it's called directly here rather than
through HTTP/TestClient/lifespan -- lifespan's `producer.start()` is what
would actually need a live broker, and this test never runs it.
"""
import pytest

import app.main as main_module
from app.main import ALERTS_TOPIC, EVENTS_TOPIC, ingest
from app.models import EventIn
from app.protocol import MessageEnvelope


class FakeProducer:
    def __init__(self) -> None:
        self.published: list[tuple[str, MessageEnvelope]] = []

    async def publish(self, topic: str, envelope: MessageEnvelope) -> None:
        self.published.append((topic, envelope))


@pytest.fixture
def fake_producer(monkeypatch):
    fake = FakeProducer()
    monkeypatch.setattr(main_module, "producer", fake)
    return fake


@pytest.mark.asyncio
async def test_ingest_publishes_the_event_to_kafka(fake_producer):
    event = EventIn(source="web-01", metric="cpu_percent", value=10.0)

    await ingest(event)

    published_topics = [topic for topic, _ in fake_producer.published]
    assert EVENTS_TOPIC in published_topics

    event_envelope = next(envelope for topic, envelope in fake_producer.published if topic == EVENTS_TOPIC)
    assert event_envelope.message_type == "monitoring.event"
    assert event_envelope.correlation_id == event.correlation_id
    assert event_envelope.data["source"] == "web-01"
    assert event_envelope.data["metric"] == "cpu_percent"
    assert event_envelope.data["value"] == 10.0
    assert event_envelope.data["status"] == "firing"


@pytest.mark.asyncio
async def test_ingest_publishes_no_alert_when_no_rule_fires(fake_producer):
    event = EventIn(source="web-01", metric="cpu_percent", value=10.0)  # well under high_cpu's >90 threshold

    await ingest(event)

    published_topics = [topic for topic, _ in fake_producer.published]
    assert EVENTS_TOPIC in published_topics
    assert ALERTS_TOPIC not in published_topics


@pytest.mark.asyncio
async def test_ingest_publishes_a_matching_alert_when_a_rule_fires(fake_producer):
    event = EventIn(source="web-01", metric="cpu_percent", value=95.0)  # breaches high_cpu (>90)

    await ingest(event)

    alert_envelopes = [envelope for topic, envelope in fake_producer.published if topic == ALERTS_TOPIC]
    assert len(alert_envelopes) == 1
    alert_envelope = alert_envelopes[0]
    assert alert_envelope.message_type == "monitoring.alert"
    assert alert_envelope.correlation_id == event.correlation_id
    assert alert_envelope.data["rule"] == "high_cpu"
    assert alert_envelope.data["severity"] == "critical"


@pytest.mark.asyncio
async def test_ingest_publishes_one_alert_per_fired_rule(fake_producer):
    # low_disk fires on disk_free_percent < 10; only one rule matches this metric.
    event = EventIn(source="db-01", metric="disk_free_percent", value=2.0)

    await ingest(event)

    alert_envelopes = [envelope for topic, envelope in fake_producer.published if topic == ALERTS_TOPIC]
    assert [envelope.data["rule"] for envelope in alert_envelopes] == ["low_disk"]
