from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any

from bot.config import get_settings


class AgentRateLimiter:
    def __init__(self, redis_client) -> None:
        self._redis = redis_client

    def _action_key(self, agent_id: int) -> str:
        return f"agent:{agent_id}:actions"

    def _window_key(self, agent_id: int, window: int) -> str:
        return f"agent:{agent_id}:window:{window}"

    def _last_action_key(self, agent_id: int) -> str:
        return f"agent:{agent_id}:last_action"

    def _cooldown_key(self, agent_id: int) -> str:
        return f"agent:{agent_id}:cooldown"

    async def check_and_increment(self, agent_id: int, max_per_hour: int | None) -> tuple[bool, int]:
        if max_per_hour is None or max_per_hour <= 0:
            return True, 0
        now = int(time.time())
        window = now // 3600
        key = self._window_key(agent_id, window)
        count = await self._redis.incr(key)
        if count == 1:
            await self._redis.expire(key, 7200)
        return count <= max_per_hour, count

    async def enforce_delay(self, agent_id: int, min_delay_seconds: float | None) -> float:
        if min_delay_seconds is None or min_delay_seconds <= 0:
            return 0.0
        key = self._last_action_key(agent_id)
        last_ts = await self._redis.get(key)
        now = time.time()
        if last_ts is not None:
            elapsed = now - float(last_ts)
            if elapsed < min_delay_seconds:
                remaining = min_delay_seconds - elapsed
                return remaining
        await self._redis.set(key, str(now), ex=max(7200, int(min_delay_seconds * 4)))
        return 0.0

    async def is_in_cooldown(self, agent_id: int, cooldown_minutes: int | None, agent_created_at: datetime | None = None) -> tuple[bool, float]:
        if cooldown_minutes is None or cooldown_minutes <= 0:
            return False, 0.0
        key = self._cooldown_key(agent_id)
        ttl = await self._redis.ttl(key)
        if ttl > 0:
            return True, ttl
        return False, 0.0

    async def start_cooldown(self, agent_id: int, cooldown_minutes: int) -> None:
        if cooldown_minutes <= 0:
            return
        key = self._cooldown_key(agent_id)
        await self._redis.set(key, "1", ex=cooldown_minutes * 60)

    async def check_safety_mode(self, agent_id: int, safety_mode_enabled: bool, safety_mode_until: datetime | None) -> bool:
        if not safety_mode_enabled or safety_mode_until is None:
            return False
        now = datetime.now(timezone.utc)
        return now < safety_mode_until

    async def get_agent_actions_count(self, agent_id: int) -> int:
        now = int(time.time())
        window = now // 3600
        key = self._window_key(agent_id, window)
        val = await self._redis.get(key)
        return int(val) if val else 0

    def _daily_key(self, agent_id: int) -> str:
        from datetime import datetime, timezone
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        return f"agent:{agent_id}:daily:{today}"

    async def check_daily_limit(self, agent_id: int, max_per_day: int | None) -> tuple[bool, int]:
        if max_per_day is None or max_per_day <= 0:
            return True, 0
        key = self._daily_key(agent_id)
        count = await self._redis.incr(key)
        if count == 1:
            await self._redis.expire(key, 86400)
        return count <= max_per_day, count

    async def record_send(self, agent_id: int) -> int:
        key = self._daily_key(agent_id)
        count = await self._redis.incr(key)
        if count == 1:
            await self._redis.expire(key, 86400)
        now = int(time.time())
        await self._redis.set(self._last_action_key(agent_id), str(now), ex=7200)
        return count

    async def get_daily_count(self, agent_id: int) -> int:
        key = self._daily_key(agent_id)
        val = await self._redis.get(key)
        return int(val) if val else 0


class ApiRateLimiter:
    def __init__(self, redis_client) -> None:
        self._redis = redis_client

    async def check_and_increment(
        self, key: str, max_requests: int, window_seconds: int = 60
    ) -> tuple[bool, int]:
        if max_requests <= 0:
            return True, 0
        now = int(time.time())
        window = now // window_seconds
        redis_key = f"apirl:{key}:{window}"
        count = await self._redis.incr(redis_key)
        if count == 1:
            await self._redis.expire(redis_key, window_seconds * 2)
        remaining = max(0, max_requests - count)
        return count <= max_requests, remaining

    async def reset_after_seconds(self, key: str, window_seconds: int = 60) -> int:
        now = int(time.time())
        return window_seconds - (now % window_seconds)
