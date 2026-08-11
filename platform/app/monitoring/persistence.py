"""Writes events/alerts/decisions into the TimescaleDB hypertables defined
in app/monitoring/models.py, and turns those tables into actual
hypertables (with retention) at startup.

Row-building is split out as pure functions (build_event_row etc.) so the
"which fields are known columns vs. extra JSONB" logic is testable without
a database. The actual DB calls are a thin, mostly-untested-by-necessity
layer on top -- see tests/test_monitoring_persistence.py for what is and
isn't covered without a live TimescaleDB.

Failures here are logged and swallowed, never raised into the caller: a
down or slow TimescaleDB must not block Kafka ingestion any more than a
down AI worker should (see app/plugins/engine.py's docstring for the same
principle applied to plugins) -- MessageStore's in-memory projection
already gives every consumer a working live view independent of this.
"""

import logging
import os
from datetime import datetime
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.monitoring.models import AlertLog, Base, DecisionLog, EventLog

logger = logging.getLogger(__name__)

EVENT_RETENTION_DAYS = int(os.environ.get("TIMESCALE_EVENT_RETENTION_DAYS", "90"))
ALERT_RETENTION_DAYS = int(os.environ.get("TIMESCALE_ALERT_RETENTION_DAYS", "90"))
# Decisions are the audit trail (АР-08: "журнал действий хранится не менее
# года" -- retained at least a year), so they default to a much longer
# window than the raw event/alert firehose.
DECISION_RETENTION_DAYS = int(os.environ.get("TIMESCALE_DECISION_RETENTION_DAYS", "400"))


def build_event_row(message_id: UUID, occurred_at: datetime, correlation_id: UUID, data: dict) -> EventLog:
    known = {"source", "status", "metric", "value", "event_id"}
    event_id = data.get("event_id")
    return EventLog(
        event_id=UUID(event_id) if event_id else message_id,
        occurred_at=occurred_at,
        correlation_id=correlation_id,
        source=data.get("source", "unknown"),
        status=data.get("status", "unknown"),
        metric=data.get("metric"),
        value=data.get("value"),
        extra={key: value for key, value in data.items() if key not in known},
    )


def build_alert_row(message_id: UUID, occurred_at: datetime, correlation_id: UUID, data: dict) -> AlertLog:
    known = {"rule", "severity", "source", "metric", "value", "threshold", "alert_id", "source_event_id"}
    alert_id = data.get("alert_id")
    source_event_id = data.get("source_event_id")
    return AlertLog(
        alert_id=UUID(alert_id) if alert_id else message_id,
        occurred_at=occurred_at,
        correlation_id=correlation_id,
        source_event_id=UUID(source_event_id) if source_event_id else None,
        rule=data.get("rule", "unknown"),
        severity=data.get("severity", "unknown"),
        source=data.get("source", "unknown"),
        metric=data.get("metric", "unknown"),
        value=float(data.get("value", 0.0)),
        threshold=float(data.get("threshold", 0.0)),
        extra={key: value for key, value in data.items() if key not in known},
    )


def build_decision_row(occurred_at: datetime, correlation_id: UUID, data: dict) -> DecisionLog:
    incident_id = data.get("incident_id")
    return DecisionLog(
        decision_id=UUID(data["decision_id"]),
        occurred_at=occurred_at,
        correlation_id=correlation_id,
        decision_type=data.get("decision_type", "unknown"),
        alert_id=UUID(data["alert_id"]),
        incident_id=UUID(incident_id) if incident_id else None,
        action=data.get("action", ""),
        reason=data.get("reason"),
        policy_id=data.get("policy_id"),
    )


async def log_event(session: AsyncSession, message_id: UUID, occurred_at: datetime, correlation_id: UUID, data: dict) -> None:
    try:
        session.add(build_event_row(message_id, occurred_at, correlation_id, data))
        await session.commit()
    except Exception:
        logger.exception("Failed to persist event %s to TimescaleDB", message_id)
        await session.rollback()


async def log_alert(session: AsyncSession, message_id: UUID, occurred_at: datetime, correlation_id: UUID, data: dict) -> None:
    try:
        session.add(build_alert_row(message_id, occurred_at, correlation_id, data))
        await session.commit()
    except Exception:
        logger.exception("Failed to persist alert %s to TimescaleDB", message_id)
        await session.rollback()


async def log_decision(session: AsyncSession, occurred_at: datetime, correlation_id: UUID, data: dict) -> None:
    try:
        session.add(build_decision_row(occurred_at, correlation_id, data))
        await session.commit()
    except Exception:
        logger.exception("Failed to persist decision %s to TimescaleDB", data.get("decision_id"))
        await session.rollback()


_HYPERTABLES = (
    ("event_log", EVENT_RETENTION_DAYS),
    ("alert_log", ALERT_RETENTION_DAYS),
    ("decision_log", DECISION_RETENTION_DAYS),
)


async def init_monitoring_models(engine: AsyncEngine) -> None:
    """Creates event_log/alert_log/decision_log if absent, converts each to
    a hypertable partitioned on occurred_at, and sets a retention policy.
    Safe to call every startup: every step is idempotent
    (if_not_exists/CREATE OR REPLACE-equivalent), matching identity/db.py's
    init_models() -- no migrations tool yet, by the same repo-wide choice.
    """
    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE"))
        await conn.run_sync(Base.metadata.create_all)
        for table, retention_days in _HYPERTABLES:
            await conn.execute(
                text(f"SELECT create_hypertable('{table}', 'occurred_at', if_not_exists => TRUE)")
            )
            try:
                await conn.execute(
                    text(
                        f"SELECT add_retention_policy('{table}', INTERVAL '{retention_days} days', "
                        "if_not_exists => TRUE)"
                    )
                )
            except Exception:
                logger.exception(
                    "Could not set a retention policy on %s -- continuing without one "
                    "(this TimescaleDB build/license may not support it)",
                    table,
                )
