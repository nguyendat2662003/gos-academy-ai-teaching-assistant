"""Fixed-window rate limiting in Redis (per user within a class, and per class)."""

import time
from dataclasses import dataclass
from typing import Literal

from redis.asyncio import Redis

WINDOW_SECONDS = 60


@dataclass(frozen=True)
class RateDecision:
    allowed: bool
    scope: Literal["user", "class"] | None = None
    notify: bool = False  # True only for the first rejection in a window -> send one polite notice


async def check_rate(
    redis: Redis, class_id: str, user_hash: str, user_limit: int, class_limit: int
) -> RateDecision:
    """Count this message and decide. Notification is de-duplicated per scope and window."""
    window = int(time.time()) // WINDOW_SECONDS
    user_key = f"rl:u:{class_id}:{user_hash}:{window}"
    class_key = f"rl:c:{class_id}:{window}"

    pipe = redis.pipeline()
    pipe.incr(user_key)
    pipe.expire(user_key, WINDOW_SECONDS * 2)
    pipe.incr(class_key)
    pipe.expire(class_key, WINDOW_SECONDS * 2)
    user_count, _, class_count, _ = await pipe.execute()

    if user_count > user_limit:
        scope: Literal["user", "class"] = "user"
        notified_key = f"rl:n:u:{class_id}:{user_hash}:{window}"
    elif class_count > class_limit:
        scope = "class"
        notified_key = f"rl:n:c:{class_id}:{window}"
    else:
        return RateDecision(allowed=True)

    first = await redis.set(notified_key, "1", nx=True, ex=WINDOW_SECONDS * 2)
    return RateDecision(allowed=False, scope=scope, notify=bool(first))
