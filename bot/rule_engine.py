from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass


INVITE_RE = re.compile(r"(?:discord(?:\.gg|(?:app)?\.com/invite))/[\w-]+", re.IGNORECASE)
URL_RE = re.compile(r"https?://", re.IGNORECASE)
ZALGO_RE = re.compile(r"[\u0300-\u036f\u0483-\u0489\u0591-\u05bd\u05bf\u05c1-\u05c2\u05c4-\u05c5\u0610-\u061a]+")


@dataclass(slots=True)
class RuleResult:
    flagged: bool
    triggers: list[str]
    score: int


class RuleEngine:
    def __init__(self, keywords: list[str] | None = None, regex_patterns: list[str] | None = None) -> None:
        self.keywords = {k.lower() for k in (keywords or ["kys", "dox", "swat", "nazi", "kill yourself"]) }
        self.regex_filters = [re.compile(p, re.IGNORECASE) for p in (regex_patterns or [r"\b(?:slur1|slur2)\b"]) ]

    def evaluate(self, content: str) -> RuleResult:
        text = content.strip()
        lower = text.lower()
        triggers: list[str] = []
        score = 0

        if any(k in lower for k in self.keywords):
            triggers.append("keyword_filter")
            score += 16

        if any(r.search(text) for r in self.regex_filters):
            triggers.append("regex_filter")
            score += 20

        letters = [c for c in text if c.isalpha()]
        if len(letters) >= 12:
            cap_ratio = sum(1 for c in letters if c.isupper()) / len(letters)
            if cap_ratio > 0.78:
                triggers.append("caps_spam")
                score += 10

        mention_count = text.count("<@")
        if mention_count >= 6:
            triggers.append("mention_spam")
            score += min(18, mention_count)

        emoji_count = sum(1 for c in text if unicodedata.category(c) == "So")
        if emoji_count >= 10:
            triggers.append("emoji_spam")
            score += min(16, emoji_count // 2)

        if INVITE_RE.search(text):
            triggers.append("invite_link")
            score += 20

        if ZALGO_RE.search(text):
            combining = sum(1 for c in text if unicodedata.combining(c) > 0)
            if combining >= 6:
                triggers.append("zalgo_text")
                score += 15

        exclamation_spam = text.count("!") >= 10 and len(text) <= 180
        if exclamation_spam and URL_RE.search(text):
            triggers.append("link_spam")
            score += 10

        return RuleResult(flagged=bool(triggers), triggers=triggers, score=min(score, 100))
