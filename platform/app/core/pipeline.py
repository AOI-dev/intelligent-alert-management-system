"""Orchestrates the alert core's two transformation stages (АР-03): a
per-alert stage, then a per-sequence stage over a rolling window. The
per-alert stage defaults to identity (classification/enrichment plugs in
there, same shape as EventFilter in app/filtering/service.py); the
per-sequence stage defaults to FlapAwareCorrelator
(app/core/correlation_automaton.py), the dedup/correlation/storm-suppression
policy the happy-path scenarios in tests/core/ specify.
"""
from collections.abc import Callable, Sequence

from app.contracts.messages import Decision, MonitoringAlert
from app.core.correlation_automaton import FlapAwareCorrelator
from app.core.ports import AlertTransform, SequenceTransform, SequenceWindow
from app.core.window import TimeBoundedWindow

DEFAULT_WINDOW_SECONDS = 300


class IdentityAlertTransform:
    """Extension point: classification/enrichment slots in here, in order."""

    def apply(self, alert: MonitoringAlert) -> MonitoringAlert:
        return alert


class PassThroughSequenceTransform:
    """Opt-out extension point: produces no decisions regardless of window
    contents. Available for callers that want to disable correlation
    entirely; CorrelationEngine itself defaults to FlapAwareCorrelator.
    """

    def apply(self, key: str, window: Sequence[MonitoringAlert]) -> list[Decision]:
        return []


def default_key(alert: MonitoringAlert) -> str:
    """Grouping key, in priority order: an explicit correlation_id label
    (the adapter/upstream vendor already knows these alerts are one
    incident), else the service label (alerts about the same service are
    presumed related), else (source, metric). Revisit once the broader
    correlation design (asset/CMDB-owner, ...) is settled; nothing
    downstream assumes this specific choice.
    """
    correlation_id = alert.labels.get("correlation_id")
    if correlation_id:
        return correlation_id
    service = alert.labels.get("service")
    if service:
        return service
    return f"{alert.source}:{alert.metric}"


class CorrelationEngine:
    def __init__(
        self,
        window: SequenceWindow | None = None,
        alert_transforms: list[AlertTransform] | None = None,
        sequence_transforms: list[SequenceTransform] | None = None,
        key_fn: Callable[[MonitoringAlert], str] = default_key,
    ) -> None:
        self._window = window if window is not None else TimeBoundedWindow(DEFAULT_WINDOW_SECONDS)
        self._alert_transforms = alert_transforms if alert_transforms is not None else [IdentityAlertTransform()]
        self._sequence_transforms = (
            sequence_transforms if sequence_transforms is not None else [FlapAwareCorrelator()]
        )
        self._key_fn = key_fn

    def process(self, alert: MonitoringAlert) -> list[Decision]:
        for transform in self._alert_transforms:
            alert = transform.apply(alert)

        key = self._key_fn(alert)
        window_contents = self._window.add(key, alert)

        decisions: list[Decision] = []
        for transform in self._sequence_transforms:
            decisions.extend(transform.apply(key, window_contents))
        return decisions
