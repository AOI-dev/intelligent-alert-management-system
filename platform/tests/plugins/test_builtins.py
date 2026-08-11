"""Tests for built-in plugin defaults.

These assert the no-op defaults are safe and the example plugins behave as
documented. Real algorithm plugins will get their own test modules here.
"""
import pytest

from app.plugins.builtins.correlation import PassThroughCorrelator
from app.plugins.builtins.enrichment import IdentityEnricher
from app.plugins.builtins.execution import LoggingExecutor
from app.plugins.builtins.sources import KafkaSource
from app.plugins.engine import PluginEngine
from app.plugins.registry import PluginRegistry
from tests.plugins.fixtures import alert


@pytest.mark.asyncio
async def test_identity_enricher_returns_alert_unchanged():
    original = alert()
    enriched = await IdentityEnricher().enrich(original, {})
    assert enriched == original


@pytest.mark.asyncio
async def test_pass_through_correlator_returns_no_decisions():
    decisions = await PassThroughCorrelator().correlate("key", [alert()], {})
    assert decisions == []


@pytest.mark.asyncio
async def test_logging_executor_can_execute_any_decision():
    from app.contracts.messages import Decision

    decision = Decision(decision_type="route", alert_id=alert().alert_id, action="log", reason="test")
    assert await LoggingExecutor().can_execute(decision) is True


@pytest.mark.asyncio
async def test_kafka_source_example_is_inert():
    source = KafkaSource("localhost:9092", "events", "alerts")
    await source.open()
    events = [e async for e in source.events()]
    alerts = [a async for a in source.alerts()]
    await source.close()
    assert events == []
    assert alerts == []


@pytest.mark.asyncio
async def test_plugin_engine_with_empty_registry_is_pass_through():
    engine = PluginEngine(PluginRegistry.empty())
    decisions = await engine.process(alert())
    assert decisions == []
