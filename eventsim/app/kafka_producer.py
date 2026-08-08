import json

from aiokafka import AIOKafkaProducer

from app.models import Alert


class AlertProducer:
    def __init__(self, bootstrap_servers: str, topic: str):
        self._topic = topic
        self._producer = AIOKafkaProducer(
            bootstrap_servers=bootstrap_servers,
            value_serializer=lambda v: json.dumps(v).encode(),
        )

    async def start(self) -> None:
        await self._producer.start()

    async def stop(self) -> None:
        await self._producer.stop()

    async def publish(self, alert: Alert) -> None:
        await self._producer.send_and_wait(self._topic, value=alert.model_dump())
