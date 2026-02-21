from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta


@dataclass(slots=True)
class RaidStatus:
    suspicious: bool
    score: float
    reasons: list[str]


class RaidDetector:
    def __init__(self) -> None:
        self.join_events: dict[int, deque[datetime]] = defaultdict(deque)
        self.msg_events: dict[int, deque[datetime]] = defaultdict(deque)
        self.new_account_events: dict[int, deque[datetime]] = defaultdict(deque)
        self.usernames: dict[int, deque[str]] = defaultdict(deque)
        self.invite_hits: dict[int, deque[datetime]] = defaultdict(deque)

    def _trim(self, d: deque, now: datetime, window_sec: int) -> None:
        cutoff = now - timedelta(seconds=window_sec)
        while d and d[0] < cutoff:
            d.popleft()

    def track_join(self, guild_id: int, username: str, account_created_at: datetime) -> None:
        now = datetime.now(UTC)
        self.join_events[guild_id].append(now)
        self.usernames[guild_id].append(username.lower())
        if now - account_created_at < timedelta(days=10):
            self.new_account_events[guild_id].append(now)

    def track_message(self, guild_id: int, contains_invite: bool) -> None:
        now = datetime.now(UTC)
        self.msg_events[guild_id].append(now)
        if contains_invite:
            self.invite_hits[guild_id].append(now)

    def evaluate(self, guild_id: int) -> RaidStatus:
        now = datetime.now(UTC)
        joins = self.join_events[guild_id]
        msgs = self.msg_events[guild_id]
        new_acc = self.new_account_events[guild_id]
        names = self.usernames[guild_id]
        invites = self.invite_hits[guild_id]

        self._trim(joins, now, 120)
        self._trim(msgs, now, 40)
        self._trim(new_acc, now, 300)
        self._trim(invites, now, 120)
        while len(names) > 80:
            names.popleft()

        reasons: list[str] = []
        score = 0.0

        if len(joins) >= 8:
            reasons.append("join_burst")
            score += 0.7
        if len(msgs) >= 50:
            reasons.append("message_burst")
            score += 0.6
        if len(new_acc) >= 6:
            reasons.append("new_account_wave")
            score += 0.6
        if len(invites) >= 8:
            reasons.append("invite_spam_spike")
            score += 0.8

        if len(names) >= 10:
            prefix_count: dict[str, int] = {}
            for n in list(names)[-30:]:
                prefix = n[:4]
                prefix_count[prefix] = prefix_count.get(prefix, 0) + 1
            if max(prefix_count.values(), default=0) >= 7:
                reasons.append("similar_usernames")
                score += 0.5

        return RaidStatus(suspicious=score >= 1.0, score=min(score, 3.0), reasons=reasons)

    def multiplier(self, guild_id: int) -> float:
        status = self.evaluate(guild_id)
        if not status.suspicious:
            return 1.0
        return min(2.2, 1.0 + (status.score * 0.35))
