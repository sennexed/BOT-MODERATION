from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import asyncpg


class Database:
    def __init__(self, dsn: str) -> None:
        self._dsn = dsn
        self._pool: asyncpg.Pool | None = None

    async def connect(self) -> None:
        self._pool = await asyncpg.create_pool(self._dsn, min_size=1, max_size=10)

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()

    @property
    def pool(self) -> asyncpg.Pool:
        if self._pool is None:
            raise RuntimeError("Database not connected")
        return self._pool

    async def initialize_schema(self) -> None:
        query = """
        CREATE TABLE IF NOT EXISTS infractions (
            id SERIAL PRIMARY KEY,
            guild_id BIGINT NOT NULL,
            user_id BIGINT NOT NULL,
            warning_type TEXT NOT NULL CHECK (warning_type IN ('verbal', 'temp', 'permanent')),
            severity TEXT NOT NULL,
            reason TEXT NOT NULL,
            confidence REAL NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            expires_at TIMESTAMPTZ NULL
        );

        CREATE INDEX IF NOT EXISTS idx_infractions_guild_user_time
            ON infractions (guild_id, user_id, created_at DESC);

        CREATE TABLE IF NOT EXISTS appeals (
            id SERIAL PRIMARY KEY,
            guild_id BIGINT NOT NULL,
            user_id BIGINT NOT NULL,
            requested_by BIGINT NOT NULL,
            note TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """
        async with self.pool.acquire() as conn:
            await conn.execute(query)

    async def add_infraction(
        self,
        guild_id: int,
        user_id: int,
        warning_type: str,
        severity: str,
        reason: str,
        confidence: float,
        expires_at: datetime | None = None,
    ) -> None:
        query = """
        INSERT INTO infractions (guild_id, user_id, warning_type, severity, reason, confidence, expires_at)
        VALUES ($1, $2, $3, $4, $5, $6, $7)
        """
        async with self.pool.acquire() as conn:
            await conn.execute(query, guild_id, user_id, warning_type, severity, reason, confidence, expires_at)

    async def get_warning_counts(self, guild_id: int, user_id: int) -> dict[str, int]:
        query = """
        SELECT
            COUNT(*) FILTER (WHERE warning_type = 'verbal') AS verbal_count,
            COUNT(*) FILTER (WHERE warning_type = 'temp' AND (expires_at IS NULL OR expires_at > NOW())) AS active_temp_count,
            COUNT(*) FILTER (WHERE warning_type = 'permanent') AS permanent_count
        FROM infractions
        WHERE guild_id = $1 AND user_id = $2
        """
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(query, guild_id, user_id)
        return {
            "verbal": int(row["verbal_count"]),
            "temp": int(row["active_temp_count"]),
            "permanent": int(row["permanent_count"]),
        }

    async def promote_temp_to_permanent_if_needed(self, guild_id: int, user_id: int) -> bool:
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                rows = await conn.fetch(
                    """
                    SELECT id
                    FROM infractions
                    WHERE guild_id = $1
                      AND user_id = $2
                      AND warning_type = 'temp'
                      AND (expires_at IS NULL OR expires_at > NOW())
                    ORDER BY created_at ASC
                    LIMIT 4
                    FOR UPDATE
                    """,
                    guild_id,
                    user_id,
                )
                if len(rows) < 4:
                    return False

                ids = [row["id"] for row in rows]
                await conn.execute("DELETE FROM infractions WHERE id = ANY($1::int[])", ids)
                await conn.execute(
                    """
                    INSERT INTO infractions (guild_id, user_id, warning_type, severity, reason, confidence)
                    VALUES ($1, $2, 'permanent', 'SEVERE', $3, $4)
                    """,
                    guild_id,
                    user_id,
                    "Auto escalation: 4 active temporary warnings converted into 1 permanent warning",
                    1.0,
                )
                return True

    async def get_recent_warnings(self, guild_id: int, user_id: int, limit: int = 25) -> list[asyncpg.Record]:
        query = """
        SELECT warning_type, severity, confidence, reason, created_at, expires_at
        FROM infractions
        WHERE guild_id = $1 AND user_id = $2
        ORDER BY created_at DESC
        LIMIT $3
        """
        async with self.pool.acquire() as conn:
            return await conn.fetch(query, guild_id, user_id, limit)

    async def clear_temp_warnings(self, guild_id: int, user_id: int) -> int:
        query = """
        DELETE FROM infractions
        WHERE guild_id = $1
          AND user_id = $2
          AND warning_type = 'temp'
          AND (expires_at IS NULL OR expires_at > NOW())
        """
        async with self.pool.acquire() as conn:
            status = await conn.execute(query, guild_id, user_id)
        return int(status.split()[-1])

    async def reset_all_warnings(self, guild_id: int, user_id: int) -> int:
        query = "DELETE FROM infractions WHERE guild_id = $1 AND user_id = $2"
        async with self.pool.acquire() as conn:
            status = await conn.execute(query, guild_id, user_id)
        return int(status.split()[-1])

    async def cleanup_expired_temp_warnings(self) -> int:
        query = "DELETE FROM infractions WHERE warning_type = 'temp' AND expires_at <= NOW()"
        async with self.pool.acquire() as conn:
            status = await conn.execute(query)
        return int(status.split()[-1])

    async def get_mod_stats(self, guild_id: int) -> dict[str, Any]:
        totals_query = """
        SELECT
            COUNT(*) AS total,
            COUNT(*) FILTER (WHERE warning_type = 'verbal') AS verbal,
            COUNT(*) FILTER (WHERE warning_type = 'temp') AS temp,
            COUNT(*) FILTER (WHERE warning_type = 'permanent') AS permanent,
            COUNT(*) FILTER (WHERE created_at >= NOW() - INTERVAL '24 hours') AS last_24h
        FROM infractions
        WHERE guild_id = $1
        """
        top_query = """
        SELECT user_id, COUNT(*) AS warnings
        FROM infractions
        WHERE guild_id = $1
        GROUP BY user_id
        ORDER BY warnings DESC
        LIMIT 5
        """
        async with self.pool.acquire() as conn:
            totals = await conn.fetchrow(totals_query, guild_id)
            top_users = await conn.fetch(top_query, guild_id)

        return {
            "total": int(totals["total"]),
            "verbal": int(totals["verbal"]),
            "temp": int(totals["temp"]),
            "permanent": int(totals["permanent"]),
            "last_24h": int(totals["last_24h"]),
            "top_users": [(int(row["user_id"]), int(row["warnings"])) for row in top_users],
        }

    async def create_appeal(self, guild_id: int, user_id: int, requested_by: int, note: str) -> None:
        query = """
        INSERT INTO appeals (guild_id, user_id, requested_by, note)
        VALUES ($1, $2, $3, $4)
        """
        async with self.pool.acquire() as conn:
            await conn.execute(query, guild_id, user_id, requested_by, note)

    async def get_permanent_warning_count(self, guild_id: int, user_id: int) -> int:
        query = """
        SELECT COUNT(*)
        FROM infractions
        WHERE guild_id = $1 AND user_id = $2 AND warning_type = 'permanent'
        """
        async with self.pool.acquire() as conn:
            value = await conn.fetchval(query, guild_id, user_id)
        return int(value or 0)

    async def get_active_temp_warning_count(self, guild_id: int, user_id: int) -> int:
        query = """
        SELECT COUNT(*)
        FROM infractions
        WHERE guild_id = $1
          AND user_id = $2
          AND warning_type = 'temp'
          AND (expires_at IS NULL OR expires_at > NOW())
        """
        async with self.pool.acquire() as conn:
            value = await conn.fetchval(query, guild_id, user_id)
        return int(value or 0)

    @staticmethod
    def utcnow() -> datetime:
        return datetime.now(UTC)
