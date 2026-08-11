"""Synthetic monitoring events for filter/classification tests."""
from datetime import datetime, timezone
from uuid import uuid4

from app.contracts.messages import MonitoringEvent


def monitoring_event(
    source: str = "zabbix",
    metric: str = "cpu",
    value: float = 95.0,
    labels: dict | None = None,
) -> MonitoringEvent:
    return MonitoringEvent(
        event_id=uuid4(),
        source=source,
        metric=metric,
        value=value,
        labels=labels or {},
    )


def normal_event() -> MonitoringEvent:
    """Healthy-looking event that should pass most filters."""
    return monitoring_event(source="prometheus", metric="cpu", value=45.0, labels={"env": "prod", "service": "api"})


def ignored_source_event() -> MonitoringEvent:
    """Event from a source on the deny-list."""
    return monitoring_event(source="staging-lab", metric="cpu", value=99.0, labels={"env": "dev"})


def maintenance_event() -> MonitoringEvent:
    """Event emitted during a scheduled maintenance window."""
    return monitoring_event(
        source="zabbix",
        metric="disk",
        value=98.0,
        labels={"maintenance": "true", "env": "prod"},
    )


def low_signal_event() -> MonitoringEvent:
    """Event below useful threshold."""
    return monitoring_event(source="prometheus", metric="memory", value=12.0, labels={"env": "prod"})


def noisy_probe_event() -> MonitoringEvent:
    """Frequent synthetic probe that should be throttled."""
    return monitoring_event(source="synthetic-probe", metric="heartbeat", value=1.0, labels={"probe": "true"})
