"""Suppresses redundant notifications: the same incident notifying the same
channel+address (webhook_url + target_id) again within a short window is
very likely the correlation engine re-emitting a route decision for an
incident that's still open (an escalation, a correlated addition -- see the
scenarios in platform/tests/core/oracle.py), not a genuinely new thing to
tell someone. Only successful deliveries start the window; a failed
delivery doesn't block a legitimate retry.
"""

import time
from collections.abc import Callable
from uuid import UUID

DedupKey = tuple[str, str, str]


class NotificationDeduplicator:
    def __init__(self, window_seconds: float, clock: Callable[[], float] = time.monotonic) -> None:
        self._window_seconds = window_seconds
        self._clock = clock
        self._last_delivered: dict[DedupKey, float] = {}

    def _key(self, incident_id: UUID, target_id: str, webhook_url: str) -> DedupKey:
        return (str(incident_id), target_id, webhook_url)

    def is_duplicate(self, incident_id: UUID, target_id: str, webhook_url: str) -> bool:
        last = self._last_delivered.get(self._key(incident_id, target_id, webhook_url))
        return last is not None and (self._clock() - last) < self._window_seconds

    def mark_delivered(self, incident_id: UUID, target_id: str, webhook_url: str) -> None:
        self._last_delivered[self._key(incident_id, target_id, webhook_url)] = self._clock()
