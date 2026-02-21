from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime


SEVERITY_WEIGHT = {
    "low": 8.0,
    "medium": 20.0,
    "high": 34.0,
    "extreme": 50.0,
}


@dataclass(slots=True)
class RiskInput:
    current_risk: float
    last_updated: datetime | None
    now: datetime
    infractions_recent: int
    ai_severity: str
    ai_confidence: float
    message_burst_factor: float
    raid_multiplier: float
    rule_score: int


class RiskEngine:
    def __init__(self, decay_per_hour: float) -> None:
        self.decay_per_hour = decay_per_hour

    def decay(self, risk: float, last_updated: datetime | None, now: datetime) -> float:
        if last_updated is None:
            return max(0.0, risk)
        delta_hours = max((now - last_updated).total_seconds() / 3600.0, 0.0)
        return max(0.0, risk - (delta_hours * self.decay_per_hour))

    def compute(self, data: RiskInput) -> int:
        decayed = self.decay(data.current_risk, data.last_updated, data.now)
        severity_base = SEVERITY_WEIGHT.get(data.ai_severity.lower(), 0.0)
        historical_weight = min(20.0, data.infractions_recent * 4.0)
        confidence_multiplier = 0.65 + max(0.0, min(1.0, data.ai_confidence))
        burst_weight = min(20.0, data.message_burst_factor * 8.0)
        raid_weight = max(1.0, data.raid_multiplier)

        raw = (
            decayed
            + historical_weight
            + (severity_base + data.rule_score) * confidence_multiplier
            + burst_weight
        ) * raid_weight

        return int(max(0.0, min(100.0, raw)))

    @staticmethod
    def now() -> datetime:
        return datetime.now(UTC)
