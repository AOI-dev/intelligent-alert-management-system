"""Built-in source adapter: wraps the existing Kafka consumers as a plugin.

This is mainly an example. Real sources can poll HTTP APIs, subscribe to
message buses, expose webhooks, etc.
"""

from collections.abc import AsyncIterator, Mapping
from typing import Any

from app.contracts.messages import MonitoringAlert, MonitoringEvent
from app.plugins.ports import AlertSource, PluginMetadata


class KafkaSource:
    """Example source adapter demonstrating the AlertSource port.

    A production version would wrap aiokafka directly here instead of relying
    on the legacy KafkaTopicConsumer in app/integration.
    """

    metadata = PluginMetadata(
        name="kafka-source-example",
        version="0.1.0",
        category="source",
        description="Example source adapter; not wired by default.",
    )

    def __init__(self, bootstrap_servers: str, events_topic: str, alerts_topic: str) -> None:
        self._bootstrap = bootstrap_servers
        self._events_topic = events_topic
        self._alerts_topic = alerts_topic

    async def open(self) -> None:
        pass

    async def close(self) -> None:
        pass

    async def events(self) -> AsyncIterator[MonitoringEvent]:
        # Placeholder: real implementation would consume from Kafka here.
        if False:
            yield MonitoringEvent.model_validate({})

    async def alerts(self) -> AsyncIterator[MonitoringAlert]:
        # Placeholder: real implementation would consume from Kafka here.
        if False:
            yield MonitoringAlert.model_validate({})
