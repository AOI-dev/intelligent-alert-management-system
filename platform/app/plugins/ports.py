"""Abstract ports (protocols) for algorithm plugins.

Every extension point is defined as a Protocol so implementations can be
classes, dataclasses, or even plain objects, and so the core stays decoupled
from any concrete algorithm.
"""

from collections.abc import AsyncIterator, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable
from uuid import UUID

from app.contracts.messages import Decision, MonitoringAlert, MonitoringEvent


@dataclass(frozen=True)
class PluginMetadata:
    """Human-readable metadata for logging, UI, and capability negotiation."""

    name: str
    version: str
    category: str
    description: str = ""
    config_schema: dict[str, Any] | None = None


@dataclass(frozen=True)
class ParsedAlert:
    """One normalized alert extracted from a vendor webhook payload.

    message_id/correlation_id are pre-computed (usually stable hashes of
    vendor identifiers) so the entrance route stays agnostic of how each
    vendor names things; `data` is the raw dict handed to MonitoringAlert.
    """

    message_id: UUID
    correlation_id: UUID
    data: dict[str, Any]


@runtime_checkable
class AlertSource(Protocol):
    """Ingest alerts and events from an external system.

    Implementations poll, subscribe, or expose webhooks. The core pulls items
    from them via an async iterator and turns them into platform messages.
    """

    @property
    def metadata(self) -> PluginMetadata: ...

    async def open(self) -> None: ...
    async def close(self) -> None: ...

    async def events(self) -> AsyncIterator[MonitoringEvent]: ...
    async def alerts(self) -> AsyncIterator[MonitoringAlert]: ...


@runtime_checkable
class WebhookAlertSource(Protocol):
    """Adapter for monitoring systems that push alerts via HTTP webhook.

    Complements AlertSource (which pulls/subscribes) for vendors that call
    us instead of us calling them. `POST /v1/integrations/{slug}/webhook`
    dispatches by `slug` to whichever adapter claims it; the route itself
    never branches on vendor identity, so wildly different payload shapes
    (Alertmanager's `alerts[]`, Zabbix's flat `eventid` object, or anything
    a future vendor sends) are entirely the adapter's concern. Register a
    new one via PLUGIN_PATHS — no core code changes required.
    """

    @property
    def metadata(self) -> PluginMetadata: ...

    @property
    def slug(self) -> str: ...

    def parse(self, payload: Any) -> Sequence[ParsedAlert]:
        """Validate and normalize a raw JSON payload.

        Raise ValueError (with a message safe to show the caller) on a
        malformed payload; the entrance route turns that into HTTP 422.
        """
        ...


@runtime_checkable
class AlertEnricher(Protocol):
    """Add context to a single alert before it enters correlation.

    Examples: severity normalization, asset lookup, CMDB enrichment, ML
    classification. Each enricher runs in order; failures in one should not
    break the chain.
    """

    @property
    def metadata(self) -> PluginMetadata: ...

    async def enrich(self, alert: MonitoringAlert, context: Mapping[str, Any]) -> MonitoringAlert: ...


@runtime_checkable
class Correlator(Protocol):
    """Inspect a sequence/window of related alerts and produce decisions.

    Examples: deduplication, storm suppression, root-cause grouping, incident
    creation policy. A single alert may belong to multiple windows.
    """

    @property
    def metadata(self) -> PluginMetadata: ...

    async def correlate(
        self,
        key: str,
        window: Sequence[MonitoringAlert],
        context: Mapping[str, Any],
    ) -> Sequence[Decision]: ...


@runtime_checkable
class DecisionExecutor(Protocol):
    """Act on a decision produced by the correlation layer.

    Examples: route to PagerDuty, create Jira ticket, suppress in Zabbix,
    send Slack notification, trigger TrueConf emergency bridge.
    """

    @property
    def metadata(self) -> PluginMetadata: ...

    async def can_execute(self, decision: Decision) -> bool: ...

    async def execute(self, decision: Decision, context: Mapping[str, Any]) -> None: ...


@runtime_checkable
class MetricExporter(Protocol):
    """Expose internal metrics or status for a plugin category.

    Examples: Prometheus counters, health probes, per-algorithm telemetry.
    """

    @property
    def metadata(self) -> PluginMetadata: ...

    def collect(self) -> Mapping[str, Any]: ...
