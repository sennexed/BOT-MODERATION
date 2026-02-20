from __future__ import annotations

import logging

from .anti_spam import AntiSpam
from .cache import Cache
from .config import Settings
from .groq_client import GroqClient
from .utils import Action, ModerationResult, Severity, detect_bypass_attempts, heuristic_moderation, normalize_content

logger = logging.getLogger(__name__)


class ModerationEngine:
    def __init__(self, settings: Settings, groq: GroqClient, cache: Cache, anti_spam: AntiSpam) -> None:
        self._settings = settings
        self._groq = groq
        self._cache = cache
        self._anti_spam = anti_spam

    async def analyze_message(self, guild_id: int, user_id: int, content: str) -> ModerationResult:
        # Defense-in-depth: normalize + bypass detection + spam checks + cooldown/rate-limit + LLM/fallback.
        normalized = normalize_content(content)
        bypass_flags = detect_bypass_attempts(content, normalized)

        if await self._anti_spam.detect_user_burst(guild_id, user_id):
            return ModerationResult(
                severity=Severity.SPAM,
                confidence=0.95,
                reasoning="Burst message spam detected",
                recommended_action=Action.DELETE,
                normalized_text=normalized,
                bypass_flags=sorted(set(bypass_flags + ["spam_burst"])),
                used_fallback=True,
            )

        cooldown_key = f"cooldown:user:{guild_id}:{user_id}"
        if not await self._cache.set_if_not_exists(
            cooldown_key, "1", ex=self._settings.user_llm_cooldown_seconds
        ):
            sev, conf, reason, action = heuristic_moderation(normalized, bypass_flags)
            return ModerationResult(
                severity=sev,
                confidence=conf,
                reasoning=f"Cooldown active; heuristic used. {reason}",
                recommended_action=action,
                normalized_text=normalized,
                bypass_flags=bypass_flags,
                used_fallback=True,
            )

        rate_key = f"ratelimit:llm:{guild_id}:{user_id}"
        if await self._cache.is_rate_limited(rate_key, self._settings.llm_rate_limit_per_minute, 60):
            sev, conf, reason, action = heuristic_moderation(normalized, bypass_flags)
            return ModerationResult(
                severity=Severity.SPAM,
                confidence=max(conf, 0.9),
                reasoning=f"LLM rate limit hit. {reason}",
                recommended_action=Action.DELETE,
                normalized_text=normalized,
                bypass_flags=sorted(set(bypass_flags + ["llm_rate_limited"])),
                used_fallback=True,
            )

        try:
            llm = await self._groq.moderate(normalized)
            return ModerationResult(
                severity=Severity(llm["severity"]),
                confidence=float(llm["confidence"]),
                reasoning=llm["reasoning"],
                recommended_action=Action(llm["recommended_action"]),
                normalized_text=normalized,
                bypass_flags=bypass_flags,
                used_fallback=False,
            )
        except Exception:
            logger.exception("Groq moderation failed; using fallback")
            sev, conf, reason, action = heuristic_moderation(normalized, bypass_flags)
            return ModerationResult(
                severity=sev,
                confidence=conf,
                reasoning=f"Fallback due to LLM failure. {reason}",
                recommended_action=action,
                normalized_text=normalized,
                bypass_flags=bypass_flags,
                used_fallback=True,
            )
