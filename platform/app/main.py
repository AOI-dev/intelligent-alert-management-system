import asyncio
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Literal
from uuid import UUID, uuid4

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from prometheus_client import Counter
from prometheus_fastapi_instrumentator import Instrumentator

from app.ai.client import configured as ai_configured
from app.ai.service import EnrichmentService
from app.contracts.messages import (
    AI_REQUESTS_TOPIC,
    AI_RESULTS_TOPIC,
    Decision,
    EnrichmentRequest,
    EnrichmentResult,
    MessageEnvelope,
    MonitoringAlert,
    MonitoringEvent,
)
from app.core.pipeline import CorrelationEngine
from app.core.rate_limit import RateLimitMiddleware, RateLimitRule
from app.filtering.service import EventFilter
from app.plugins.builtins.webhooks import AlertmanagerWebhookSource, ZabbixWebhookSource
from app.plugins.engine import PluginEngine
from app.plugins.registry import PluginRegistry
from app.identity.db import SessionLocal, init_models
from app.identity.db import _engine as identity_engine
from app.identity.dependencies import require_role
from app.identity.models import Identity
from app.identity.repository import ensure_seed_roles
from app.identity.router import admin_router as identity_admin_router
from app.identity.router import router as identity_router
from app.integration.kafka_consumer import KafkaTopicConsumer
from app.integration.kafka_producer import KafkaProducer
from app.integration.normalizers import normalize_zabbix_problem, to_event_data
from app.integration.zabbix import ZabbixApiClient
from app.monitoring.persistence import init_monitoring_models, log_alert, log_decision, log_event
from app.monitoring.query import filter_messages, find_by_field, summarize
from app.monitoring.store import MessageStore

logger = logging.getLogger(__name__)
KAFKA_BOOTSTRAP_SERVERS = os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "eventsim-kafka:9092")
EVENTS_TOPIC = os.environ.get("KAFKA_EVENTS_TOPIC", "monitoring.events.v1")
ALERTS_TOPIC = os.environ.get("KAFKA_ALERTS_TOPIC", "monitoring.alerts.v1")
DECISIONS_TOPIC = os.environ.get("KAFKA_DECISIONS_TOPIC", "monitoring.decisions.v1")
CONSUMER_GROUP = os.environ.get("KAFKA_CONSUMER_GROUP", "platform-ingestion-v1")
HISTORY_LIMIT = int(os.environ.get("PLATFORM_HISTORY_LIMIT", "500"))
ZABBIX_API_URL = os.environ.get("ZABBIX_API_URL", "")
ZABBIX_API_TOKEN = os.environ.get("ZABBIX_API_TOKEN", "")
ZABBIX_RECONCILE_INTERVAL = int(os.environ.get("ZABBIX_RECONCILE_INTERVAL", "60"))
RATE_LIMIT_WEBHOOK_CAPACITY = float(os.environ.get("RATE_LIMIT_WEBHOOK_CAPACITY", "60"))
RATE_LIMIT_WEBHOOK_REFILL_PER_SECOND = float(os.environ.get("RATE_LIMIT_WEBHOOK_REFILL_PER_SECOND", "5"))
RATE_LIMIT_API_CAPACITY = float(os.environ.get("RATE_LIMIT_API_CAPACITY", "120"))
RATE_LIMIT_API_REFILL_PER_SECOND = float(os.environ.get("RATE_LIMIT_API_REFILL_PER_SECOND", "20"))
# AI enrichment is off unless explicitly enabled (see flags.env): the rest of
# the pipeline must be provably correct on its own before a model's output is
# allowed anywhere near it.
AI_ENRICHMENT_MODE = os.environ.get("AI_ENRICHMENT_MODE", "off")
AI_ENRICHMENT_TIMEOUT = float(os.environ.get("AI_ENRICHMENT_TIMEOUT_SECONDS", "30"))

