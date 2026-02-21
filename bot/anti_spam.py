from __future__ import annotations

import time

from .cache import Cache


class AntiSpam:
    def __init__(
        self,
        cache: Cache,
        spam_window_seconds: int,
        spam_burst_count: int,
        raid_window_seconds: int,
        raid_toxic_threshold: int,
    ) -> None:
        self._cache = cache
        self._spam_window_seconds = spam_window_seconds
        self._spam_burst_count = spam_burst_count
        self._raid_window_seconds = raid_window_seconds
        self._raid_toxic_threshold = raid_toxic_threshold

    async def detect_user_burst(self, guild_id: int, user_id: int) -> bool:
        key = f"spam:user:{guild_id}:{user_id}"
        now = time.time()
        _, is_spam = await self._cache.add_timestamp_and_count(
            key, now, self._spam_window_seconds, self._spam_burst_count
        )
        return is_spam

    async def mark_toxic_and_check_raid(
        self, guild_id: int, channel_id: int, threshold: int | None = None, window: int | None = None
    ) -> bool:
        key = f"raid:channel:{guild_id}:{channel_id}"
        now = time.time()
        raid_window = window if window is not None else self._raid_window_seconds
        raid_threshold = threshold if threshold is not None else self._raid_toxic_threshold
        _, raid = await self._cache.add_timestamp_and_count(
            key, now, raid_window, raid_threshold
        )
        return raid

    async def set_lockdown_enabled(self, guild_id: int, enabled: bool) -> None:
        await self._cache.set_json(f"lockdown:enabled:{guild_id}", {"enabled": enabled}, ex=86400 * 30)

    async def is_lockdown_enabled(self, guild_id: int) -> bool:
        payload = await self._cache.get_json(f"lockdown:enabled:{guild_id}")
        return bool(payload and payload.get("enabled"))

    async def set_raid_threshold(self, guild_id: int, threshold: int, window: int) -> None:
        await self._cache.set_json(
            f"raid:threshold:{guild_id}",
            {"threshold": threshold, "window": window},
            ex=86400 * 30,
        )

    async def get_raid_threshold(self, guild_id: int) -> tuple[int, int]:
        payload = await self._cache.get_json(f"raid:threshold:{guild_id}")
        if not payload:
            return self._raid_toxic_threshold, self._raid_window_seconds
        return int(payload.get("threshold", self._raid_toxic_threshold)), int(
            payload.get("window", self._raid_window_seconds)
        )
