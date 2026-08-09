from typing import Protocol


class NotificationProvider(Protocol):
    """Delivery integration boundary; no provider is attached in this increment."""

    async def deliver(self, recipient: str, payload: dict) -> None: ...
