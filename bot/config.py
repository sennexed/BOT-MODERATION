from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

from dotenv import load_dotenv


@dataclass(slots=True)
class Settings:
    discord_token: str
    groq_api_key: str
    groq_model: str
    database_url: str
    redis_url: str
    log_level: str
    moderation_timeout_seconds: float
    user_llm_cooldown_seconds: int
    llm_rate_limit_per_minute: int
    spam_window_seconds: int
    spam_burst_count: int
    raid_window_seconds: int
    raid_toxic_threshold: int
    default_timeout_minutes: int
    risk_decay_per_hour: float
    risk_warn_threshold: float
    risk_delete_threshold: float
    risk_timeout_threshold: float
    risk_kick_threshold: float
    risk_ban_threshold: float
    command_guild_id: Optional[int]


def _required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise ValueError(f"Missing required environment variable: {name}")
    return value


def _int(name: str, default: int) -> int:
    value = os.getenv(name)
    return int(value) if value is not None else default


def _float(name: str, default: float) -> float:
    value = os.getenv(name)
    return float(value) if value is not None else default


def load_settings() -> Settings:
    load_dotenv()

    settings = Settings(
        discord_token=_required("DISCORD_TOKEN"),
        groq_api_key=_required("GROQ_API_KEY"),
        groq_model=os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile").strip(),
        database_url=_required("DATABASE_URL"),
        redis_url=os.getenv("REDIS_URL", "redis://localhost:6379/0").strip(),
        log_level=os.getenv("LOG_LEVEL", "INFO").upper().strip(),
        moderation_timeout_seconds=_float("MODERATION_TIMEOUT_SECONDS", 8.0),
        user_llm_cooldown_seconds=_int("USER_LLM_COOLDOWN_SECONDS", 3),
        llm_rate_limit_per_minute=_int("LLM_RATE_LIMIT_PER_MINUTE", 20),
        spam_window_seconds=_int("SPAM_WINDOW_SECONDS", 8),
        spam_burst_count=_int("SPAM_BURST_COUNT", 6),
        raid_window_seconds=_int("RAID_WINDOW_SECONDS", 15),
        raid_toxic_threshold=_int("RAID_TOXIC_THRESHOLD", 5),
        default_timeout_minutes=_int("DEFAULT_TIMEOUT_MINUTES", 30),
        risk_decay_per_hour=_float("RISK_DECAY_PER_HOUR", 1.5),
        risk_warn_threshold=_float("RISK_WARN_THRESHOLD", 3.0),
        risk_delete_threshold=_float("RISK_DELETE_THRESHOLD", 5.0),
        risk_timeout_threshold=_float("RISK_TIMEOUT_THRESHOLD", 8.0),
        risk_kick_threshold=_float("RISK_KICK_THRESHOLD", 12.0),
        risk_ban_threshold=_float("RISK_BAN_THRESHOLD", 16.0),
        command_guild_id=int(os.getenv("COMMAND_GUILD_ID", "0")) or None,
    )

    if settings.risk_decay_per_hour < 0:
        raise ValueError("RISK_DECAY_PER_HOUR must be >= 0")
    if settings.spam_burst_count < 2:
        raise ValueError("SPAM_BURST_COUNT must be >= 2")

    return settings
