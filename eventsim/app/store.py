from collections import deque


class AlertStore:
    """Ring buffer of the most recent alerts, newest first, for the viewer page."""

    def __init__(self, maxlen: int = 200):
        self._items: deque[dict] = deque(maxlen=maxlen)

    def add(self, alert: dict) -> None:
        self._items.appendleft(alert)

    def list(self) -> list[dict]:
        return list(self._items)
