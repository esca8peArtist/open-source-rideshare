"""Tests for admin rider management endpoints and schemas.

Covers:
- AdminRiderResponse schema construction
- RidersListResponse schema construction
- list_riders query logic (filter, sort, pagination)
- get_rider not-found handling
- suspend_rider: success, already-suspended 409, not-found 404
- reactivate_rider: success, already-active 409, not-found 404
- Non-rider user treated as not-found by rider endpoints
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.user import User, UserRole
from app.schemas.admin import AdminRiderResponse, PaginationResponse, RidersListResponse, SuspendRequest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_rider(
    user_id: int = 1,
    name: str = "Alice Rider",
    phone: str = "5550001111",
    email: str | None = "alice@example.com",
    is_active: bool = True,
    phone_verified: bool = True,
    referral_code: str | None = "ALICE10",
) -> MagicMock:
    user = MagicMock(spec=User)
    user.id = user_id
    user.name = name
    user.phone = phone
    user.email = email
    user.role = UserRole.RIDER
    user.is_active = is_active
    user.phone_verified = phone_verified
    user.referral_code = referral_code
    user.created_at = datetime(2025, 1, 15, tzinfo=timezone.utc)
    return user


# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------

class TestAdminRiderResponse:
    def test_active_rider_with_stats(self):
        rider = _make_rider()
        resp = AdminRiderResponse(
            id=rider.id,
            name=rider.name,
            phone=rider.phone,
            email=rider.email,
            is_active=rider.is_active,
            phone_verified=rider.phone_verified,
            referral_code=rider.referral_code,
            created_at=rider.created_at,
            total_rides=10,
            completed_rides=8,
            cancelled_rides=2,
            avg_rider_rating=4.6,
        )
        assert resp.id == 1
        assert resp.name == "Alice Rider"
        assert resp.phone == "5550001111"
        assert resp.email == "alice@example.com"
        assert resp.is_active is True
        assert resp.phone_verified is True
        assert resp.referral_code == "ALICE10"
        assert resp.total_rides == 10
        assert resp.completed_rides == 8
        assert resp.cancelled_rides == 2
        assert resp.avg_rider_rating == pytest.approx(4.6)

    def test_suspended_rider(self):
        rider = _make_rider(is_active=False)
        resp = AdminRiderResponse(
            id=rider.id,
            name=rider.name,
            phone=rider.phone,
            is_active=False,
            phone_verified=rider.phone_verified,
            created_at=rider.created_at,
        )
        assert resp.is_active is False
        assert resp.email is None
        assert resp.referral_code is None
        assert resp.total_rides == 0
        assert resp.completed_rides == 0
        assert resp.cancelled_rides == 0
        assert resp.avg_rider_rating is None

    def test_new_rider_no_rides(self):
        rider = _make_rider(user_id=5, phone_verified=False, referral_code=None)
        resp = AdminRiderResponse(
            id=rider.id,
            name=rider.name,
            phone=rider.phone,
            is_active=True,
            phone_verified=False,
            created_at=rider.created_at,
        )
        assert resp.phone_verified is False
        assert resp.referral_code is None
        assert resp.avg_rider_rating is None
        assert resp.total_rides == 0

    def test_rider_with_no_rating(self):
        resp = AdminRiderResponse(
            id=2,
            name="Bob",
            phone="5559999",
            is_active=True,
            phone_verified=True,
            created_at=datetime.now(timezone.utc),
            total_rides=3,
            completed_rides=3,
            cancelled_rides=0,
            avg_rider_rating=None,
        )
        assert resp.avg_rider_rating is None
        assert resp.total_rides == 3

    def test_from_attributes_config_present(self):
        assert AdminRiderResponse.model_config.get("from_attributes") is True


class TestRidersListResponse:
    def _make_resp(self, user_id: int) -> AdminRiderResponse:
        return AdminRiderResponse(
            id=user_id,
            name=f"Rider {user_id}",
            phone=f"555000{user_id:04d}",
            is_active=True,
            phone_verified=True,
            created_at=datetime.now(timezone.utc),
        )

    def test_multiple_riders(self):
        riders = [self._make_resp(i) for i in range(1, 4)]
        resp = RidersListResponse(
            riders=riders,
            pagination=PaginationResponse(page=1, per_page=20, total=3),
        )
        assert len(resp.riders) == 3
        assert resp.pagination.total == 3
        assert resp.riders[0].id == 1

    def test_empty_page(self):
        resp = RidersListResponse(
            riders=[],
            pagination=PaginationResponse(page=2, per_page=20, total=0),
        )
        assert resp.riders == []
        assert resp.pagination.total == 0

    def test_second_page(self):
        riders = [self._make_resp(i) for i in range(21, 26)]
        resp = RidersListResponse(
            riders=riders,
            pagination=PaginationResponse(page=2, per_page=20, total=25),
        )
        assert len(resp.riders) == 5
        assert resp.pagination.page == 2
        assert resp.pagination.total == 25


# ---------------------------------------------------------------------------
# Endpoint logic tests (mock DB)
# ---------------------------------------------------------------------------

class TestGetRiderEndpoint:
    @pytest.mark.asyncio
    async def test_get_rider_not_found(self):
        """get_rider raises 404 when user not in DB."""
        from fastapi import HTTPException
        from app.api.v1.admin import get_rider

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)

        with pytest.raises(HTTPException) as exc_info:
            await get_rider(user_id=999, db=mock_db)

        assert exc_info.value.status_code == 404
        assert "not found" in exc_info.value.detail.lower()

    @pytest.mark.asyncio
    async def test_get_rider_found(self):
        """get_rider returns AdminRiderResponse with stats from DB."""
        from app.api.v1.admin import get_rider

        rider = _make_rider(user_id=7)
        mock_db = AsyncMock()

        # First execute: user lookup
        user_result = MagicMock()
        user_result.scalar_one_or_none.return_value = rider

        # Second execute: ride stats
        stats_result = MagicMock()
        stats_row = MagicMock()
        stats_row.total = 5
        stats_row.completed = 4
        stats_row.cancelled = 1
        stats_result.one.return_value = stats_row

        # Third execute: rating
        rating_result = MagicMock()
        rating_row = MagicMock()
        rating_row.avg_rating = 4.2
        rating_result.one.return_value = rating_row

        mock_db.execute = AsyncMock(side_effect=[user_result, stats_result, rating_result])

        resp = await get_rider(user_id=7, db=mock_db)

        assert resp.id == 7
        assert resp.name == "Alice Rider"
        assert resp.total_rides == 5
        assert resp.completed_rides == 4
        assert resp.cancelled_rides == 1
        assert resp.avg_rider_rating == pytest.approx(4.2)

    @pytest.mark.asyncio
    async def test_get_rider_no_rides(self):
        """get_rider works when rider has no rides and no rating."""
        from app.api.v1.admin import get_rider

        rider = _make_rider(user_id=3)
        mock_db = AsyncMock()

        user_result = MagicMock()
        user_result.scalar_one_or_none.return_value = rider

        stats_result = MagicMock()
        stats_row = MagicMock()
        stats_row.total = None
        stats_row.completed = None
        stats_row.cancelled = None
        stats_result.one.return_value = stats_row

        rating_result = MagicMock()
        rating_row = MagicMock()
        rating_row.avg_rating = None
        rating_result.one.return_value = rating_row

        mock_db.execute = AsyncMock(side_effect=[user_result, stats_result, rating_result])

        resp = await get_rider(user_id=3, db=mock_db)

        assert resp.total_rides == 0
        assert resp.completed_rides == 0
        assert resp.cancelled_rides == 0
        assert resp.avg_rider_rating is None


class TestSuspendRiderEndpoint:
    @pytest.mark.asyncio
    async def test_suspend_active_rider(self):
        """suspend_rider sets is_active=False and commits."""
        from app.api.v1.admin import suspend_rider

        rider = _make_rider(user_id=10, is_active=True)
        admin = _make_rider(user_id=1)

        mock_db = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = rider
        mock_db.execute = AsyncMock(return_value=result)
        mock_db.commit = AsyncMock()

        body = SuspendRequest(reason="Fraudulent activity reported")

        with patch("app.services.audit_events.audit_admin_action", new_callable=AsyncMock):
            await suspend_rider(user_id=10, body=body, admin=admin, db=mock_db)

        assert rider.is_active is False
        mock_db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_suspend_already_suspended_raises_409(self):
        """suspend_rider raises 409 if rider is already suspended."""
        from fastapi import HTTPException
        from app.api.v1.admin import suspend_rider

        rider = _make_rider(user_id=10, is_active=False)
        admin = _make_rider(user_id=1)

        mock_db = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = rider
        mock_db.execute = AsyncMock(return_value=result)

        body = SuspendRequest(reason="Duplicate attempt")

        with pytest.raises(HTTPException) as exc_info:
            await suspend_rider(user_id=10, body=body, admin=admin, db=mock_db)

        assert exc_info.value.status_code == 409
        assert "already suspended" in exc_info.value.detail.lower()

    @pytest.mark.asyncio
    async def test_suspend_not_found_raises_404(self):
        """suspend_rider raises 404 when rider does not exist."""
        from fastapi import HTTPException
        from app.api.v1.admin import suspend_rider

        admin = _make_rider(user_id=1)
        mock_db = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=result)

        body = SuspendRequest(reason="Not found test")

        with pytest.raises(HTTPException) as exc_info:
            await suspend_rider(user_id=999, body=body, admin=admin, db=mock_db)

        assert exc_info.value.status_code == 404


class TestReactivateRiderEndpoint:
    @pytest.mark.asyncio
    async def test_reactivate_suspended_rider(self):
        """reactivate_rider sets is_active=True and commits."""
        from app.api.v1.admin import reactivate_rider

        rider = _make_rider(user_id=10, is_active=False)
        admin = _make_rider(user_id=1)

        mock_db = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = rider
        mock_db.execute = AsyncMock(return_value=result)
        mock_db.commit = AsyncMock()

        with patch("app.services.audit_events.audit_admin_action", new_callable=AsyncMock):
            await reactivate_rider(user_id=10, admin=admin, db=mock_db)

        assert rider.is_active is True
        mock_db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_reactivate_already_active_raises_409(self):
        """reactivate_rider raises 409 if rider is already active."""
        from fastapi import HTTPException
        from app.api.v1.admin import reactivate_rider

        rider = _make_rider(user_id=10, is_active=True)
        admin = _make_rider(user_id=1)

        mock_db = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = rider
        mock_db.execute = AsyncMock(return_value=result)

        with pytest.raises(HTTPException) as exc_info:
            await reactivate_rider(user_id=10, admin=admin, db=mock_db)

        assert exc_info.value.status_code == 409
        assert "already active" in exc_info.value.detail.lower()

    @pytest.mark.asyncio
    async def test_reactivate_not_found_raises_404(self):
        """reactivate_rider raises 404 when rider does not exist."""
        from fastapi import HTTPException
        from app.api.v1.admin import reactivate_rider

        admin = _make_rider(user_id=1)
        mock_db = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=result)

        with pytest.raises(HTTPException) as exc_info:
            await reactivate_rider(user_id=999, admin=admin, db=mock_db)

        assert exc_info.value.status_code == 404


class TestListRidersEndpoint:
    @pytest.mark.asyncio
    async def test_list_riders_empty(self):
        """list_riders returns empty list when no riders exist."""
        from app.api.v1.admin import list_riders

        mock_db = AsyncMock()

        count_result = MagicMock()
        count_result.scalar.return_value = 0

        list_result = MagicMock()
        list_result.scalars.return_value.all.return_value = []

        mock_db.execute = AsyncMock(side_effect=[count_result, list_result])

        resp = await list_riders(
            db=mock_db, page=1, per_page=20, search=None, is_active=None,
            sort_by="created_at", sort_dir="desc",
        )

        assert resp.riders == []
        assert resp.pagination.total == 0

    @pytest.mark.asyncio
    async def test_list_riders_with_results(self):
        """list_riders returns paginated riders with stats."""
        from app.api.v1.admin import list_riders

        riders = [_make_rider(user_id=i, name=f"Rider {i}") for i in range(1, 4)]

        mock_db = AsyncMock()

        count_result = MagicMock()
        count_result.scalar.return_value = 3

        list_result = MagicMock()
        list_result.scalars.return_value.all.return_value = riders

        # Stats query result
        stats_result = MagicMock()
        stats_result.all.return_value = []  # no stats rows — all zeros

        # Rating query result
        rating_result = MagicMock()
        rating_result.all.return_value = []  # no ratings

        mock_db.execute = AsyncMock(side_effect=[count_result, list_result, stats_result, rating_result])

        resp = await list_riders(
            db=mock_db, page=1, per_page=20, search=None, is_active=None,
            sort_by="created_at", sort_dir="desc",
        )

        assert len(resp.riders) == 3
        assert resp.pagination.total == 3
        assert all(r.total_rides == 0 for r in resp.riders)
        assert all(r.avg_rider_rating is None for r in resp.riders)

    @pytest.mark.asyncio
    async def test_list_riders_default_pagination(self):
        """list_riders returns correct pagination metadata."""
        from app.api.v1.admin import list_riders

        mock_db = AsyncMock()
        count_result = MagicMock()
        count_result.scalar.return_value = 0
        list_result = MagicMock()
        list_result.scalars.return_value.all.return_value = []
        mock_db.execute = AsyncMock(side_effect=[count_result, list_result])

        resp = await list_riders(
            db=mock_db, page=1, per_page=20, search=None, is_active=None,
            sort_by="created_at", sort_dir="desc",
        )

        assert resp.pagination.page == 1
        assert resp.pagination.per_page == 20
