import asyncpg
import json
from typing import Optional, Dict, Any
from datetime import datetime, UTC


class Database:
    def __init__(self, dsn: str):
        self.dsn = dsn
        self.pool: Optional[asyncpg.Pool] = None

    # =========================
    # CONNECTION
    # =========================

    async def connect(self):
        if self.pool:
            return

        self.pool = await asyncpg.create_pool(
            dsn=self.dsn,
            min_size=1,
            max_size=10
        )

        await self.init_schema()

    async def close(self):
        if self.pool:
            await self.pool.close()
            self.pool = None

    def now(self):
        return datetime.now(UTC)

    # =========================
    # SCHEMA
    # =========================

    async def init_schema(self):
        async with self.pool.acquire() as conn:

            await conn.execute("""
                CREATE TABLE IF NOT EXISTS guild_config (
                    guild_id BIGINT PRIMARY KEY,
                    ai_sensitivity FLOAT DEFAULT 0.5,
                    confidence_threshold FLOAT DEFAULT 0.6,
                    strict_ai_enabled BOOLEAN DEFAULT FALSE,
                    ai_shadow_mode BOOLEAN DEFAULT FALSE,
                    raid_mode TEXT DEFAULT 'auto',
                    escalation_temp_days INTEGER DEFAULT 3,
                    log_channel_id BIGINT,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                );
            """)

            await conn.execute("""
                CREATE TABLE IF NOT EXISTS infractions (
                    id SERIAL PRIMARY KEY,
                    case_id TEXT,
                    guild_id BIGINT,
                    user_id BIGINT,
                    action TEXT,
                    severity TEXT,
                    category TEXT,
                    risk_score INTEGER,
                    ai_confidence FLOAT,
                    reason TEXT,
                    explanation TEXT,
                    expires_at TIMESTAMPTZ,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                );
            """)

            await conn.execute("""
                CREATE TABLE IF NOT EXISTS user_risk (
                    guild_id BIGINT,
                    user_id BIGINT,
                    risk_score FLOAT DEFAULT 0,
                    last_updated TIMESTAMPTZ DEFAULT NOW(),
                    PRIMARY KEY (guild_id, user_id)
                );
            """)

            await conn.execute("""
                CREATE TABLE IF NOT EXISTS analytics_cache (
                    guild_id BIGINT PRIMARY KEY,
                    payload JSONB,
                    updated_at TIMESTAMPTZ DEFAULT NOW()
                );
            """)

    # =========================
    # GUILD CONFIG
    # =========================

    async def get_or_create_guild_config(self, guild_id: int):
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM guild_config WHERE guild_id = $1",
                guild_id
            )
            if row:
                return dict(row)

            await conn.execute(
                "INSERT INTO guild_config (guild_id) VALUES ($1)",
                guild_id
            )

            row = await conn.fetchrow(
                "SELECT * FROM guild_config WHERE guild_id = $1",
                guild_id
            )
            return dict(row)

    async def update_guild_config(self, guild_id: int, **fields):
        async with self.pool.acquire() as conn:
            for key, value in fields.items():
                await conn.execute(
                    f"UPDATE guild_config SET {key} = $1 WHERE guild_id = $2",
                    value,
                    guild_id
                )

    # =========================
    # INFRACTIONS
    # =========================

    async def create_infraction(self, **data):
        async with self.pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO infractions
                (case_id, guild_id, user_id, action, severity, category,
                 risk_score, ai_confidence, reason, explanation, expires_at)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)
            """,
                data["case_id"],
                data["guild_id"],
                data["user_id"],
                data["action"],
                data["severity"],
                data["category"],
                data["risk_score"],
                data["ai_confidence"],
                data["reason"],
                data["explanation"],
                data["expires_at"]
            )

    async def get_user_infraction_counts(self, guild_id: int, user_id: int):
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT action FROM infractions
                WHERE guild_id = $1 AND user_id = $2
            """, guild_id, user_id)

        verbal = sum(1 for r in rows if r["action"] == "verbal")
        temp = sum(1 for r in rows if r["action"] == "temp")
        permanent = sum(1 for r in rows if r["action"] == "permanent")

        return {
            "verbal": verbal,
            "temp": temp,
            "permanent": permanent,
            "recent": len(rows)
        }

    async def cleanup_expired_infractions(self):
        async with self.pool.acquire() as conn:
            result = await conn.execute("""
                DELETE FROM infractions
                WHERE expires_at IS NOT NULL
                AND expires_at < NOW()
            """)
            return int(result.split(" ")[1])

    async def auto_expire_old_cases(self):
        return await self.cleanup_expired_infractions()

    # =========================
    # RISK
    # =========================

    async def get_risk_row(self, guild_id: int, user_id: int):
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT risk_score, last_updated
                FROM user_risk
                WHERE guild_id = $1 AND user_id = $2
            """, guild_id, user_id)

            if row:
                return dict(row)

            await conn.execute("""
                INSERT INTO user_risk (guild_id, user_id)
                VALUES ($1, $2)
            """, guild_id, user_id)

            return {"risk_score": 0.0, "last_updated": None}

    async def upsert_risk(self, guild_id: int, user_id: int, new_score: float):
        async with self.pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO user_risk (guild_id, user_id, risk_score, last_updated)
                VALUES ($1, $2, $3, NOW())
                ON CONFLICT (guild_id, user_id)
                DO UPDATE SET
                    risk_score = $3,
                    last_updated = NOW()
            """, guild_id, user_id, new_score)

    # =========================
    # ANALYTICS
    # =========================

    async def cache_analytics(self, guild_id: int, payload: Dict[str, Any]):
        async with self.pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO analytics_cache (guild_id, payload)
                VALUES ($1, $2)
                ON CONFLICT (guild_id)
                DO UPDATE SET payload = EXCLUDED.payload,
                              updated_at = NOW()
            """, guild_id, json.dumps(payload or {}))

    async def get_server_analytics(self, guild_id: int):
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT payload FROM analytics_cache WHERE guild_id = $1",
                guild_id
            )
            return json.loads(row["payload"]) if row else {}