filter_service = EventFilter()
plugin_registry = PluginRegistry.from_env(
    dict(os.environ), extra=[AlertmanagerWebhookSource(), ZabbixWebhookSource()]
)
plugin_engine = PluginEngine(plugin_registry)
correlation_engine = CorrelationEngine()
enrichment_service = EnrichmentService()
events = MessageStore(HISTORY_LIMIT)
alerts = MessageStore(HISTORY_LIMIT)
decisions = MessageStore(HISTORY_LIMIT)
consumed_total = Counter("platform_kafka_messages_total", "Kafka messages consumed", ["topic", "outcome"])
produced_total = Counter("platform_kafka_published_total", "Kafka messages published", ["topic", "source"])
webhooks_total = Counter("platform_webhooks_total", "Monitoring webhooks received", ["source", "outcome"])
zabbix_reconcile_total = Counter("platform_zabbix_reconcile_total", "Zabbix reconciliation results", ["outcome"])
decisions_total = Counter("platform_core_decisions_total", "Decisions produced by the alert core", ["decision_type"])


async def handle_event(message: MessageEnvelope) -> None:
    event = MonitoringEvent.model_validate(message.data)
    if filter_service.accept(event) and events.add(message.model_dump(mode="json")):
        consumed_total.labels(topic=EVENTS_TOPIC, outcome="accepted").inc()
        async with SessionLocal() as session:
            await log_event(session, message.message_id, message.occurred_at, message.correlation_id, message.data)
    else:
        consumed_total.labels(topic=EVENTS_TOPIC, outcome="duplicate_or_filtered").inc()


async def handle_alert(message: MessageEnvelope) -> None:
    if not alerts.add(message.model_dump(mode="json")):
        consumed_total.labels(topic=ALERTS_TOPIC, outcome="duplicate").inc()
        return
    consumed_total.labels(topic=ALERTS_TOPIC, outcome="accepted").inc()
    async with SessionLocal() as session:
        await log_alert(session, message.message_id, message.occurred_at, message.correlation_id, message.data)

    alert = MonitoringAlert.model_validate(message.data)
    for decision in await plugin_engine.process(alert):
        await publish_decision(decision, message.correlation_id)
    # Legacy pipeline kept available until plugin engine is fully validated.
    for decision in correlation_engine.process(alert):
        await publish_decision(decision, message.correlation_id)
    if AI_ENRICHMENT_MODE != "off":
        asyncio.create_task(enrich_alert(alert, message.correlation_id))


async def enrich_alert(alert: MonitoringAlert, correlation_id: UUID) -> None:
    """Fire-and-forget AI enrichment for one accepted alert.

    Runs detached from handle_alert: the deterministic path (store,
    correlate, decide) has already completed before this starts, and a slow
    or dead model must never back-pressure alert consumption. The request
    envelope is published to AI_REQUESTS_TOPIC so the job is auditable and
    a future horizontally scalable worker group can take it over without a
    contract change (the in-process call below is the current worker);
    results land on AI_RESULTS_TOPIC. On any model failure the service
    returns a valid fallback result (confidence 0.0, explanation naming the
    failure), which is published as-is rather than retried — the deadline
    has already passed for this alert by then.
    """
    producer: KafkaProducer | None = app.state.producer
    if producer is None:
        return
    request = EnrichmentRequest(
        alert=alert,
        requested_capabilities=["classification", "priority", "root_cause"],
        deadline_at=datetime.now(timezone.utc) + timedelta(seconds=AI_ENRICHMENT_TIMEOUT),
        feature_mode=AI_ENRICHMENT_MODE,
    )
    await producer.publish(
        AI_REQUESTS_TOPIC,
        MessageEnvelope(
            message_type="ai.enrichment.request",
            producer="platform-core",
            correlation_id=correlation_id,
            data=request.model_dump(mode="json"),
        ),
    )
    produced_total.labels(topic=AI_REQUESTS_TOPIC, source="platform-core").inc()

    try:
        results = await asyncio.wait_for(enrichment_service.enrich(request), timeout=AI_ENRICHMENT_TIMEOUT)
    except Exception as exc:
        # enrich() is contract-bound never to raise (it returns fallback
        # results on model failure), so reaching here means something
        # unexpected — a timeout, a bug. Publish the same fallback shape so
        # results-topic consumers always see one result per capability per
        # request, rather than a silent gap.
        logger.exception("enrichment failed unexpectedly for alert %s", alert.alert_id)
        results = [
            EnrichmentResult(
                alert_id=alert.alert_id,
                capability=capability,
                confidence=0.0,
                explanation=f"enrichment failed unexpectedly: {exc.__class__.__name__}",
                model_name="unavailable",
                model_version="0",
            )
            for capability in request.requested_capabilities
        ]
    for result in results:
        await producer.publish(
            AI_RESULTS_TOPIC,
            MessageEnvelope(
                message_type="ai.enrichment.result",
                producer="platform-ai",
                correlation_id=correlation_id,
                data=result.model_dump(mode="json"),
            ),
        )
        produced_total.labels(topic=AI_RESULTS_TOPIC, source="platform-ai").inc()


