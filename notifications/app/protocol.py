from datetime import datetime, timezone
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

SCHEMA_VERSION = "1.0"
NOTIFICATION_REQUESTS_TOPIC = "monitoring.notification-requests.v1"
NOTIFICATION_RESULTS_TOPIC = "monitoring.notification-results.v1"


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
        "notification.requested",
        "notification.delivered",
        "notification.failed",
    ]
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    producer: str
    correlation_id: UUID
    data: dict
