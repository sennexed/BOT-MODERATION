import asyncpg
import json
from typing import Optional, Dict, Any


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

        await self.initialize_schema()

    async def close(self):
        if self.pool:
            await self.pool.close()
            self.pool = None

    # =========================
    # SCHEMA
    # =========================

    async def initialize_schema(self):
        if not self.pool:
            raise RuntimeError("Database not connected")

        async with self.pool.acquire() as conn:

            # Guild config table
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS guild_config (
                    guild_id BIGINT PRIMARY KEY,
                    ai_sensitivity FLOAT DEFAULT 0.5,
                    confidence_threshold FLOAT DEFAULT 0.6,
                    strict_ai_enabled BOOLEAN DEFAULT FALSE,
                    ai_strict_mode BOOLEAN DEFAULT FALSE,
                    ai_shadow_mode BOOLEAN DEFAULT FALSE,
                    raid_mode TEXT DEFAULT 'auto',
                    escalation_temp_days INTEGER DEFAULT 3,
                    max_warnings_before_escalation INTEGER DEFAULT 5,
                    log_channel_id BIGINT,
                    mod_role_id BIGINT,
                    admin_role_id BIGINT,
                    auto_reinforcement BOOLEAN DEFAULT TRUE,
                    threat_level INTEGER DEFAULT 0,
                    auto_lockdown BOOLEAN DEFAULT FALSE,
                    reinforcement_mode TEXT DEFAULT 'adaptive',
                    reinforcement_last_escalation TIMESTAMPTZ,
                    reinforcement_manual_override BOOLEAN DEFAULT FALSE,
                    analytics_enabled BOOLEAN DEFAULT TRUE,
                    created_at TIMESTAMP DEFAULT NOW(),
                    updated_at TIMESTAMP DEFAULT NOW()
                );
            """)

            # Infractions
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS infractions (
                    id SERIAL PRIMARY KEY,
                    guild_id BIGINT NOT NULL,
                    user_id BIGINT NOT NULL,
                    warning_type TEXT,
                    action TEXT,
                    severity INTEGER,
                    reason TEXT,
                    confidence FLOAT,
                    expires_at TIMESTAMP,
                    created_at TIMESTAMP DEFAULT NOW()
                );
            """)

            # Appeals
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS appeals (
                    id SERIAL PRIMARY KEY,
                    guild_id BIGINT NOT NULL,
                    user_id BIGINT NOT NULL,
                    infraction_id INTEGER,
                    reason TEXT,
                    status TEXT DEFAULT 'pending',
                    created_at TIMESTAMP DEFAULT NOW()
                );
            """)

            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_appeals_guild_status
                ON appeals (guild_id, status);
            """)

            # User risk
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS user_risk (
                    guild_id BIGINT NOT NULL,
                    user_id BIGINT NOT NULL,
                    risk_score FLOAT DEFAULT 0,
                    warning_count INTEGER DEFAULT 0,
                    last_updated TIMESTAMP DEFAULT NOW(),
                    PRIMARY KEY (guild_id, user_id)
                );
            """)

            # Analytics cache
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS analytics_cache (
                    guild_id BIGINT PRIMARY KEY,
                    payload JSONB,
                    updated_at TIMESTAMP DEFAULT NOW()
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

    # =========================
    # RISK SYSTEM
    # =========================

    async def get_risk_row(self, guild_id: int, user_id: int):
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT risk_score, warning_count
                FROM user_risk
                WHERE guild_id = $1 AND user_id = $2
            """, guild_id, user_id)

            if row:
                return dict(row)

            await conn.execute("""
                INSERT INTO user_risk (guild_id, user_id)
                VALUES ($1, $2)
            """, guild_id, user_id)

            return {"risk_score": 0.0, "warning_count": 0}

    async def update_risk(self, guild_id: int, user_id: int, risk_delta: float, warning_increment: int = 0):
        async with self.pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO user_risk (guild_id, user_id, risk_score, warning_count)
                VALUES ($1, $2, $3, $4)
                ON CONFLICT (guild_id, user_id)
                DO UPDATE SET
                    risk_score = user_risk.risk_score + $3,
                    warning_count = user_risk.warning_count + $4,
                    last_updated = NOW();
            """, guild_id, user_id, risk_delta, warning_increment)

    # =========================
    # CLEANUP
    # =========================

    async def cleanup_expired_infractions(self):
        async with self.pool.acquire() as conn:
            result = await conn.execute("""
                DELETE FROM infractions
                WHERE expires_at IS NOT NULL
                AND expires_at < NOW();
            """)
            try:
                return int(result.split(" ")[1])
            except:
                return 0

    async def auto_expire_old_cases(self):
        return await self.cleanup_expired_infractions()

    # =========================
    # ANALYTICS CACHE
    # =========================

    async def cache_analytics(self, guild_id: int, payload: Dict[str, Any]):
        async with self.pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO analytics_cache (guild_id, payload)
                VALUES ($1, $2)
                ON CONFLICT (guild_id)
                DO UPDATE SET payload = EXCLUDED.payload,
                              updated_at = NOW();
            """, guild_id, json.dumps(payload))

    async def get_server_analytics(self, guild_id: int):
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT payload FROM analytics_cache WHERE guild_id = $1",
                guild_id
            )
            if row:
                return json.loads(row["payload"])
            return None
