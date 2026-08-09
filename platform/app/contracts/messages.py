from datetime import datetime, timezone
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

SCHEMA_VERSION = "1.0"
EVENTS_TOPIC = "monitoring.events.v1"
ALERTS_TOPIC = "monitoring.alerts.v1"
AI_REQUESTS_TOPIC = "monitoring.ai.enrichment.v1"
AI_RESULTS_TOPIC = "monitoring.ai.results.v1"


class MonitoringEvent(BaseModel):
    event_id: UUID = Field(default_factory=uuid4)
    source: str
    metric: str
    value: float
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


class MessageEnvelope(BaseModel):
    schema_version: Literal["1.0"] = SCHEMA_VERSION
    message_id: UUID = Field(default_factory=uuid4)
    message_type: Literal["monitoring.event", "monitoring.alert", "ai.enrichment.request", "ai.enrichment.result"]
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
