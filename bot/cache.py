from __future__ import annotations

import json
import time
from typing import Any

from redis.asyncio import Redis


class Cache:
    def __init__(self, redis_url: str) -> None:
        self._redis = Redis.from_url(redis_url, decode_responses=True)

    async def close(self) -> None:
        await self._redis.aclose()

    async def get_json(self, key: str) -> dict[str, Any] | None:
        value = await self._redis.get(key)
        if value is None:
            return None
        return json.loads(value)

    async def set_json(self, key: str, payload: dict[str, Any], ex: int | None = None) -> None:
        await self._redis.set(key, json.dumps(payload), ex=ex)

    async def is_rate_limited(self, key: str, limit: int, window_seconds: int) -> bool:
        current = await self._redis.incr(key)
        if current == 1:
            await self._redis.expire(key, window_seconds)
        return current > limit

    @staticmethod
    def _risk_key(guild_id: int, user_id: int) -> str:
        return f"risk:{guild_id}:{user_id}"

    async def get_risk_score(self, guild_id: int, user_id: int, decay_per_hour: float) -> float:
        now = time.time()
        payload = await self.get_json(self._risk_key(guild_id, user_id))
        if not payload:
            return 0.0

        score = float(payload.get("score", 0.0))
        last_updated = float(payload.get("updated", now))
        elapsed_hours = max(0.0, (now - last_updated) / 3600.0)
        decayed = max(0.0, score - elapsed_hours * decay_per_hour)
        await self.set_json(self._risk_key(guild_id, user_id), {"score": decayed, "updated": now}, ex=86400 * 30)
        return decayed

    async def increment_risk_score(self, guild_id: int, user_id: int, delta: float, decay_per_hour: float) -> float:
        current = await self.get_risk_score(guild_id, user_id, decay_per_hour)
        updated = max(0.0, current + delta)
        await self.set_json(
            self._risk_key(guild_id, user_id),
            {"score": updated, "updated": time.time()},
            ex=86400 * 30,
        )
        return updated

    async def clear_risk_score(self, guild_id: int, user_id: int) -> None:
        await self._redis.delete(self._risk_key(guild_id, user_id))

    async def get_sensitivity(self, guild_id: int, default: float) -> float:
        key = f"config:sensitivity:{guild_id}"
        value = await self._redis.get(key)
        if value is None:
            return default
        try:
            parsed = float(value)
        except ValueError:
            return default
        return max(0.0, min(1.0, parsed))

    async def set_sensitivity(self, guild_id: int, sensitivity: float) -> None:
        key = f"config:sensitivity:{guild_id}"
        await self._redis.set(key, str(max(0.0, min(1.0, sensitivity))))

    async def set_lockdown(self, guild_id: int, enabled: bool) -> None:
        await self._redis.set(f"config:lockdown:{guild_id}", "1" if enabled else "0")

    async def is_lockdown(self, guild_id: int) -> bool:
        value = await self._redis.get(f"config:lockdown:{guild_id}")
        return value == "1"
