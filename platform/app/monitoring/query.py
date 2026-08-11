"""Pure query/filter helpers over MessageStore's bounded live-window
projection (see app/monitoring/store.py). Kept separate from app/main.py's
route handlers so they're directly unit-testable without FastAPI, auth, or
Kafka in the loop.

Items come in two shapes from MessageStore.list(): envelope-wrapped
(events/alerts -- {"data": {...}, "occurred_at": ..., ...}) and flat
(decisions, stored as the object itself with no envelope). Every helper
here handles both via `item.get("data", item)`.
"""

from datetime import datetime
from typing import Any


def filter_messages(items: list[dict], since: datetime | None = None, **data_filters: str | None) -> list[dict]:
    """Keep items with occurred_at >= since (when given) and matching every
    non-None field in data_filters, case-insensitively, against `data`.
    """
    active_filters = {field: value for field, value in data_filters.items() if value is not None}

    def matches(item: dict) -> bool:
        if since is not None:
            occurred_at = item.get("occurred_at")
            if occurred_at is None or datetime.fromisoformat(occurred_at) < since:
                return False
        data = item.get("data", item)
        return all(str(data.get(field, "")).lower() == value.lower() for field, value in active_filters.items())

    return [item for item in items if matches(item)]


def find_by_field(items: list[dict], field: str, value: str) -> dict | None:
    """First item whose `data` (or the item itself) has field == value."""
    for item in items:
        data = item.get("data", item)
        if str(data.get(field, "")) == value:
            return item
    return None


def summarize(events_count: int, alert_items: list[dict], decision_items: list[dict], window_limit: int) -> dict[str, Any]:
    severity_counts: dict[str, int] = {}
    for item in alert_items:
        severity = item.get("data", {}).get("severity", "unknown")
        severity_counts[severity] = severity_counts.get(severity, 0) + 1

    decision_counts: dict[str, int] = {}
    for item in decision_items:
        decision_type = item.get("data", item).get("decision_type", "unknown")
        decision_counts[decision_type] = decision_counts.get(decision_type, 0) + 1

    return {
        "events_in_window": events_count,
        "alerts_in_window": len(alert_items),
        "alerts_by_severity": severity_counts,
        "decisions_by_type": decision_counts,
        "window_limit": window_limit,
    }
