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

    async def init_schema(self):
        await self.initialize_schema()

    # =========================
    # SCHEMA
    # =========================

    async def initialize_schema(self):
        if not self.pool:
            raise RuntimeError("Database not connected")

        async with self.pool.acquire() as conn:

            # =========================
            # GUILD CONFIG (FULL ENTERPRISE SCHEMA)
            # =========================

            await conn.execute("""
            CREATE TABLE IF NOT EXISTS guild_config (
                guild_id BIGINT PRIMARY KEY,

                -- AI Core
                ai_sensitivity FLOAT DEFAULT 0.5,
                confidence_threshold FLOAT DEFAULT 0.6,
                strict_ai_enabled BOOLEAN DEFAULT FALSE,
                ai_strict_mode BOOLEAN DEFAULT FALSE,
                ai_shadow_mode BOOLEAN DEFAULT FALSE,

                -- Security
                raid_mode TEXT DEFAULT 'auto',
                escalation_temp_days INTEGER DEFAULT 3,
                max_warnings_before_escalation INTEGER DEFAULT 5,

                -- Roles & Logging
                log_channel_id BIGINT,
                mod_role_id BIGINT,
                admin_role_id BIGINT,

                -- Reinforcement
                auto_reinforcement BOOLEAN DEFAULT TRUE,
                threat_level INTEGER DEFAULT 0,
                auto_lockdown BOOLEAN DEFAULT FALSE,
                reinforcement_mode TEXT DEFAULT 'adaptive',
                reinforcement_last_escalation TIMESTAMPTZ,
                reinforcement_manual_override BOOLEAN DEFAULT FALSE,

                -- Analytics
                analytics_enabled BOOLEAN DEFAULT TRUE,

                -- Meta
                created_at TIMESTAMP DEFAULT NOW(),
                updated_at TIMESTAMP DEFAULT NOW()
            );
            """)

            # Safe migrations
            await conn.execute("ALTER TABLE guild_config ADD COLUMN IF NOT EXISTS ai_strict_mode BOOLEAN DEFAULT FALSE;")
            await conn.execute("ALTER TABLE guild_config ADD COLUMN IF NOT EXISTS ai_shadow_mode BOOLEAN DEFAULT FALSE;")
            await conn.execute("ALTER TABLE guild_config ADD COLUMN IF NOT EXISTS escalation_temp_days INTEGER DEFAULT 3;")
            await conn.execute("ALTER TABLE guild_config ADD COLUMN IF NOT EXISTS admin_role_id BIGINT;")
            await conn.execute("ALTER TABLE guild_config ADD COLUMN IF NOT EXISTS analytics_enabled BOOLEAN DEFAULT TRUE;")
            await conn.execute("ALTER TABLE guild_config ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP DEFAULT NOW();")
            await conn.execute("ALTER TABLE guild_config ADD COLUMN IF NOT EXISTS max_warnings_before_escalation INTEGER DEFAULT 5;")

            # =========================
            # INFRACTIONS
            # =========================

            await conn.execute("""
            CREATE TABLE IF NOT EXISTS infractions (
                id SERIAL PRIMARY KEY,
                guild_id BIGINT NOT NULL,
                user_id BIGINT NOT NULL,
                action TEXT,
                severity INTEGER,
                reason TEXT,
                confidence FLOAT,
                expires_at TIMESTAMP NULL,
                created_at TIMESTAMP DEFAULT NOW()
            );
            """)

            # =========================
            # APPEALS
            # =========================

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

            # =========================
            # ANALYTICS CACHE
            # =========================

            await conn.execute("""
            CREATE TABLE IF NOT EXISTS analytics_cache (
                guild_id BIGINT PRIMARY KEY,
                payload JSONB,
                updated_at TIMESTAMP DEFAULT NOW()
            );
            """)

    # =========================
    # ANALYTICS CACHE
    # =========================

    async def cache_analytics(self, guild_id: int, payload: Dict[str, Any]):
        if not self.pool:
            raise RuntimeError("Database not connected")

        async with self.pool.acquire() as conn:
            await conn.execute("""
            INSERT INTO analytics_cache (guild_id, payload)
            VALUES ($1, $2)
            ON CONFLICT (guild_id)
            DO UPDATE SET payload = EXCLUDED.payload,
                          updated_at = NOW();
            """, guild_id, json.dumps(payload))

    async def get_server_analytics(self, guild_id: int):
        if not self.pool:
            raise RuntimeError("Database not connected")

        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT payload FROM analytics_cache WHERE guild_id = $1",
                guild_id
            )

            if row:
                return json.loads(row["payload"])

            return None

    # =========================
    # CLEANUP
    # =========================

    async def cleanup_expired_infractions(self):
        if not self.pool:
            raise RuntimeError("Database not connected")

        async with self.pool.acquire() as conn:
            result = await conn.execute("""
                DELETE FROM infractions
                WHERE expires_at IS NOT NULL
                AND expires_at < NOW();
            """)

            try:
                return int(result.split(" ")[1])
            except (IndexError, ValueError):
                return 0

    async def auto_expire_old_cases(self):
        return await self.cleanup_expired_infractions()
