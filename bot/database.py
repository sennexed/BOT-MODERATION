from __future__ import annotations

import asyncpg
from typing import Optional


class Database:
    def __init__(self, database_url: str) -> None:
        self.database_url = database_url
        self.pool: Optional[asyncpg.Pool] = None

    async def connect(self) -> None:
        self.pool = await asyncpg.create_pool(self.database_url)

    async def close(self) -> None:
        if self.pool:
            await self.pool.close()

    # ==============================
    # FIXED: USE risk_scores TABLE
    # ==============================

    async def get_risk_row(self, guild_id: int, user_id: int):
        async with self.pool.acquire() as conn:
            # Ensure row exists with default 0 risk_score
            await conn.execute("""
                INSERT INTO risk_scores (guild_id, user_id, risk_score)
                VALUES ($1, $2, 0.0)
                ON CONFLICT (guild_id, user_id) DO NOTHING
            """, guild_id, user_id)

            return await conn.fetchrow("""
                SELECT guild_id, user_id, risk_score, last_updated
                FROM risk_scores
                WHERE guild_id = $1 AND user_id = $2
            """, guild_id, user_id)

    async def upsert_risk(self, guild_id: int, user_id: int, risk_score: float):
        # STRICT FIX: prevent NULL ever entering DB
        risk_score = float(risk_score or 0.0)

        async with self.pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO risk_scores (guild_id, user_id, risk_score, last_updated)
                VALUES ($1, $2, $3, NOW())
                ON CONFLICT (guild_id, user_id)
                DO UPDATE SET
                    risk_score = EXCLUDED.risk_score,
                    last_updated = NOW()
            """, guild_id, user_id, risk_score)

    # ==============================
    # REST OF FILE UNCHANGED
    # ==============================

    async def get_or_create_guild_config(self, guild_id: int):
        async with self.pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO guild_config (guild_id)
                VALUES ($1)
                ON CONFLICT (guild_id) DO NOTHING
            """, guild_id)

            return await conn.fetchrow("""
                SELECT *
                FROM guild_config
                WHERE guild_id = $1
            """, guild_id)

    async def create_infraction(self, **kwargs):
        async with self.pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO infractions (
                    case_id,
                    guild_id,
                    user_id,
                    moderator_id,
                    source,
                    category,
                    severity,
                    action,
                    risk_score,
                    ai_confidence,
                    reason,
                    explanation,
                    expires_at
                )
                VALUES (
                    $1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13
                )
            """,
                kwargs["case_id"],
                kwargs["guild_id"],
                kwargs["user_id"],
                kwargs["moderator_id"],
                kwargs["source"],
                kwargs["category"],
                kwargs["severity"],
                kwargs["action"],
                int(kwargs["risk_score"] or 0),
                kwargs["ai_confidence"],
                kwargs["reason"],
                kwargs["explanation"],
                kwargs["expires_at"],
                              )
