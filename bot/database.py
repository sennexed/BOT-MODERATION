from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any

import asyncpg


class Database:
    def __init__(self, dsn: str) -> None:
        self._dsn = dsn
        self._pool: asyncpg.Pool | None = None

    async def connect(self) -> None:
        self._pool = await asyncpg.create_pool(
            self._dsn,
            min_size=1,
            max_size=12,
            max_inactive_connection_lifetime=300.0,
            command_timeout=30.0,
        )

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()

    @property
    def pool(self) -> asyncpg.Pool:
        if self._pool is None:
            raise RuntimeError("Database not connected")
        return self._pool

    @staticmethod
    def now() -> datetime:
        return datetime.now(UTC)

    @staticmethod
    def utcnow() -> datetime:
        return datetime.now(UTC)

    async def init_schema(self) -> None:
        await self.initialize_schema()

    async def initialize_schema(self) -> None:
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS guild_config (
                        guild_id BIGINT PRIMARY KEY,
                        ai_sensitivity DOUBLE PRECISION NOT NULL DEFAULT 0.55,
                        confidence_threshold DOUBLE PRECISION NOT NULL DEFAULT 0.60,
                        ai_strict_mode BOOLEAN NOT NULL DEFAULT FALSE,
                        ai_shadow_mode BOOLEAN NOT NULL DEFAULT FALSE,
                        raid_mode TEXT NOT NULL DEFAULT 'auto',
                        escalation_temp_days INTEGER NOT NULL DEFAULT 30,
                        log_channel_id BIGINT,
                        mod_role_id BIGINT,
                        admin_role_id BIGINT,
                        analytics_enabled BOOLEAN NOT NULL DEFAULT TRUE,
                        strict_ai_enabled BOOLEAN NOT NULL DEFAULT FALSE,
                        max_warnings_before_escalation INTEGER NOT NULL DEFAULT 5,
                        max_warnings INTEGER NOT NULL DEFAULT 5,
                        auto_reinforcement BOOLEAN NOT NULL DEFAULT TRUE,
                        threat_level INTEGER NOT NULL DEFAULT 0,
                        auto_lockdown BOOLEAN NOT NULL DEFAULT FALSE,
                        reinforcement_mode TEXT NOT NULL DEFAULT 'adaptive',
                        reinforcement_last_escalation TIMESTAMPTZ,
                        reinforcement_manual_override BOOLEAN NOT NULL DEFAULT FALSE,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    );
                    """
                )

                await conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS infractions (
                        id BIGSERIAL PRIMARY KEY,
                        case_id TEXT UNIQUE,
                        guild_id BIGINT NOT NULL,
                        user_id BIGINT NOT NULL,
                        moderator_id BIGINT,
                        source TEXT NOT NULL DEFAULT 'ai',
                        category TEXT NOT NULL DEFAULT 'manual',
                        warning_type TEXT NOT NULL DEFAULT 'verbal',
                        severity TEXT NOT NULL DEFAULT 'medium',
                        action TEXT NOT NULL DEFAULT 'verbal',
                        risk_score INTEGER NOT NULL DEFAULT 0,
                        confidence DOUBLE PRECISION,
                        ai_confidence DOUBLE PRECISION,
                        reason TEXT NOT NULL,
                        explanation TEXT NOT NULL DEFAULT '',
                        active BOOLEAN NOT NULL DEFAULT TRUE,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        expires_at TIMESTAMPTZ
                    );
                    """
                )

                await conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS appeals (
                        id BIGSERIAL PRIMARY KEY,
                        case_id TEXT NOT NULL,
                        guild_id BIGINT NOT NULL,
                        user_id BIGINT NOT NULL,
                        requested_by BIGINT NOT NULL,
                        status TEXT NOT NULL DEFAULT 'pending',
                        review_note TEXT,
                        reviewer_id BIGINT,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        reviewed_at TIMESTAMPTZ
                    );
                    """
                )

                await conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS risk_scores (
                        guild_id BIGINT NOT NULL,
                        user_id BIGINT NOT NULL,
                        risk_score DOUBLE PRECISION NOT NULL DEFAULT 0,
                        last_updated TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        PRIMARY KEY (guild_id, user_id)
                    );
                    """
                )

                await conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS moderator_actions (
                        id BIGSERIAL PRIMARY KEY,
                        guild_id BIGINT NOT NULL,
                        moderator_id BIGINT NOT NULL,
                        action_type TEXT NOT NULL,
                        case_id TEXT,
                        details JSONB NOT NULL DEFAULT '{}'::jsonb,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    );
                    """
                )

                await conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS analytics_cache (
                        guild_id BIGINT PRIMARY KEY,
                        payload JSONB NOT NULL,
                        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        generated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    );
                    """
                )

                for ddl in (
                    "ALTER TABLE guild_config ADD COLUMN IF NOT EXISTS ai_sensitivity DOUBLE PRECISION NOT NULL DEFAULT 0.55;",
                    "ALTER TABLE guild_config ADD COLUMN IF NOT EXISTS confidence_threshold DOUBLE PRECISION NOT NULL DEFAULT 0.60;",
                    "ALTER TABLE guild_config ADD COLUMN IF NOT EXISTS ai_strict_mode BOOLEAN NOT NULL DEFAULT FALSE;",
                    "ALTER TABLE guild_config ADD COLUMN IF NOT EXISTS ai_shadow_mode BOOLEAN NOT NULL DEFAULT FALSE;",
                    "ALTER TABLE guild_config ADD COLUMN IF NOT EXISTS raid_mode TEXT NOT NULL DEFAULT 'auto';",
                    "ALTER TABLE guild_config ADD COLUMN IF NOT EXISTS escalation_temp_days INTEGER NOT NULL DEFAULT 30;",
                    "ALTER TABLE guild_config ADD COLUMN IF NOT EXISTS log_channel_id BIGINT;",
                    "ALTER TABLE guild_config ADD COLUMN IF NOT EXISTS mod_role_id BIGINT;",
                    "ALTER TABLE guild_config ADD COLUMN IF NOT EXISTS admin_role_id BIGINT;",
                    "ALTER TABLE guild_config ADD COLUMN IF NOT EXISTS analytics_enabled BOOLEAN NOT NULL DEFAULT TRUE;",
                    "ALTER TABLE guild_config ADD COLUMN IF NOT EXISTS strict_ai_enabled BOOLEAN NOT NULL DEFAULT FALSE;",
                    "ALTER TABLE guild_config ADD COLUMN IF NOT EXISTS max_warnings_before_escalation INTEGER NOT NULL DEFAULT 5;",
                    "ALTER TABLE guild_config ADD COLUMN IF NOT EXISTS max_warnings INTEGER NOT NULL DEFAULT 5;",
                    "ALTER TABLE guild_config ADD COLUMN IF NOT EXISTS auto_reinforcement BOOLEAN NOT NULL DEFAULT TRUE;",
                    "ALTER TABLE guild_config ADD COLUMN IF NOT EXISTS threat_level INTEGER NOT NULL DEFAULT 0;",
                    "ALTER TABLE guild_config ADD COLUMN IF NOT EXISTS auto_lockdown BOOLEAN NOT NULL DEFAULT FALSE;",
                    "ALTER TABLE guild_config ADD COLUMN IF NOT EXISTS reinforcement_mode TEXT NOT NULL DEFAULT 'adaptive';",
                    "ALTER TABLE guild_config ADD COLUMN IF NOT EXISTS reinforcement_last_escalation TIMESTAMPTZ;",
                    "ALTER TABLE guild_config ADD COLUMN IF NOT EXISTS reinforcement_manual_override BOOLEAN NOT NULL DEFAULT FALSE;",
                    "ALTER TABLE guild_config ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT NOW();",
                    "ALTER TABLE guild_config ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW();",
                    "ALTER TABLE infractions ADD COLUMN IF NOT EXISTS case_id TEXT;",
                    "ALTER TABLE infractions ADD COLUMN IF NOT EXISTS moderator_id BIGINT;",
                    "ALTER TABLE infractions ADD COLUMN IF NOT EXISTS source TEXT NOT NULL DEFAULT 'ai';",
                    "ALTER TABLE infractions ADD COLUMN IF NOT EXISTS category TEXT NOT NULL DEFAULT 'manual';",
                    "ALTER TABLE infractions ADD COLUMN IF NOT EXISTS warning_type TEXT NOT NULL DEFAULT 'verbal';",
                    "ALTER TABLE infractions ADD COLUMN IF NOT EXISTS severity TEXT NOT NULL DEFAULT 'medium';",
                    "ALTER TABLE infractions ADD COLUMN IF NOT EXISTS action TEXT NOT NULL DEFAULT 'verbal';",
                    "ALTER TABLE infractions ADD COLUMN IF NOT EXISTS risk_score INTEGER NOT NULL DEFAULT 0;",
                    "ALTER TABLE infractions ADD COLUMN IF NOT EXISTS confidence DOUBLE PRECISION;",
                    "ALTER TABLE infractions ADD COLUMN IF NOT EXISTS ai_confidence DOUBLE PRECISION;",
                    "ALTER TABLE infractions ADD COLUMN IF NOT EXISTS explanation TEXT NOT NULL DEFAULT '';",
                    "ALTER TABLE infractions ADD COLUMN IF NOT EXISTS active BOOLEAN NOT NULL DEFAULT TRUE;",
                    "ALTER TABLE infractions ADD COLUMN IF NOT EXISTS expires_at TIMESTAMPTZ;",
                    "ALTER TABLE analytics_cache ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW();",
                    "ALTER TABLE analytics_cache ADD COLUMN IF NOT EXISTS generated_at TIMESTAMPTZ NOT NULL DEFAULT NOW();",
                ):
                    await conn.execute(ddl)

                await conn.execute("UPDATE infractions SET case_id = COALESCE(case_id, 'LEGACY-' || id::text) WHERE case_id IS NULL")
                await conn.execute("UPDATE infractions SET action = warning_type WHERE action IS NULL OR action = ''")
                await conn.execute("UPDATE infractions SET warning_type = action WHERE warning_type IS NULL OR warning_type = ''")
                await conn.execute("UPDATE infractions SET ai_confidence = confidence WHERE ai_confidence IS NULL AND confidence IS NOT NULL")
                await conn.execute("UPDATE infractions SET confidence = ai_confidence WHERE confidence IS NULL AND ai_confidence IS NOT NULL")
                await conn.execute("UPDATE guild_config SET max_warnings = max_warnings_before_escalation WHERE max_warnings IS DISTINCT FROM max_warnings_before_escalation")

                await conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_infractions_case_id ON infractions(case_id)")
                await conn.execute("CREATE INDEX IF NOT EXISTS idx_infractions_guild_user ON infractions (guild_id, user_id)")
                await conn.execute("CREATE INDEX IF NOT EXISTS idx_infractions_guild_created ON infractions (guild_id, created_at DESC)")
                await conn.execute("CREATE INDEX IF NOT EXISTS idx_appeals_guild_status ON appeals (guild_id, status)")
                await conn.execute("CREATE INDEX IF NOT EXISTS idx_risk_scores_guild_user ON risk_scores (guild_id, user_id)")
                await conn.execute("CREATE INDEX IF NOT EXISTS idx_mod_actions_guild_user ON moderator_actions (guild_id, moderator_id)")

    async def get_or_create_guild_config(self, guild_id: int) -> asyncpg.Record:
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO guild_config (guild_id)
                VALUES ($1)
                ON CONFLICT (guild_id) DO NOTHING
                """,
                guild_id,
            )
            row = await conn.fetchrow(
                """
                SELECT
                    guild_id,
                    ai_sensitivity,
                    confidence_threshold,
                    ai_strict_mode,
                    ai_shadow_mode,
                    raid_mode,
                    escalation_temp_days,
                    log_channel_id,
                    mod_role_id,
                    admin_role_id,
                    analytics_enabled,
                    strict_ai_enabled,
                    max_warnings_before_escalation,
                    max_warnings,
                    auto_reinforcement,
                    threat_level,
                    auto_lockdown,
                    reinforcement_mode,
                    reinforcement_last_escalation,
                    reinforcement_manual_override,
                    created_at,
                    updated_at
                FROM guild_config
                WHERE guild_id = $1
                """,
                guild_id,
            )
        assert row is not None
        return row

    async def update_guild_config(self, guild_id: int, **updates: Any) -> asyncpg.Record:
        if not updates:
            return await self.get_or_create_guild_config(guild_id)

        allowed = {
            "ai_sensitivity",
            "confidence_threshold",
            "ai_strict_mode",
            "ai_shadow_mode",
            "raid_mode",
            "escalation_temp_days",
            "log_channel_id",
            "mod_role_id",
            "admin_role_id",
            "analytics_enabled",
            "strict_ai_enabled",
            "max_warnings_before_escalation",
            "max_warnings",
            "auto_reinforcement",
            "threat_level",
            "auto_lockdown",
            "reinforcement_mode",
            "reinforcement_last_escalation",
            "reinforcement_manual_override",
        }
        filtered = {k: v for k, v in updates.items() if k in allowed}
        if not filtered:
            return await self.get_or_create_guild_config(guild_id)

        if "threat_level" in filtered:
            threat = int(filtered["threat_level"])
            filtered["threat_level"] = max(0, min(4, threat))

        if "max_warnings_before_escalation" in filtered and "max_warnings" not in filtered:
            filtered["max_warnings"] = int(filtered["max_warnings_before_escalation"])
        if "max_warnings" in filtered and "max_warnings_before_escalation" not in filtered:
            filtered["max_warnings_before_escalation"] = int(filtered["max_warnings"])

        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO guild_config (guild_id)
                VALUES ($1)
                ON CONFLICT (guild_id) DO NOTHING
                """,
                guild_id,
            )

            keys = list(filtered.keys())
            set_clause = ", ".join(f"{k} = ${i}" for i, k in enumerate(keys, start=2))
            values = [filtered[k] for k in keys]

            await conn.execute(
                f"UPDATE guild_config SET {set_clause}, updated_at = NOW() WHERE guild_id = $1",
                guild_id,
                *values,
            )

        return await self.get_or_create_guild_config(guild_id)

    async def create_infraction(
        self,
        case_id: str,
        guild_id: int,
        user_id: int,
        moderator_id: int | None,
        source: str,
        category: str,
        severity: str,
        action: str,
        risk_score: float,
        ai_confidence: float | None,
        reason: str,
        explanation: str,
        expires_at: datetime | None = None,
    ) -> None:
        normalized_action = str(action).lower()
        warning_type = normalized_action if normalized_action in {"verbal", "temp", "permanent"} else normalized_action
        confidence = float(ai_confidence) if ai_confidence is not None else None

        query = """
        INSERT INTO infractions (
            case_id,
            guild_id,
            user_id,
            moderator_id,
            source,
            category,
            warning_type,
            severity,
            action,
            risk_score,
            confidence,
            ai_confidence,
            reason,
            explanation,
            expires_at,
            active
        ) VALUES (
            $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $11, $12, $13, $14, TRUE
        )
        """
        async with self.pool.acquire() as conn:
            await conn.execute(
                query,
                case_id,
                guild_id,
                user_id,
                moderator_id,
                source,
                category,
                warning_type,
                severity.lower(),
                normalized_action,
                int(round(float(risk_score))),
                confidence,
                reason,
                explanation,
                expires_at,
            )

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
        wt = str(warning_type).lower()
        sev = str(severity).lower()
        cid = f"W-{uuid.uuid4().hex[:10].upper()}"
        await self.create_infraction(
            case_id=cid,
            guild_id=guild_id,
            user_id=user_id,
            moderator_id=None,
            source="manual",
            category="manual",
            severity=sev,
            action=wt,
            risk_score=0,
            ai_confidence=float(confidence),
            reason=reason,
            explanation=reason,
            expires_at=expires_at,
        )

    async def get_warning_counts(self, guild_id: int, user_id: int) -> dict[str, int]:
        query = """
        SELECT
            COUNT(*) FILTER (WHERE warning_type = 'verbal') AS verbal_count,
            COUNT(*) FILTER (
                WHERE warning_type = 'temp'
                AND active = TRUE
                AND (expires_at IS NULL OR expires_at > NOW())
            ) AS active_temp_count,
            COUNT(*) FILTER (WHERE warning_type = 'permanent') AS permanent_count
        FROM infractions
        WHERE guild_id = $1 AND user_id = $2
        """
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(query, guild_id, user_id)

        return {
            "verbal": int(row["verbal_count"] or 0) if row else 0,
            "temp": int(row["active_temp_count"] or 0) if row else 0,
            "permanent": int(row["permanent_count"] or 0) if row else 0,
        }

    async def get_user_infraction_counts(self, guild_id: int, user_id: int) -> dict[str, int]:
        counts = await self.get_warning_counts(guild_id, user_id)
        query = """
        SELECT COUNT(*)::INT
        FROM infractions
        WHERE guild_id = $1
          AND user_id = $2
          AND created_at >= NOW() - INTERVAL '30 days'
        """
        async with self.pool.acquire() as conn:
            recent = await conn.fetchval(query, guild_id, user_id)
        return {
            "verbal": counts["verbal"],
            "temp": counts["temp"],
            "permanent": counts["permanent"],
            "recent": int(recent or 0),
        }

    async def get_recent_warnings(self, guild_id: int, user_id: int, limit: int = 15) -> list[asyncpg.Record]:
        query = """
        SELECT id, warning_type, severity, reason, confidence, ai_confidence, expires_at, created_at
        FROM infractions
        WHERE guild_id = $1 AND user_id = $2
        ORDER BY created_at DESC
        LIMIT $3
        """
        async with self.pool.acquire() as conn:
            return await conn.fetch(query, guild_id, user_id, max(1, int(limit)))

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
        return await self.cleanup_expired_infractions()

    async def cleanup_expired_infractions(self) -> int:
        query = """
        DELETE FROM infractions
        WHERE warning_type = 'temp'
          AND expires_at IS NOT NULL
          AND expires_at <= NOW()
        """
        async with self.pool.acquire() as conn:
            status = await conn.execute(query)
        return int(status.split()[-1])

    async def auto_expire_old_cases(self) -> int:
        query = """
        UPDATE infractions
        SET active = FALSE
        WHERE active = TRUE
          AND expires_at IS NOT NULL
          AND expires_at <= NOW()
          AND warning_type IN ('temp', 'timeout')
        """
        async with self.pool.acquire() as conn:
            status = await conn.execute(query)
        return int(status.split()[-1])

    async def promote_temp_to_permanent_if_needed(self, guild_id: int, user_id: int) -> bool:
        config = await self.get_or_create_guild_config(guild_id)
        threshold = int(config["max_warnings_before_escalation"] or 5)
        count = await self.get_active_temp_warning_count(guild_id, user_id)
        if count < threshold:
            return False

        cid = f"AUTO-{uuid.uuid4().hex[:10].upper()}"
        await self.create_infraction(
            case_id=cid,
            guild_id=guild_id,
            user_id=user_id,
            moderator_id=None,
            source="system",
            category="escalation",
            severity="high",
            action="permanent",
            risk_score=0,
            ai_confidence=None,
            reason="Automatic escalation from repeated temporary warnings",
            explanation="Auto-escalation threshold reached",
            expires_at=None,
        )
        return True

    async def get_mod_stats(self, guild_id: int) -> dict[str, Any]:
        totals_query = """
        SELECT
            COUNT(*) AS total,
            COUNT(*) FILTER (WHERE warning_type = 'verbal') AS verbal,
            COUNT(*) FILTER (WHERE warning_type = 'temp') AS temp,
            COUNT(*) FILTER (
                WHERE warning_type = 'temp'
                AND active = TRUE
                AND (expires_at IS NULL OR expires_at > NOW())
            ) AS active_temp,
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
            "total": int(totals["total"] or 0) if totals else 0,
            "verbal": int(totals["verbal"] or 0) if totals else 0,
            "temp": int(totals["temp"] or 0) if totals else 0,
            "active_temp": int(totals["active_temp"] or 0) if totals else 0,
            "permanent": int(totals["permanent"] or 0) if totals else 0,
            "last_24h": int(totals["last_24h"] or 0) if totals else 0,
            "top_users": [(int(row["user_id"]), int(row["warnings"])) for row in top_users],
        }

    async def get_permanent_warning_count(self, guild_id: int, user_id: int) -> int:
        query = """
        SELECT COUNT(*)
        FROM infractions
        WHERE guild_id = $1
          AND user_id = $2
          AND warning_type = 'permanent'
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
          AND active = TRUE
          AND (expires_at IS NULL OR expires_at > NOW())
        """
        async with self.pool.acquire() as conn:
            value = await conn.fetchval(query, guild_id, user_id)
        return int(value or 0)

    async def upsert_risk(self, guild_id: int, user_id: int, risk_score: float) -> None:
        query = """
        INSERT INTO risk_scores (guild_id, user_id, risk_score, last_updated)
        VALUES ($1, $2, $3, NOW())
        ON CONFLICT (guild_id, user_id)
        DO UPDATE SET risk_score = EXCLUDED.risk_score, last_updated = NOW()
        """
        async with self.pool.acquire() as conn:
            await conn.execute(query, guild_id, user_id, float(risk_score))

    async def get_risk_row(self, guild_id: int, user_id: int) -> asyncpg.Record | None:
        query = """
        SELECT guild_id, user_id, risk_score, last_updated
        FROM risk_scores
        WHERE guild_id = $1 AND user_id = $2
        """
        async with self.pool.acquire() as conn:
            return await conn.fetchrow(query, guild_id, user_id)

    async def risk_leaderboard(self, guild_id: int, limit: int = 10) -> list[asyncpg.Record]:
        query = """
        SELECT user_id, risk_score, last_updated
        FROM risk_scores
        WHERE guild_id = $1
        ORDER BY risk_score DESC
        LIMIT $2
        """
        async with self.pool.acquire() as conn:
            return await conn.fetch(query, guild_id, max(1, int(limit)))

    async def reset_risk(self, guild_id: int, user_id: int | None = None) -> None:
        async with self.pool.acquire() as conn:
            if user_id is None:
                await conn.execute("DELETE FROM risk_scores WHERE guild_id = $1", guild_id)
            else:
                await conn.execute("DELETE FROM risk_scores WHERE guild_id = $1 AND user_id = $2", guild_id, user_id)

    async def get_case(self, guild_id: int, case_id: str) -> asyncpg.Record | None:
        query = """
        SELECT *
        FROM infractions
        WHERE guild_id = $1 AND case_id = $2
        LIMIT 1
        """
        async with self.pool.acquire() as conn:
            return await conn.fetchrow(query, guild_id, case_id)

    async def set_case_active(self, guild_id: int, case_id: str, active: bool) -> None:
        query = "UPDATE infractions SET active = $3 WHERE guild_id = $1 AND case_id = $2"
        async with self.pool.acquire() as conn:
            await conn.execute(query, guild_id, case_id, bool(active))

    async def create_appeal(
        self,
        guild_id: int,
        user_id: int,
        requested_by: int,
        note: str,
    ) -> None:
        case = await self.get_case(guild_id, note)
        case_id_value = note if case else f"NOTE-{uuid.uuid4().hex[:8].upper()}"
        query = """
        INSERT INTO appeals (case_id, guild_id, user_id, requested_by, review_note)
        VALUES ($1, $2, $3, $4, $5)
        """
        async with self.pool.acquire() as conn:
            await conn.execute(query, case_id_value, guild_id, user_id, requested_by, note)

    async def list_appeals(self, guild_id: int, status: str | None = None) -> list[asyncpg.Record]:
        async with self.pool.acquire() as conn:
            if status:
                return await conn.fetch(
                    """
                    SELECT * FROM appeals
                    WHERE guild_id = $1 AND status = $2
                    ORDER BY created_at DESC
                    """,
                    guild_id,
                    status,
                )
            return await conn.fetch(
                """
                SELECT * FROM appeals
                WHERE guild_id = $1
                ORDER BY created_at DESC
                """,
                guild_id,
            )

    async def review_appeal(
        self,
        appeal_id: int,
        guild_id: int,
        reviewer_id: int,
        status: str,
        note: str,
    ) -> asyncpg.Record | None:
        query = """
        UPDATE appeals
        SET status = $4,
            review_note = $5,
            reviewer_id = $3,
            reviewed_at = NOW()
        WHERE id = $1
          AND guild_id = $2
        RETURNING *
        """
        async with self.pool.acquire() as conn:
            return await conn.fetchrow(query, appeal_id, guild_id, reviewer_id, status, note)

    async def log_moderator_action(
        self,
        guild_id: int,
        moderator_id: int,
        action_type: str,
        case_id: str | None,
        details: dict[str, Any] | None = None,
    ) -> None:
        query = """
        INSERT INTO moderator_actions (guild_id, moderator_id, action_type, case_id, details)
        VALUES ($1, $2, $3, $4, $5::jsonb)
        """
        payload = details or {}
        async with self.pool.acquire() as conn:
            await conn.execute(query, guild_id, moderator_id, action_type, case_id, json.dumps(payload))

    async def get_server_analytics(self, guild_id: int) -> dict[str, Any]:
        query = """
        SELECT
            COUNT(*)::INT AS total,
            COUNT(*) FILTER (WHERE action = 'verbal')::INT AS verbal,
            COUNT(*) FILTER (WHERE action = 'temp')::INT AS temporary,
            COUNT(*) FILTER (WHERE action = 'permanent')::INT AS permanent,
            COUNT(*) FILTER (WHERE created_at >= NOW() - INTERVAL '24 hours')::INT AS last_24h,
            COUNT(*) FILTER (
                WHERE created_at >= NOW() - INTERVAL '48 hours'
                  AND created_at < NOW() - INTERVAL '24 hours'
            )::INT AS prev_24h,
            COUNT(*) FILTER (WHERE severity IN ('high', 'severe', 'extreme'))::INT AS high_severity,
            AVG(NULLIF(risk_score, 0))::DOUBLE PRECISION AS avg_risk
        FROM infractions
        WHERE guild_id = $1
        """
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(query, guild_id)

        payload = {
            "total": int(row["total"] or 0) if row else 0,
            "verbal": int(row["verbal"] or 0) if row else 0,
            "temporary": int(row["temporary"] or 0) if row else 0,
            "permanent": int(row["permanent"] or 0) if row else 0,
            "last_24h": int(row["last_24h"] or 0) if row else 0,
            "prev_24h": int(row["prev_24h"] or 0) if row else 0,
            "high_severity": int(row["high_severity"] or 0) if row else 0,
            "avg_risk": float(row["avg_risk"] or 0.0) if row else 0.0,
            "generated_at": self.now().isoformat(),
        }
        return payload

    async def cache_analytics(self, guild_id: int, payload: dict[str, Any]) -> None:
        query = """
        INSERT INTO analytics_cache (guild_id, payload, updated_at, generated_at)
        VALUES ($1, $2::jsonb, NOW(), NOW())
        ON CONFLICT (guild_id)
        DO UPDATE SET payload = EXCLUDED.payload, updated_at = NOW(), generated_at = NOW()
        """
        async with self.pool.acquire() as conn:
            await conn.execute(query, guild_id, json.dumps(payload))

    async def get_toxicity_trend(self, guild_id: int, hours: int = 24) -> list[tuple[str, int]]:
        capped = max(1, min(168, int(hours)))
        query = """
        SELECT
            to_char(date_trunc('hour', created_at), 'YYYY-MM-DD"T"HH24:00:00"Z"') AS hour,
            COUNT(*)::INT AS count
        FROM infractions
        WHERE guild_id = $1
          AND created_at >= NOW() - ($2::INT * INTERVAL '1 hour')
          AND (
            category <> 'benign'
            OR severity IN ('medium', 'high', 'severe', 'extreme')
            OR action IN ('temp', 'permanent', 'timeout', 'ban')
          )
        GROUP BY 1
        ORDER BY 1 ASC
        """
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(query, guild_id, capped)
        return [(str(r["hour"]), int(r["count"])) for r in rows]
