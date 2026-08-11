"""TimescaleDB-backed history for events/alerts/decisions (АР-08).

Wired alongside, not instead of, MessageStore's in-memory live-tail cache
(app/monitoring/store.py, app/monitoring/query.py) -- this is the
persistent, range-queryable side of the split from that design
discussion: a bounded in-memory cache is right for "what's happening
now" (what a polling dashboard needs), wrong for time-range/audit queries
once retention needs exceed the live window, which is what this is for.

Each table mirrors its contract's minimal-vs-open shape: a handful of
known, indexed columns for what's actually used to filter (source,
severity, status, correlation_id), plus an `extra` JSONB column holding
the rest of the message body verbatim -- so MonitoringEvent's
extra="allow" openness (see app/contracts/messages.py) doesn't need a
schema migration to persist here too; a new field just rides along in
`extra` until/unless it earns a real column.

occurred_at is every table's hypertable partition column and part of a
composite primary key with the row's own id -- TimescaleDB requires the
partition column in any unique constraint, and (id, occurred_at) is
enough for that here since ids are already unique on their own.
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import DateTime, Float, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class EventLog(Base):
    __tablename__ = "event_log"

    event_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    correlation_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), index=True)
    source: Mapped[str] = mapped_column(String(255), index=True)
    status: Mapped[str] = mapped_column(String(64))
    metric: Mapped[str | None] = mapped_column(String(255), nullable=True)
    value: Mapped[float | None] = mapped_column(Float, nullable=True)
    extra: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)


class AlertLog(Base):
    __tablename__ = "alert_log"

    alert_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    correlation_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), index=True)
    source_event_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    rule: Mapped[str] = mapped_column(String(255))
    severity: Mapped[str] = mapped_column(String(16), index=True)
    source: Mapped[str] = mapped_column(String(255), index=True)
    metric: Mapped[str] = mapped_column(String(255))
    value: Mapped[float] = mapped_column(Float)
    threshold: Mapped[float] = mapped_column(Float)
    extra: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)


class DecisionLog(Base):
    __tablename__ = "decision_log"

    decision_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    correlation_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), index=True)
    decision_type: Mapped[str] = mapped_column(String(16), index=True)
    alert_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True))
    incident_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    action: Mapped[str] = mapped_column(String(255))
    reason: Mapped[str | None] = mapped_column(String, nullable=True)
    policy_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
