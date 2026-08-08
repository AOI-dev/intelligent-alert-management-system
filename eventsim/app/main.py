import asyncio
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import FileResponse
from prometheus_client import Counter
from prometheus_fastapi_instrumentator import Instrumentator

from app.kafka_consumer import AlertConsumer
from app.kafka_producer import AlertProducer
from app.models import Alert, EventIn
from app.rules import RULES, evaluate
from app.simulator import generate_synthetic_event
from app.store import AlertStore

KAFKA_BOOTSTRAP_SERVERS = os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092")
KAFKA_TOPIC = os.environ.get("KAFKA_TOPIC", "alerts")
KAFKA_CONSUMER_GROUP = os.environ.get("KAFKA_CONSUMER_GROUP", "eventsim-viewer")
AUTOGENERATE = os.environ.get("EVENTSIM_AUTOGENERATE", "false").lower() == "true"
AUTOGENERATE_INTERVAL = float(os.environ.get("EVENTSIM_AUTOGENERATE_INTERVAL", "10"))

events_total = Counter("eventsim_events_total", "Synthetic events ingested")
alerts_total = Counter("eventsim_alerts_total", "Alerts fired, by rule", ["rule", "severity"])

producer = AlertProducer(KAFKA_BOOTSTRAP_SERVERS, KAFKA_TOPIC)
store = AlertStore()
consumer = AlertConsumer(KAFKA_BOOTSTRAP_SERVERS, KAFKA_TOPIC, KAFKA_CONSUMER_GROUP, store)


async def _autogenerate_loop() -> None:
    while True:
        await asyncio.sleep(AUTOGENERATE_INTERVAL)
        await ingest(generate_synthetic_event())


@asynccontextmanager
async def lifespan(_app: FastAPI):
    await producer.start()
    await consumer.start()
    consumer_task = asyncio.create_task(consumer.run())
    autogen_task = asyncio.create_task(_autogenerate_loop()) if AUTOGENERATE else None
    try:
        yield
    finally:
        if autogen_task:
            autogen_task.cancel()
        consumer_task.cancel()
        await producer.stop()
        await consumer.stop()


app = FastAPI(title="eventsim", lifespan=lifespan)
Instrumentator().instrument(app).expose(app, endpoint="/metrics")


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.get("/rules")
async def list_rules() -> list[dict]:
    return [r.__dict__ for r in RULES]


@app.get("/alerts")
async def list_alerts() -> list[dict]:
    return store.list()


@app.get("/")
async def viewer() -> FileResponse:
    return FileResponse("app/static/index.html")


@app.post("/events", response_model=list[Alert])
async def ingest(event: EventIn) -> list[Alert]:
    events_total.inc()
    fired = evaluate(event)
    for alert in fired:
        alerts_total.labels(rule=alert.rule, severity=alert.severity).inc()
        await producer.publish(alert)
    return fired
