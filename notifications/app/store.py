from collections import deque
from uuid import UUID


class MessageStore:
    """Bounded in-memory projection of recent notification results."""

    def __init__(self, limit: int):
        self._items: deque[dict] = deque(maxlen=limit)
        self._seen: deque[UUID] = deque(maxlen=limit * 2)
        self._seen_ids: set[UUID] = set()

    def add(self, message: dict) -> bool:
        message_id = message["message_id"]
        if message_id in self._seen_ids:
            return False
        if len(self._seen) == self._seen.maxlen:
            self._seen_ids.remove(self._seen.popleft())
        self._seen.append(message_id)
        self._seen_ids.add(message_id)
        self._items.appendleft(message)
        return True

    def list(self) -> list[dict]:
        return list(self._items)
