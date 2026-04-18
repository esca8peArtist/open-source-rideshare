"""Tests for the safe arrival confirmation feature.

POST   /riders/me/rides/{ride_id}/safe-arrival
GET    /riders/me/rides/{ride_id}/safe-arrival

Coverage
--------
Service: confirm_safe_arrival
  - creates record for a completed ride
  - raises LookupError if ride does not exist
  - raises LookupError if ride belongs to a different rider
  - raises ValueError if ride is not COMPLETED
  - raises RuntimeError on duplicate confirmation
  - stores optional notes
  - confirmed_at is set

Service: get_safe_arrival
  - returns record for the correct owner
  - returns None for wrong user_id
  - returns None when no confirmation exists

Router: POST /riders/me/rides/{ride_id}/safe-arrival
  - 201 for a valid completed ride
  - 400 for non-completed ride (MATCHED status)
  - 404 when ride not found
  - 404 when ride belongs to another rider
  - 409 on duplicate confirmation

Router: GET /riders/me/rides/{ride_id}/safe-arrival
  - 200 returns SafeArrivalResponse after successful POST
  - 404 when not yet confirmed

Schema
  - SafeArrivalCreate defaults notes to None
  - SafeArrivalResponse model_config from_attributes=True
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock

from app.schemas.rider_safety import SafeArrivalCreate, SafeArrivalResponse
from app.services.rider_safety import (
    _reset_store,
    confirm_safe_arrival,
    get_safe_arrival,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def reset_safety_store():
    _reset_store()
    yield
    _reset_store()


def _make_mock_db(rider_id: int, ride_id: int, status_value: str = "completed"):
    """Build a mock DB session that returns a ride with the given status."""
    from app.models.ride import RideStatus

    mock_ride = MagicMock()
    mock_ride.id = ride_id
    mock_ride.rider_id = rider_id
    mock_ride.status = RideStatus(status_value)

    mock_result = MagicMock()
    mock_result.scalar_one_or_none = MagicMock(return_value=mock_ride)

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=mock_result)
    return mock_db


def _make_missing_db():
    """Build a mock DB that returns no ride."""
    mock_result = MagicMock()
    mock_result.scalar_one_or_none = MagicMock(return_value=None)
    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=mock_result)
    return mock_db


# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------


class TestSchemas:
    def test_safe_arrival_create_notes_defaults_none(self):
        req = SafeArrivalCreate()
        assert req.notes is None

    def test_safe_arrival_create_with_notes(self):
        req = SafeArrivalCreate(notes="Arrived safely at my front door.")
        assert req.notes == "Arrived safely at my front door."

    def test_safe_arrival_response_from_attributes(self):
        assert SafeArrivalResponse.model_config.get("from_attributes") is True


# ---------------------------------------------------------------------------
# Service: confirm_safe_arrival
# ---------------------------------------------------------------------------


class TestConfirmSafeArrival:
    @pytest.mark.asyncio
    async def test_creates_record_for_completed_ride(self):
        mock_db = _make_mock_db(rider_id=1, ride_id=100, status_value="completed")
        record = await confirm_safe_arrival(db=mock_db, ride_id=100, user_id=1)
        assert record["ride_id"] == 100
        assert record["user_id"] == 1

    @pytest.mark.asyncio
    async def test_confirmed_at_is_set(self):
        from datetime import datetime
        mock_db = _make_mock_db(rider_id=1, ride_id=100)
        record = await confirm_safe_arrival(db=mock_db, ride_id=100, user_id=1)
        assert isinstance(record["confirmed_at"], datetime)

    @pytest.mark.asyncio
    async def test_stores_optional_notes(self):
        mock_db = _make_mock_db(rider_id=1, ride_id=100)
        record = await confirm_safe_arrival(
            db=mock_db, ride_id=100, user_id=1, notes="Home safe."
        )
        assert record["notes"] == "Home safe."

    @pytest.mark.asyncio
    async def test_notes_defaults_to_none(self):
        mock_db = _make_mock_db(rider_id=1, ride_id=100)
        record = await confirm_safe_arrival(db=mock_db, ride_id=100, user_id=1)
        assert record["notes"] is None

    @pytest.mark.asyncio
    async def test_raises_lookup_error_when_ride_not_found(self):
        mock_db = _make_missing_db()
        with pytest.raises(LookupError):
            await confirm_safe_arrival(db=mock_db, ride_id=999, user_id=1)

    @pytest.mark.asyncio
    async def test_raises_lookup_error_for_wrong_rider(self):
        # Ride belongs to rider_id=1, but we pass user_id=2
        mock_db = _make_mock_db(rider_id=1, ride_id=100)
        with pytest.raises(LookupError):
            await confirm_safe_arrival(db=mock_db, ride_id=100, user_id=2)

    @pytest.mark.asyncio
    async def test_raises_value_error_for_non_completed_ride(self):
        mock_db = _make_mock_db(rider_id=1, ride_id=100, status_value="matched")
        with pytest.raises(ValueError, match="ride must be completed"):
            await confirm_safe_arrival(db=mock_db, ride_id=100, user_id=1)

    @pytest.mark.asyncio
    async def test_raises_value_error_for_in_progress_ride(self):
        mock_db = _make_mock_db(rider_id=1, ride_id=100, status_value="in_progress")
        with pytest.raises(ValueError, match="ride must be completed"):
            await confirm_safe_arrival(db=mock_db, ride_id=100, user_id=1)

    @pytest.mark.asyncio
    async def test_raises_runtime_error_on_duplicate(self):
        mock_db = _make_mock_db(rider_id=1, ride_id=100)
        await confirm_safe_arrival(db=mock_db, ride_id=100, user_id=1)
        with pytest.raises(RuntimeError, match="safe arrival already confirmed"):
            await confirm_safe_arrival(db=mock_db, ride_id=100, user_id=1)

    @pytest.mark.asyncio
    async def test_id_is_integer(self):
        mock_db = _make_mock_db(rider_id=1, ride_id=100)
        record = await confirm_safe_arrival(db=mock_db, ride_id=100, user_id=1)
        assert isinstance(record["id"], int)

    @pytest.mark.asyncio
    async def test_different_rides_get_different_ids(self):
        db1 = _make_mock_db(rider_id=1, ride_id=100)
        db2 = _make_mock_db(rider_id=1, ride_id=200)
        r1 = await confirm_safe_arrival(db=db1, ride_id=100, user_id=1)
        r2 = await confirm_safe_arrival(db=db2, ride_id=200, user_id=1)
        assert r1["id"] != r2["id"]


# ---------------------------------------------------------------------------
# Service: get_safe_arrival
# ---------------------------------------------------------------------------


class TestGetSafeArrival:
    @pytest.mark.asyncio
    async def test_returns_record_for_correct_owner(self):
        mock_db = _make_mock_db(rider_id=1, ride_id=100)
        await confirm_safe_arrival(db=mock_db, ride_id=100, user_id=1)
        result = await get_safe_arrival(db=mock_db, ride_id=100, user_id=1)
        assert result is not None
        assert result["ride_id"] == 100

    @pytest.mark.asyncio
    async def test_returns_none_for_wrong_user(self):
        mock_db = _make_mock_db(rider_id=1, ride_id=100)
        await confirm_safe_arrival(db=mock_db, ride_id=100, user_id=1)
        result = await get_safe_arrival(db=mock_db, ride_id=100, user_id=99)
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_when_no_confirmation(self):
        mock_db = AsyncMock()
        result = await get_safe_arrival(db=mock_db, ride_id=999, user_id=1)
        assert result is None


# ---------------------------------------------------------------------------
# Router tests
# ---------------------------------------------------------------------------


class TestRouter:
    @pytest.mark.asyncio
    async def test_post_returns_201_for_completed_ride(self):
        from fastapi import HTTPException
        from app.api.v1.rider_safety import post_confirm_safe_arrival

        mock_rider = MagicMock()
        mock_rider.id = 1
        mock_db = _make_mock_db(rider_id=1, ride_id=100)

        body = SafeArrivalCreate(notes="All good.")
        result = await post_confirm_safe_arrival(
            ride_id=100, body=body, rider=mock_rider, db=mock_db
        )
        assert isinstance(result, SafeArrivalResponse)
        assert result.ride_id == 100
        assert result.user_id == 1

    @pytest.mark.asyncio
    async def test_post_400_for_non_completed_ride(self):
        from fastapi import HTTPException
        from app.api.v1.rider_safety import post_confirm_safe_arrival

        mock_rider = MagicMock()
        mock_rider.id = 1
        mock_db = _make_mock_db(rider_id=1, ride_id=100, status_value="matched")

        body = SafeArrivalCreate()
        with pytest.raises(HTTPException) as exc_info:
            await post_confirm_safe_arrival(
                ride_id=100, body=body, rider=mock_rider, db=mock_db
            )
        assert exc_info.value.status_code == 400
        assert "completed" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_post_404_when_ride_not_found(self):
        from fastapi import HTTPException
        from app.api.v1.rider_safety import post_confirm_safe_arrival

        mock_rider = MagicMock()
        mock_rider.id = 1
        mock_db = _make_missing_db()

        body = SafeArrivalCreate()
        with pytest.raises(HTTPException) as exc_info:
            await post_confirm_safe_arrival(
                ride_id=999, body=body, rider=mock_rider, db=mock_db
            )
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_post_404_when_ride_belongs_to_another_rider(self):
        from fastapi import HTTPException
        from app.api.v1.rider_safety import post_confirm_safe_arrival

        mock_rider = MagicMock()
        mock_rider.id = 2  # Different user
        mock_db = _make_mock_db(rider_id=1, ride_id=100)  # Belongs to rider 1

        body = SafeArrivalCreate()
        with pytest.raises(HTTPException) as exc_info:
            await post_confirm_safe_arrival(
                ride_id=100, body=body, rider=mock_rider, db=mock_db
            )
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_post_409_on_duplicate_confirmation(self):
        from fastapi import HTTPException
        from app.api.v1.rider_safety import post_confirm_safe_arrival

        mock_rider = MagicMock()
        mock_rider.id = 1
        mock_db = _make_mock_db(rider_id=1, ride_id=100)

        body = SafeArrivalCreate()
        # First confirmation
        await post_confirm_safe_arrival(
            ride_id=100, body=body, rider=mock_rider, db=mock_db
        )
        # Second should 409
        with pytest.raises(HTTPException) as exc_info:
            await post_confirm_safe_arrival(
                ride_id=100, body=body, rider=mock_rider, db=mock_db
            )
        assert exc_info.value.status_code == 409

    @pytest.mark.asyncio
    async def test_get_returns_200_after_confirmation(self):
        from fastapi import HTTPException
        from app.api.v1.rider_safety import (
            get_safe_arrival_endpoint,
            post_confirm_safe_arrival,
        )

        mock_rider = MagicMock()
        mock_rider.id = 1
        mock_db = _make_mock_db(rider_id=1, ride_id=100)

        body = SafeArrivalCreate(notes="Made it.")
        await post_confirm_safe_arrival(
            ride_id=100, body=body, rider=mock_rider, db=mock_db
        )

        result = await get_safe_arrival_endpoint(
            ride_id=100, rider=mock_rider, db=mock_db
        )
        assert isinstance(result, SafeArrivalResponse)
        assert result.ride_id == 100
        assert result.notes == "Made it."

    @pytest.mark.asyncio
    async def test_get_404_when_not_confirmed(self):
        from fastapi import HTTPException
        from app.api.v1.rider_safety import get_safe_arrival_endpoint

        mock_rider = MagicMock()
        mock_rider.id = 1
        mock_db = AsyncMock()

        with pytest.raises(HTTPException) as exc_info:
            await get_safe_arrival_endpoint(
                ride_id=100, rider=mock_rider, db=mock_db
            )
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_response_notes_stored_correctly(self):
        from app.api.v1.rider_safety import post_confirm_safe_arrival

        mock_rider = MagicMock()
        mock_rider.id = 1
        mock_db = _make_mock_db(rider_id=1, ride_id=100)

        body = SafeArrivalCreate(notes="Safe and sound at home.")
        result = await post_confirm_safe_arrival(
            ride_id=100, body=body, rider=mock_rider, db=mock_db
        )
        assert result.notes == "Safe and sound at home."
