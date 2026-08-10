import asyncio
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from uuid import UUID, uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from prometheus_client import Counter
from prometheus_fastapi_instrumentator import Instrumentator

from app.contracts.messages import MessageEnvelope, MonitoringEvent
from app.filtering.service import EventFilter
from app.integration.kafka_consumer import KafkaTopicConsumer
from app.integration.kafka_producer import KafkaProducer
from app.integration.normalizers import normalize_alertmanager, normalize_zabbix_problem
from app.integration.zabbix import ZabbixApiClient
from app.monitoring.store import MessageStore

logger = logging.getLogger(__name__)
KAFKA_BOOTSTRAP_SERVERS = os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "eventsim-kafka:9092")
EVENTS_TOPIC = os.environ.get("KAFKA_EVENTS_TOPIC", "monitoring.events.v1")
ALERTS_TOPIC = os.environ.get("KAFKA_ALERTS_TOPIC", "monitoring.alerts.v1")
CONSUMER_GROUP = os.environ.get("KAFKA_CONSUMER_GROUP", "platform-ingestion-v1")
HISTORY_LIMIT = int(os.environ.get("PLATFORM_HISTORY_LIMIT", "500"))
ZABBIX_API_URL = os.environ.get("ZABBIX_API_URL", "")
ZABBIX_API_TOKEN = os.environ.get("ZABBIX_API_TOKEN", "")
ZABBIX_RECONCILE_INTERVAL = int(os.environ.get("ZABBIX_RECONCILE_INTERVAL", "60"))

filter_service = EventFilter()
events = MessageStore(HISTORY_LIMIT)
alerts = MessageStore(HISTORY_LIMIT)
consumed_total = Counter("platform_kafka_messages_total", "Kafka messages consumed", ["topic", "outcome"])
produced_total = Counter("platform_kafka_published_total", "Kafka messages published", ["topic", "source"])
webhooks_total = Counter("platform_webhooks_total", "Monitoring webhooks received", ["source", "outcome"])
zabbix_reconcile_total = Counter("platform_zabbix_reconcile_total", "Zabbix reconciliation results", ["outcome"])


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


async def publish_alert(producer: KafkaProducer, message_id: UUID, correlation_id: UUID, data: dict, source: str) -> None:
    await producer.publish(
        ALERTS_TOPIC,
        MessageEnvelope(
            message_id=message_id,
            message_type="monitoring.alert",
            occurred_at=datetime.now(timezone.utc),
            producer=source,
            correlation_id=correlation_id,
            data=data,
        ),
    )
    produced_total.labels(topic=ALERTS_TOPIC, source=source).inc()


async def reconcile_zabbix(producer: KafkaProducer) -> None:
    if not (ZABBIX_API_URL and ZABBIX_API_TOKEN):
        return
    client = ZabbixApiClient(ZABBIX_API_URL, ZABBIX_API_TOKEN)
    try:
        for problem in await client.open_problems():
            message_id, correlation_id, data = normalize_zabbix_problem(problem)
            await publish_alert(producer, message_id, correlation_id, data, "zabbix-api")
        zabbix_reconcile_total.labels(outcome="success").inc()
    except Exception:
        logger.exception("Zabbix problem reconciliation failed")
        zabbix_reconcile_total.labels(outcome="failure").inc()


async def zabbix_reconcile_loop(producer: KafkaProducer) -> None:
    while True:
        await reconcile_zabbix(producer)
        await asyncio.sleep(ZABBIX_RECONCILE_INTERVAL)


@asynccontextmanager
async def lifespan(app: FastAPI):
    producer = KafkaProducer(KAFKA_BOOTSTRAP_SERVERS)
    event_consumer = KafkaTopicConsumer(
        KAFKA_BOOTSTRAP_SERVERS, EVENTS_TOPIC, f"{CONSUMER_GROUP}-events", handle_event
    )
    alert_consumer = KafkaTopicConsumer(
        KAFKA_BOOTSTRAP_SERVERS, ALERTS_TOPIC, f"{CONSUMER_GROUP}-alerts", handle_alert
    )
    try:
        await producer.start()
        await event_consumer.start()
        await alert_consumer.start()
    except Exception as error:
        await producer.stop()
        await event_consumer.stop()
        await alert_consumer.stop()
        app.state.kafka_status = f"unavailable: {error.__class__.__name__}"
        app.state.producer = None
        yield
        return
    app.state.kafka_status = "connected"
    app.state.producer = producer
    tasks = [
        asyncio.create_task(event_consumer.run()),
        asyncio.create_task(alert_consumer.run()),
    ]
    if ZABBIX_API_URL and ZABBIX_API_TOKEN:
        tasks.append(asyncio.create_task(zabbix_reconcile_loop(producer)))
    try:
        yield
    finally:
        for task in tasks:
            task.cancel()
        await producer.stop()
        await event_consumer.stop()
        await alert_consumer.stop()


app = FastAPI(title="monitoring-platform", lifespan=lifespan)
Instrumentator().instrument(app).expose(app, endpoint="/metrics")


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "kafka": app.state.kafka_status}


@app.get("/v1/contours")
async def contours() -> dict:
    return {
        "integration": {
            "kafka": app.state.kafka_status,
            "alertmanager_webhook": "active",
            "zabbix_api_reconciliation": "active" if ZABBIX_API_TOKEN else "awaiting_token",
            "prometheus_api": "deferred; Alertmanager owns alert lifecycle",
        },
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


async def _require_producer() -> KafkaProducer:
    producer: KafkaProducer | None = app.state.producer
    if producer is None:
        raise HTTPException(status_code=503, detail="Kafka producer unavailable")
    return producer


@app.post("/v1/integrations/alertmanager/webhook", status_code=202)
async def alertmanager_webhook(request: Request) -> dict:
    producer = await _require_producer()
    payload = await request.json()
    alert_items = payload.get("alerts")
    if not isinstance(alert_items, list):
        webhooks_total.labels(source="alertmanager", outcome="invalid").inc()
        raise HTTPException(status_code=422, detail="Alertmanager payload must contain alerts[]")
    for alert in alert_items:
        message_id, correlation_id, data = normalize_alertmanager(alert)
        await publish_alert(producer, message_id, correlation_id, data, "alertmanager")
    webhooks_total.labels(source="alertmanager", outcome="accepted").inc()
    return {"accepted": len(alert_items)}


@app.post("/v1/integrations/zabbix/webhook", status_code=202)
async def zabbix_webhook(request: Request) -> dict:
    """Accept the explicit Zabbix action-webhook payload documented in README."""
    producer = await _require_producer()
    payload = await request.json()
    if not isinstance(payload.get("eventid"), (str, int)):
        webhooks_total.labels(source="zabbix", outcome="invalid").inc()
        raise HTTPException(status_code=422, detail="Zabbix payload must contain eventid")
    message_id, correlation_id, data = normalize_zabbix_problem(payload)
    await publish_alert(producer, message_id, correlation_id, data, "zabbix-webhook")
    webhooks_total.labels(source="zabbix", outcome="accepted").inc()
    return {"accepted": 1}


@app.get("/")
async def landing() -> FileResponse:
    return FileResponse("app/static/index.html")
