"""Built-in enrichment plugin: identity transform, used as a no-op default."""

from collections.abc import Mapping
from typing import Any

from app.contracts.messages import MonitoringAlert
from app.plugins.ports import AlertEnricher, PluginMetadata


class IdentityEnricher:
    """Default enricher that returns the alert unchanged.

    Replace with real implementations by listing them in PLUGIN_PATHS.
    """

    metadata = PluginMetadata(
        name="identity-enricher",
        version="0.1.0",
        category="enrichment",
        description="Returns every alert unchanged; safe no-op default.",
    )

    async def enrich(self, alert: MonitoringAlert, context: Mapping[str, Any]) -> MonitoringAlert:
        return alert
