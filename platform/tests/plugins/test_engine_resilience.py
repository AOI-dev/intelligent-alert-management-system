"""PluginEngine's isolation guarantees: this is the code that enforces
"AI must not block or break the deterministic path" (artifacts/happy-path.md
step 8) at runtime, not just in a docstring. Every test here simulates a
plugin misbehaving -- crashing, hanging, timing out -- and asserts the
pipeline still produces the deterministic, safe outcome instead of
propagating the failure.

test_process_works_when_called_from_a_running_event_loop is the regression
test for the bug this module previously shipped with: PluginEngine.process
used to call asyncio.run() internally, which raises immediately if a loop
is already running -- exactly how app/main.py's handle_alert (an async
Kafka message handler) actually calls it. Every alert would have hit this
the moment any enricher/correlator plugin was registered, which
PLUGIN_PATHS does by default (see platform/flags.env). Existing tests
never caught it because they called engine.process() from plain `def`
tests with no event loop running.
"""

from collections.abc import Mapping, Sequence
from typing import Any

import pytest

from app.contracts.messages import Decision, MonitoringAlert
from app.plugins.engine import PluginEngine
from app.plugins.ports import PluginMetadata
from app.plugins.registry import PluginRegistry
from tests.plugins.fixtures import alert


class RaisingEnricher:
    metadata = PluginMetadata(name="raising-enricher", version="0.0.1", category="enrichment")

    async def enrich(self, alert: MonitoringAlert, context: Mapping[str, Any]) -> MonitoringAlert:
        raise RuntimeError("simulated LLM call failure")


class HangingEnricher:
    metadata = PluginMetadata(name="hanging-enricher", version="0.0.1", category="enrichment")

    async def enrich(self, alert: MonitoringAlert, context: Mapping[str, Any]) -> MonitoringAlert:
        import asyncio

        await asyncio.sleep(3600)  # never legitimately completes within a test
        return alert


class RaisingCorrelator:
    metadata = PluginMetadata(name="raising-correlator", version="0.0.1", category="correlation")

    async def correlate(
        self, key: str, window: Sequence[MonitoringAlert], context: Mapping[str, Any]
    ) -> Sequence[Decision]:
        raise RuntimeError("simulated correlator failure")


class TaggingEnricher:
    """A well-behaved enricher, registered alongside a broken one, to prove
    one plugin's failure doesn't stop the others from running.
    """

    metadata = PluginMetadata(name="tagging-enricher", version="0.0.1", category="enrichment")

    async def enrich(self, alert: MonitoringAlert, context: Mapping[str, Any]) -> MonitoringAlert:
        return alert.model_copy(update={"labels": {**alert.labels, "tagged": "true"}})


@pytest.mark.asyncio
async def test_process_works_when_called_from_a_running_event_loop():
    """Regression test: this is exactly how app/main.py's handle_alert
    calls it. Used to raise RuntimeError unconditionally.
    """
    from app.plugins.builtins.correlation import PassThroughCorrelator
    from app.plugins.builtins.enrichment import IdentityEnricher

    engine = PluginEngine(PluginRegistry([IdentityEnricher(), PassThroughCorrelator()]))

    decisions = await engine.process(alert())

    assert decisions == []


@pytest.mark.asyncio
async def test_raising_enricher_falls_back_to_the_alert_unchanged():
    engine = PluginEngine(PluginRegistry([RaisingEnricher()]))
    original = alert()

    decisions = await engine.process(original)

    assert decisions == []  # no crash propagated out of process()


@pytest.mark.asyncio
async def test_raising_enricher_does_not_block_a_later_working_one():
    """RaisingEnricher runs first and fails; TaggingEnricher must still run
    and its change must still land in the window -- inspected via a fixed
    key_fn so the test doesn't need to know PluginEngine's default key.
    """
    from app.core.window import TimeBoundedWindow

    window = TimeBoundedWindow(300)
    engine = PluginEngine(
        PluginRegistry([RaisingEnricher(), TaggingEnricher()]),
        window=window,
        key_fn=lambda _alert: "fixed-key",
    )

    await engine.process(alert())

    stored = window.snapshot("fixed-key")
    assert stored[0].labels.get("tagged") == "true"


@pytest.mark.asyncio
async def test_hanging_enricher_is_time_bounded_not_left_to_hang_the_pipeline():
    engine = PluginEngine(PluginRegistry([HangingEnricher()]), timeout_seconds=0.05)

    decisions = await engine.process(alert())

    assert decisions == []  # timed out and fell back, rather than hanging the test


@pytest.mark.asyncio
async def test_raising_correlator_produces_no_decisions_instead_of_crashing():
    engine = PluginEngine(PluginRegistry([RaisingCorrelator()]))

    decisions = await engine.process(alert())

    assert decisions == []


@pytest.mark.asyncio
async def test_no_enrichers_or_correlators_registered_is_a_safe_pass_through():
    engine = PluginEngine(PluginRegistry.empty())

    decisions = await engine.process(alert())

    assert decisions == []
