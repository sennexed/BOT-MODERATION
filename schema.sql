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

CREATE TABLE IF NOT EXISTS risk_scores (
    guild_id BIGINT NOT NULL,
    user_id BIGINT NOT NULL,
    risk_score DOUBLE PRECISION NOT NULL DEFAULT 0,
    last_updated TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (guild_id, user_id)
);

CREATE TABLE IF NOT EXISTS moderator_actions (
    id BIGSERIAL PRIMARY KEY,
    guild_id BIGINT NOT NULL,
    moderator_id BIGINT NOT NULL,
    action_type TEXT NOT NULL,
    case_id TEXT,
    details JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS analytics_cache (
    guild_id BIGINT PRIMARY KEY,
    payload JSONB NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    generated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_infractions_guild_user ON infractions (guild_id, user_id);
CREATE INDEX IF NOT EXISTS idx_infractions_guild_created ON infractions (guild_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_appeals_guild_user ON appeals (guild_id, user_id);
CREATE INDEX IF NOT EXISTS idx_risk_scores_guild_user ON risk_scores (guild_id, user_id);
CREATE INDEX IF NOT EXISTS idx_mod_actions_guild_user ON moderator_actions (guild_id, moderator_id);
