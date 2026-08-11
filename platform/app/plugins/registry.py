"""Plugin discovery and lifecycle management.

Plugins are loaded from dotted Python paths configured in the environment.
A plugin is any object that exposes a `metadata: PluginMetadata` attribute
and implements one of the Protocols in app.plugins.ports.
"""

from __future__ import annotations

import importlib
import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from app.plugins.ports import (
    AlertEnricher,
    AlertSource,
    Correlator,
    DecisionExecutor,
    MetricExporter,
    PluginMetadata,
    WebhookAlertSource,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PluginBucket:
    """Typed collections of loaded plugins, grouped by capability."""

    sources: list[AlertSource] = field(default_factory=list)
    webhook_sources: list[WebhookAlertSource] = field(default_factory=list)
    enrichers: list[AlertEnricher] = field(default_factory=list)
    correlators: list[Correlator] = field(default_factory=list)
    executors: list[DecisionExecutor] = field(default_factory=list)
    exporters: list[MetricExporter] = field(default_factory=list)


class PluginRegistry:
    """Discovers and holds plugin instances.

    Usage:
        registry = PluginRegistry.from_env()
        for enricher in registry.enrichers:
            alert = await enricher.enrich(alert, context)
    """

    def __init__(self, plugins: Sequence[Any]) -> None:
        self._bucket = PluginBucket()
        self._webhook_by_slug: dict[str, WebhookAlertSource] = {}
        for plugin in plugins:
            self._register(plugin)

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None, extra: Sequence[Any] = ()) -> "PluginRegistry":
        """Load plugin paths from PLUGIN_PATHS (comma-separated dotted paths).

        `extra` seeds always-on builtins (e.g. the Alertmanager/Zabbix webhook
        adapters) ahead of anything PLUGIN_PATHS adds, so a misconfigured env
        var that reuses a builtin's webhook slug fails loudly at startup
        instead of silently shadowing it.

        Example:
            PLUGIN_PATHS=app.plugins.builtins.dedup,app.plugins.custom.ml_correlator
        """
        env = env or {}
        paths_str = env.get("PLUGIN_PATHS", "")
        paths = [p.strip() for p in paths_str.split(",") if p.strip()]
        plugins: list[Any] = list(extra)
        for path in paths:
            try:
                plugins.append(cls._load(path))
            except Exception:
                logger.exception("Failed to load plugin %s", path)
        return cls(plugins)

    @classmethod
    def empty(cls) -> "PluginRegistry":
        return cls([])

    @staticmethod
    def _load(dotted_path: str) -> Any:
        module_name, attr_name = dotted_path.rsplit(".", 1)
        module = importlib.import_module(module_name)
        factory = getattr(module, attr_name)
        # Support both class constructors and pre-built singletons.
        return factory() if callable(factory) else factory

    def _register(self, plugin: Any) -> None:
        meta: PluginMetadata | None = getattr(plugin, "metadata", None)
        if meta is None:
            logger.warning("Plugin %r has no metadata; skipping", plugin)
            return

        registered = False
        if isinstance(plugin, AlertSource):
            self._bucket.sources.append(plugin)
            registered = True
        if isinstance(plugin, WebhookAlertSource):
            claimant = self._webhook_by_slug.get(plugin.slug)
            if claimant is not None:
                raise ValueError(
                    f"Webhook slug '{plugin.slug}' is already claimed by "
                    f"{claimant.metadata.name}; {meta.name} cannot reuse it"
                )
            self._bucket.webhook_sources.append(plugin)
            self._webhook_by_slug[plugin.slug] = plugin
            registered = True
        if isinstance(plugin, AlertEnricher):
            self._bucket.enrichers.append(plugin)
            registered = True
        if isinstance(plugin, Correlator):
            self._bucket.correlators.append(plugin)
            registered = True
        if isinstance(plugin, DecisionExecutor):
            self._bucket.executors.append(plugin)
            registered = True
        if isinstance(plugin, MetricExporter):
            self._bucket.exporters.append(plugin)
            registered = True

        if registered:
            logger.info("Registered plugin %s v%s (%s)", meta.name, meta.version, meta.category)
        else:
            logger.warning("Plugin %s does not implement any known port", meta.name)

    @property
    def sources(self) -> Sequence[AlertSource]:
        return self._bucket.sources

    @property
    def webhook_sources(self) -> Sequence[WebhookAlertSource]:
        return self._bucket.webhook_sources

    def webhook_source(self, slug: str) -> WebhookAlertSource | None:
        return self._webhook_by_slug.get(slug)

    @property
    def enrichers(self) -> Sequence[AlertEnricher]:
        return self._bucket.enrichers

    @property
    def correlators(self) -> Sequence[Correlator]:
        return self._bucket.correlators

    @property
    def executors(self) -> Sequence[DecisionExecutor]:
        return self._bucket.executors

    @property
    def exporters(self) -> Sequence[MetricExporter]:
        return self._bucket.exporters

    @property
    def all_metadata(self) -> Sequence[PluginMetadata]:
        return [p.metadata for bucket in self._bucket.__dict__.values() for p in bucket]
