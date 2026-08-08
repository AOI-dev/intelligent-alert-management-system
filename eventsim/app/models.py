import time

from pydantic import BaseModel, Field


class EventIn(BaseModel):
    source: str
    metric: str
    value: float
    labels: dict[str, str] = {}


class Alert(BaseModel):
    rule: str
    severity: str
    source: str
    metric: str
    value: float
    threshold: float
    labels: dict[str, str] = {}
    timestamp: float = Field(default_factory=time.time)
