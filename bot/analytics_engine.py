from typing import Any
from .database import Database


class AnalyticsEngine:
    def __init__(self, db: Database):
        self.db = db

    async def snapshot(self, guild_id: int) -> dict[str, Any]:
        payload = {
            "status": "ok"
        }
        await self.db.cache_analytics(guild_id, payload)
        return payload