DECISION_MESSAGE_TYPES: dict[str, Literal["decision.dedup", "decision.route", "decision.suppress"]] = {
    "dedup": "decision.dedup",
    "route": "decision.route",
    "suppress": "decision.suppress",
}


async def publish_decision(decision: Decision, correlation_id: UUID) -> None:
    decisions.add(decision.model_dump(mode="json"))
    decisions_total.labels(decision_type=decision.decision_type).inc()
    async with SessionLocal() as session:
        await log_decision(session, datetime.now(timezone.utc), correlation_id, decision.model_dump(mode="json"))
    producer: KafkaProducer | None = app.state.producer
    if producer is None:
        return
    await producer.publish(
        DECISIONS_TOPIC,
        MessageEnvelope(
            message_type=DECISION_MESSAGE_TYPES[decision.decision_type],
            producer="platform-core",
            correlation_id=correlation_id,
            data=decision.model_dump(mode="json"),
        ),
    )
    produced_total.labels(topic=DECISIONS_TOPIC, source="platform-core").inc()


async def publish_alert(producer: KafkaProducer, message_id: UUID, correlation_id: UUID, data: dict, source: str) -> None:
    """`data` should already carry `source_event_id` -- see publish_event's
    docstring for why message_id doubles as that link.
    """
    await producer.publish(
        ALERTS_TOPIC,
        MessageEnvelope(
            message_id=message_id,
            message_type="monitoring.alert",
            occurred_at=datetime.now(timezone.utc),
            producer=source,
            correlation_id=correlation_id,
            data={**data, "source_event_id": str(message_id)},
        ),
    )
    produced_total.labels(topic=ALERTS_TOPIC, source=source).inc()


async def publish_event(producer: KafkaProducer, message_id: UUID, correlation_id: UUID, alert_data: dict, source: str) -> None:
    """Publish the raw event corresponding to an already-normalized alert
    (see to_event_data) -- every alert from a real vendor gets a matching
    event on EVENTS_TOPIC, not just synthetic ones from eventsim.

    Reuses `message_id` -- already a stable hash of the vendor's own
    occurrence identity (see normalize_*'s stable_id calls) -- as both this
    Kafka message's id and the event's own `event_id`, so publish_alert can
    set the same value as the alert's `source_event_id` without any lookup:
    both sides derive it from the same source data, independently.
    """
    event_data = to_event_data(alert_data)
    event_data.setdefault("event_id", str(message_id))
    await producer.publish(
        EVENTS_TOPIC,
        MessageEnvelope(
            message_id=message_id,
            message_type="monitoring.event",
            occurred_at=datetime.now(timezone.utc),
            producer=source,
            correlation_id=correlation_id,
            data=event_data,
        ),
    )
    produced_total.labels(topic=EVENTS_TOPIC, source=source).inc()


