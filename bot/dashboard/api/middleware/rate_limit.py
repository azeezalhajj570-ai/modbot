from __future__ import annotations

import logging
from typing import Awaitable, Callable

from fastapi import Request, Response
from redis.asyncio import Redis
from redis.exceptions import RedisError
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from bot.config import get_settings
from bot.utils.rate_limiter import ApiRateLimiter

logger = logging.getLogger(__name__)


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(
        self,
        app: ASGIApp,
        *,
        redis: Redis | None = None,
        requests_per_minute: int = 100,
        burst: int = 25,
        exempt_paths: set[str] | None = None,
    ) -> None:
        super().__init__(app)
        self._redis = redis
        self._requests_per_minute = requests_per_minute
        self._burst = burst
        self._exempt_paths = exempt_paths or {"/health", "/favicon.ico"}
        self._settings = get_settings()

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        path = request.url.path.rstrip("/") or "/"

        if path in self._exempt_paths or not self._settings.rate_limit_enabled:
            return await call_next(request)

        if self._redis is None:
            return await call_next(request)

        client_ip = self._resolve_client_ip(request)
        limiter = ApiRateLimiter(self._redis)

        try:
            allowed, remaining = await limiter.check_and_increment(
                client_ip, self._requests_per_minute, window_seconds=60
            )
        except RedisError:
            logger.warning("Rate limiter Redis unavailable — allowing request", exc_info=True)
            return await call_next(request)

        reset_after = await limiter.reset_after_seconds(client_ip)

        if not allowed:
            logger.warning("Rate limit exceeded for %s on %s", client_ip, path)
            return Response(
                content='{"detail":"Too many requests — rate limit exceeded"}',
                status_code=429,
                media_type="application/json",
                headers={
                    "Retry-After": str(reset_after),
                    "X-RateLimit-Limit": str(self._requests_per_minute),
                    "X-RateLimit-Remaining": "0",
                    "X-RateLimit-Reset": str(reset_after),
                },
            )

        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(self._requests_per_minute)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        response.headers["X-RateLimit-Reset"] = str(reset_after)
        return response

    @staticmethod
    def _resolve_client_ip(request: Request) -> str:
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            return forwarded.split(",")[0].strip()
        client = request.client
        return client.host if client else "unknown"
