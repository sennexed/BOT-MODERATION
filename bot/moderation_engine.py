from __future__ import annotations

import logging

from .cache import Cache
from .config import Settings
from .groq_client import GroqClient
from .utils import (
    ModerationDecision,
    RecommendedAction,
    Severity,
    detect_bypass_attempts,
    normalize_content,
)

logger = logging.getLogger(__name__)


SEVERITY_TO_ACTION: dict[Severity, RecommendedAction] = {
    Severity.SAFE: RecommendedAction.NONE,
    Severity.WARNING: RecommendedAction.VERBAL,
    Severity.TOXIC: RecommendedAction.TEMP,
    Severity.NSFW: RecommendedAction.TEMP,
    Severity.SPAM: RecommendedAction.TEMP,
    Severity.SEVERE: RecommendedAction.PERMANENT,
    Severity.HATE: RecommendedAction.PERMANENT,
    Severity.THREAT: RecommendedAction.PERMANENT,
}

ACTION_RANK = {
    RecommendedAction.NONE: 0,
    RecommendedAction.VERBAL: 1,
    RecommendedAction.TEMP: 2,
    RecommendedAction.PERMANENT: 3,
}


class ModerationEngine:
    def __init__(self, settings: Settings, groq: GroqClient, cache: Cache) -> None:
        self._settings = settings
        self._groq = groq
        self._cache = cache

    async def moderate_message(
        self,
        guild_id: int,
        user_id: int,
        content: str,
        confidence_threshold: float,
        active_temp_count: int,
        permanent_count: int,
        risk_score: float,
    ) -> ModerationDecision:
        normalized = normalize_content(content)
        bypass_flags = detect_bypass_attempts(content, normalized)

        rate_key = f"ratelimit:groq:{guild_id}:{user_id}"
        if await self._cache.is_rate_limited(rate_key, self._settings.groq_rate_limit_per_minute, 60):
            return ModerationDecision(
                severity=Severity.SPAM,
                confidence=1.0,
                reasoning="Groq call rate limit exceeded for user",
                action=RecommendedAction.TEMP,
                normalized_text=normalized,
                bypass_flags=sorted(set(bypass_flags + ["groq_rate_limit"])),
                risk_score=risk_score,
            )

        llm = await self._groq.moderate(normalized)

        severity = Severity(llm["severity"])
        confidence = float(llm["confidence"])
        reasoning = str(llm["reasoning"])
        recommended_action = RecommendedAction(llm["recommended_action"])

        base_action = SEVERITY_TO_ACTION[severity]
        action = max(base_action, recommended_action, key=lambda a: ACTION_RANK[a])

        if confidence < confidence_threshold and action != RecommendedAction.NONE:
            action = RecommendedAction.VERBAL
            reasoning = f"Low-confidence downgrade ({confidence:.2f}<{confidence_threshold:.2f}). {reasoning}"

        if risk_score >= self._settings.risk_permanent_threshold and action == RecommendedAction.TEMP:
            action = RecommendedAction.PERMANENT
            reasoning = f"Risk escalation to permanent (risk={risk_score:.2f}). {reasoning}"
        elif risk_score >= self._settings.risk_temp_threshold and action == RecommendedAction.VERBAL:
            action = RecommendedAction.TEMP
            reasoning = f"Risk escalation to temp (risk={risk_score:.2f}). {reasoning}"

        if permanent_count >= 4 and action in {RecommendedAction.VERBAL, RecommendedAction.TEMP}:
            action = RecommendedAction.PERMANENT
            reasoning = f"Escalated due to existing 4 permanent warnings. {reasoning}"

        if active_temp_count >= 3 and action == RecommendedAction.VERBAL:
            action = RecommendedAction.TEMP
            reasoning = f"Escalated due to existing 3 active temp warnings. {reasoning}"

        if len(bypass_flags) >= 3 and action == RecommendedAction.VERBAL:
            action = RecommendedAction.TEMP
            reasoning = f"Escalated due to bypass indicators ({', '.join(bypass_flags)}). {reasoning}"

        return ModerationDecision(
            severity=severity,
            confidence=confidence,
            reasoning=reasoning,
            action=action,
            normalized_text=normalized,
            bypass_flags=bypass_flags,
            risk_score=risk_score,
        )
