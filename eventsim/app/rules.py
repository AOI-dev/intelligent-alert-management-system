import operator
from dataclasses import dataclass

from app.models import Alert, EventIn

_OPS = {">": operator.gt, "<": operator.lt, ">=": operator.ge, "<=": operator.le}


@dataclass(frozen=True)
class Rule:
    name: str
    metric: str
    op: str
    threshold: float
    severity: str


# Dead-simple, hardcoded trigger set for the MVP. Once real monitoring-system
# API calls are wired up, this is where their alerting conditions get mapped.
RULES: list[Rule] = [
    Rule(name="high_cpu", metric="cpu_percent", op=">", threshold=90, severity="critical"),
    Rule(name="low_disk", metric="disk_free_percent", op="<", threshold=10, severity="warning"),
    Rule(name="high_latency", metric="latency_ms", op=">", threshold=500, severity="warning"),
]


def evaluate(event: EventIn) -> list[Alert]:
    fired = []
    for rule in RULES:
        if rule.metric != event.metric:
            continue
        if _OPS[rule.op](event.value, rule.threshold):
            fired.append(
                Alert(
                    correlation_id=event.correlation_id,
                    rule=rule.name,
                    severity=rule.severity,
                    source=event.source,
                    metric=event.metric,
                    value=event.value,
                    threshold=rule.threshold,
                    labels=event.labels,
                )
            )
    return fired
