"""Tests for rate limiting — core service and FastAPI integration."""

import time
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.services.rate_limiter import RateLimitResult, SlidingWindowLimiter, limiter


# ---------------------------------------------------------------------------
# Core SlidingWindowLimiter tests
# ---------------------------------------------------------------------------


class TestSlidingWindowLimiter:
    def setup_method(self):
        self.lim = SlidingWindowLimiter()

    def test_first_hit_allowed(self):
        result = self.lim.hit("k1", limit=3, window_seconds=60)
        assert result.allowed is True
        assert result.remaining == 2
        assert result.limit == 3
        assert result.retry_after == 0.0

    def test_hits_up_to_limit_allowed(self):
        for i in range(5):
            result = self.lim.hit("k2", limit=5, window_seconds=60)
        assert result.allowed is True
        assert result.remaining == 0

    def test_hit_over_limit_rejected(self):
        for _ in range(3):
            self.lim.hit("k3", limit=3, window_seconds=60)
        result = self.lim.hit("k3", limit=3, window_seconds=60)
        assert result.allowed is False
        assert result.remaining == 0
        assert result.retry_after > 0

    def test_different_keys_independent(self):
        for _ in range(3):
            self.lim.hit("a", limit=3, window_seconds=60)
        # "a" is exhausted, but "b" should be fine
        result = self.lim.hit("b", limit=3, window_seconds=60)
        assert result.allowed is True
        assert result.remaining == 2

    def test_window_expiry(self):
        # Use a very short window and mock time to test expiry
        with patch("app.services.rate_limiter.time") as mock_time:
            mock_time.monotonic.return_value = 1000.0
            self.lim.hit("exp", limit=2, window_seconds=10)
            self.lim.hit("exp", limit=2, window_seconds=10)
            result = self.lim.hit("exp", limit=2, window_seconds=10)
            assert result.allowed is False

            # Advance time past the window
            mock_time.monotonic.return_value = 1011.0
            result = self.lim.hit("exp", limit=2, window_seconds=10)
            assert result.allowed is True
            assert result.remaining == 1

    def test_check_does_not_consume(self):
        result = self.lim.check("chk", limit=1, window_seconds=60)
        assert result.allowed is True
        assert result.remaining == 1

        # check again — still allowed since check doesn't consume
        result = self.lim.check("chk", limit=1, window_seconds=60)
        assert result.allowed is True

        # now actually hit
        self.lim.hit("chk", limit=1, window_seconds=60)
        result = self.lim.check("chk", limit=1, window_seconds=60)
        assert result.allowed is False

    def test_reset_key(self):
        for _ in range(3):
            self.lim.hit("rst", limit=3, window_seconds=60)
        assert self.lim.hit("rst", limit=3, window_seconds=60).allowed is False
        self.lim.reset("rst")
        assert self.lim.hit("rst", limit=3, window_seconds=60).allowed is True

    def test_clear_all(self):
        self.lim.hit("x", limit=1, window_seconds=60)
        self.lim.hit("y", limit=1, window_seconds=60)
        self.lim.clear()
        assert self.lim.hit("x", limit=1, window_seconds=60).allowed is True
        assert self.lim.hit("y", limit=1, window_seconds=60).allowed is True

    def test_result_dataclass_frozen(self):
        result = RateLimitResult(allowed=True, limit=5, remaining=4, retry_after=0.0)
        with pytest.raises(AttributeError):
            result.allowed = False

    def test_retry_after_is_positive_when_rejected(self):
        with patch("app.services.rate_limiter.time") as mock_time:
            mock_time.monotonic.return_value = 100.0
            self.lim.hit("ra", limit=1, window_seconds=30)
            mock_time.monotonic.return_value = 105.0
            result = self.lim.hit("ra", limit=1, window_seconds=30)
            assert result.allowed is False
            assert result.retry_after > 0
            assert result.retry_after <= 30


# ---------------------------------------------------------------------------
# FastAPI integration tests — auth rate limits
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clear_limiter():
    """Clear limiter state between tests so they don't interfere."""
    limiter.clear()
    yield
    limiter.clear()


