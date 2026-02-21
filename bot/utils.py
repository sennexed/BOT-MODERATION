from __future__ import annotations

import base64
import binascii
import json
import logging
import re
import unicodedata
from dataclasses import dataclass
from enum import Enum
from typing import Any


ZERO_WIDTH_RE = re.compile(r"[\u200B-\u200F\u202A-\u202E\u2060\uFEFF]")
WHITESPACE_RE = re.compile(r"\s+")
CHAR_SPLIT_RE = re.compile(r"\b(?:[a-zA-Z]\s){3,}[a-zA-Z]\b")
REPEATED_SYMBOL_RE = re.compile(r"([^\w\s])\1{4,}")
BASE64_TOKEN_RE = re.compile(r"\b[A-Za-z0-9+/]{16,}={0,2}\b")

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

THREAT_WORDS = {"kill", "shoot", "bomb", "stab", "murder", "dox", "swat"}
HATE_WORDS = {"nazi", "racial", "genocide", "slur", "supremacist"}
NSFW_WORDS = {"nude", "porn", "nsfw", "explicit", "xxx"}
TOXIC_WORDS = {"idiot", "stupid", "trash", "loser", "moron"}
SPAM_WORDS = {"free nitro", "airdrop", "click here", "subscribe", "buy now"}
SEVERE_WORDS = {"self harm", "suicide", "terror", "rape"}


class Severity(str, Enum):
    SAFE = "SAFE"
    WARNING = "WARNING"
    TOXIC = "TOXIC"
    SEVERE = "SEVERE"
    NSFW = "NSFW"
    SPAM = "SPAM"
    HATE = "HATE"
    THREAT = "THREAT"


class Action(str, Enum):
    NONE = "none"
    WARN = "warn"
    DELETE = "delete"
    TIMEOUT = "timeout"
    KICK = "kick"
    BAN = "ban"


@dataclass(slots=True)
class ModerationResult:
    severity: Severity
    confidence: float
    reasoning: str
    recommended_action: Action
    normalized_text: str
    bypass_flags: list[str]
    used_fallback: bool


def normalize_content(text: str) -> str:
    cleaned = ZERO_WIDTH_RE.sub("", text)
    normalized = unicodedata.normalize("NFKC", cleaned).translate(HOMOGLYPH_MAP)
    lowered = normalized.lower()
    return WHITESPACE_RE.sub(" ", lowered).strip()


def detect_bypass_attempts(original_text: str, normalized_text: str) -> list[str]:
    flags: list[str] = []

    if original_text != ZERO_WIDTH_RE.sub("", original_text):
        flags.append("invisible_characters")
    if CHAR_SPLIT_RE.search(original_text):
        flags.append("character_splitting")
    if REPEATED_SYMBOL_RE.search(original_text):
        flags.append("repeated_symbols")
    transformed = unicodedata.normalize("NFKC", ZERO_WIDTH_RE.sub("", original_text)).translate(HOMOGLYPH_MAP)
    if transformed.lower() != ZERO_WIDTH_RE.sub("", original_text).lower():
        flags.append("unicode_homoglyph")

    non_ascii = sum(1 for ch in original_text if ord(ch) > 127)
    if original_text and non_ascii / len(original_text) > 0.35:
        flags.append("unicode_abuse")

    if _contains_base64_harassment(normalized_text):
        flags.append("base64_obfuscation")

    return sorted(set(flags))


def _contains_base64_harassment(text: str) -> bool:
    for token in BASE64_TOKEN_RE.findall(text):
        try:
            decoded = base64.b64decode(token + "==", validate=False)
            plain = decoded.decode("utf-8", errors="ignore").lower()
        except (binascii.Error, UnicodeDecodeError):
            continue
        if any(word in plain for word in THREAT_WORDS | HATE_WORDS | TOXIC_WORDS):
            return True
    return False


def heuristic_moderation(normalized_text: str, bypass_flags: list[str]) -> tuple[Severity, float, str, Action]:
    if any(word in normalized_text for word in THREAT_WORDS):
        return Severity.THREAT, 0.92, "Threatening language detected by fallback heuristic", Action.BAN
    if any(word in normalized_text for word in HATE_WORDS):
        return Severity.HATE, 0.89, "Potential hate content detected by fallback heuristic", Action.KICK
    if any(word in normalized_text for word in SEVERE_WORDS):
        return Severity.SEVERE, 0.86, "Severe policy violation detected by fallback heuristic", Action.TIMEOUT
    if any(word in normalized_text for word in NSFW_WORDS):
        return Severity.NSFW, 0.83, "NSFW content detected by fallback heuristic", Action.DELETE
    if any(word in normalized_text for word in SPAM_WORDS):
        return Severity.SPAM, 0.8, "Spam pattern detected by fallback heuristic", Action.DELETE
    if any(word in normalized_text for word in TOXIC_WORDS):
        return Severity.TOXIC, 0.74, "Toxic language detected by fallback heuristic", Action.WARN
    if bypass_flags:
        return Severity.WARNING, 0.7, "Bypass attempt indicators detected", Action.WARN
    return Severity.SAFE, 0.99, "No policy concerns detected", Action.NONE


def parse_llm_json(raw_content: str) -> dict[str, Any]:
    raw_content = raw_content.strip()
    try:
        return json.loads(raw_content)
    except json.JSONDecodeError:
        start = raw_content.find("{")
        end = raw_content.rfind("}")
        if start == -1 or end == -1 or start >= end:
            raise ValueError("LLM output did not contain JSON object")
        return json.loads(raw_content[start : end + 1])


def clamp_confidence(value: Any) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, numeric))


def setup_structured_logging(level: str) -> None:
    class JsonFormatter(logging.Formatter):
        def format(self, record: logging.LogRecord) -> str:
            payload = {
                "level": record.levelname,
                "logger": record.name,
                "message": record.getMessage(),
                "time": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
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
