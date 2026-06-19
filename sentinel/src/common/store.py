import redis.asyncio as redis
from typing import Protocol, List, Dict, Optional
from collections import deque
from datetime import datetime, timezone
import time
from .config import settings

class Store(Protocol):
    async def append_window(self, tenant_id: str, agent_id: str, event: dict) -> None: ...
    async def get_window(self, tenant_id: str, agent_id: str, horizon_s: float) -> list[dict]: ...
    async def get_all_agent_ids(self, tenant_id: str) -> list[str]: ...
    async def freeze(self, tenant_id: str, agent_id: str, reason: list[str]) -> None: ...
    async def unfreeze(self, tenant_id: str, agent_id: str) -> None: ...
    async def is_frozen(self, tenant_id: str, agent_id: str) -> bool: ...
    async def frozen_agents(self, tenant_id: str) -> dict[str, list[str]]: ...
    async def get_trust_score(self, tenant_id: str, agent_id: str) -> float: ...
    async def set_trust_score(self, tenant_id: str, agent_id: str, score: float) -> None: ...
    async def append_ledger(self, tenant_id: str, entry: dict) -> None: ...
    async def get_ledger(self, tenant_id: str) -> list[dict]: ...
    async def get_webhook_url(self, tenant_id: str) -> Optional[str]: ...
    async def set_webhook_url(self, tenant_id: str, url: str) -> None: ...

class InMemoryStore:
    def __init__(self):
        self._windows: Dict[str, deque[dict]] = {}
        self._frozen: Dict[str, List[str]] = {}
        self._trust_scores: Dict[str, float] = {}
        self._ledger: Dict[str, List[dict]] = {}
        self._webhooks: Dict[str, str] = {}

    def _parse_ts(self, ts_str: str) -> float:
        if ts_str.endswith("Z"):
            ts_str = ts_str[:-1] + "+00:00"
        return datetime.fromisoformat(ts_str).timestamp()

    def _key(self, tenant_id: str, agent_id: str) -> str:
        return f"{tenant_id}:{agent_id}"

    async def append_window(self, tenant_id: str, agent_id: str, event: dict) -> None:
        key = self._key(tenant_id, agent_id)
        if key not in self._windows:
            self._windows[key] = deque()
        self._windows[key].append(event)
        
        now = time.time()
        while self._windows[key]:
            oldest_event = self._windows[key][0]
            dt_ts = self._parse_ts(oldest_event['timestamp'])
            if (now - dt_ts) > settings.MAX_WINDOW_SECONDS:
                self._windows[key].popleft()
            else:
                break

    async def get_window(self, tenant_id: str, agent_id: str, horizon_s: float) -> list[dict]:
        key = self._key(tenant_id, agent_id)
        if key not in self._windows:
            return []
        
        now = time.time()
        result = []
        for event in list(self._windows[key]):
            dt_ts = self._parse_ts(event['timestamp'])
            if (now - dt_ts) <= horizon_s:
                result.append(event)
        return result

    async def get_all_agent_ids(self, tenant_id: str) -> list[str]:
        prefix = f"{tenant_id}:"
        return [k.split(":", 1)[1] for k in self._windows.keys() if k.startswith(prefix)]

    async def freeze(self, tenant_id: str, agent_id: str, reason: list[str]) -> None:
        key = self._key(tenant_id, agent_id)
        self._frozen[key] = reason

    async def unfreeze(self, tenant_id: str, agent_id: str) -> None:
        key = self._key(tenant_id, agent_id)
        if key in self._frozen:
            del self._frozen[key]

    async def is_frozen(self, tenant_id: str, agent_id: str) -> bool:
        key = self._key(tenant_id, agent_id)
        return key in self._frozen

    async def frozen_agents(self, tenant_id: str) -> dict[str, list[str]]:
        prefix = f"{tenant_id}:"
        return {k.split(":", 1)[1]: v for k, v in self._frozen.items() if k.startswith(prefix)}

    async def get_trust_score(self, tenant_id: str, agent_id: str) -> float:
        key = self._key(tenant_id, agent_id)
        return self._trust_scores.get(key, 1.0)

    async def set_trust_score(self, tenant_id: str, agent_id: str, score: float) -> None:
        key = self._key(tenant_id, agent_id)
        self._trust_scores[key] = score

    async def append_ledger(self, tenant_id: str, entry: dict) -> None:
        if tenant_id not in self._ledger:
            self._ledger[tenant_id] = []
        self._ledger[tenant_id].append(entry)

    async def get_ledger(self, tenant_id: str) -> list[dict]:
        return self._ledger.get(tenant_id, [])

    async def get_webhook_url(self, tenant_id: str) -> Optional[str]:
        return self._webhooks.get(tenant_id)

    async def set_webhook_url(self, tenant_id: str, url: str) -> None:
        self._webhooks[tenant_id] = url

