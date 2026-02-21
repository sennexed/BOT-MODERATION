from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import httpx

from .utils import RecommendedAction, Severity, clamp_confidence, parse_llm_json

logger = logging.getLogger(__name__)


class GroqClient:
    def __init__(self, api_key: str, model: str, timeout_seconds: float) -> None:
        self._api_key = api_key
        self._model = model
        self._timeout_seconds = timeout_seconds
        self._client = httpx.AsyncClient(
            base_url="https://api.groq.com/openai/v1",
            timeout=httpx.Timeout(timeout_seconds),
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def moderate(self, content: str) -> dict[str, Any]:
        last_error: Exception | None = None
        for attempt in (1, 2):
            try:
                return await self._moderate_once(content)
            except (ValueError, KeyError, json.JSONDecodeError) as exc:
                last_error = exc
                logger.warning("Malformed Groq JSON on attempt %s", attempt)
        if last_error is not None:
            raise last_error
        raise RuntimeError("Unexpected moderation failure")

    async def _moderate_once(self, content: str) -> dict[str, Any]:
        prompt = (
            "You are a strict moderation classifier. Return JSON only with exactly these keys: "
            "severity, confidence, reasoning, recommended_action. "
            "Allowed severity values: SAFE, WARNING, TOXIC, SEVERE, HATE, THREAT, NSFW, SPAM. "
            "Allowed recommended_action values: verbal, temp, permanent, none. "
            "confidence must be a number between 0 and 1. "
            "reasoning must be short and concise."
        )

        payload = {
            "model": self._model,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": prompt},
                {"role": "user", "content": f"Moderate this message: {json.dumps(content)}"},
            ],
        }

        async with asyncio.timeout(self._timeout_seconds):
            response = await self._client.post(
                "/chat/completions",
                headers={"Authorization": f"Bearer {self._api_key}"},
                json=payload,
            )
        response.raise_for_status()
        data = response.json()
        raw_text = data["choices"][0]["message"]["content"]
        parsed = parse_llm_json(raw_text)

        required = {"severity", "confidence", "reasoning", "recommended_action"}
        if not required.issubset(parsed.keys()):
            raise ValueError("Missing required moderation JSON keys")

        severity = str(parsed["severity"]).upper()
        if severity not in {x.value for x in Severity}:
            raise ValueError(f"Invalid severity: {severity}")

        action = str(parsed["recommended_action"]).lower()
        if action not in {x.value for x in RecommendedAction}:
            raise ValueError(f"Invalid recommended_action: {action}")

        return {
            "severity": severity,
            "confidence": clamp_confidence(parsed["confidence"]),
            "reasoning": str(parsed["reasoning"]).strip()[:220],
            "recommended_action": action,
        }
