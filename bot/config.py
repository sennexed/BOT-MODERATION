from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv


@dataclass(slots=True)
class Settings:
    discord_token: str
    database_url: str
    groq_api_key: str
    groq_model: str
    groq_timeout_seconds: float
    log_level: str
    command_guild_id: int | None
    default_ai_sensitivity: float
    default_confidence_threshold: float
    default_temp_days: int
    risk_decay_per_hour: float


def _required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise ValueError(f"Missing required environment variable: {name}")
    return value


def _as_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    return float(raw) if raw is not None else default


def _as_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    return int(raw) if raw is not None else default


def _opt_int(name: str) -> int | None:
    raw = os.getenv(name, "").strip()
    return int(raw) if raw else None


def load_settings() -> Settings:
    load_dotenv()
    settings = Settings(
        discord_token=_required("DISCORD_TOKEN"),
        database_url=_required("DATABASE_URL"),
        groq_api_key=_required("GROQ_API_KEY"),
        groq_model=os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile").strip(),
        groq_timeout_seconds=_as_float("GROQ_TIMEOUT_SECONDS", 8.0),
        log_level=os.getenv("LOG_LEVEL", "INFO").upper().strip(),
        command_guild_id=_opt_int("COMMAND_GUILD_ID"),
        default_ai_sensitivity=_as_float("DEFAULT_AI_SENSITIVITY", 0.55),
        default_confidence_threshold=_as_float("DEFAULT_CONFIDENCE_THRESHOLD", 0.60),
        default_temp_days=_as_int("DEFAULT_TEMP_DAYS", 30),
        risk_decay_per_hour=_as_float("RISK_DECAY_PER_HOUR", 1.0),
    )
    if not 0.0 <= settings.default_ai_sensitivity <= 1.0:
        raise ValueError("DEFAULT_AI_SENSITIVITY must be in [0, 1]")
    if not 0.0 <= settings.default_confidence_threshold <= 1.0:
        raise ValueError("DEFAULT_CONFIDENCE_THRESHOLD must be in [0, 1]")
    if settings.groq_timeout_seconds <= 0:
        raise ValueError("GROQ_TIMEOUT_SECONDS must be > 0")
    if settings.default_temp_days <= 0:
        raise ValueError("DEFAULT_TEMP_DAYS must be > 0")
    return settings
