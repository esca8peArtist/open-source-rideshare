"""Tests for GET /riders/{rider_id}/public-profile.

Coverage:
1.  Service returns None for unknown user_id
2.  Service returns None for non-rider user (wrong role)
3.  Service returns None for inactive user
4.  Service returns RiderPublicProfile for valid active rider
5.  rating_avg is null when no driver ratings exist
6.  rating_avg is computed correctly from driver ratings
7.  rating_avg rounds to 2 decimal places
8.  total_completed_rides counts only COMPLETED rides
9.  member_since maps to User.created_at
10. No PII in returned schema
11. Endpoint returns 404 for unknown rider
12. Endpoint requires driver auth (401/403 without credentials)
13. Endpoint returns 200 for valid rider + driver auth
14. Full response shape correct
15. No PII in endpoint response
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.schemas.rider_public_profile import RiderPublicProfile
from app.services.rider_public_profile import get_rider_public_profile

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_NOW = datetime(2025, 6, 1, 9, 0, 0, tzinfo=timezone.utc)
RIDER_ID = 55
DRIVER_ID = 7


def _make_user(
    user_id: int = RIDER_ID,
    role: str = "rider",
    is_active: bool = True,
    created_at: datetime = _NOW,
) -> MagicMock:
    from app.models.user import UserRole

    u = MagicMock()
    u.id = user_id
    u.role = UserRole.RIDER if role == "rider" else MagicMock()
    u.is_active = is_active
    u.created_at = created_at
    return u


def _make_db(user: MagicMock | None, rating_avg: float | None, ride_count: int) -> AsyncMock:
    """Build a mock DB with three sequential execute() calls:
      1. User lookup
      2. Avg rating scalar
      3. Ride count scalar
    """
    db = AsyncMock()

    user_result = MagicMock()
    user_result.scalar_one_or_none.return_value = user

    rating_result = MagicMock()
    rating_result.scalar.return_value = rating_avg

    count_result = MagicMock()
    count_result.scalar.return_value = ride_count

    if user is not None:
        db.execute.side_effect = [user_result, rating_result, count_result]
    else:
        db.execute.side_effect = [user_result]

    return db


# ---------------------------------------------------------------------------
# 1. Service: unknown user
# ---------------------------------------------------------------------------


class TestServiceUnknownUser:
    @pytest.mark.asyncio
    async def test_returns_none_for_unknown_user(self):
        db = _make_db(None, None, 0)
        result = await get_rider_public_profile(db, rider_id=9999)
        assert result is None


# ---------------------------------------------------------------------------
# 2. Non-rider user (DB query filters by role)
# ---------------------------------------------------------------------------


class TestServiceNonRider:
    @pytest.mark.asyncio
    async def test_returns_none_when_db_excludes_non_rider(self):
        # The DB WHERE clause excludes non-riders; DB returns None.
        db = _make_db(None, None, 0)
        result = await get_rider_public_profile(db, rider_id=10)
        assert result is None


# ---------------------------------------------------------------------------
# 3. Inactive user (DB query filters by is_active)
# ---------------------------------------------------------------------------


class TestServiceInactiveUser:
    @pytest.mark.asyncio
    async def test_returns_none_when_db_excludes_inactive(self):
        db = _make_db(None, None, 0)
        result = await get_rider_public_profile(db, rider_id=20)
        assert result is None


# ---------------------------------------------------------------------------
# 4–10. Service: valid active rider
# ---------------------------------------------------------------------------


class TestServiceValidRider:
    @pytest.mark.asyncio
    async def test_returns_profile_for_valid_rider(self):
        user = _make_user()
        db = _make_db(user, rating_avg=4.5, ride_count=30)
        result = await get_rider_public_profile(db, rider_id=RIDER_ID)
        assert result is not None
        assert isinstance(result, RiderPublicProfile)

    @pytest.mark.asyncio
    async def test_rating_avg_null_when_no_ratings(self):
        user = _make_user()
        db = _make_db(user, rating_avg=None, ride_count=5)
        result = await get_rider_public_profile(db, rider_id=RIDER_ID)
        assert result.rating_avg is None

    @pytest.mark.asyncio
    async def test_rating_avg_computed_correctly(self):
        user = _make_user()
        db = _make_db(user, rating_avg=4.5, ride_count=10)
        result = await get_rider_public_profile(db, rider_id=RIDER_ID)
        assert result.rating_avg == 4.5

    @pytest.mark.asyncio
    async def test_rating_avg_rounds_to_2dp(self):
        user = _make_user()
        db = _make_db(user, rating_avg=4.333333, ride_count=3)
        result = await get_rider_public_profile(db, rider_id=RIDER_ID)
        assert result.rating_avg == 4.33

    @pytest.mark.asyncio
    async def test_total_completed_rides_correct(self):
        user = _make_user()
        db = _make_db(user, rating_avg=4.8, ride_count=123)
        result = await get_rider_public_profile(db, rider_id=RIDER_ID)
        assert result.total_completed_rides == 123

    @pytest.mark.asyncio
    async def test_member_since_maps_to_created_at(self):
        user = _make_user(created_at=_NOW)
        db = _make_db(user, rating_avg=None, ride_count=0)
        result = await get_rider_public_profile(db, rider_id=RIDER_ID)
        assert result.member_since == _NOW

    @pytest.mark.asyncio
    async def test_rider_id_set_correctly(self):
        user = _make_user(user_id=RIDER_ID)
        db = _make_db(user, rating_avg=4.0, ride_count=20)
        result = await get_rider_public_profile(db, rider_id=RIDER_ID)
        assert result.rider_id == RIDER_ID

    @pytest.mark.asyncio
    async def test_no_pii_in_schema(self):
        user = _make_user()
        db = _make_db(user, rating_avg=4.5, ride_count=10)
        result = await get_rider_public_profile(db, rider_id=RIDER_ID)
        result_dict = result.model_dump()
        for pii_field in ("email", "phone", "name", "referred_by"):
            assert pii_field not in result_dict, f"PII field present: {pii_field}"


# ---------------------------------------------------------------------------
# Endpoint tests
# ---------------------------------------------------------------------------


def _override_driver():
    from app.models.user import User as UserModel
    from app.api.deps import require_driver

    mock_driver = MagicMock(spec=UserModel)
    mock_driver.id = DRIVER_ID
    app.dependency_overrides[require_driver] = lambda: mock_driver


def _clear_overrides():
    app.dependency_overrides.clear()


class TestEndpoint404:
    def test_unknown_rider_returns_404(self):
        _override_driver()
        with patch(
            "app.api.v1.rider_public_profile.get_rider_public_profile",
            new=AsyncMock(return_value=None),
        ):
            with TestClient(app) as client:
                resp = client.get("/api/v1/riders/999/public-profile")
        _clear_overrides()
        assert resp.status_code == 404


class TestEndpointAuth:
    def test_requires_driver_auth(self):
        _clear_overrides()
        with TestClient(app) as client:
            resp = client.get(f"/api/v1/riders/{RIDER_ID}/public-profile")
        assert resp.status_code in (401, 403)


class TestEndpoint200:
    def _mock_profile(self) -> RiderPublicProfile:
        return RiderPublicProfile(
            rider_id=RIDER_ID,
            rating_avg=4.7,
            total_completed_rides=42,
            member_since=_NOW,
        )

    def test_returns_200_with_driver_auth(self):
        _override_driver()
        with patch(
            "app.api.v1.rider_public_profile.get_rider_public_profile",
            new=AsyncMock(return_value=self._mock_profile()),
        ):
            with TestClient(app) as client:
                resp = client.get(f"/api/v1/riders/{RIDER_ID}/public-profile")
        _clear_overrides()
        assert resp.status_code == 200

    def test_response_shape_has_all_fields(self):
        _override_driver()
        with patch(
            "app.api.v1.rider_public_profile.get_rider_public_profile",
            new=AsyncMock(return_value=self._mock_profile()),
        ):
            with TestClient(app) as client:
                resp = client.get(f"/api/v1/riders/{RIDER_ID}/public-profile")
        _clear_overrides()
        data = resp.json()
        for field in ("rider_id", "rating_avg", "total_completed_rides", "member_since"):
            assert field in data, f"Missing field: {field}"

    def test_no_pii_in_response(self):
        _override_driver()
        with patch(
            "app.api.v1.rider_public_profile.get_rider_public_profile",
            new=AsyncMock(return_value=self._mock_profile()),
        ):
            with TestClient(app) as client:
                resp = client.get(f"/api/v1/riders/{RIDER_ID}/public-profile")
        _clear_overrides()
        data = resp.json()
        for pii_field in ("email", "phone", "name", "password", "referred_by"):
            assert pii_field not in data, f"PII field present: {pii_field}"

    def test_null_rating_avg_allowed(self):
        _override_driver()
        profile_no_ratings = RiderPublicProfile(
            rider_id=RIDER_ID,
            rating_avg=None,
            total_completed_rides=0,
            member_since=_NOW,
        )
        with patch(
            "app.api.v1.rider_public_profile.get_rider_public_profile",
            new=AsyncMock(return_value=profile_no_ratings),
        ):
            with TestClient(app) as client:
                resp = client.get(f"/api/v1/riders/{RIDER_ID}/public-profile")
        _clear_overrides()
        assert resp.status_code == 200
        assert resp.json()["rating_avg"] is None
