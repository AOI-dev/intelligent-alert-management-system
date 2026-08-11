"""Handler-level tests: dedup runs before delivery is even attempted (no
HTTP call happens for a suppressed duplicate), a suppressed duplicate
publishes nothing at all to Kafka (invisible outside this process -- see
build_handler's docstring in app/main.py for why), and only a successful
delivery starts the dedup window -- a failed one must not block a retry.
"""
from uuid import uuid4

import pytest

import app.main as main_module
from app.dedup import NotificationDeduplicator
from app.protocol import MessageEnvelope, NotificationRequest


class FakeProducer:
    def __init__(self) -> None:
        self.published: list[tuple[str, MessageEnvelope]] = []

    async def publish(self, topic: str, envelope: MessageEnvelope) -> None:
        self.published.append((topic, envelope))


class FakeResponse:
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code


class FakeHttpClient:
    """Records every POST and returns a scripted status code, so tests can
    assert a suppressed duplicate never reaches the network at all.
    """

    calls: list[str] = []
    status_code = 200

    def __init__(self, *args, **kwargs) -> None:
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc) -> bool:
        return False

    async def post(self, url: str, json: dict) -> FakeResponse:
        FakeHttpClient.calls.append(url)
        return FakeResponse(FakeHttpClient.status_code)


@pytest.fixture(autouse=True)
def fake_http(monkeypatch):
    FakeHttpClient.calls = []
    FakeHttpClient.status_code = 200
    monkeypatch.setattr(main_module.httpx, "AsyncClient", FakeHttpClient)
    return FakeHttpClient


def _request(**overrides) -> NotificationRequest:
    fields = dict(
        incident_id=uuid4(),
        target_id="user-1",
        webhook_url="https://hook.example/a",
        priority="p2",
        reason="test",
        payload={"text": "hi"},
    )
    fields.update(overrides)
    return NotificationRequest(**fields)


def _envelope(request: NotificationRequest) -> MessageEnvelope:
    return MessageEnvelope(
        message_type="notification.requested",
        producer="test",
        correlation_id=uuid4(),
        data=request.model_dump(mode="json"),
    )


def _outcomes(producer: FakeProducer) -> list[str]:
    return [main_module.NotificationResult.model_validate(envelope.data).outcome for _, envelope in producer.published]


@pytest.mark.asyncio
async def test_second_notification_for_the_same_incident_channel_and_address_is_deduplicated(fake_http):
    producer = FakeProducer()
    handler = main_module.build_handler(producer, NotificationDeduplicator(window_seconds=300))
    request = _request()

    await handler(_envelope(request))
    await handler(_envelope(request))

    assert len(fake_http.calls) == 1  # the duplicate never reached the network
    # ...and never reached Kafka either: no second NotificationResult, no
    # new outcome value -- the duplicate is invisible outside this process.
    assert _outcomes(producer) == ["delivered"]


@pytest.mark.asyncio
async def test_different_incident_to_the_same_address_is_not_deduplicated(fake_http):
    producer = FakeProducer()
    handler = main_module.build_handler(producer, NotificationDeduplicator(window_seconds=300))

    await handler(_envelope(_request(incident_id=uuid4())))
    await handler(_envelope(_request(incident_id=uuid4())))

    assert len(fake_http.calls) == 2
    assert _outcomes(producer) == ["delivered", "delivered"]


@pytest.mark.asyncio
async def test_a_failed_delivery_does_not_block_a_retry(fake_http):
    producer = FakeProducer()
    handler = main_module.build_handler(producer, NotificationDeduplicator(window_seconds=300))
    request = _request()

    fake_http.status_code = 500
    await handler(_envelope(request))
    fake_http.status_code = 200
    await handler(_envelope(request))

    assert len(fake_http.calls) == 2
    assert _outcomes(producer) == ["failed", "delivered"]
