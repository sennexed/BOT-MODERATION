from __future__ import annotations

import json
import logging
import re
import unicodedata
from dataclasses import dataclass
from enum import Enum
from typing import Any


ZERO_WIDTH_RE = re.compile(r"[\u200B-\u200F\u202A-\u202E\u2060\uFEFF]")
MULTISPACE_RE = re.compile(r"\s+")
CHAR_SPLIT_RE = re.compile(r"\b(?:[a-zA-Z]\s){3,}[a-zA-Z]\b")
REPEATED_CHAR_RE = re.compile(r"([a-zA-Z])\1{3,}")
LEET_TOKEN_RE = re.compile(r"(?i)\b(?=[a-z0-9]*\d)[a-z0-9]{3,}\b")

LEET_MAP = str.maketrans({"0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "7": "t", "8": "b"})
HOMOGLYPH_MAP = str.maketrans(
    {
        "а": "a",
        "е": "e",
        "і": "i",
        "о": "o",
        "р": "p",
        "с": "c",
        "х": "x",
        "у": "y",
        "Α": "A",
        "Β": "B",
        "Ε": "E",
        "Η": "H",
        "Ι": "I",
        "Κ": "K",
        "Μ": "M",
        "Ν": "N",
        "Ο": "O",
        "Ρ": "P",
        "Τ": "T",
        "Χ": "X",
    }
)


class Severity(str, Enum):
    SAFE = "SAFE"
    WARNING = "WARNING"
    TOXIC = "TOXIC"
    SEVERE = "SEVERE"
    HATE = "HATE"
    THREAT = "THREAT"
    NSFW = "NSFW"
    SPAM = "SPAM"


class WarningType(str, Enum):
    VERBAL = "verbal"
    TEMP = "temp"
    PERMANENT = "permanent"


class RecommendedAction(str, Enum):
    NONE = "none"
    VERBAL = "verbal"
    TEMP = "temp"
    PERMANENT = "permanent"


@dataclass(slots=True)
class ModerationDecision:
    severity: Severity
    confidence: float
    reasoning: str
    action: RecommendedAction
    normalized_text: str
    bypass_flags: list[str]
    risk_score: float


def normalize_content(text: str) -> str:
    text = ZERO_WIDTH_RE.sub("", text)
    text = unicodedata.normalize("NFKC", text)
    text = text.translate(HOMOGLYPH_MAP)
    text = text.lower().translate(LEET_MAP)
    text = REPEATED_CHAR_RE.sub(lambda m: m.group(1) * 2, text)
    return MULTISPACE_RE.sub(" ", text).strip()


def detect_bypass_attempts(original_text: str, normalized_text: str) -> list[str]:
    flags: list[str] = []

    if original_text != ZERO_WIDTH_RE.sub("", original_text):
        flags.append("zero_width")
    if CHAR_SPLIT_RE.search(original_text):
        flags.append("character_splitting")
    if REPEATED_CHAR_RE.search(original_text):
        flags.append("repeated_characters")

    nfkc = unicodedata.normalize("NFKC", original_text)
    if nfkc.translate(HOMOGLYPH_MAP).lower() != nfkc.lower():
        flags.append("homoglyph")

    if LEET_TOKEN_RE.search(original_text):
        flags.append("leet")

    return sorted(set(flags))


def clamp_confidence(value: Any) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, v))


def parse_llm_json(raw: str) -> dict[str, Any]:
    raw = raw.strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        start = raw.find("{")
        end = raw.rfind("}")
        if start < 0 or end < 0 or end <= start:
            raise ValueError("LLM response did not contain valid JSON")
        return json.loads(raw[start : end + 1])


def setup_structured_logging(level: str) -> None:
    class JsonFormatter(logging.Formatter):
        def format(self, record: logging.LogRecord) -> str:
            payload = {
                "time": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
                "level": record.levelname,
                "logger": record.name,
                "message": record.getMessage(),
            }
            if record.exc_info:
                payload["exception"] = self.formatException(record.exc_info)
            return json.dumps(payload, ensure_ascii=True)

    root = logging.getLogger()
    root.handlers.clear()
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root.addHandler(handler)
    root.setLevel(getattr(logging, level, logging.INFO))
