"""Plugin extension points for the monitoring platform.

Implementations live in app/plugins/<category>/<name>.py and are discovered
via PluginRegistry. The core application never imports concrete plugins
directly; it only calls the abstract methods defined here.
"""

from app.plugins.ports import (
    AlertEnricher,
    AlertSource,
    Correlator,
    DecisionExecutor,
    MetricExporter,
    PluginMetadata,
)
from app.plugins.registry import PluginRegistry

__all__ = [
    "AlertEnricher",
    "AlertSource",
    "Correlator",
    "DecisionExecutor",
    "MetricExporter",
    "PluginMetadata",
    "PluginRegistry",
]
