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
