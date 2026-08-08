import json

from aiokafka import AIOKafkaConsumer

from app.store import AlertStore


class AlertConsumer:
    def __init__(self, bootstrap_servers: str, topic: str, group_id: str, store: AlertStore):
        self._consumer = AIOKafkaConsumer(
            topic,
            bootstrap_servers=bootstrap_servers,
            group_id=group_id,
            auto_offset_reset="earliest",
            value_deserializer=lambda v: json.loads(v.decode()),
        )
        self._store = store

    async def start(self) -> None:
        await self._consumer.start()

    async def stop(self) -> None:
        await self._consumer.stop()

    async def run(self) -> None:
        async for msg in self._consumer:
            self._store.add(msg.value)
