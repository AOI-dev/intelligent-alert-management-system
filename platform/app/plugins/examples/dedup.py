"""Example correlator: suppress duplicate alerts with the same fingerprint.

This is intentionally simple. A production version would use a persistent
store (Redis/TimescaleDB) instead of an in-memory set.
"""

from collections.abc import Mapping, Sequence
from typing import Any

from app.contracts.messages import Decision, MonitoringAlert
from app.plugins.ports import Correlator, PluginMetadata


class FingerprintDedupCorrelator:
    """Suppress an alert if its fingerprint was seen recently."""

    metadata = PluginMetadata(
        name="fingerprint-dedup",
        version="0.1.0",
        category="correlation",
        description="Suppress duplicate alerts by fingerprint.",
    )

    def __init__(self, ttl_seconds: int = 300) -> None:
        self._ttl = ttl_seconds
        self._seen: dict[str, MonitoringAlert] = {}

    def _fingerprint(self, alert: MonitoringAlert) -> str:
        return f"{alert.source}:{alert.metric}:{alert.severity}"

    async def correlate(
        self,
        key: str,
        window: Sequence[MonitoringAlert],
        context: Mapping[str, Any],
    ) -> Sequence[Decision]:
        if not window:
            return []

        latest = window[-1]
        fp = self._fingerprint(latest)
        if fp in self._seen:
            return [
                Decision(
                    decision_type="suppress",
                    alert_id=latest.message_id,
                    reason=f"duplicate fingerprint {fp}",
                )
            ]

        self._seen[fp] = latest
        return []
