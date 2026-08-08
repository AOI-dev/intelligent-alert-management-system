import random

from app.models import EventIn
from app.rules import RULES

_SOURCES = ["web-01", "web-02", "db-01", "worker-03"]


def generate_synthetic_event() -> EventIn:
    """Random event over one of the known rule metrics.

    Occasionally exceeds its threshold so autogenerate mode has something to
    fire triggers on without a real monitoring system feeding it yet.
    """
    rule = random.choice(RULES)
    breach = random.random() < 0.2
    if breach:
        value = rule.threshold * (1.2 if rule.op in (">", ">=") else 0.5)
    else:
        value = rule.threshold * (0.5 if rule.op in (">", ">=") else 1.5)
    return EventIn(source=random.choice(_SOURCES), metric=rule.metric, value=round(value, 2))
