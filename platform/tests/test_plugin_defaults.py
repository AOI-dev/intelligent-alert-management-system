"""Pins the PLUGIN_PATHS default in flags.env against the code it names.

PLUGIN_PATHS is a comma-separated list of dotted paths resolved at runtime,
and PluginRegistry.from_env logs-and-continues when one fails to load. A
renamed or mistyped plugin therefore degrades silently to "that extension
point does nothing" -- which is exactly how PassThroughCorrelator ended up
being the deployed correlation policy while the real one sat unused.
"""
import asyncio
from pathlib import Path

from app.contracts.messages import MonitoringAlert
from app.core.correlation_automaton import FlapAwareCorrelator
from app.plugins.registry import PluginRegistry

FLAGS = Path(__file__).resolve().parents[1] / "flags.env"


def _plugin_paths_from_flags() -> str:
    for line in FLAGS.read_text().splitlines():
        if line.startswith("PLUGIN_PATHS="):
            return line.split("=", 1)[1]
    raise AssertionError("PLUGIN_PATHS is not set in flags.env")


def _alert(**overrides) -> MonitoringAlert:
    fields: dict = dict(
        rule="high_cpu", severity="critical", source="db-01",
        metric="cpu_percent", value=97.0, threshold=90.0,
        labels={"service": "db_primary"},
    )
    fields.update(overrides)
    return MonitoringAlert(**fields)


def test_every_plugin_named_in_flags_env_actually_loads():
    paths = _plugin_paths_from_flags()
    registry = PluginRegistry.from_env({"PLUGIN_PATHS": paths})
    expected = len([p for p in paths.split(",") if p.strip()])
    assert len(registry.all_metadata) == expected, (
        f"PLUGIN_PATHS names {expected} plugins but only "
        f"{len(registry.all_metadata)} loaded: {[m.name for m in registry.all_metadata]}"
    )


def test_default_correlator_is_the_real_policy_not_the_placeholder():
    """The deployed default must decide something. A pass-through here means
    PluginEngine produces no decisions at all."""
    registry = PluginRegistry.from_env({"PLUGIN_PATHS": _plugin_paths_from_flags()})
    names = [c.metadata.name for c in registry.correlators]
    assert names == ["flap-aware-correlator"], names


def test_plugin_correlator_matches_the_policy_it_wraps():
    """The plugin adapter must not diverge from app/core/correlation_automaton.py
    -- the core tests pin that module, and this is what actually runs."""
    registry = PluginRegistry.from_env({"PLUGIN_PATHS": _plugin_paths_from_flags()})
    plugin = registry.correlators[0]
    window = [_alert(), _alert()]  # identical repeat -> dedup

    via_plugin = asyncio.run(plugin.correlate("db_primary", window, {}))
    direct = FlapAwareCorrelator().apply("db_primary", window)

    assert [(d.decision_type, d.action, d.policy_id) for d in via_plugin] == [
        (d.decision_type, d.action, d.policy_id) for d in direct
    ]
    assert [d.decision_type for d in via_plugin] == ["dedup"]
