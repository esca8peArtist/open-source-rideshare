"""Tests for admin user management endpoints.

Service unit tests (AsyncMock DB):
  1.  list_users returns empty result when no non-admin users exist
  2.  list_users returns rider and driver users
  3.  list_users filters by role=rider correctly
  4.  list_users filters by role=driver correctly
  5.  list_users filters by status=suspended correctly
  6.  list_users search by name (case-insensitive)
  7.  list_users search by email (case-insensitive)
  8.  list_users respects page_size cap of 100
  9.  get_user_detail raises ValueError for unknown user
  10. get_user_detail returns correct ride stats for rider
  11. suspend_user raises _AlreadyInStateError when already suspended
  12. suspend_user sets status to SUSPENDED and records reason
  13. activate_user raises _AlreadyInStateError when already active
  14. activate_user sets status to ACTIVE and clears suspension_reason

API integration tests (conftest fixtures + real DB):
  15. GET /admin/users — 401 with no auth
  16. GET /admin/users — 403 with rider token
  17. GET /admin/users — 403 with driver token
  18. GET /admin/users — 200 with admin token returns correct structure
  19. GET /admin/users — role filter returns only matching users
  20. GET /admin/users — status filter returns only matching users
  21. GET /admin/users/{id} — 404 for unknown user
  22. GET /admin/users/{id} — 200 returns full profile fields
  23. GET /admin/users/{id} — 403 with rider token
  24. POST /admin/users/{id}/suspend — 404 for unknown user
  25. POST /admin/users/{id}/suspend — 200 suspends user
  26. POST /admin/users/{id}/suspend — 409 when already suspended
  27. POST /admin/users/{id}/activate — 409 when already active
  28. POST /admin/users/{id}/activate — 200 reactivates suspended user
  29. POST /admin/users/{id}/activate — 403 with rider token
  30. GET /admin/users — 422 for invalid role filter value
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.ride import Ride, RideStatus
from app.models.user import User, UserRole, UserStatus
from app.schemas.admin_user_management import ActivateUserRequest, SuspendUserRequest
from app.services.admin_user_management import (
    _AlreadyInStateError,
    activate_user,
    get_user_detail,
    list_users,
    suspend_user,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 1, 15, 12, 0, 0, tzinfo=timezone.utc)


def _make_user(
    id: int = 1,
    name: str = "Alice",
    email: str | None = "alice@example.com",
    phone: str = "+15550001111",
    role: UserRole = UserRole.RIDER,
    status: UserStatus = UserStatus.ACTIVE,
    is_active: bool = True,
    created_at: datetime = _NOW,
    updated_at: datetime = _NOW,
    phone_verified: bool = True,
    suspension_reason: str | None = None,
    referral_code: str | None = None,
    referred_by: int | None = None,
) -> MagicMock:
    user = MagicMock(spec=User)
    user.id = id
    user.name = name
    user.email = email
    user.phone = phone
    user.role = role
    user.status = status
    user.is_active = is_active
    user.created_at = created_at
    user.updated_at = updated_at
    user.phone_verified = phone_verified
    user.suspension_reason = suspension_reason
    user.referral_code = referral_code
    user.referred_by = referred_by
    return user


def _scalar_result(value) -> MagicMock:
    """Build a mock execute result that returns value from scalar_one()."""
    r = MagicMock()
    r.scalar_one.return_value = value
    return r


def _scalars_all_result(items: list) -> MagicMock:
    """Build a mock execute result that returns items from scalars().all()."""
    r = MagicMock()
    scalars = MagicMock()
    scalars.all.return_value = items
    r.scalars.return_value = scalars
    return r


def _all_result(rows: list) -> MagicMock:
    """Build a mock execute result that returns rows from .all()."""
    r = MagicMock()
    r.all.return_value = rows
    return r


def _scalar_one_or_none_result(value) -> MagicMock:
    r = MagicMock()
    r.scalar_one_or_none.return_value = value
    return r


def auth_header(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Service unit tests
# ---------------------------------------------------------------------------


class TestListUsersService:

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_users(self):
        """Test 1: returns empty UserListResponse when no users exist."""
        db = AsyncMock()
        # count query returns 0; paginated query returns empty list; ride count queries
        db.execute = AsyncMock(
            side_effect=[
                _scalar_result(0),        # count
                _scalars_all_result([]),  # users
            ]
        )
        result = await list_users(db)
        assert result.total_count == 0
        assert result.users == []
        assert result.page == 1

    @pytest.mark.asyncio
    async def test_returns_riders_and_drivers(self):
        """Test 2: returns rows for both riders and driver users."""
        rider = _make_user(id=1, role=UserRole.RIDER)
        driver = _make_user(id=2, role=UserRole.DRIVER, phone="+15550002222")

        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                _scalar_result(2),                    # count
                _scalars_all_result([rider, driver]),  # users page
                _all_result([]),                       # rider ride counts
                _all_result([]),                       # driver ride counts
            ]
        )
        result = await list_users(db)
        assert result.total_count == 2
        assert len(result.users) == 2

    @pytest.mark.asyncio
    async def test_filters_by_role_rider(self):
        """Test 3: role=rider returns only rider users."""
        rider = _make_user(id=1, role=UserRole.RIDER)
        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                _scalar_result(1),
                _scalars_all_result([rider]),
                _all_result([]),
                _all_result([]),
            ]
        )
        result = await list_users(db, role="rider")
        assert len(result.users) == 1
        assert result.users[0].role == "rider"

    @pytest.mark.asyncio
    async def test_filters_by_role_driver(self):
        """Test 4: role=driver returns only driver users."""
        driver = _make_user(id=2, role=UserRole.DRIVER, phone="+15550002222")
        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                _scalar_result(1),
                _scalars_all_result([driver]),
                _all_result([]),
                _all_result([]),
            ]
        )
        result = await list_users(db, role="driver")
        assert len(result.users) == 1
        assert result.users[0].role == "driver"

    @pytest.mark.asyncio
    async def test_filters_by_status_suspended(self):
        """Test 5: status=suspended returns only suspended users."""
        suspended = _make_user(id=3, status=UserStatus.SUSPENDED, phone="+15550003333")
        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                _scalar_result(1),
                _scalars_all_result([suspended]),
                _all_result([]),
                _all_result([]),
            ]
        )
        result = await list_users(db, status="suspended")
        assert len(result.users) == 1
        assert result.users[0].status == "suspended"

    @pytest.mark.asyncio
    async def test_search_by_name(self):
        """Test 6: search filters by name substring."""
        alice = _make_user(id=1, name="Alice Smith")
        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                _scalar_result(1),
                _scalars_all_result([alice]),
                _all_result([]),
                _all_result([]),
            ]
        )
        result = await list_users(db, search="alice")
        assert len(result.users) == 1
        assert result.users[0].name == "Alice Smith"

    @pytest.mark.asyncio
    async def test_search_by_email(self):
        """Test 7: search filters by email substring."""
        user = _make_user(id=1, email="findme@example.com")
        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                _scalar_result(1),
                _scalars_all_result([user]),
                _all_result([]),
                _all_result([]),
            ]
        )
        result = await list_users(db, search="findme")
        assert len(result.users) == 1
        assert result.users[0].email == "findme@example.com"

    @pytest.mark.asyncio
    async def test_page_size_capped_at_100(self):
        """Test 8: page_size > 100 is capped at 100."""
        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                _scalar_result(0),
                _scalars_all_result([]),
            ]
        )
        result = await list_users(db, page_size=500)
        assert result.page_size == 100


class TestGetUserDetailService:

    @pytest.mark.asyncio
    async def test_raises_for_unknown_user(self):
        """Test 9: raises ValueError when user does not exist."""
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_scalar_one_or_none_result(None))
        with pytest.raises(ValueError, match="not found"):
            await get_user_detail(db, user_id=999)

    @pytest.mark.asyncio
    async def test_returns_ride_stats_for_rider(self):
        """Test 10: returns accurate ride stats (total, completed, cancelled, avg_rating)."""
        user = _make_user(id=1, role=UserRole.RIDER)
        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                _scalar_one_or_none_result(user),  # user lookup
                _scalar_result(5),   # rider total rides
                _scalar_result(3),   # rider completed rides
                _scalar_result(1),   # rider cancelled rides
                _scalar_result(0),   # driver total rides
                _scalar_result(0),   # driver completed rides
                _scalar_result(0),   # driver cancelled rides
                _scalar_result(4.5), # avg rating (rider receives driver_rating)
            ]
        )
        result = await get_user_detail(db, user_id=1)
        assert result.ride_stats.total_rides == 5
        assert result.ride_stats.completed_rides == 3
        assert result.ride_stats.cancelled_rides == 1
        assert result.ride_stats.avg_rating == 4.5


class TestSuspendUserService:

    @pytest.mark.asyncio
    async def test_already_suspended_raises_error(self):
        """Test 11: _AlreadyInStateError raised when user is already suspended."""
        user = _make_user(id=1, status=UserStatus.SUSPENDED)
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_scalar_one_or_none_result(user))

        body = SuspendUserRequest(reason="Fraud", notify_user=False)
        with pytest.raises(_AlreadyInStateError):
            await suspend_user(db, user_id=1, admin_id=99, body=body)

    @pytest.mark.asyncio
    async def test_suspend_sets_status_and_reason(self):
        """Test 12: suspend_user sets status to SUSPENDED and records the reason."""
        user = _make_user(id=1, status=UserStatus.ACTIVE)
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_scalar_one_or_none_result(user))
        db.flush = AsyncMock()

        body = SuspendUserRequest(reason="Repeated violations", notify_user=False)
        result = await suspend_user(db, user_id=1, admin_id=99, body=body)

        assert result.new_status == "suspended"
        assert result.previous_status == "active"
        assert user.status == UserStatus.SUSPENDED
        assert user.suspension_reason == "Repeated violations"


class TestActivateUserService:

    @pytest.mark.asyncio
    async def test_already_active_raises_error(self):
        """Test 13: _AlreadyInStateError raised when user is already active."""
        user = _make_user(id=1, status=UserStatus.ACTIVE)
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_scalar_one_or_none_result(user))

        body = ActivateUserRequest(notify_user=False)
        with pytest.raises(_AlreadyInStateError):
            await activate_user(db, user_id=1, admin_id=99, body=body)

    @pytest.mark.asyncio
    async def test_activate_sets_status_and_clears_reason(self):
        """Test 14: activate_user sets status to ACTIVE and clears suspension_reason."""
        user = _make_user(id=1, status=UserStatus.SUSPENDED, suspension_reason="Old reason")
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_scalar_one_or_none_result(user))
        db.flush = AsyncMock()

        body = ActivateUserRequest(reason="Appeal approved", notify_user=False)
        result = await activate_user(db, user_id=1, admin_id=99, body=body)

        assert result.new_status == "active"
        assert result.previous_status == "suspended"
        assert user.status == UserStatus.ACTIVE
        assert user.suspension_reason is None


# ---------------------------------------------------------------------------
# API integration tests
# ---------------------------------------------------------------------------

BASE_LIST = "/api/v1/admin/users"


@pytest.mark.anyio
class TestAdminUserListEndpoint:

    async def test_no_auth_returns_401(self, client):
        """Test 15: 401 with no auth."""
        resp = await client.get(BASE_LIST)
        assert resp.status_code == 401

    async def test_rider_token_returns_403(self, client, rider, rider_token):
        """Test 16: 403 with rider token."""
        resp = await client.get(BASE_LIST, headers=auth_header(rider_token))
        assert resp.status_code == 403

    async def test_driver_token_returns_403(self, client, driver_user, driver_token):
        """Test 17: 403 with driver token."""
        resp = await client.get(BASE_LIST, headers=auth_header(driver_token))
        assert resp.status_code == 403

    async def test_admin_token_returns_200_with_structure(self, client, admin_user, admin_token):
        """Test 18: 200 with admin token returns expected structure."""
        resp = await client.get(BASE_LIST, headers=auth_header(admin_token))
        assert resp.status_code == 200
        data = resp.json()
        assert "users" in data
        assert "total_count" in data
        assert "page" in data
        assert "page_size" in data
        assert isinstance(data["users"], list)
        assert isinstance(data["total_count"], int)

    async def test_role_filter_rider_returns_only_riders(
        self, client, rider, driver_user, admin_user, admin_token
    ):
        """Test 19: role=rider filter excludes drivers."""
        resp = await client.get(
            BASE_LIST, headers=auth_header(admin_token), params={"role": "rider"}
        )
        assert resp.status_code == 200
        data = resp.json()
        for user in data["users"]:
            assert user["role"] == "rider"

    async def test_status_filter_suspended_returns_only_suspended(
        self, client, rider, admin_user, admin_token, db
    ):
        """Test 20: status=suspended filter returns only suspended accounts."""
        # Suspend the rider directly in the DB
        rider.status = UserStatus.SUSPENDED
        rider.suspension_reason = "test"
        await db.flush()

        resp = await client.get(
            BASE_LIST, headers=auth_header(admin_token), params={"status": "suspended"}
        )
        assert resp.status_code == 200
        data = resp.json()
        for user in data["users"]:
            assert user["status"] == "suspended"

    async def test_invalid_role_filter_returns_422(self, client, admin_user, admin_token):
        """Test 30: 422 for invalid role filter value."""
        resp = await client.get(
            BASE_LIST, headers=auth_header(admin_token), params={"role": "superuser"}
        )
        assert resp.status_code == 422


@pytest.mark.anyio
class TestAdminUserDetailEndpoint:

    async def test_unknown_user_returns_404(self, client, admin_user, admin_token):
        """Test 21: 404 for non-existent user."""
        resp = await client.get(f"{BASE_LIST}/999999", headers=auth_header(admin_token))
        assert resp.status_code == 404

    async def test_returns_full_profile_fields(self, client, rider, admin_user, admin_token):
        """Test 22: 200 returns all expected profile fields."""
        resp = await client.get(f"{BASE_LIST}/{rider.id}", headers=auth_header(admin_token))
        assert resp.status_code == 200
        data = resp.json()
        for field in (
            "id", "name", "email", "phone", "role", "status",
            "is_active", "phone_verified", "suspension_reason",
            "referral_code", "referred_by", "created_at", "updated_at", "ride_stats",
        ):
            assert field in data, f"Missing field: {field}"
        stats = data["ride_stats"]
        for stat_field in ("total_rides", "completed_rides", "cancelled_rides", "avg_rating"):
            assert stat_field in stats, f"Missing ride_stats field: {stat_field}"

    async def test_rider_token_returns_403(self, client, rider, rider_token):
        """Test 23: 403 when non-admin requests user detail."""
        resp = await client.get(f"{BASE_LIST}/{rider.id}", headers=auth_header(rider_token))
        assert resp.status_code == 403


@pytest.mark.anyio
class TestAdminSuspendUserEndpoint:

    async def test_unknown_user_returns_404(self, client, admin_user, admin_token):
        """Test 24: 404 for non-existent user."""
        resp = await client.post(
            f"{BASE_LIST}/999999/suspend",
            headers=auth_header(admin_token),
            json={"reason": "spam", "notify_user": False},
        )
        assert resp.status_code == 404

    async def test_suspend_active_user_returns_200(self, client, rider, admin_user, admin_token):
        """Test 25: 200 successfully suspends an active user."""
        resp = await client.post(
            f"{BASE_LIST}/{rider.id}/suspend",
            headers=auth_header(admin_token),
            json={"reason": "Policy violation", "notify_user": False},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["new_status"] == "suspended"
        assert data["previous_status"] == "active"
        assert data["user_id"] == rider.id

    async def test_suspend_already_suspended_returns_409(
        self, client, rider, admin_user, admin_token, db
    ):
        """Test 26: 409 when user is already suspended."""
        rider.status = UserStatus.SUSPENDED
        rider.suspension_reason = "Already done"
        await db.flush()

        resp = await client.post(
            f"{BASE_LIST}/{rider.id}/suspend",
            headers=auth_header(admin_token),
            json={"reason": "Again", "notify_user": False},
        )
        assert resp.status_code == 409


@pytest.mark.anyio
class TestAdminActivateUserEndpoint:

    async def test_activate_already_active_returns_409(
        self, client, rider, admin_user, admin_token
    ):
        """Test 27: 409 when user is already active."""
        # rider fixture starts active
        resp = await client.post(
            f"{BASE_LIST}/{rider.id}/activate",
            headers=auth_header(admin_token),
            json={"reason": "", "notify_user": False},
        )
        assert resp.status_code == 409

    async def test_activate_suspended_user_returns_200(
        self, client, rider, admin_user, admin_token, db
    ):
        """Test 28: 200 successfully activates a suspended user."""
        rider.status = UserStatus.SUSPENDED
        rider.suspension_reason = "test"
        await db.flush()

        resp = await client.post(
            f"{BASE_LIST}/{rider.id}/activate",
            headers=auth_header(admin_token),
            json={"reason": "Appeal approved", "notify_user": False},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["new_status"] == "active"
        assert data["previous_status"] == "suspended"
        assert data["user_id"] == rider.id

    async def test_activate_rider_token_returns_403(
        self, client, rider, rider_token
    ):
        """Test 29: 403 when non-admin attempts activation."""
        resp = await client.post(
            f"{BASE_LIST}/{rider.id}/activate",
            headers=auth_header(rider_token),
            json={"reason": "", "notify_user": False},
        )
        assert resp.status_code == 403
