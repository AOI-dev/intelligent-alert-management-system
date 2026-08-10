"""Built-in correlation plugin: pass-through, used as a no-op default."""

from collections.abc import Mapping, Sequence
from typing import Any

from app.contracts.messages import Decision, MonitoringAlert
from app.plugins.ports import Correlator, PluginMetadata


class PassThroughCorrelator:
    """Default correlator that produces no decisions.

    Replace with real implementations by listing them in PLUGIN_PATHS.
    Multiple correlators run in order and their decisions are concatenated.
    """

    metadata = PluginMetadata(
        name="pass-through-correlator",
        version="0.1.0",
        category="correlation",
        description="Produces no decisions; placeholder for dedup/correlation algorithms.",
    )

    async def correlate(
        self,
        key: str,
        window: Sequence[MonitoringAlert],
        context: Mapping[str, Any],
    ) -> Sequence[Decision]:
        return []
