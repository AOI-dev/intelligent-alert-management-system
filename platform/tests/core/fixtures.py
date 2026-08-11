"""Synthetic alert sequences for correlation/detection tests."""
from collections.abc import Callable
from uuid import UUID, uuid4

from app.contracts.messages import MonitoringAlert


class FakeClock:
    def __init__(self, start: float = 0.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def make_alert(
    rule: str = "cpu-high",
    severity: str = "critical",
    source: str = "zabbix",
    metric: str = "cpu",
    value: float = 99.0,
    threshold: float = 90.0,
    labels: dict | None = None,
    alert_id: UUID | None = None,
) -> MonitoringAlert:
    return MonitoringAlert(
        alert_id=alert_id or uuid4(),
        rule=rule,
        severity=severity,
        source=source,
        metric=metric,
        value=value,
        threshold=threshold,
        labels=labels or {},
    )


def make_sequence(
    count: int,
    factory: Callable[[int], MonitoringAlert],
) -> list[MonitoringAlert]:
    return [factory(i) for i in range(count)]


def duplicate_storm(count: int = 10) -> list[MonitoringAlert]:
    """Identical alerts that should collapse into one incident."""
    base = make_alert(rule="disk-full", severity="critical", source="zabbix", metric="disk", value=98.0)
    return [base.model_copy(update={"alert_id": uuid4()}) for _ in range(count)]


def correlated_cascade() -> list[MonitoringAlert]:
    """Three related alerts from the same service chain."""
    base_labels = {"service": "payments", "correlation_id": "cascade-1"}
    return [
        make_alert(rule="db-latency", severity="critical", source="zabbix", metric="db_latency", value=2.5, labels=base_labels),
        make_alert(rule="api-errors", severity="high", source="prometheus", metric="api_5xx_rate", value=12.0, labels=base_labels),
        make_alert(rule="frontend-errors", severity="high", source="prometheus", metric="frontend_error_rate", value=7.0, labels=base_labels),
    ]


def severity_escalation() -> list[MonitoringAlert]:
    """Same symptom, severity increases over time."""
    base = make_alert(rule="memory-pressure", source="zabbix", metric="memory", value=92.0)
    return [
        base.model_copy(update={"alert_id": uuid4(), "severity": "warning"}),
        base.model_copy(update={"alert_id": uuid4(), "severity": "high"}),
        base.model_copy(update={"alert_id": uuid4(), "severity": "critical"}),
    ]


def flapping_alerts() -> list[MonitoringAlert]:
    """Rapidly toggling alert that should be suppressed."""
    base = make_alert(rule="service-up", source="zabbix", metric="up", value=1.0)
    return [
        base.model_copy(update={"alert_id": uuid4(), "severity": "critical"}),
        base.model_copy(update={"alert_id": uuid4(), "severity": "resolved"}),
        base.model_copy(update={"alert_id": uuid4(), "severity": "critical"}),
        base.model_copy(update={"alert_id": uuid4(), "severity": "resolved"}),
    ]


def multi_tenant_noise() -> list[MonitoringAlert]:
    """Unrelated services firing at the same time; each keeps its own incident."""
    return [
        make_alert(rule="cpu-high", source="zabbix", metric="cpu", value=99.0, labels={"service": "payments"}),
        make_alert(rule="cpu-high", source="zabbix", metric="cpu", value=98.0, labels={"service": "auth"}),
        make_alert(rule="disk-full", source="zabbix", metric="disk", value=97.0, labels={"service": "warehouse"}),
    ]
