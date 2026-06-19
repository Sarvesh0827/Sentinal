from typing import AsyncGenerator, Protocol, Dict, List
import asyncio
from .config import settings

class Broker(Protocol):
    async def publish(self, topic: str, message: dict) -> None: ...
    async def subscribe(self, topic: str, group: str | None = None) -> AsyncGenerator[dict, None]: ...
    async def close(self) -> None: ...

class InMemoryBroker:
    def __init__(self):
        self._subscribers: Dict[str, List[asyncio.Queue]] = {}

    async def publish(self, topic: str, message: dict) -> None:
        if topic in self._subscribers:
            for q in self._subscribers[topic]:
                await q.put(message)

    async def subscribe(self, topic: str, group: str | None = None) -> AsyncGenerator[dict, None]:
        q = asyncio.Queue()
        if topic not in self._subscribers:
            self._subscribers[topic] = []
        self._subscribers[topic].append(q)
        try:
            while True:
                msg = await q.get()
                yield msg
        finally:
            self._subscribers[topic].remove(q)

    async def close(self) -> None:
        pass

import json

class KafkaBroker:
    def __init__(self):
        from aiokafka import AIOKafkaProducer
        self.bootstrap = settings.KAFKA_BOOTSTRAP
        self.producer = AIOKafkaProducer(bootstrap_servers=self.bootstrap)
        self.consumers = []
        self._producer_started = False

    async def publish(self, topic: str, message: dict) -> None:
        if not self._producer_started:
            await self.producer.start()
            self._producer_started = True
        payload = json.dumps(message).encode('utf-8')
        await self.producer.send_and_wait(topic, payload)

    async def subscribe(self, topic: str, group: str | None = None) -> AsyncGenerator[dict, None]:
        from aiokafka import AIOKafkaConsumer
        consumer = AIOKafkaConsumer(
            topic,
            bootstrap_servers=self.bootstrap,
            group_id=group,
            auto_offset_reset='latest'
        )
        await consumer.start()
        self.consumers.append(consumer)
        try:
            async for msg in consumer:
                yield json.loads(msg.value.decode('utf-8'))
        finally:
            await consumer.stop()

    async def close(self) -> None:
        if self._producer_started:
            await self.producer.stop()
        for c in self.consumers:
            await c.stop()

def make_broker() -> Broker:
    if settings.USE_KAFKA:
        return KafkaBroker()
    return InMemoryBroker()
