CREATE TABLE IF NOT EXISTS infractions (
    id SERIAL PRIMARY KEY,
    guild_id BIGINT NOT NULL,
    user_id BIGINT NOT NULL,
    severity TEXT NOT NULL,
    action TEXT NOT NULL,
    confidence REAL,
    reasoning TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_infractions_guild_user
ON infractions (guild_id, user_id, created_at DESC);
