import asyncio
import json
import logging
from collections.abc import Awaitable, Callable

from aiokafka import AIOKafkaConsumer
from pydantic import ValidationError

from app.contracts.messages import MessageEnvelope

logger = logging.getLogger(__name__)
MessageHandler = Callable[[MessageEnvelope], Awaitable[None]]


class KafkaTopicConsumer:
    def __init__(self, bootstrap_servers: str, topic: str, group_id: str, handler: MessageHandler):
        self._consumer = AIOKafkaConsumer(
            topic,
            bootstrap_servers=bootstrap_servers,
            group_id=group_id,
            auto_offset_reset="earliest",
            value_deserializer=lambda value: json.loads(value.decode()),
        )
        self._handler = handler

    async def start(self) -> None:
        await self._consumer.start()

    async def stop(self) -> None:
        await self._consumer.stop()

    async def run(self) -> None:
        try:
            async for message in self._consumer:
                try:
                    await self._handler(MessageEnvelope.model_validate(message.value))
                except (ValidationError, ValueError, KeyError) as error:
                    logger.warning("dropping malformed Kafka message: %s", error)
        except asyncio.CancelledError:
            raise
