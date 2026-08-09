from typing import Protocol

from app.contracts.messages import MonitoringEvent


class MonitoringSourceAdapter(Protocol):
    """Future Zabbix/Prometheus adapters normalize vendor payloads here."""

    async def receive(self) -> MonitoringEvent: ...