class TestAuthRateLimits:
    """Test that login and register endpoints are rate-limited."""

    async def test_login_within_limit(self, client: AsyncClient, rider: "User"):
        """Normal login attempts should succeed (up to the limit)."""
        for _ in range(5):
            resp = await client.post(
                "/api/v1/auth/login",
                json={"phone": "+15551000001", "password": "testpass123"},
            )
            assert resp.status_code in (200, 401)  # auth result, not 429

    async def test_login_rate_limited(self, client: AsyncClient, rider: "User"):
        """Exceeding login rate limit returns 429."""
        for _ in range(5):
            await client.post(
                "/api/v1/auth/login",
                json={"phone": "+15551000001", "password": "wrong"},
            )
        resp = await client.post(
            "/api/v1/auth/login",
            json={"phone": "+15551000001", "password": "wrong"},
        )
        assert resp.status_code == 429
        assert "Retry-After" in resp.headers
        assert resp.json()["detail"] == "Too many requests"

    async def test_register_rate_limited(self, client: AsyncClient):
        """Exceeding register rate limit returns 429."""
        for i in range(3):
            await client.post(
                "/api/v1/auth/register",
                json={
                    "phone": f"+1555200000{i}",
                    "name": f"User{i}",
                    "email": f"u{i}@test.com",
                    "password": "testpass123",
                    "role": "rider",
                },
            )
        resp = await client.post(
            "/api/v1/auth/register",
            json={
                "phone": "+15552000009",
                "name": "Blocked",
                "email": "blocked@test.com",
                "password": "testpass123",
                "role": "rider",
            },
        )
        assert resp.status_code == 429

    async def test_rate_limit_headers_on_429(self, client: AsyncClient, rider: "User"):
        """429 responses include standard rate limit headers."""
        for _ in range(5):
            await client.post(
                "/api/v1/auth/login",
                json={"phone": "+15551000001", "password": "wrong"},
            )
        resp = await client.post(
            "/api/v1/auth/login",
            json={"phone": "+15551000001", "password": "wrong"},
        )
        assert resp.status_code == 429
        assert "X-RateLimit-Limit" in resp.headers
        assert "X-RateLimit-Remaining" in resp.headers
        assert resp.headers["X-RateLimit-Remaining"] == "0"

    async def test_different_ips_separate_limits(self, app):
        """Requests from different IPs have independent rate limits."""
        transport = ASGITransport(app=app)

        # Exhaust limit from IP "1.2.3.4"
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            for _ in range(5):
                await c.post(
                    "/api/v1/auth/login",
                    json={"phone": "+15551000001", "password": "wrong"},
                    headers={"X-Forwarded-For": "1.2.3.4"},
                )
            resp = await c.post(
                "/api/v1/auth/login",
                json={"phone": "+15551000001", "password": "wrong"},
                headers={"X-Forwarded-For": "1.2.3.4"},
            )
            assert resp.status_code == 429

            # Different IP should still be allowed
            resp2 = await c.post(
                "/api/v1/auth/login",
                json={"phone": "+15551000001", "password": "wrong"},
                headers={"X-Forwarded-For": "5.6.7.8"},
            )
            assert resp2.status_code != 429


class TestRideRequestRateLimit:
    """Test ride request endpoint rate limiting."""

    async def test_ride_request_rate_limited(self, client: AsyncClient, rider: "User", rider_token: str):
        """Exceeding ride request limit returns 429."""
        from tests.conftest import auth_header

        for _ in range(10):
            await client.post(
                "/api/v1/rides/request",
                json={
                    "pickup": {"lat": 40.7128, "lng": -74.0060},
                    "dropoff": {"lat": 40.7580, "lng": -73.9855},
                },
                headers=auth_header(rider_token),
            )
        resp = await client.post(
            "/api/v1/rides/request",
            json={
                "pickup": {"lat": 40.7128, "lng": -74.0060},
                "dropoff": {"lat": 40.7580, "lng": -73.9855},
            },
            headers=auth_header(rider_token),
        )
        assert resp.status_code == 429
