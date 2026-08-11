"""Built-in correlation plugins: a no-op default, and an adapter exposing the
deterministic FlapAwareCorrelator policy through the plugin port."""

from collections.abc import Mapping, Sequence
from typing import Any

from app.contracts.messages import Decision, MonitoringAlert
from app.core.correlation_automaton import FlapAwareCorrelator
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


class FlapAwareCorrelatorPlugin:
    """Exposes app/core/correlation_automaton.py's policy on the plugin port.

    Without this, the two engines in app/main.py are not comparable: the
    legacy CorrelationEngine defaults to FlapAwareCorrelator and produces
    dedup/route/suppress decisions, while PluginEngine gets whatever
    PLUGIN_PATHS lists -- which is PassThroughCorrelator, i.e. nothing. Any
    measurement of "what the plugin pipeline decides" was therefore measuring
    an empty policy.

    The wrapped policy is a pure function of (key, window) with no I/O (see
    that module's docstring on replaying history rather than holding mutable
    state), so satisfying the async Correlator port needs no executor hop.
    """

    metadata = PluginMetadata(
        name="flap-aware-correlator",
        version="0.1.0",
        category="correlation",
        description="Dedup, cascade folding and flap suppression; the deterministic default policy.",
    )

    def __init__(self, policy: FlapAwareCorrelator | None = None) -> None:
        self._policy = policy or FlapAwareCorrelator()

    async def correlate(
        self,
        key: str,
        window: Sequence[MonitoringAlert],
        context: Mapping[str, Any],
    ) -> Sequence[Decision]:
        return self._policy.apply(key, window)
