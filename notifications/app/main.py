import asyncio
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from uuid import UUID

import httpx
from fastapi import FastAPI
from prometheus_client import Counter
from prometheus_fastapi_instrumentator import Instrumentator

from app.dedup import NotificationDeduplicator
from app.kafka_consumer import KafkaTopicConsumer
from app.kafka_producer import KafkaProducer
from app.protocol import (
    NOTIFICATION_REQUESTS_TOPIC,
    NOTIFICATION_RESULTS_TOPIC,
    MessageEnvelope,
    NotificationRequest,
    NotificationResult,
)
from app.store import MessageStore

logger = logging.getLogger(__name__)
KAFKA_BOOTSTRAP_SERVERS = os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "eventsim-kafka:9092")
REQUESTS_TOPIC = os.environ.get("KAFKA_NOTIFICATION_REQUESTS_TOPIC", NOTIFICATION_REQUESTS_TOPIC)
RESULTS_TOPIC = os.environ.get("KAFKA_NOTIFICATION_RESULTS_TOPIC", NOTIFICATION_RESULTS_TOPIC)
CONSUMER_GROUP = os.environ.get("KAFKA_CONSUMER_GROUP", "notification-dispatcher-v1")
HISTORY_LIMIT = int(os.environ.get("NOTIFICATIONS_HISTORY_LIMIT", "500"))
WEBHOOK_TIMEOUT_SECONDS = float(os.environ.get("WEBHOOK_TIMEOUT_SECONDS", "10"))
DEDUP_WINDOW_SECONDS = float(os.environ.get("NOTIFICATION_DEDUP_WINDOW_SECONDS", "300"))

results = MessageStore(HISTORY_LIMIT)
consumed_total = Counter("notifications_kafka_messages_total", "Notification requests consumed", ["outcome"])
produced_total = Counter("notifications_kafka_published_total", "Notification results published", ["outcome"])
deliveries_total = Counter("notifications_deliveries_total", "Webhook delivery attempts", ["outcome"])
# Pure in-memory state, no I/O -- safe to construct at import time (unlike
# KafkaProducer below, which needs a running loop and is built in lifespan()).
deduplicator = NotificationDeduplicator(DEDUP_WINDOW_SECONDS)


async def publish_result(producer: KafkaProducer, correlation_id: UUID, result: NotificationResult) -> None:
    message_type = "notification.delivered" if result.outcome == "delivered" else "notification.failed"
    await producer.publish(
        RESULTS_TOPIC,
        MessageEnvelope(
            message_type=message_type,
            occurred_at=datetime.now(timezone.utc),
            producer="notification-dispatcher",
            correlation_id=correlation_id,
            data=result.model_dump(mode="json"),
        ),
    )
    produced_total.labels(outcome=result.outcome).inc()


async def deliver(request: NotificationRequest) -> NotificationResult:
    try:
        async with httpx.AsyncClient(timeout=WEBHOOK_TIMEOUT_SECONDS) as client:
            response = await client.post(request.webhook_url, json=request.payload)
        if 200 <= response.status_code < 300:
            deliveries_total.labels(outcome="delivered").inc()
            return NotificationResult(
                notification_id=request.notification_id,
                target_id=request.target_id,
                outcome="delivered",
                status_code=response.status_code,
            )
        deliveries_total.labels(outcome="failed").inc()
        return NotificationResult(
            notification_id=request.notification_id,
            target_id=request.target_id,
            outcome="failed",
            status_code=response.status_code,
            error=f"webhook returned {response.status_code}",
        )
    except httpx.HTTPError as error:
        deliveries_total.labels(outcome="failed").inc()
        return NotificationResult(
            notification_id=request.notification_id,
            target_id=request.target_id,
            outcome="failed",
            error=str(error),
        )


def build_handler(producer: KafkaProducer, dedup: NotificationDeduplicator):
    async def handle_notification_request(message: MessageEnvelope) -> None:
        request = NotificationRequest.model_validate(message.data)

        if dedup.is_duplicate(request.incident_id, request.target_id, request.webhook_url):
            # Deliberately invisible outside this process: no delivery is
            # attempted, no NotificationResult is published, and
            # NotificationResult/MessageEnvelope's contracts are untouched
            # -- nothing consuming monitoring.notification-results.v1 needs
            # to learn a new outcome exists just because this dispatcher
            # suppressed a repeat. What's below is this dispatcher's own
            # operational visibility only (metrics, /v1/results), not a
            # cross-service signal.
            consumed_total.labels(outcome="deduplicated").inc()
            results.add(
                {
                    "message_id": str(message.message_id),
                    "notification_id": str(request.notification_id),
                    "target_id": request.target_id,
                    "outcome": "deduplicated",
                }
            )
            return

        result = await deliver(request)
        if result.outcome == "delivered":
            dedup.mark_delivered(request.incident_id, request.target_id, request.webhook_url)
        consumed_total.labels(outcome=result.outcome).inc()
        results.add({"message_id": str(message.message_id), **result.model_dump(mode="json")})
        await publish_result(producer, message.correlation_id, result)

    return handle_notification_request


@asynccontextmanager
async def lifespan(app: FastAPI):
    producer = KafkaProducer(KAFKA_BOOTSTRAP_SERVERS)
    consumer = KafkaTopicConsumer(
        KAFKA_BOOTSTRAP_SERVERS, REQUESTS_TOPIC, f"{CONSUMER_GROUP}-requests", build_handler(producer, deduplicator)
    )
    try:
        await producer.start()
        await consumer.start()
    except Exception as error:
        await producer.stop()
        await consumer.stop()
        app.state.kafka_status = f"unavailable: {error.__class__.__name__}"
        yield
        return
    app.state.kafka_status = "connected"
    task = asyncio.create_task(consumer.run())
    try:
        yield
    finally:
        task.cancel()
        await producer.stop()
        await consumer.stop()


app = FastAPI(title="notification-dispatcher", lifespan=lifespan)
Instrumentator().instrument(app).expose(app, endpoint="/metrics")


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "kafka": app.state.kafka_status}


@app.get("/v1/results")
async def list_results() -> list[dict]:
    return results.list()
