import asyncio
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import FileResponse
from prometheus_client import Counter
from prometheus_fastapi_instrumentator import Instrumentator

from app.contracts.messages import MessageEnvelope, MonitoringEvent
from app.filtering.service import EventFilter
from app.integration.kafka_consumer import KafkaTopicConsumer
from app.monitoring.store import MessageStore

KAFKA_BOOTSTRAP_SERVERS = os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "eventsim-kafka:9092")
EVENTS_TOPIC = os.environ.get("KAFKA_EVENTS_TOPIC", "monitoring.events.v1")
ALERTS_TOPIC = os.environ.get("KAFKA_ALERTS_TOPIC", "monitoring.alerts.v1")
CONSUMER_GROUP = os.environ.get("KAFKA_CONSUMER_GROUP", "platform-ingestion-v1")
HISTORY_LIMIT = int(os.environ.get("PLATFORM_HISTORY_LIMIT", "500"))

filter_service = EventFilter()
events = MessageStore(HISTORY_LIMIT)
alerts = MessageStore(HISTORY_LIMIT)
consumed_total = Counter("platform_kafka_messages_total", "Kafka messages consumed", ["topic", "outcome"])


async def handle_event(message: MessageEnvelope) -> None:
    event = MonitoringEvent.model_validate(message.data)
    if filter_service.accept(event) and events.add(message.model_dump(mode="json")):
        consumed_total.labels(topic=EVENTS_TOPIC, outcome="accepted").inc()
    else:
        consumed_total.labels(topic=EVENTS_TOPIC, outcome="duplicate_or_filtered").inc()


async def handle_alert(message: MessageEnvelope) -> None:
    if alerts.add(message.model_dump(mode="json")):
        consumed_total.labels(topic=ALERTS_TOPIC, outcome="accepted").inc()
    else:
        consumed_total.labels(topic=ALERTS_TOPIC, outcome="duplicate").inc()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    event_consumer = KafkaTopicConsumer(
        KAFKA_BOOTSTRAP_SERVERS, EVENTS_TOPIC, f"{CONSUMER_GROUP}-events", handle_event
    )
    alert_consumer = KafkaTopicConsumer(
        KAFKA_BOOTSTRAP_SERVERS, ALERTS_TOPIC, f"{CONSUMER_GROUP}-alerts", handle_alert
    )
    try:
        await event_consumer.start()
        await alert_consumer.start()
    except Exception as error:
        # The read API must stay available while a producer/Kafka is restarting.
        await event_consumer.stop()
        await alert_consumer.stop()
        _app.state.kafka_status = f"unavailable: {error.__class__.__name__}"
        yield
        return
    _app.state.kafka_status = "connected"
    tasks = [asyncio.create_task(event_consumer.run()), asyncio.create_task(alert_consumer.run())]
    try:
        yield
    finally:
        for task in tasks:
            task.cancel()
        await event_consumer.stop()
        await alert_consumer.stop()


app = FastAPI(title="monitoring-platform", lifespan=lifespan)
Instrumentator().instrument(app).expose(app, endpoint="/metrics")


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.get("/v1/contours")
async def contours() -> dict:
    return {
        "integration": "Kafka consumers active; Zabbix and Prometheus adapters deferred",
        "filtering": "pass-through policy",
        "alerts": "Kafka alert projection active",
        "monitoring": "bounded in-memory read model; TimescaleDB deferred",
        "routing": "port reserved; no delivery adapter",
        "ai": "Kafka extension topics reserved; no worker required",
    }


@app.get("/v1/events")
async def list_events() -> list[dict]:
    return events.list()


@app.get("/v1/alerts")
async def list_alerts() -> list[dict]:
    return alerts.list()


@app.get("/")
async def landing() -> FileResponse:
    return FileResponse("app/static/index.html")
