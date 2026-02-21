import asyncpg
import json
from typing import Optional, Dict, Any


class Database:
    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool

    # =========================
    # INITIALIZATION
    # =========================

    async def init_schema(self):
        await self.initialize_schema()

    async def initialize_schema(self):
        async with self.pool.acquire() as conn:

            # -------------------------
            # GUILD CONFIG
            # -------------------------
            await conn.execute("""
            CREATE TABLE IF NOT EXISTS guild_config (
                guild_id BIGINT PRIMARY KEY,
                ai_sensitivity FLOAT DEFAULT 0.6,
                confidence_threshold FLOAT DEFAULT 0.7,
                strict_ai_enabled BOOLEAN DEFAULT FALSE,
                raid_mode TEXT DEFAULT 'off',
                auto_reinforcement BOOLEAN DEFAULT FALSE,
                auto_lockdown BOOLEAN DEFAULT FALSE,
                max_warnings INTEGER DEFAULT 3,
                log_channel_id BIGINT,
                mod_role_id BIGINT,
                created_at TIMESTAMP DEFAULT NOW()
            );
            """)

            # Safe column migrations
            await conn.execute("ALTER TABLE guild_config ADD COLUMN IF NOT EXISTS ai_sensitivity FLOAT DEFAULT 0.6;")
            await conn.execute("ALTER TABLE guild_config ADD COLUMN IF NOT EXISTS confidence_threshold FLOAT DEFAULT 0.7;")
            await conn.execute("ALTER TABLE guild_config ADD COLUMN IF NOT EXISTS strict_ai_enabled BOOLEAN DEFAULT FALSE;")
            await conn.execute("ALTER TABLE guild_config ADD COLUMN IF NOT EXISTS raid_mode TEXT DEFAULT 'off';")
            await conn.execute("ALTER TABLE guild_config ADD COLUMN IF NOT EXISTS auto_reinforcement BOOLEAN DEFAULT FALSE;")
            await conn.execute("ALTER TABLE guild_config ADD COLUMN IF NOT EXISTS auto_lockdown BOOLEAN DEFAULT FALSE;")

            # -------------------------
            # INFRACTIONS
            # -------------------------
            await conn.execute("""
            CREATE TABLE IF NOT EXISTS infractions (
                id SERIAL PRIMARY KEY,
                guild_id BIGINT NOT NULL,
                user_id BIGINT NOT NULL,
                warning_type TEXT,
                severity INTEGER,
                reason TEXT,
                confidence FLOAT,
                expires_at TIMESTAMP NULL,
                created_at TIMESTAMP DEFAULT NOW()
            );
            """)

            # -------------------------
            # APPEALS
            # -------------------------
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

            # Safe migration
            await conn.execute("ALTER TABLE appeals ADD COLUMN IF NOT EXISTS status TEXT DEFAULT 'pending';")

            await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_appeals_guild_status
            ON appeals (guild_id, status);
            """)

            # -------------------------
            # ANALYTICS CACHE
            # -------------------------
            await conn.execute("""
            CREATE TABLE IF NOT EXISTS analytics_cache (
                guild_id BIGINT PRIMARY KEY,
                payload JSONB,
                updated_at TIMESTAMP DEFAULT NOW()
            );
            """)

    # =========================
    # GUILD CONFIG METHODS
    # =========================

    async def get_or_create_guild_config(self, guild_id: int):
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM guild_config WHERE guild_id = $1",
                guild_id
            )

            if not row:
                await conn.execute(
                    "INSERT INTO guild_config (guild_id) VALUES ($1)",
                    guild_id
                )
                row = await conn.fetchrow(
                    "SELECT * FROM guild_config WHERE guild_id = $1",
                    guild_id
                )

            return row

    async def update_guild_config(self, guild_id: int, **kwargs):
        if not kwargs:
            return

        columns = []
        values = []
        index = 1

        for key, value in kwargs.items():
            columns.append(f"{key} = ${index}")
            values.append(value)
            index += 1

        query = f"""
        UPDATE guild_config
        SET {', '.join(columns)}
        WHERE guild_id = ${index}
        """

        values.append(guild_id)

        async with self.pool.acquire() as conn:
            await conn.execute(query, *values)

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

    # =========================
    # CLEANUP
    # =========================

    async def cleanup_expired_infractions(self):
        async with self.pool.acquire() as conn:
            return await conn.execute("""
            DELETE FROM infractions
            WHERE expires_at IS NOT NULL
            AND expires_at < NOW();
            """)
