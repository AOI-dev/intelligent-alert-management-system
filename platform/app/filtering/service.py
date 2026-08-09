from app.contracts.messages import MonitoringEvent


class EventFilter:
    """Extension point for policy, storm suppression, and allow/deny decisions."""

    def accept(self, _event: MonitoringEvent) -> bool:
        return True