import json

class RedisStore:
    def __init__(self):
    
        self.redis = redis.from_url(settings.REDIS_URL, decode_responses=True)

    def _parse_ts(self, ts_str: str) -> float:
        if ts_str.endswith("Z"):
            ts_str = ts_str[:-1] + "+00:00"
        return datetime.fromisoformat(ts_str).timestamp()

    async def append_window(self, tenant_id: str, agent_id: str, event: dict) -> None:
        ts = self._parse_ts(event['timestamp'])
        key = f"window:{tenant_id}:{agent_id}"
        event_json = json.dumps(event)
        
        await self.redis.zadd(key, {event_json: ts})
        
        min_ts = time.time() - settings.MAX_WINDOW_SECONDS
        await self.redis.zremrangebyscore(key, "-inf", min_ts)
        
        await self.redis.sadd(f"agents:{tenant_id}", agent_id)

    async def get_window(self, tenant_id: str, agent_id: str, horizon_s: float) -> list[dict]:
        key = f"window:{tenant_id}:{agent_id}"
        min_ts = time.time() - horizon_s
        records = await self.redis.zrangebyscore(key, min_ts, "+inf")
        return [json.loads(r) for r in records]

    async def get_all_agent_ids(self, tenant_id: str) -> list[str]:
        return list(await self.redis.smembers(f"agents:{tenant_id}"))

    async def freeze(self, tenant_id: str, agent_id: str, reason: list[str]) -> None:
        await self.redis.hset(f"frozen:{tenant_id}", agent_id, json.dumps(reason))

    async def unfreeze(self, tenant_id: str, agent_id: str) -> None:
        await self.redis.hdel(f"frozen:{tenant_id}", agent_id)

    async def is_frozen(self, tenant_id: str, agent_id: str) -> bool:
        return await self.redis.hexists(f"frozen:{tenant_id}", agent_id)

    async def frozen_agents(self, tenant_id: str) -> dict[str, list[str]]:
        frozen_data = await self.redis.hgetall(f"frozen:{tenant_id}")
        return {k: json.loads(v) for k, v in frozen_data.items()}

    async def get_trust_score(self, tenant_id: str, agent_id: str) -> float:
        score = await self.redis.hget(f"trust_scores:{tenant_id}", agent_id)
        if score is None:
            return 1.0
        return float(score)

    async def set_trust_score(self, tenant_id: str, agent_id: str, score: float) -> None:
        await self.redis.hset(f"trust_scores:{tenant_id}", agent_id, str(score))

    async def append_ledger(self, tenant_id: str, entry: dict) -> None:
        await self.redis.rpush(f"ledger:{tenant_id}", json.dumps(entry))

    async def get_ledger(self, tenant_id: str) -> list[dict]:
        records = await self.redis.lrange(f"ledger:{tenant_id}", 0, -1)
        return [json.loads(r) for r in records]

    async def get_webhook_url(self, tenant_id: str) -> Optional[str]:
        return await self.redis.hget("webhooks", tenant_id)

    async def set_webhook_url(self, tenant_id: str, url: str) -> None:
        await self.redis.hset("webhooks", tenant_id, url)

def make_store() -> Store:
    if settings.USE_REDIS:
        return RedisStore()
    return InMemoryStore()
