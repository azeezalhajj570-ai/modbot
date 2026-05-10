from __future__ import annotations

import hashlib
import re
import time
from typing import Any

from bot.moderation.schemas import ModerationAction, ModerationCategory, ModerationDecision


class RepeatedMessageDetector:
    def __init__(self, redis_client: Any | None = None, window_seconds: int = 300, threshold: int = 3) -> None:
        self.redis = redis_client
        self.window_seconds = window_seconds
        self.threshold = threshold
        self._local_cache: dict[str, list[float]] = {}  # Fallback for dev/tests without Redis

    def _normalize(self, text: str) -> str:
        # lowercase
        text = text.lower()
        # strip URLs
        text = re.sub(r"https?://\S+|www\.\S+", "", text)
        # normalize whitespace
        text = re.sub(r"\s+", " ", text).strip()
        # remove common punctuation
        text = re.sub(r"[^\w\s\u0600-\u06FF]", "", text)
        return text

    def _fingerprint(self, text: str) -> str:
        normalized = self._normalize(text)
        if not normalized:
            return ""
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()

    async def check(self, group_id: int, user_id: int, text: str) -> ModerationDecision:
        fingerprint = self._fingerprint(text)
        if not fingerprint:
            return ModerationDecision(ModerationCategory.SAFE, 0.0, "empty_after_normalization")

        key = f"repeat:{group_id}:{fingerprint}"
        now = time.time()

        if self.redis:
            # Use Redis Sorted Set to track timestamps of this fingerprint in this group
            pipe = self.redis.pipeline()
            # Remove old timestamps outside the window
            pipe.zremrangebyscore(key, 0, now - self.window_seconds)
            # Add current timestamp
            pipe.zadd(key, {str(now): now})
            # Count occurrences in the window
            pipe.zcard(key)
            # Set expiry for the key
            pipe.expire(key, self.window_seconds)
            results = await pipe.execute()
            count = results[2]
        else:
            # In-memory fallback
            timestamps = self._local_cache.get(key, [])
            timestamps = [t for t in timestamps if t > now - self.window_seconds]
            timestamps.append(now)
            self._local_cache[key] = timestamps
            count = len(timestamps)

        if count >= self.threshold:
            return ModerationDecision(
                category=ModerationCategory.REPEATED_PROMO,
                confidence=0.8 + min(0.19, (count - self.threshold) * 0.05),
                reason=f"repeated_message_count_{count}",
                matched_signals=[f"repeat_count:{count}"],
                recommended_action=ModerationAction.REVIEW if count < self.threshold + 2 else ModerationAction.DELETE,
            )

        return ModerationDecision(ModerationCategory.SAFE, 0.0, "clean")
