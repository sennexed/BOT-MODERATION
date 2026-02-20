from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from .utils import Action, Severity, clamp_confidence, parse_llm_json

logger = logging.getLogger(__name__)


class GroqClient:
    def __init__(self, api_key: str, model: str, timeout_seconds: float) -> None:
        self._api_key = api_key
        self._model = model
        self._timeout = timeout_seconds
        self._client = httpx.AsyncClient(
            base_url="https://api.groq.com/openai/v1",
            timeout=httpx.Timeout(timeout_seconds),
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def moderate(self, content: str) -> dict[str, Any]:
        prompt = (
            "You are a strict moderation classifier. "
            "Return JSON only with keys: severity, confidence, reasoning, recommended_action. "
            "Allowed severity: SAFE, WARNING, TOXIC, SEVERE, NSFW, SPAM, HATE, THREAT. "
            "Allowed recommended_action: none, warn, delete, timeout, kick, ban. "
            "Confidence must be float 0-1. reasoning max 200 chars."
        )

        payload = {
            "model": self._model,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": prompt},
                {
                    "role": "user",
                    "content": f"Analyze this message for policy violations: {json.dumps(content)}",
                },
            ],
        }

        response = await self._client.post(
            "/chat/completions",
            headers={"Authorization": f"Bearer {self._api_key}"},
            json=payload,
        )
        response.raise_for_status()
        data = response.json()
        content = data["choices"][0]["message"]["content"]
        parsed = parse_llm_json(content)

        severity = str(parsed.get("severity", "SAFE")).upper()
        if severity not in {item.value for item in Severity}:
            raise ValueError(f"Invalid LLM severity: {severity}")

        action = str(parsed.get("recommended_action", "none")).lower()
        if action not in {item.value for item in Action}:
            raise ValueError(f"Invalid LLM action: {action}")

        return {
            "severity": severity,
            "confidence": clamp_confidence(parsed.get("confidence")),
            "reasoning": str(parsed.get("reasoning", "")).strip()[:200],
            "recommended_action": action,
        }
