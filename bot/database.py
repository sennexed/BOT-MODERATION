from __future__ import annotations

import json
from typing import Any

import asyncpg


class Database:
    def __init__(self, dsn: str) -> None:
        self._dsn = dsn
        self._pool: asyncpg.Pool | None = None

    async def connect(self) -> None:
        self._pool = await asyncpg.create_pool(self._dsn, min_size=1, max_size=10)

    async def close(self) -> None:
        if self._pool:
            await self._pool.close()

    @property
    def pool(self) -> asyncpg.Pool:
        if not self._pool:
            raise RuntimeError("Database is not connected")
        return self._pool

    async def initialize_schema(self) -> None:
        query = """
        CREATE TABLE IF NOT EXISTS infractions (
            id BIGSERIAL PRIMARY KEY,
            guild_id BIGINT NOT NULL,
            channel_id BIGINT NOT NULL,
            message_id BIGINT,
            user_id BIGINT NOT NULL,
            severity TEXT NOT NULL,
            confidence DOUBLE PRECISION NOT NULL,
            action_taken TEXT NOT NULL,
            reasoning TEXT NOT NULL,
            normalized_content TEXT NOT NULL,
            bypass_flags JSONB NOT NULL DEFAULT '[]'::jsonb,
            risk_score DOUBLE PRECISION NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );

        CREATE TABLE IF NOT EXISTS user_risk (
            guild_id BIGINT NOT NULL,
            user_id BIGINT NOT NULL,
            risk_score DOUBLE PRECISION NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (guild_id, user_id)
        );

        CREATE TABLE IF NOT EXISTS lockdown_events (
            id BIGSERIAL PRIMARY KEY,
            guild_id BIGINT NOT NULL,
            channel_id BIGINT NOT NULL,
            enabled BOOLEAN NOT NULL,
            reason TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );

        CREATE INDEX IF NOT EXISTS idx_infractions_guild_user_time
            ON infractions (guild_id, user_id, created_at DESC);
        """
        async with self.pool.acquire() as conn:
            await conn.execute(query)

    async def log_infraction(self, payload: dict[str, Any]) -> None:
        query = """
        INSERT INTO infractions (
            guild_id, channel_id, message_id, user_id,
            severity, confidence, action_taken, reasoning,
            normalized_content, bypass_flags, risk_score
        ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)
        """
        async with self.pool.acquire() as conn:
            await conn.execute(
                query,
                payload["guild_id"],
                payload["channel_id"],
                payload.get("message_id"),
                payload["user_id"],
                payload["severity"],
                payload["confidence"],
                payload["action_taken"],
                payload["reasoning"],
                payload["normalized_content"],
                json.dumps(payload.get("bypass_flags", [])),
                payload["risk_score"],
            )

    async def get_user_infraction_count(self, guild_id: int, user_id: int, hours: int = 168) -> int:
        query = """
        SELECT COUNT(*)
        FROM infractions
        WHERE guild_id = $1
          AND user_id = $2
          AND created_at >= NOW() - ($3 || ' hours')::interval
          AND severity <> 'SAFE'
        """
        async with self.pool.acquire() as conn:
            value = await conn.fetchval(query, guild_id, user_id, hours)
        return int(value or 0)

    async def get_user_infractions(self, guild_id: int, user_id: int, limit: int = 20) -> list[asyncpg.Record]:
        query = """
        SELECT created_at, severity, action_taken, confidence, reasoning
        FROM infractions
        WHERE guild_id = $1 AND user_id = $2
        ORDER BY created_at DESC
        LIMIT $3
        """
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(query, guild_id, user_id, limit)
        return rows

    async def set_user_risk(self, guild_id: int, user_id: int, risk_score: float) -> None:
        query = """
        INSERT INTO user_risk (guild_id, user_id, risk_score, updated_at)
        VALUES ($1,$2,$3,NOW())
        ON CONFLICT (guild_id, user_id)
        DO UPDATE SET risk_score = EXCLUDED.risk_score, updated_at = NOW()
        """
        async with self.pool.acquire() as conn:
            await conn.execute(query, guild_id, user_id, risk_score)

    async def get_user_risk(self, guild_id: int, user_id: int) -> float:
        query = "SELECT risk_score FROM user_risk WHERE guild_id = $1 AND user_id = $2"
        async with self.pool.acquire() as conn:
            value = await conn.fetchval(query, guild_id, user_id)
        return float(value or 0.0)

    async def clear_user_risk(self, guild_id: int, user_id: int) -> None:
        query = "DELETE FROM user_risk WHERE guild_id = $1 AND user_id = $2"
        async with self.pool.acquire() as conn:
            await conn.execute(query, guild_id, user_id)

    async def get_mod_stats(self, guild_id: int) -> dict[str, Any]:
        query = """
        SELECT
            COUNT(*) AS total,
            COUNT(*) FILTER (WHERE severity <> 'SAFE') AS violations,
            COUNT(*) FILTER (WHERE created_at >= NOW() - INTERVAL '24 hours') AS last_24h
        FROM infractions
        WHERE guild_id = $1
        """
        severity_query = """
        SELECT severity, COUNT(*) AS count
        FROM infractions
        WHERE guild_id = $1
        GROUP BY severity
        ORDER BY count DESC
        """
        async with self.pool.acquire() as conn:
            totals = await conn.fetchrow(query, guild_id)
            severities = await conn.fetch(severity_query, guild_id)

        by_severity = {row["severity"]: int(row["count"]) for row in severities}
        return {
            "total": int(totals["total"]),
            "violations": int(totals["violations"]),
            "last_24h": int(totals["last_24h"]),
            "by_severity": by_severity,
        }

    async def log_lockdown_event(self, guild_id: int, channel_id: int, enabled: bool, reason: str) -> None:
        query = """
        INSERT INTO lockdown_events (guild_id, channel_id, enabled, reason)
        VALUES ($1,$2,$3,$4)
        """
        async with self.pool.acquire() as conn:
            await conn.execute(query, guild_id, channel_id, enabled, reason)
