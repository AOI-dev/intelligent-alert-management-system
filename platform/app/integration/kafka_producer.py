import json

from aiokafka import AIOKafkaProducer

from app.contracts.messages import MessageEnvelope


class KafkaProducer:
    def __init__(self, bootstrap_servers: str):
        self._producer = AIOKafkaProducer(bootstrap_servers=bootstrap_servers)

    async def start(self) -> None:
        await self._producer.start()

    async def stop(self) -> None:
        await self._producer.stop()

    async def publish(self, topic: str, message: MessageEnvelope) -> None:
        await self._producer.send_and_wait(
            topic,
            key=str(message.message_id).encode(),
            value=json.dumps(message.model_dump(mode="json")).encode(),
        )
