"""Extension points for the alert core (АР-03/АР-04): a per-alert stage
followed by a per-sequence stage over a rolling window of recent alerts.

What "recent" means -- window size, eviction policy, the key that groups
alerts into one sequence, tumbling vs. sliding vs. session semantics -- is
NOT decided here. That's real, disputed design work belonging to a later
increment. This module only fixes the shape transforms plug into, so that
work can land without reshaping the pipeline around it.
"""
from collections.abc import Sequence
from typing import Protocol

from app.contracts.messages import Decision, MonitoringAlert


class AlertTransform(Protocol):
    """Per-alert stage: classification, enrichment, normalization beyond
    the ingestion adapter. Runs once per alert, before it joins any window.
    """

    def apply(self, alert: MonitoringAlert) -> MonitoringAlert: ...


class SequenceWindow(Protocol):
    """Rolling view over the incoming alert flow, keyed by whatever the
    caller decides groups alerts into one sequence (service, asset,
    rule+source, correlation id, ...). Implementations own sizing and
    eviction; callers only see what currently belongs to a key.
    """

    def add(self, key: str, alert: MonitoringAlert) -> Sequence[MonitoringAlert]:
        """Record `alert` under `key` and return the key's current contents."""
        ...

    def snapshot(self, key: str) -> Sequence[MonitoringAlert]: ...


class SequenceTransform(Protocol):
    """Per-sequence stage: dedup, correlation, storm suppression -- anything
    that needs to see everything the window currently holds for one key,
    not just the latest alert. The concrete algorithm is out of scope here;
    this is only the seam it plugs into.
    """

    def apply(self, key: str, window: Sequence[MonitoringAlert]) -> list[Decision]: ...
