"""Tests for pool passenger safety features.

GET /api/v1/pools/{pool_id}/passengers — co-rider roster
Pool-join notification — notify existing riders when a new one joins

Coverage
--------
Schema:
  1.  PoolPassengerEntry — required fields present
  2.  PoolPassengerEntry — is_me=True when rider is the caller
  3.  PoolPassengerEntry — is_me=False for other riders
  4.  PoolPassengersResponse — required fields present
  5.  PoolPassengersResponse — total_riders matches len(passengers)

Notification types and templates:
  6.  NotificationType.POOL_RIDER_JOINED exists in enum
  7.  pool_rider_joined template returns push channel
  8.  pool_rider_joined body contains new rider's name
  9.  pool_rider_joined body falls back gracefully with default name

Endpoint — mocked DB:
  10. 401 when no auth token provided
  11. 404 when pool not found
  12. Returns correct passenger count
  13. Returns correct first names (first word of User.name)
  14. is_me=True for the calling user's own entry
  15. is_me=False for co-riders
  16. Cancelled legs are excluded from roster
  17. Empty pool returns total_riders=0 and empty list

notify_pool_rider_joined dispatcher:
  18. Sends one notification per existing rider
  19. Uses POOL_RIDER_JOINED type
  20. Passes new_rider_name as template kwarg
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.pool import LegStatus
from app.schemas.pool import PoolPassengerEntry, PoolPassengersResponse
from app.services.notification_templates import pool_rider_joined, TEMPLATES
from app.services.notifications import NotificationChannel, NotificationType


NOW = datetime(2026, 4, 18, 12, 0, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_user(user_id: int = 1, name: str = "Alice Smith") -> MagicMock:
    user = MagicMock()
    user.id = user_id
    user.name = name
    user.role = MagicMock()
    user.role.value = "rider"
    user.is_active = True
    return user


def _make_leg(
    leg_id: int,
    ride_id: int,
    rider_id: int,
    status: LegStatus = LegStatus.WAITING_PICKUP,
) -> MagicMock:
    leg = MagicMock()
    leg.id = leg_id
    leg.ride_id = ride_id
    leg.pool_id = 1
    leg.status = status

    ride = MagicMock()
    ride.id = ride_id
    ride.rider_id = rider_id
    leg.ride = ride

    return leg


def _make_pool(pool_id: int = 1, legs: list | None = None) -> MagicMock:
    pool = MagicMock()
    pool.id = pool_id
    pool.legs = legs or []
    return pool


def _make_db_pool_found(pool: MagicMock, riders: list[MagicMock]) -> AsyncMock:
    """Mock DB: first execute returns pool, subsequent ones return riders."""
    db = AsyncMock()

    pool_result = MagicMock()
    pool_result.unique.return_value.scalar_one_or_none.return_value = pool

    rider_results = []
    for rider in riders:
        r = MagicMock()
        r.scalar_one_or_none.return_value = rider
        rider_results.append(r)

    db.execute = AsyncMock(side_effect=[pool_result] + rider_results)
    return db


def _make_db_pool_not_found() -> AsyncMock:
    db = AsyncMock()
    result = MagicMock()
    result.unique.return_value.scalar_one_or_none.return_value = None
    db.execute = AsyncMock(return_value=result)
    return db


# ---------------------------------------------------------------------------
# 1–5: Schema tests
# ---------------------------------------------------------------------------


class TestPoolPassengerEntrySchema:
    def test_required_fields_present(self):
        entry = PoolPassengerEntry(rider_first_name="Alice", is_me=True)
        assert entry.rider_first_name == "Alice"
        assert entry.is_me is True

    def test_is_me_true(self):
        entry = PoolPassengerEntry(rider_first_name="Bob", is_me=True)
        assert entry.is_me is True

    def test_is_me_false(self):
        entry = PoolPassengerEntry(rider_first_name="Carol", is_me=False)
        assert entry.is_me is False


class TestPoolPassengersResponseSchema:
    def test_required_fields_present(self):
        resp = PoolPassengersResponse(
            pool_id=1,
            total_riders=2,
            passengers=[
                PoolPassengerEntry(rider_first_name="Alice", is_me=True),
                PoolPassengerEntry(rider_first_name="Bob", is_me=False),
            ],
        )
        assert resp.pool_id == 1
        assert resp.total_riders == 2
        assert len(resp.passengers) == 2

    def test_total_riders_matches_list_length(self):
        passengers = [
            PoolPassengerEntry(rider_first_name="Alice", is_me=True),
            PoolPassengerEntry(rider_first_name="Bob", is_me=False),
            PoolPassengerEntry(rider_first_name="Carol", is_me=False),
        ]
        resp = PoolPassengersResponse(pool_id=5, total_riders=3, passengers=passengers)
        assert resp.total_riders == len(resp.passengers)


# ---------------------------------------------------------------------------
# 6–9: Notification type and template tests
# ---------------------------------------------------------------------------


class TestPoolRiderJoinedNotificationType:
    def test_enum_value_exists(self):
        assert NotificationType.POOL_RIDER_JOINED == "pool_rider_joined"

    def test_registered_in_templates(self):
        assert NotificationType.POOL_RIDER_JOINED in TEMPLATES


class TestPoolRiderJoinedTemplate:
    def test_returns_push_channel(self):
        _, _, channels = pool_rider_joined(new_rider_name="Dave")
        assert NotificationChannel.PUSH in channels

    def test_body_contains_rider_name(self):
        _, body, _ = pool_rider_joined(new_rider_name="Eve")
        assert "Eve" in body

    def test_default_name_fallback(self):
        title, body, _ = pool_rider_joined()
        assert "new rider" in body.lower()

    def test_title_present(self):
        title, _, _ = pool_rider_joined(new_rider_name="Frank")
        assert len(title) > 0


# ---------------------------------------------------------------------------
# 10: HTTP auth test
# ---------------------------------------------------------------------------


class TestPoolPassengersAuth:
    @pytest.mark.asyncio
    async def test_requires_authentication(self):
        from httpx import ASGITransport, AsyncClient
        from app.main import app

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/v1/pools/1/passengers")
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# 11–17: Endpoint unit tests (direct call, mocked DB)
# ---------------------------------------------------------------------------


class TestGetPoolPassengersEndpoint:
    @pytest.mark.asyncio
    async def test_pool_not_found_returns_404(self):
        from fastapi import HTTPException
        from app.api.v1.pools import get_pool_passengers

        caller = _make_user(user_id=10)
        db = _make_db_pool_not_found()

        with pytest.raises(HTTPException) as exc_info:
            await get_pool_passengers(pool_id=99, user=caller, db=db)
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_returns_correct_passenger_count(self):
        from app.api.v1.pools import get_pool_passengers

        caller = _make_user(user_id=10, name="Alice Smith")
        rider2 = _make_user(user_id=11, name="Bob Jones")

        leg1 = _make_leg(leg_id=1, ride_id=1, rider_id=10)
        leg2 = _make_leg(leg_id=2, ride_id=2, rider_id=11)
        pool = _make_pool(legs=[leg1, leg2])

        db = _make_db_pool_found(pool, riders=[caller, rider2])
        result = await get_pool_passengers(pool_id=1, user=caller, db=db)

        assert result.total_riders == 2
        assert len(result.passengers) == 2

    @pytest.mark.asyncio
    async def test_first_name_extracted_from_full_name(self):
        from app.api.v1.pools import get_pool_passengers

        caller = _make_user(user_id=10, name="Alice Smith")
        rider2 = _make_user(user_id=11, name="Bob Jones")

        leg1 = _make_leg(leg_id=1, ride_id=1, rider_id=10)
        leg2 = _make_leg(leg_id=2, ride_id=2, rider_id=11)
        pool = _make_pool(legs=[leg1, leg2])

        db = _make_db_pool_found(pool, riders=[caller, rider2])
        result = await get_pool_passengers(pool_id=1, user=caller, db=db)

        first_names = {p.rider_first_name for p in result.passengers}
        assert "Alice" in first_names
        assert "Bob" in first_names

    @pytest.mark.asyncio
    async def test_is_me_true_for_calling_user(self):
        from app.api.v1.pools import get_pool_passengers

        caller = _make_user(user_id=10, name="Alice Smith")
        rider2 = _make_user(user_id=11, name="Bob Jones")

        leg1 = _make_leg(leg_id=1, ride_id=1, rider_id=10)
        leg2 = _make_leg(leg_id=2, ride_id=2, rider_id=11)
        pool = _make_pool(legs=[leg1, leg2])

        db = _make_db_pool_found(pool, riders=[caller, rider2])
        result = await get_pool_passengers(pool_id=1, user=caller, db=db)

        my_entries = [p for p in result.passengers if p.is_me]
        other_entries = [p for p in result.passengers if not p.is_me]
        assert len(my_entries) == 1
        assert my_entries[0].rider_first_name == "Alice"
        assert len(other_entries) == 1
        assert other_entries[0].rider_first_name == "Bob"

    @pytest.mark.asyncio
    async def test_cancelled_legs_excluded(self):
        from app.api.v1.pools import get_pool_passengers

        caller = _make_user(user_id=10, name="Alice Smith")

        active_leg = _make_leg(leg_id=1, ride_id=1, rider_id=10, status=LegStatus.WAITING_PICKUP)
        cancelled_leg = _make_leg(leg_id=2, ride_id=2, rider_id=11, status=LegStatus.CANCELLED)
        pool = _make_pool(legs=[active_leg, cancelled_leg])

        # Only one user query since cancelled leg is skipped
        db = _make_db_pool_found(pool, riders=[caller])
        result = await get_pool_passengers(pool_id=1, user=caller, db=db)

        assert result.total_riders == 1
        assert result.passengers[0].is_me is True

    @pytest.mark.asyncio
    async def test_empty_pool_returns_zero(self):
        from app.api.v1.pools import get_pool_passengers

        caller = _make_user(user_id=10)
        pool = _make_pool(legs=[])

        db = _make_db_pool_found(pool, riders=[])
        result = await get_pool_passengers(pool_id=1, user=caller, db=db)

        assert result.total_riders == 0
        assert result.passengers == []


# ---------------------------------------------------------------------------
# 18–20: notify_pool_rider_joined dispatcher tests
# ---------------------------------------------------------------------------


class TestNotifyPoolRiderJoined:
    @pytest.mark.asyncio
    async def test_sends_one_notification_per_rider(self):
        from app.services.notification_events import notify_pool_rider_joined

        db = AsyncMock()
        db.execute = AsyncMock(return_value=MagicMock(one_or_none=MagicMock(return_value=None)))

        with patch("app.services.notification_events.send_ride_notification") as mock_send:
            mock_send.return_value = None
            # Patch _get_user_contact to return dummy values
            with patch("app.services.notification_events._get_user_contact", new=AsyncMock(return_value=("+15550001111", "a@b.com"))):
                await notify_pool_rider_joined(
                    db=db,
                    existing_rider_ids=[1, 2, 3],
                    new_rider_name="Diana",
                    ride_id=42,
                )
            assert mock_send.call_count == 3

    @pytest.mark.asyncio
    async def test_uses_pool_rider_joined_type(self):
        from app.services.notification_events import notify_pool_rider_joined

        db = AsyncMock()
        captured_types = []

        async def mock_send(user_id, type, ride_id, db, phone, email, **kwargs):
            captured_types.append(type)

        with patch("app.services.notification_events.send_ride_notification", side_effect=mock_send):
            with patch("app.services.notification_events._get_user_contact", new=AsyncMock(return_value=(None, None))):
                await notify_pool_rider_joined(
                    db=db,
                    existing_rider_ids=[5],
                    new_rider_name="Eve",
                    ride_id=10,
                )
        assert captured_types == [NotificationType.POOL_RIDER_JOINED]

    @pytest.mark.asyncio
    async def test_passes_new_rider_name_kwarg(self):
        from app.services.notification_events import notify_pool_rider_joined

        db = AsyncMock()
        captured_kwargs = []

        async def mock_send(user_id, type, ride_id, db, phone, email, **kwargs):
            captured_kwargs.append(kwargs)

        with patch("app.services.notification_events.send_ride_notification", side_effect=mock_send):
            with patch("app.services.notification_events._get_user_contact", new=AsyncMock(return_value=(None, None))):
                await notify_pool_rider_joined(
                    db=db,
                    existing_rider_ids=[7],
                    new_rider_name="Frank",
                    ride_id=10,
                )
        assert captured_kwargs[0].get("new_rider_name") == "Frank"
