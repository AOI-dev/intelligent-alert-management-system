"""Synthetic alerts for plugin algorithm tests."""
from uuid import uuid4

from app.contracts.messages import MonitoringAlert


def alert(
    rule: str = "cpu-high",
    severity: str = "critical",
    source: str = "zabbix",
    metric: str = "cpu",
    value: float = 99.0,
    labels: dict | None = None,
) -> MonitoringAlert:
    return MonitoringAlert(
        alert_id=uuid4(),
        rule=rule,
        severity=severity,
        source=source,
        metric=metric,
        value=value,
        threshold=90.0,
        labels=labels or {},
    )
