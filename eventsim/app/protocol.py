from datetime import datetime, timezone
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class MessageEnvelope(BaseModel):
    schema_version: Literal["1.0"] = "1.0"
    message_id: UUID = Field(default_factory=uuid4)
    message_type: Literal["monitoring.event", "monitoring.alert"]
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    producer: str = "eventsim"
    correlation_id: UUID
    data: dict
