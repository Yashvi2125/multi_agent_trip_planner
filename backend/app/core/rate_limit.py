import time
from collections import defaultdict, deque

from fastapi import Request

from app.core.config import get_settings
from app.core.errors import AppError

_hits: dict[str, deque[float]] = defaultdict(deque)


def rate_limit(max_calls: int, per_seconds: int):
    """Simple in-memory sliding window, keyed by client IP + route. Fine for a single instance."""

    def dep(request: Request) -> None:
        if not get_settings().rate_limit_enabled:
            return
        key = f"{request.client.host if request.client else 'anon'}:{request.url.path}"
        now = time.monotonic()
        q = _hits[key]
        while q and now - q[0] > per_seconds:
            q.popleft()
        if len(q) >= max_calls:
            raise AppError("rate_limited", "That's a lot of attempts. Give it a minute and try again.", 429)
        q.append(now)

    return dep
