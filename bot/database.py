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
    # SCHEMA (HARDENED)
    # =========================

    async def initialize_schema(self):
        if not self.pool:
            raise RuntimeError("Database not connected")

        async with self.pool.acquire() as conn:

            # =========================
            # GUILD CONFIG
            # =========================

            await conn.execute("""
            CREATE TABLE IF NOT EXISTS guild_config (
                guild_id BIGINT PRIMARY KEY
            );
            """)

            await conn.execute("ALTER TABLE guild_config ADD COLUMN IF NOT EXISTS ai_sensitivity FLOAT DEFAULT 0.5;")
            await conn.execute("ALTER TABLE guild_config ADD COLUMN IF NOT EXISTS confidence_threshold FLOAT DEFAULT 0.6;")
            await conn.execute("ALTER TABLE guild_config ADD COLUMN IF NOT EXISTS strict_ai_enabled BOOLEAN DEFAULT FALSE;")
            await conn.execute("ALTER TABLE guild_config ADD COLUMN IF NOT EXISTS ai_strict_mode BOOLEAN DEFAULT FALSE;")
            await conn.execute("ALTER TABLE guild_config ADD COLUMN IF NOT EXISTS ai_shadow_mode BOOLEAN DEFAULT FALSE;")
            await conn.execute("ALTER TABLE guild_config ADD COLUMN IF NOT EXISTS raid_mode TEXT DEFAULT 'auto';")
            await conn.execute("ALTER TABLE guild_config ADD COLUMN IF NOT EXISTS escalation_temp_days INTEGER DEFAULT 3;")
            await conn.execute("ALTER TABLE guild_config ADD COLUMN IF NOT EXISTS max_warnings_before_escalation INTEGER DEFAULT 5;")
            await conn.execute("ALTER TABLE guild_config ADD COLUMN IF NOT EXISTS log_channel_id BIGINT;")
            await conn.execute("ALTER TABLE guild_config ADD COLUMN IF NOT EXISTS mod_role_id BIGINT;")
            await conn.execute("ALTER TABLE guild_config ADD COLUMN IF NOT EXISTS admin_role_id BIGINT;")
            await conn.execute("ALTER TABLE guild_config ADD COLUMN IF NOT EXISTS auto_reinforcement BOOLEAN DEFAULT TRUE;")
            await conn.execute("ALTER TABLE guild_config ADD COLUMN IF NOT EXISTS threat_level INTEGER DEFAULT 0;")
            await conn.execute("ALTER TABLE guild_config ADD COLUMN IF NOT EXISTS auto_lockdown BOOLEAN DEFAULT FALSE;")
            await conn.execute("ALTER TABLE guild_config ADD COLUMN IF NOT EXISTS reinforcement_mode TEXT DEFAULT 'adaptive';")
            await conn.execute("ALTER TABLE guild_config ADD COLUMN IF NOT EXISTS reinforcement_last_escalation TIMESTAMPTZ;")
            await conn.execute("ALTER TABLE guild_config ADD COLUMN IF NOT EXISTS reinforcement_manual_override BOOLEAN DEFAULT FALSE;")
            await conn.execute("ALTER TABLE guild_config ADD COLUMN IF NOT EXISTS analytics_enabled BOOLEAN DEFAULT TRUE;")
            await conn.execute("ALTER TABLE guild_config ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT NOW();")
            await conn.execute("ALTER TABLE guild_config ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP DEFAULT NOW();")

            # =========================
            # INFRACTIONS
            # =========================

            await conn.execute("""
            CREATE TABLE IF NOT EXISTS infractions (
                id SERIAL PRIMARY KEY,
                guild_id BIGINT NOT NULL,
                user_id BIGINT NOT NULL
            );
            """)

            await conn.execute("ALTER TABLE infractions ADD COLUMN IF NOT EXISTS warning_type TEXT;")
            await conn.execute("ALTER TABLE infractions ADD COLUMN IF NOT EXISTS action TEXT;")
            await conn.execute("ALTER TABLE infractions ADD COLUMN IF NOT EXISTS severity INTEGER;")
            await conn.execute("ALTER TABLE infractions ADD COLUMN IF NOT EXISTS reason TEXT;")
            await conn.execute("ALTER TABLE infractions ADD COLUMN IF NOT EXISTS confidence FLOAT;")
            await conn.execute("ALTER TABLE infractions ADD COLUMN IF NOT EXISTS expires_at TIMESTAMP;")
            await conn.execute("ALTER TABLE infractions ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT NOW();")

            # =========================
            # APPEALS
            # =========================

            await conn.execute("""
            CREATE TABLE IF NOT EXISTS appeals (
                id SERIAL PRIMARY KEY,
                guild_id BIGINT NOT NULL,
                user_id BIGINT NOT NULL
            );
            """)

            await conn.execute("ALTER TABLE appeals ADD COLUMN IF NOT EXISTS infraction_id INTEGER;")
            await conn.execute("ALTER TABLE appeals ADD COLUMN IF NOT EXISTS reason TEXT;")
            await conn.execute("ALTER TABLE appeals ADD COLUMN IF NOT EXISTS status TEXT DEFAULT 'pending';")
            await conn.execute("ALTER TABLE appeals ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT NOW();")

            await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_appeals_guild_status
            ON appeals (guild_id, status);
            """)

            # =========================
            # USER RISK
            # =========================

            await conn.execute("""
            CREATE TABLE IF NOT EXISTS user_risk (
                guild_id BIGINT NOT NULL,
                user_id BIGINT NOT NULL,
                PRIMARY KEY (guild_id, user_id)
            );
            """)

            await conn.execute("ALTER TABLE user_risk ADD COLUMN IF NOT EXISTS risk_score FLOAT DEFAULT 0;")
            await conn.execute("ALTER TABLE user_risk ADD COLUMN IF NOT EXISTS warning_count INTEGER DEFAULT 0;")
            await conn.execute("ALTER TABLE user_risk ADD COLUMN IF NOT EXISTS last_updated TIMESTAMP DEFAULT NOW();")

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
