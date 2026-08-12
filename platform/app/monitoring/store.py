from collections import deque
from uuid import UUID


class MessageStore:
    """Bounded in-memory projection; TimescaleDB replaces it in a later contour.

    `id_field` names the field that identifies a record for deduplication.
    Envelope-wrapped records (events, alerts) carry `message_id`; decisions
    are stored flat and carry `decision_id` instead. Passing the wrong one is
    not a soft failure -- add() raises KeyError, and the Kafka consumer
    classifies that as a malformed message and drops it -- so the two shapes
    have to be told apart explicitly rather than guessed at.
    """

    def __init__(self, limit: int, id_field: str = "message_id"):
        self._id_field = id_field
        self._items: deque[dict] = deque(maxlen=limit)
        self._seen: deque[UUID] = deque(maxlen=limit * 2)
        self._seen_ids: set[UUID] = set()

    def add(self, message: dict) -> bool:
        message_id = message[self._id_field]
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
