"""Example enricher: add a synthetic tag based on severity.

Demonstrates how to modify an alert without touching the core pipeline.
"""

from collections.abc import Mapping
from typing import Any

from app.contracts.messages import MonitoringAlert
from app.plugins.ports import AlertEnricher, PluginMetadata


class SeverityTagEnricher:
    """Adds a 'priority' tag inferred from the alert severity."""

    metadata = PluginMetadata(
        name="severity-tag-enricher",
        version="0.1.0",
        category="enrichment",
        description="Tags alerts with a priority derived from severity.",
    )

    async def enrich(self, alert: MonitoringAlert, context: Mapping[str, Any]) -> MonitoringAlert:
        priority = {"critical": "p1", "high": "p2", "warning": "p3"}.get(alert.severity, "p4")
        tags = dict(alert.tags or {})
        tags["priority"] = priority
        # Return a new alert instance; MonitoringAlert is immutable-ish via pydantic.
        return alert.model_copy(update={"tags": tags})
