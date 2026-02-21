from __future__ import annotations

import json
from dataclasses import dataclass

import httpx


@dataclass(slots=True)
class AIResult:
    category: str
    severity: str
    confidence: float
    explanation: str


class GroqClient:
    def __init__(self, api_key: str, model: str, timeout: float) -> None:
        self._api_key = api_key
        self._model = model
        self._client = httpx.AsyncClient(
            base_url="https://api.groq.com/openai/v1",
            timeout=httpx.Timeout(timeout),
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def classify(self, content: str) -> AIResult:
        system = (
            "You are a Discord safety classification engine. Return strict JSON with keys: "
            "category, severity, confidence, explanation. "
            "Category options: harassment, hate, threat, sexual, spam, scam, self-harm, benign. "
            "Severity options: low, medium, high, extreme. "
            "Confidence is 0..1. Explanation is concise and policy-focused."
        )
        payload = {
            "model": self._model,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": content[:1800]},
            ],
        }
        response = await self._client.post(
            "/chat/completions",
            headers={"Authorization": f"Bearer {self._api_key}"},
            json=payload,
        )
        response.raise_for_status()
        raw = response.json()["choices"][0]["message"]["content"]
        data = json.loads(raw)

        category = str(data.get("category", "benign")).lower()
        severity = str(data.get("severity", "low")).lower()
        confidence = float(data.get("confidence", 0.0))
        explanation = str(data.get("explanation", "No explanation provided.")).strip()

        if category not in {"harassment", "hate", "threat", "sexual", "spam", "scam", "self-harm", "benign"}:
            category = "benign"
        if severity not in {"low", "medium", "high", "extreme"}:
            severity = "low"

        confidence = max(0.0, min(1.0, confidence))
        return AIResult(category=category, severity=severity, confidence=confidence, explanation=explanation[:600])
