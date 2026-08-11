import asyncio
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from prometheus_client import Counter
from prometheus_fastapi_instrumentator import Instrumentator

from app.kafka_producer import MonitoringProducer
from app.models import Alert, EventIn
from app.protocol import MessageEnvelope
from app.rules import RULES, evaluate
from app.simulator import generate_synthetic_event

KAFKA_BOOTSTRAP_SERVERS = os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092")
EVENTS_TOPIC = os.environ.get("KAFKA_EVENTS_TOPIC", "monitoring.events.v1")
ALERTS_TOPIC = os.environ.get("KAFKA_ALERTS_TOPIC", "monitoring.alerts.v1")
AUTOGENERATE = os.environ.get("EVENTSIM_AUTOGENERATE", "false").lower() == "true"
AUTOGENERATE_INTERVAL = float(os.environ.get("EVENTSIM_AUTOGENERATE_INTERVAL", "10"))

events_total = Counter("eventsim_events_total", "Synthetic events ingested")
alerts_total = Counter("eventsim_alerts_total", "Alerts fired, by rule", ["rule", "severity"])

# Constructed in lifespan(), not here: aiokafka's AIOKafkaProducer requires a
# running event loop as of aiokafka 0.11, so building it at import time
# breaks any plain `import app.main` (a test, a REPL, `python -c`) with no
# loop running yet -- matches how platform/app/main.py and
# notifications/app/main.py already do this.
producer: MonitoringProducer | None = None


async def _autogenerate_loop() -> None:
    while True:
        await asyncio.sleep(AUTOGENERATE_INTERVAL)
        await ingest(generate_synthetic_event())


@asynccontextmanager
async def lifespan(_app: FastAPI):
    global producer
    producer = MonitoringProducer(KAFKA_BOOTSTRAP_SERVERS)
    await producer.start()
    autogen_task = asyncio.create_task(_autogenerate_loop()) if AUTOGENERATE else None
    try:
        yield
    finally:
        if autogen_task:
            autogen_task.cancel()
        await producer.stop()


app = FastAPI(title="eventsim", lifespan=lifespan)
Instrumentator().instrument(app).expose(app, endpoint="/metrics")


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.get("/rules")
async def list_rules() -> list[dict]:
    return [rule.__dict__ for rule in RULES]


@app.post("/events", response_model=list[Alert])
async def ingest(event: EventIn) -> list[Alert]:
    events_total.inc()
    await producer.publish(
        EVENTS_TOPIC,
        MessageEnvelope(
            message_type="monitoring.event",
            correlation_id=event.correlation_id,
            data=event.model_dump(mode="json"),
        ),
    )
    fired = evaluate(event)
    for alert in fired:
        alerts_total.labels(rule=alert.rule, severity=alert.severity).inc()
        await producer.publish(
            ALERTS_TOPIC,
            MessageEnvelope(
                message_type="monitoring.alert",
                correlation_id=event.correlation_id,
                data=alert.model_dump(mode="json"),
            ),
        )
    return fired
