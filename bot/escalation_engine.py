from dataclasses import dataclass


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
            return EscalationDecision("timeout", "timeout", 48, "Risk exceeded 90")

        if sev == "extreme":
            return EscalationDecision("ban", "ban", None, "Extreme severity")

        if sev == "high" and risk_score >= 80:
            return EscalationDecision("permanent", "permanent", None, "High severity")

        if verbal_count < 1:
            return EscalationDecision("verbal", "verbal", None, "Initial warning")

        return EscalationDecision("temp", "temp", 24, "Temporary strike")
