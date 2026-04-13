"""Sliding-window rate limiter with pluggable backend.

Ships with an in-memory backend (suitable for single-process / dev).
Swap to Redis in production by replacing the backend — call sites stay the same.
"""

from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass
from threading import Lock


@dataclass(frozen=True)
class RateLimitResult:
    """Outcome of a rate-limit check."""

    allowed: bool
    limit: int
    remaining: int
    retry_after: float  # seconds until the window resets (0 if allowed)


class SlidingWindowLimiter:
    """In-memory sliding-window rate limiter.

    Each (key, window) pair tracks request timestamps.  Old entries are pruned
    on every check so memory stays bounded.
    """

    def __init__(self) -> None:
        self._windows: dict[str, list[float]] = defaultdict(list)
        self._lock = Lock()

    def check(self, key: str, limit: int, window_seconds: int) -> RateLimitResult:
        """Check whether *key* is within its rate limit.

        Returns a ``RateLimitResult`` **without** consuming a request slot.
        Call ``hit`` to actually record a request.
        """
        now = time.monotonic()
        cutoff = now - window_seconds

        with self._lock:
            entries = self._windows[key]
            # prune expired
            entries[:] = [t for t in entries if t > cutoff]
            remaining = max(0, limit - len(entries))
            if remaining > 0:
                retry_after = 0.0
            else:
                retry_after = entries[0] - cutoff if entries else 0.0

        return RateLimitResult(
            allowed=remaining > 0,
            limit=limit,
            remaining=remaining,
            retry_after=round(retry_after, 1),
        )

    def hit(self, key: str, limit: int, window_seconds: int) -> RateLimitResult:
        """Record a request for *key* and return the rate-limit status.

        If the request would exceed the limit, the hit is **not** recorded and
        ``allowed`` is ``False``.
        """
        now = time.monotonic()
        cutoff = now - window_seconds

        with self._lock:
            entries = self._windows[key]
            entries[:] = [t for t in entries if t > cutoff]

            if len(entries) >= limit:
                retry_after = entries[0] - cutoff if entries else 0.0
                return RateLimitResult(
                    allowed=False,
                    limit=limit,
                    remaining=0,
                    retry_after=round(retry_after, 1),
                )

            entries.append(now)
            remaining = limit - len(entries)

        return RateLimitResult(
            allowed=True,
            limit=limit,
            remaining=remaining,
            retry_after=0.0,
        )

    def reset(self, key: str) -> None:
        """Clear all entries for *key* (useful in tests)."""
        with self._lock:
            self._windows.pop(key, None)

    def clear(self) -> None:
        """Clear all state (useful in tests)."""
        with self._lock:
            self._windows.clear()


# Module-level singleton — importable from anywhere.
limiter = SlidingWindowLimiter()
