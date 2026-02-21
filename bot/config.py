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
    groq_timeout_seconds: float
    groq_rate_limit_per_minute: int
    default_confidence_threshold: float
    default_sensitivity: float
    risk_decay_per_hour: float
    risk_temp_threshold: float
    risk_permanent_threshold: float
    temp_warning_days: int
    timeout_hours: int
    command_guild_id: Optional[int]
    mod_alert_channel_id: Optional[int]


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


def _optional_int(name: str) -> Optional[int]:
    value = os.getenv(name, "").strip()
    if not value:
        return None
    return int(value)


def load_settings() -> Settings:
    load_dotenv()

    settings = Settings(
        discord_token=_required("DISCORD_TOKEN"),
        groq_api_key=_required("GROQ_API_KEY"),
        groq_model=os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile").strip(),
        database_url=_required("DATABASE_URL"),
        redis_url=os.getenv("REDIS_URL", "redis://localhost:6379/0").strip(),
        log_level=os.getenv("LOG_LEVEL", "INFO").upper().strip(),
        groq_timeout_seconds=_float("GROQ_TIMEOUT_SECONDS", 3.0),
        groq_rate_limit_per_minute=_int("GROQ_RATE_LIMIT_PER_MINUTE", 15),
        default_confidence_threshold=_float("DEFAULT_CONFIDENCE_THRESHOLD", 0.65),
        default_sensitivity=_float("DEFAULT_SENSITIVITY", 0.65),
        risk_decay_per_hour=_float("RISK_DECAY_PER_HOUR", 0.3),
        risk_temp_threshold=_float("RISK_TEMP_THRESHOLD", 4.0),
        risk_permanent_threshold=_float("RISK_PERMANENT_THRESHOLD", 8.0),
        temp_warning_days=_int("TEMP_WARNING_DAYS", 30),
        timeout_hours=_int("TIMEOUT_HOURS", 48),
        command_guild_id=_optional_int("COMMAND_GUILD_ID"),
        mod_alert_channel_id=_optional_int("MOD_ALERT_CHANNEL_ID"),
    )

    if not 0 <= settings.default_confidence_threshold <= 1:
        raise ValueError("DEFAULT_CONFIDENCE_THRESHOLD must be between 0 and 1")
    if not 0 <= settings.default_sensitivity <= 1:
        raise ValueError("DEFAULT_SENSITIVITY must be between 0 and 1")
    if settings.groq_timeout_seconds <= 0:
        raise ValueError("GROQ_TIMEOUT_SECONDS must be > 0")

    return settings
