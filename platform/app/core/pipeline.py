"""Orchestrates the alert core's two transformation stages (АР-03): a
per-alert stage, then a per-sequence stage over a rolling window. Defaults
are pass-through, same as EventFilter in app/filtering/service.py -- this
lays down the pipeline shape, not the dedup/correlation policy that will
eventually fill it in.
"""
from collections.abc import Callable, Sequence

from app.contracts.messages import Decision, MonitoringAlert
from app.core.ports import AlertTransform, SequenceTransform, SequenceWindow
from app.core.window import TimeBoundedWindow

DEFAULT_WINDOW_SECONDS = 300


class IdentityAlertTransform:
    """Extension point: classification/enrichment slots in here, in order."""

    def apply(self, alert: MonitoringAlert) -> MonitoringAlert:
        return alert


class PassThroughSequenceTransform:
    """Extension point: dedup/correlation/storm-suppression slots in here.
    Produces no decisions until a real policy is implemented.
    """

    def apply(self, _key: str, _window: Sequence[MonitoringAlert]) -> list[Decision]:
        return []


def default_key(alert: MonitoringAlert) -> str:
    """Placeholder grouping key -- (source, metric). Revisit once the
    correlation design (asset/service/CMDB-owner, correlation id, ...) is
    settled; nothing downstream assumes this specific choice.
    """
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
            sequence_transforms if sequence_transforms is not None else [PassThroughSequenceTransform()]
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
