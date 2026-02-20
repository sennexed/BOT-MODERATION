from __future__ import annotations

import time

from .cache import Cache
from .database import Database
from .utils import Severity


SEVERITY_WEIGHTS: dict[Severity, float] = {
    Severity.SAFE: 0.0,
    Severity.WARNING: 1.0,
    Severity.TOXIC: 2.0,
    Severity.SPAM: 2.0,
    Severity.NSFW: 3.0,
    Severity.HATE: 5.0,
    Severity.THREAT: 6.0,
    Severity.SEVERE: 4.0,
}


class ReinforcementEngine:
    def __init__(self, cache: Cache, db: Database, decay_per_hour: float) -> None:
        self._cache = cache
        self._db = db
        self._decay_per_hour = decay_per_hour

    @staticmethod
    def _key(guild_id: int, user_id: int) -> str:
        return f"risk:{guild_id}:{user_id}"

    async def get_risk(self, guild_id: int, user_id: int) -> float:
        # Risk score decays over time so old behavior has less impact than recent infractions.
        cached = await self._cache.get_json(self._key(guild_id, user_id))
        now = time.time()
        if cached:
            score = float(cached.get("score", 0.0))
            updated = float(cached.get("updated", now))
        else:
            score = await self._db.get_user_risk(guild_id, user_id)
            updated = now

        elapsed_hours = max(0.0, (now - updated) / 3600.0)
        decayed = max(0.0, score - elapsed_hours * self._decay_per_hour)
        await self._cache.set_json(self._key(guild_id, user_id), {"score": decayed, "updated": now}, ex=86400)
        return decayed

    async def apply_infraction(self, guild_id: int, user_id: int, severity: Severity, bypass_count: int) -> float:
        current = await self.get_risk(guild_id, user_id)
        increase = SEVERITY_WEIGHTS[severity] + min(3.0, bypass_count * 0.5)
        updated = max(0.0, current + increase)
        now = time.time()
        await self._cache.set_json(self._key(guild_id, user_id), {"score": updated, "updated": now}, ex=86400)
        await self._db.set_user_risk(guild_id, user_id, updated)
        return updated

    async def clear_risk(self, guild_id: int, user_id: int) -> None:
        await self._cache.delete(self._key(guild_id, user_id))
        await self._db.clear_user_risk(guild_id, user_id)
