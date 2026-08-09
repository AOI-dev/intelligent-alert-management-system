from typing import Protocol

from app.contracts.messages import EnrichmentRequest, EnrichmentResult


class EnrichmentPublisher(Protocol):
    """Kafka-backed extension point for independently scalable AI workers."""

    async def publish(self, request: EnrichmentRequest) -> None: ...


class EnrichmentResultHandler(Protocol):
    """The core may merge a result only while its correlation is still relevant."""

    async def handle(self, result: EnrichmentResult) -> None: ...