async def reconcile_zabbix(producer: KafkaProducer) -> None:
    if not (ZABBIX_API_URL and ZABBIX_API_TOKEN):
        return
    client = ZabbixApiClient(ZABBIX_API_URL, ZABBIX_API_TOKEN)
    try:
        for problem in await client.open_problems():
            message_id, correlation_id, data = normalize_zabbix_problem(problem)
            await publish_event(producer, message_id, correlation_id, data, "zabbix-api")
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
    try:
        await init_models()
        async with SessionLocal() as session:
            await ensure_seed_roles(session)
        app.state.identity_status = "connected"
    except Exception as error:
        logger.exception("Identity database unavailable")
        app.state.identity_status = f"unavailable: {error.__class__.__name__}"

    # Separate status/try-except from identity above: this is a distinct
    # concern (hypertable/extension setup can fail independently of plain
    # table creation, e.g. against a non-Timescale Postgres) and a failure
    # here must not get misreported as an identity DB problem.
    try:
        await init_monitoring_models(identity_engine)
        app.state.monitoring_db_status = "connected"
    except Exception as error:
        logger.exception("Monitoring TimescaleDB projection unavailable")
        app.state.monitoring_db_status = f"unavailable: {error.__class__.__name__}"

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
app.add_middleware(
    RateLimitMiddleware,
    rules=[
        # Webhooks are unauthenticated, machine-to-machine, and bursty by
        # nature (a storm at the monitored system means a storm here too) —
        # narrower prefix, stricter budget. /health and /metrics match no
        # rule and stay unlimited.
        RateLimitRule(
            prefix="/v1/integrations",
            capacity=RATE_LIMIT_WEBHOOK_CAPACITY,
            refill_per_second=RATE_LIMIT_WEBHOOK_REFILL_PER_SECOND,
        ),
        RateLimitRule(
            prefix="/v1",
            capacity=RATE_LIMIT_API_CAPACITY,
            refill_per_second=RATE_LIMIT_API_REFILL_PER_SECOND,
        ),
    ],
)
Instrumentator().instrument(app).expose(app, endpoint="/metrics")
app.include_router(identity_router)
app.include_router(identity_admin_router)

ANY_AUTHENTICATED_ROLE = require_role("viewer", "engineer", "admin")


def oauth_is_configured() -> bool:
    """Frontend-visible readiness check. Never expose credential values; the
    browser only needs to know whether its login link can be actionable."""
    return all(
        os.environ.get(name)
        for name in (
            "TRUECONF_BASE_URL",
            "TRUECONF_OAUTH_CLIENT_ID",
            "TRUECONF_OAUTH_CLIENT_SECRET",
            "TRUECONF_OAUTH_REDIRECT_URI",
        )
    )


@app.get("/health")
async def health() -> dict:
    return {
        "status": "ok",
        "kafka": app.state.kafka_status,
        "identity_db": app.state.identity_status,
        "monitoring_db": app.state.monitoring_db_status,
        "auth": "configured" if oauth_is_configured() else "not_configured",
    }


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
        "core": "rolling-window pipeline wired to live alerts; FlapAwareCorrelator dedups/correlates/suppresses (app/core/correlation_automaton.py)",
        "plugins": [m.name for m in plugin_registry.all_metadata],
        "monitoring": f"bounded in-memory live-tail read model; TimescaleDB history projection ({app.state.monitoring_db_status})",
        "routing": "port reserved; no delivery adapter",
        "ai": (
            f"EnrichmentService (app/ai/): mode={AI_ENRICHMENT_MODE}, vLLM "
            f"{'configured' if ai_configured() else 'not configured'}; enrichment is "
            "fire-and-forget off the alert path — results on monitoring.ai.results.v1"
        ),
        "identity": f"TrueConf OAuth2 + role table ({app.state.identity_status})",
    }


@app.get("/v1/events")
async def list_events(
    source: str | None = None,
    status: str | None = None,
    since: datetime | None = None,
    _: Identity = Depends(ANY_AUTHENTICATED_ROLE),
) -> list[dict]:
    return filter_messages(events.list(), since, source=source, status=status)


