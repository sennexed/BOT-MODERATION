from __future__ import annotations

from dataclasses import dataclass


STATE_ORDER = ["safe", "monitor", "verbal", "temp", "permanent", "timeout", "ban"]


@dataclass(slots=True)
class EscalationDecision:
    state: str
    action: str
    duration_hours: int | None
    reason: str


class EscalationEngine:
    def choose_action(
        self,
        *,
        risk_score: int,
        verbal_count: int,
        active_temp_count: int,
        permanent_count: int,
        ai_severity: str,
    ) -> EscalationDecision:
        sev = ai_severity.lower()

        if risk_score > 90:
            return EscalationDecision("timeout", "timeout", 48, "Risk score exceeded 90")

        if permanent_count >= 5:
            return EscalationDecision("timeout", "timeout", 48, "Five permanent infractions reached")

        if active_temp_count >= 4:
            return EscalationDecision("permanent", "permanent", None, "Four active temp infractions converted")

        if sev == "extreme":
            return EscalationDecision("ban", "ban", None, "Extreme severity content")
        if sev == "high" and risk_score >= 80:
            return EscalationDecision("permanent", "permanent", None, "High severity with elevated risk")

        if verbal_count < 1:
            return EscalationDecision("verbal", "verbal", None, "Initial policy verbal warning")

        return EscalationDecision("temp", "temp", 24 * 30, "Second policy strike issued as temp")
