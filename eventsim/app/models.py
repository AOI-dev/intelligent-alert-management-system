import time
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class EventIn(BaseModel):
    event_id: UUID = Field(default_factory=uuid4)
    correlation_id: UUID = Field(default_factory=uuid4)
    source: str
    metric: str
    value: float
    # platform's MonitoringEvent (app/contracts/messages.py) requires
    # status as of the Zabbix/Prometheus event-ingestion increment;
    # eventsim only ever simulates an active reading, so this is a fixed
    # default rather than something callers need to pass.
    status: str = "firing"
    labels: dict[str, str] = {}


class Alert(BaseModel):
    alert_id: UUID = Field(default_factory=uuid4)
    correlation_id: UUID
    rule: str
    severity: str
    source: str
    metric: str
    value: float
    threshold: float
    labels: dict[str, str] = {}
    timestamp: float = Field(default_factory=time.time)
