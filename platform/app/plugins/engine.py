"""Polymorphic orchestration layer.

The engine consumes alerts from whatever sources are registered, runs them
through enrichers and correlators, and dispatches decisions to executors.
It does not branch on specific implementations; it only iterates over the
registry buckets.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping, Sequence
from typing import Any

from app.contracts.messages import Decision, MonitoringAlert, MonitoringEvent
from app.core.pipeline import CorrelationEngine
from app.core.ports import AlertTransform, SequenceTransform, SequenceWindow
from app.core.window import TimeBoundedWindow
from app.plugins.ports import AlertEnricher, AlertSource, Correlator, DecisionExecutor
from app.plugins.registry import PluginRegistry

logger = logging.getLogger(__name__)


class _EnricherAdapter(AlertTransform):
    """Wraps an AlertEnricher plugin so it fits the existing pipeline stage."""

    def __init__(self, enricher: AlertEnricher, context: Mapping[str, Any]) -> None:
        self._enricher = enricher
        self._context = context

    def apply(self, alert: MonitoringAlert) -> MonitoringAlert:
        # Synchronous adapter for the async enricher.
        return asyncio.run(self._enricher.enrich(alert, self._context))


class _CorrelatorAdapter(SequenceTransform):
    """Wraps a Correlator plugin so it fits the existing pipeline stage."""

    def __init__(self, correlator: Correlator, context: Mapping[str, Any]) -> None:
        self._correlator = correlator
        self._context = context

    def apply(self, key: str, window: Sequence[MonitoringAlert]) -> list[Decision]:
        return list(asyncio.run(self._correlator.correlate(key, window, self._context)))


class PluginEngine:
    """Runs the alert pipeline using whatever plugins are in the registry.

    The engine itself is stateless; the window is injected so different
    windowing strategies remain pluggable.
    """

    def __init__(
        self,
        registry: PluginRegistry,
        context: Mapping[str, Any] | None = None,
        window: SequenceWindow | None = None,
    ) -> None:
        self._registry = registry
        self._context = dict(context or {})
        self._window = window if window is not None else TimeBoundedWindow(300)

        alert_transforms = [
            _EnricherAdapter(e, self._context) for e in registry.enrichers
        ] or [_EnricherAdapter(_NoOpEnricher(), self._context)]

        sequence_transforms = [
            _CorrelatorAdapter(c, self._context) for c in registry.correlators
        ] or [_CorrelatorAdapter(_NoOpCorrelator(), self._context)]

        self._pipeline = CorrelationEngine(
            window=self._window,
            alert_transforms=alert_transforms,
            sequence_transforms=sequence_transforms,
        )

    def process(self, alert: MonitoringAlert) -> list[Decision]:
        return self._pipeline.process(alert)

    async def dispatch(self, decision: Decision) -> None:
        for executor in self._registry.executors:
            try:
                if await executor.can_execute(decision):
                    await executor.execute(decision, self._context)
            except Exception:
                logger.exception("Executor %s failed for decision %s", executor.metadata.name, decision.alert_id)

    async def run_source(self, source: AlertSource) -> None:
        await source.open()
        try:
            async for alert in source.alerts():
                for decision in self.process(alert):
                    await self.dispatch(decision)
        finally:
            await source.close()


class _NoOpEnricher(AlertEnricher):
    metadata = {"name": "noop-enricher", "version": "0.0.0", "category": "enrichment"}  # type: ignore[arg-type]

    async def enrich(self, alert: MonitoringAlert, context: Mapping[str, Any]) -> MonitoringAlert:
        return alert


class _NoOpCorrelator(Correlator):
    metadata = {"name": "noop-correlator", "version": "0.0.0", "category": "correlation"}  # type: ignore[arg-type]

    async def correlate(
        self, key: str, window: Sequence[MonitoringAlert], context: Mapping[str, Any]
    ) -> Sequence[Decision]:
        return []