@app.get("/v1/alerts")
async def list_alerts(
    severity: str | None = None,
    source: str | None = None,
    since: datetime | None = None,
    _: Identity = Depends(ANY_AUTHENTICATED_ROLE),
) -> list[dict]:
    return filter_messages(alerts.list(), since, severity=severity, source=source)


@app.get("/v1/alerts/{alert_id}")
async def get_alert(alert_id: UUID, _: Identity = Depends(ANY_AUTHENTICATED_ROLE)) -> dict:
    found = find_by_field(alerts.list(), "alert_id", str(alert_id))
    if found is None:
        raise HTTPException(status_code=404, detail="alert not found in the retained window")
    return found


@app.get("/v1/summary")
async def summary(_: Identity = Depends(ANY_AUTHENTICATED_ROLE)) -> dict:
    return summarize(len(events.list()), alerts.list(), decisions.list(), HISTORY_LIMIT)


@app.get("/v1/decisions")
async def list_decisions(
    decision_type: str | None = None,
    _: Identity = Depends(ANY_AUTHENTICATED_ROLE),
) -> list[dict]:
    return filter_messages(decisions.list(), None, decision_type=decision_type)


INCIDENTS_NOT_IMPLEMENTED = (
    "incidents are not implemented yet -- monitoring.incident-events.v1 is a defined "
    "contract that nothing publishes to; see README's Incidents section. This is a "
    "stub returning 501 on purpose, not an empty result set standing in for 'no "
    "incidents' -- those are different things and conflating them would be a lie."
)


@app.get("/v1/incidents")
async def list_incidents(_: Identity = Depends(ANY_AUTHENTICATED_ROLE)) -> list[dict]:
    raise HTTPException(status_code=501, detail=INCIDENTS_NOT_IMPLEMENTED)


@app.get("/v1/incidents/{incident_id}")
async def get_incident(incident_id: UUID, _: Identity = Depends(ANY_AUTHENTICATED_ROLE)) -> dict:
    raise HTTPException(status_code=501, detail=INCIDENTS_NOT_IMPLEMENTED)


@app.post("/v1/incidents/{incident_id}/ack")
async def acknowledge_incident(incident_id: UUID, _: Identity = Depends(ANY_AUTHENTICATED_ROLE)) -> dict:
    raise HTTPException(status_code=501, detail=INCIDENTS_NOT_IMPLEMENTED)


async def _require_producer() -> KafkaProducer:
    producer: KafkaProducer | None = app.state.producer
    if producer is None:
        raise HTTPException(status_code=503, detail="Kafka producer unavailable")
    return producer


@app.post("/v1/integrations/{slug}/webhook", status_code=202)
async def integration_webhook(slug: str, request: Request) -> dict:
    """Dispatch a vendor webhook to whichever WebhookAlertSource claims `slug`.

    Adding a monitoring client with a different payload shape means writing
    a new adapter (see app/plugins/ports.py:WebhookAlertSource) and pointing
    PLUGIN_PATHS at it — this route does not change.
    """
    source = plugin_registry.webhook_source(slug)
    if source is None:
        raise HTTPException(status_code=404, detail=f"No webhook adapter registered for '{slug}'")
    producer = await _require_producer()
    payload = await request.json()
    try:
        parsed = source.parse(payload)
    except ValueError as error:
        webhooks_total.labels(source=slug, outcome="invalid").inc()
        raise HTTPException(status_code=422, detail=str(error)) from error
    for item in parsed:
        await publish_event(producer, item.message_id, item.correlation_id, item.data, slug)
        await publish_alert(producer, item.message_id, item.correlation_id, item.data, slug)
    webhooks_total.labels(source=slug, outcome="accepted").inc()
    return {"accepted": len(parsed)}


@app.get("/")
async def landing() -> FileResponse:
    return FileResponse("app/static/index.html")
