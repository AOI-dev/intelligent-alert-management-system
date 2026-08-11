"""A generic rolling window: bounded, per-key alert history evicted by
wall-clock age. This is the mechanism the eventual dedup/correlation
algorithm will read from -- not that algorithm itself. Window size, the
grouping key, and tumbling/sliding/session semantics are placeholders here
and expected to change once that design is settled.
"""
import time
from collections import defaultdict, deque
from collections.abc import Callable, Sequence

from app.contracts.messages import MonitoringAlert


class TimeBoundedWindow:
    def __init__(self, window_seconds: float, now_fn: Callable[[], float] = time.monotonic) -> None:
        self._window_seconds = window_seconds
        self._now_fn = now_fn
        self._by_key: dict[str, deque[tuple[float, MonitoringAlert]]] = defaultdict(deque)

    def _evict_expired(self, key: str) -> None:
        cutoff = self._now_fn() - self._window_seconds
        bucket = self._by_key[key]
        while bucket and bucket[0][0] < cutoff:
            bucket.popleft()

    def add(self, key: str, alert: MonitoringAlert) -> Sequence[MonitoringAlert]:
        self._by_key[key].append((self._now_fn(), alert))
        self._evict_expired(key)
        return self.snapshot(key)

    def snapshot(self, key: str) -> Sequence[MonitoringAlert]:
        self._evict_expired(key)
        return [alert for _, alert in self._by_key[key]]
