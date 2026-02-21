from __future__ import annotations

from typing import Any

from .database import Database


class AnalyticsEngine:
    def __init__(self, db: Database) -> None:
        self.db = db

    async def snapshot(self, guild_id: int) -> dict[str, Any]:
        payload = await self.db.get_server_analytics(guild_id)
        await self.db.cache_analytics(guild_id, payload)
        return payload

    async def toxicity_trend(self, guild_id: int, hours: int = 24) -> list[tuple[str, int]]:
        return await self.db.get_toxicity_trend(guild_id, hours)
