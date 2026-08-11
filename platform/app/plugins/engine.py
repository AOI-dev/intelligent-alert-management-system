"""Polymorphic orchestration layer.

The engine consumes alerts from whatever sources are registered, runs them
through enrichers and correlators, and dispatches decisions to executors.
It does not branch on specific implementations; it only iterates over the
registry buckets.

Enrichment and correlation plugins are async (see app/plugins/ports.py --
an AI-backed enricher calling out to vLLM is exactly the case these ports
exist for). That's the whole reason PluginEngine doesn't reuse
CorrelationEngine (app/core/pipeline.py) as its execution engine even
though the shape looks similar: CorrelationEngine's AlertTransform/
SequenceTransform are deliberately synchronous, so bridging an async
plugin into them meant asyncio.run()-ing a coroutine from inside
PluginEngine.process() -- which crashes outright the moment process() is
itself called from a running event loop, exactly how app/main.py's
handle_alert (an async Kafka message handler) actually calls it. Every
alert would have hit this the moment any enricher/correlator plugin was
registered (PLUGIN_PATHS ships IdentityEnricher/PassThroughCorrelator by
default -- see platform/flags.env).

Fixed by making PluginEngine's own pipeline natively async end to end, and
-- since a plugin here may be an AI call subject to the same "AI must not
block or break the deterministic path" requirement as
app/ai/ (artifacts/happy-path.md step 8) -- every plugin call is time-
bounded and failure-isolated: a slow or raising enricher/correlator/
executor degrades to a safe default (the alert unchanged; no decisions;
skip this executor) and is logged, never propagated. One plugin's timeout
or bug can't take down ingestion for every other alert the way the
asyncio.run() bug could.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from app.contracts.messages import Decision, MonitoringAlert
from app.core.pipeline import default_key
from app.core.ports import SequenceWindow
from app.core.window import TimeBoundedWindow
from app.plugins.ports import AlertSource, PluginMetadata
from app.plugins.registry import PluginRegistry

logger = logging.getLogger(__name__)

DEFAULT_PLUGIN_TIMEOUT_SECONDS = 5.0


class PluginEngine:
    """Runs the alert pipeline using whatever plugins are in the registry.

    The engine itself is stateless; the window is injected so different
    windowing strategies remain pluggable. No enrichers/correlators
    registered is a valid, safe state -- the alert passes through
    unchanged and no decisions are produced -- so no NoOp placeholders are
    needed to represent it.
    """

    def __init__(
        self,
        registry: PluginRegistry,
        context: Mapping[str, Any] | None = None,
        window: SequenceWindow | None = None,
        key_fn: Callable[[MonitoringAlert], str] = default_key,
        timeout_seconds: float = DEFAULT_PLUGIN_TIMEOUT_SECONDS,
    ) -> None:
        self._registry = registry
        self._context = dict(context or {})
        self._window = window if window is not None else TimeBoundedWindow(300)
        self._key_fn = key_fn
        self._timeout_seconds = timeout_seconds

    async def _call(self, metadata: PluginMetadata, coro) -> Any:
        """Runs one plugin call under the shared timeout/failure isolation.
        Returns None on timeout or exception -- callers treat None as
        "this plugin contributed nothing this time", the safe default.
        """
        try:
            return await asyncio.wait_for(coro, timeout=self._timeout_seconds)
        except TimeoutError:
            logger.warning("Plugin %s timed out after %.1fs; skipping it", metadata.name, self._timeout_seconds)
        except Exception:
            logger.exception("Plugin %s failed; skipping it", metadata.name)
        return None

    async def _enrich(self, alert: MonitoringAlert) -> MonitoringAlert:
        for enricher in self._registry.enrichers:
            enriched = await self._call(enricher.metadata, enricher.enrich(alert, self._context))
            if enriched is not None:
                alert = enriched
        return alert

    async def _correlate(self, key: str, window: Sequence[MonitoringAlert]) -> list[Decision]:
        decisions: list[Decision] = []
        for correlator in self._registry.correlators:
            result = await self._call(correlator.metadata, correlator.correlate(key, window, self._context))
            if result:
                decisions.extend(result)
        return decisions

    async def process(self, alert: MonitoringAlert) -> list[Decision]:
        alert = await self._enrich(alert)
        key = self._key_fn(alert)
        window_contents = self._window.add(key, alert)
        return await self._correlate(key, window_contents)

    async def dispatch(self, decision: Decision) -> None:
        for executor in self._registry.executors:
            can_execute = await self._call(executor.metadata, executor.can_execute(decision))
            if can_execute:
                await self._call(executor.metadata, executor.execute(decision, self._context))

    async def run_source(self, source: AlertSource) -> None:
        await source.open()
        try:
            async for alert in source.alerts():
                for decision in await self.process(alert):
                    await self.dispatch(decision)
        finally:
            await source.close()
