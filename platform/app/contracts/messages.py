from datetime import datetime, timezone
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

SCHEMA_VERSION = "1.0"
EVENTS_TOPIC = "monitoring.events.v1"
ALERTS_TOPIC = "monitoring.alerts.v1"
AI_REQUESTS_TOPIC = "monitoring.ai.enrichment.v1"
AI_RESULTS_TOPIC = "monitoring.ai.results.v1"
INCIDENT_EVENTS_TOPIC = "monitoring.incident-events.v1"
DECISIONS_TOPIC = "monitoring.decisions.v1"
NOTIFICATION_REQUESTS_TOPIC = "monitoring.notification-requests.v1"
NOTIFICATION_RESULTS_TOPIC = "monitoring.notification-results.v1"


class MonitoringEvent(BaseModel):
    event_id: UUID = Field(default_factory=uuid4)
    source: str
    metric: str
    value: float
    labels: dict[str, str] = Field(default_factory=dict)


class MonitoringObservation(BaseModel):
    observation_id: UUID = Field(default_factory=uuid4)
    source: str
    metric: str
    value: float
    unit: str | None = None
    labels: dict[str, str] = Field(default_factory=dict)


class MonitoringAlert(BaseModel):
    alert_id: UUID = Field(default_factory=uuid4)
    rule: str
    severity: str
    source: str
    metric: str
    value: float
    threshold: float
    labels: dict[str, str] = Field(default_factory=dict)


class IncidentEvent(BaseModel):
    incident_id: UUID = Field(default_factory=uuid4)
    status: Literal["open", "updated", "resolved"]
    severity: str
    service: str | None = None
    labels: dict[str, str] = Field(default_factory=dict)
    alert_count: int = 1
    first_alert_id: UUID
    last_alert_id: UUID
    opened_at: datetime
    updated_at: datetime
    resolved_at: datetime | None = None


class Decision(BaseModel):
    decision_id: UUID = Field(default_factory=uuid4)
    decision_type: Literal["dedup", "route", "suppress"]
    alert_id: UUID
    incident_id: UUID | None = None
    action: str
    reason: str
    policy_id: str | None = None


class NotificationRequest(BaseModel):
    notification_id: UUID = Field(default_factory=uuid4)
    incident_id: UUID
    target_id: str
    webhook_url: str
    priority: str
    reason: str
    payload: dict = Field(default_factory=dict)


class NotificationResult(BaseModel):
    notification_id: UUID
    target_id: str
    outcome: Literal["delivered", "failed"]
    status_code: int | None = None
    error: str | None = None
    attempt: int = 1


class MessageEnvelope(BaseModel):
    schema_version: Literal["1.0"] = SCHEMA_VERSION
    message_id: UUID = Field(default_factory=uuid4)
    message_type: Literal[
        "monitoring.observation",
        "monitoring.event",
        "monitoring.alert",
        "ai.enrichment.request",
        "ai.enrichment.result",
        "incident.created",
        "incident.updated",
        "incident.resolved",
        "decision.dedup",
        "decision.route",
        "decision.suppress",
        "notification.requested",
        "notification.delivered",
        "notification.failed",
    ]
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    producer: str
    correlation_id: UUID
    data: dict


class EnrichmentRequest(BaseModel):
    alert: MonitoringAlert
    requested_capabilities: list[str]
    deadline_at: datetime
    feature_mode: Literal["off", "shadow", "suggest", "assisted"] = "suggest"


class EnrichmentResult(BaseModel):
    alert_id: UUID
    capability: str
    confidence: float = Field(ge=0, le=1)
    explanation: str
    model_name: str
    model_version: str
    recommendation: str | None = None
