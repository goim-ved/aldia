"""Redis-backed Sliding-Window Rate Limiter dependency for FastAPI."""

import time
import logging
from typing import Any
from fastapi import HTTPException, Request, status
import redis.asyncio as aioredis

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

# Module-level Redis client singleton
_redis_client: aioredis.Redis | None = None


async def get_redis_client() -> aioredis.Redis:
    """Obtain or initialize the async Redis client."""
    global _redis_client
    if _redis_client is None:
        _redis_client = aioredis.from_url(
            settings.REDIS_URL,
            encoding="utf-8",
            decode_responses=True,
        )
    return _redis_client


async def close_redis_client() -> None:
    """Close the global Redis client connection."""
    global _redis_client
    if _redis_client is not None:
        await _redis_client.aclose()
        _redis_client = None


class RateLimiter:
    """Sliding-window rate limiter dependency using Redis sorted sets."""

    def __init__(
        self,
        requests_limit: int | None = None,
        window_seconds: int | None = None,
        key_prefix: str = "rate_limit",
    ) -> None:
        """Initialize RateLimiter with custom limits or fallback to settings."""
        self.requests_limit = requests_limit or settings.RATE_LIMIT_REQUESTS
        self.window_seconds = window_seconds or settings.RATE_LIMIT_WINDOW_SECONDS
        self.key_prefix = key_prefix

    async def __call__(self, request: Request) -> None:
        """Evaluate client rate limit based on client IP or user ID."""
        # Determine client identifier: authenticated user sub or remote IP
        client_ip = request.client.host if request.client else "unknown_host"
        user_id = getattr(request.state, "user_id", None)
        identifier = f"user_{user_id}" if user_id else f"ip_{client_ip}"
        
        path = request.url.path
        rate_key = f"{self.key_prefix}:{identifier}:{path}"

        try:
            redis_conn = await get_redis_client()
            now = time.time()
            window_start = now - self.window_seconds

            # Execute atomic sliding window algorithm using Redis pipeline
            async with redis_conn.pipeline(transaction=True) as pipe:
                # 1. Remove expired entries older than the sliding window
                pipe.zremrangebyscore(rate_key, 0, window_start)
                # 2. Count current entries in window
                pipe.zcard(rate_key)
                results: list[Any] = await pipe.execute()

            current_count = results[1]

            if current_count >= self.requests_limit:
                retry_after = self.window_seconds
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail={
                        "error": "Rate limit exceeded",
                        "limit": self.requests_limit,
                        "window_seconds": self.window_seconds,
                        "retry_after_seconds": retry_after,
                    },
                    headers={"Retry-After": str(retry_after)},
                )

            # Record this request with microsecond-level uniqueness
            member_value = f"{now}"
            async with redis_conn.pipeline(transaction=True) as pipe:
                pipe.zadd(rate_key, {member_value: now})
                pipe.expire(rate_key, self.window_seconds + 5)
                await pipe.execute()

        except HTTPException:
            raise
        except Exception as exc:
            # Graceful degradation: log warning and proceed if Redis is unreachable in dev/test
            logger.warning(
                "Redis rate limiter encountered error, failing open: %s", exc
            )
