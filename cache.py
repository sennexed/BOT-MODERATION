from __future__ import annotations

import json
import time
from typing import Any

from redis.asyncio import Redis


class Cache:
    def __init__(self, redis_url: str) -> None:
        self._redis = Redis.from_url(redis_url, decode_responses=True)

    async def close(self) -> None:
        await self._redis.close()

    async def get_json(self, key: str) -> dict[str, Any] | None:
        value = await self._redis.get(key)
        if value is None:
            return None
        return json.loads(value)

    async def set_json(self, key: str, payload: dict[str, Any], ex: int | None = None) -> None:
        await self._redis.set(key, json.dumps(payload), ex=ex)

    async def delete(self, key: str) -> None:
        await self._redis.delete(key)

    async def set_if_not_exists(self, key: str, value: str, ex: int) -> bool:
        result = await self._redis.set(key, value, ex=ex, nx=True)
        return bool(result)

    async def is_rate_limited(self, key: str, limit: int, window_seconds: int) -> bool:
        current = await self._redis.incr(key)
        if current == 1:
            await self._redis.expire(key, window_seconds)
        return current > limit

    async def add_timestamp_and_count(
        self, key: str, now_seconds: float, window_seconds: int, max_count: int
    ) -> tuple[int, bool]:
        pipe = self._redis.pipeline()
        min_score = now_seconds - window_seconds
        pipe.zadd(key, {str(now_seconds): now_seconds})
        pipe.zremrangebyscore(key, 0, min_score)
        pipe.zcard(key)
        pipe.expire(key, window_seconds + 2)
        _, _, count, _ = await pipe.execute()
        return int(count), int(count) >= max_count

    async def get_or_set_default(self, key: str, default: str, ex: int | None = None) -> str:
        value = await self._redis.get(key)
        if value is None:
            await self._redis.set(key, default, ex=ex)
            return default
        return value
