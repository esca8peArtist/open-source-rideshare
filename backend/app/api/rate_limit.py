"""FastAPI dependencies for rate limiting."""

from __future__ import annotations

from fastapi import HTTPException, Request, status

from app.services.rate_limiter import limiter


class RateLimit:
    """Callable dependency that enforces a rate limit on a route.

    Usage::

        @router.post("/login", dependencies=[Depends(RateLimit(5, 60))])
        async def login(...): ...

    The key is derived from the client IP by default.  Pass ``key_func``
    to customise (e.g. use the authenticated user id instead).
    """

    def __init__(
        self,
        limit: int,
        window_seconds: int,
        *,
        key_prefix: str = "",
        key_func: callable | None = None,
    ) -> None:
        self.limit = limit
        self.window_seconds = window_seconds
        self.key_prefix = key_prefix
        self.key_func = key_func

    async def __call__(self, request: Request) -> None:
        if self.key_func is not None:
            key_value = self.key_func(request)
        else:
            key_value = _client_ip(request)

        key = f"rl:{self.key_prefix}:{key_value}" if self.key_prefix else f"rl:{request.url.path}:{key_value}"

        result = limiter.hit(key, self.limit, self.window_seconds)

        if not result.allowed:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many requests",
                headers={
                    "Retry-After": str(int(result.retry_after) + 1),
                    "X-RateLimit-Limit": str(result.limit),
                    "X-RateLimit-Remaining": "0",
                },
            )


def _client_ip(request: Request) -> str:
    """Best-effort client IP, respecting X-Forwarded-For behind a proxy."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"
