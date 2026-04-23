"""Integration tests: ride completion triggers incentive progress.

Covers:
- complete_ride calls record_trip_completion with correct args
- ride completion is resilient to incentive failures (fire-and-forget)
- quest progress advances through the DB when a ride completes
- peak-hours bonus accumulates across multiple completions
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.models.incentive import DriverIncentiveProgress, IncentiveProgram, ProgressStatus, ProgramType
from app.models.ride import Ride, RideStatus
from app.models.user import User, UserRole
from app.services.incentives import (
    create_or_get_progress,
    get_driver_progress,
    record_trip_completion,
)
from tests.conftest import auth_header

NOW = datetime(2026, 4, 23, 10, 0, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Helpers shared across unit tests
# ---------------------------------------------------------------------------


def _make_user(user_id: int = 20, role: UserRole = UserRole.DRIVER) -> MagicMock:
    u = MagicMock(spec=User)
    u.id = user_id
    u.role = role
    u.name = "Test"
    u.referred_by = None
    return u


def _make_ride(
    ride_id: int = 1,
    driver_id: int = 20,
    rider_id: int = 10,
    status: RideStatus = RideStatus.IN_PROGRESS,
    fare: float = 18.00,
) -> MagicMock:
    r = MagicMock(spec=Ride)
    r.id = ride_id
    r.driver_id = driver_id
    r.rider_id = rider_id
    r.status = status
    r.estimated_fare = fare
    r.actual_fare = fare
    r.completed_at = NOW
    return r


def _make_mock_db(ride, fare: float = 18.00) -> AsyncMock:
    """Return a mock db with enough side_effect entries to pass complete_ride."""
    ride_result = MagicMock()
    ride_result.scalar_one_or_none.return_value = ride

    count_result = MagicMock()
    count_result.scalar.return_value = 1  # not first ride

    rider_obj = MagicMock()
    rider_obj.referred_by = None
    rider_result = MagicMock()
    rider_result.scalar_one_or_none.return_value = rider_obj

    profile = MagicMock()
    profile.total_trips = 10
    profile_result = MagicMock()
    profile_result.scalar_one_or_none.return_value = profile

    # driver referral lookup — returns None (no pending referral)
    referral_result = MagicMock()
    referral_result.scalar_one_or_none.return_value = None

    db = AsyncMock()
    db.execute.side_effect = [ride_result, count_result, rider_result, profile_result, referral_result]
    return db


# ---------------------------------------------------------------------------
# Unit tests: wiring
# ---------------------------------------------------------------------------


class TestCompleteRideCallsIncentives:
    @pytest.mark.asyncio
    @patch("app.api.websocket.notify_ride_status", new_callable=AsyncMock)
    @patch("app.api.v1.rides.get_matching_engine", new_callable=AsyncMock)
    @patch("app.services.incentives.record_trip_completion", new_callable=AsyncMock)
    async def test_record_trip_completion_is_called(
        self,
        mock_record,
        mock_engine_fn,
        mock_ws,
    ):
        """complete_ride calls record_trip_completion with driver_id, ride_id, completed_at."""
        from app.api.v1.rides import complete_ride

        mock_engine_fn.return_value = AsyncMock()

        driver = _make_user(user_id=20)
        ride = _make_ride(ride_id=5, driver_id=20)
        db = _make_mock_db(ride)

        result = await complete_ride(ride_id=5, driver=driver, db=db)

        assert result["status"] == "completed"
        mock_record.assert_awaited_once()
        call_kwargs = mock_record.call_args
        assert call_kwargs.kwargs.get("driver_id") == 20 or call_kwargs.args[1] == 20
        assert call_kwargs.kwargs.get("ride_id") == 5 or call_kwargs.args[2] == 5

    @pytest.mark.asyncio
    @patch("app.api.websocket.notify_ride_status", new_callable=AsyncMock)
    @patch("app.api.v1.rides.get_matching_engine", new_callable=AsyncMock)
    @patch(
        "app.services.incentives.record_trip_completion",
        new_callable=AsyncMock,
        side_effect=RuntimeError("DB exploded"),
    )
    async def test_incentive_failure_does_not_block_ride_completion(
        self,
        mock_record,
        mock_engine_fn,
        mock_ws,
    ):
        """Ride completion succeeds even if record_trip_completion raises."""
        from app.api.v1.rides import complete_ride

        mock_engine_fn.return_value = AsyncMock()

        driver = _make_user(user_id=20)
        ride = _make_ride(ride_id=6, driver_id=20)
        db = _make_mock_db(ride)

        # Should not raise
        result = await complete_ride(ride_id=6, driver=driver, db=db)
        assert result["status"] == "completed"


# ---------------------------------------------------------------------------
# Integration tests: real DB — incentive progress via service
# ---------------------------------------------------------------------------


def _make_program(
    db,
    name: str,
    program_type: str = ProgramType.QUEST.value,
    bonus_amount: float = 20.0,
    trip_target: int = 3,
) -> IncentiveProgram:
    p = IncentiveProgram(
        name=name,
        description="Test",
        program_type=program_type,
        bonus_amount=bonus_amount,
        trip_target=trip_target,
        start_date=date.today(),
        is_active=True,
    )
    db.add(p)
    return p


@pytest.mark.anyio
class TestQuestProgressOnRideComplete:
    async def test_quest_increments_on_completion(self, db, driver_user):
        """record_trip_completion advances quest progress for the completing driver."""
        _make_program(db, name="QuestWire", trip_target=3)
        await db.flush()
        result = await db.execute(
            select(IncentiveProgram).where(IncentiveProgram.name == "QuestWire")
        )
        program = result.scalar_one()

        await record_trip_completion(db, driver_id=driver_user.id, ride_id=1, completed_at=NOW)

        progress = await get_driver_progress(db, driver_user.id, program.id, date.today())
        assert progress is not None
        assert progress.trips_completed == 1
        assert progress.status == ProgressStatus.ACTIVE.value

    async def test_quest_completes_at_trip_target(self, db, driver_user):
        """Quest moves to COMPLETED status when driver hits trip_target."""
        _make_program(db, name="QuestFinish", trip_target=2, bonus_amount=10.0)
        await db.flush()
        result = await db.execute(
            select(IncentiveProgram).where(IncentiveProgram.name == "QuestFinish")
        )
        program = result.scalar_one()

        await record_trip_completion(db, driver_id=driver_user.id, ride_id=10, completed_at=NOW)
        await record_trip_completion(db, driver_id=driver_user.id, ride_id=11, completed_at=NOW)

        progress = await get_driver_progress(db, driver_user.id, program.id, date.today())
        assert progress.status == ProgressStatus.COMPLETED.value
        assert progress.bonus_earned == 10.0

    async def test_other_driver_unaffected(self, db, driver_user, rider):
        """Only the completing driver's progress is updated."""
        _make_program(db, name="QuestIsolated", trip_target=5)
        await db.flush()
        result = await db.execute(
            select(IncentiveProgram).where(IncentiveProgram.name == "QuestIsolated")
        )
        program = result.scalar_one()

        await record_trip_completion(db, driver_id=driver_user.id, ride_id=20, completed_at=NOW)

        # rider is a different user — should have no progress record
        other_progress = await get_driver_progress(db, rider.id, program.id, date.today())
        assert other_progress is None


@pytest.mark.anyio
class TestPeakHoursProgressOnRideComplete:
    async def test_peak_hours_bonus_accumulates(self, db, driver_user):
        """Peak-hours program bonus accumulates each qualifying trip."""
        from datetime import time as dtime

        p = IncentiveProgram(
            name="PeakWire",
            description="Peak",
            program_type=ProgramType.PEAK_HOURS.value,
            bonus_amount=2.50,
            trip_target=None,
            start_date=date.today(),
            start_time=dtime(8, 0),
            end_time=dtime(12, 0),
            is_active=True,
        )
        db.add(p)
        await db.flush()
        result = await db.execute(
            select(IncentiveProgram).where(IncentiveProgram.name == "PeakWire")
        )
        program = result.scalar_one()

        # NOW is 10:00 — within window
        await record_trip_completion(db, driver_id=driver_user.id, ride_id=30, completed_at=NOW)
        await record_trip_completion(db, driver_id=driver_user.id, ride_id=31, completed_at=NOW)

        progress = await get_driver_progress(db, driver_user.id, program.id, date.today())
        assert progress is not None
        assert progress.trips_completed == 2
        assert abs(progress.bonus_earned - 5.00) < 0.01


@pytest.mark.anyio
class TestIncentiveProgressViaAPI:
    async def test_pending_earnings_reflects_completed_quest(
        self, client: AsyncClient, driver_token, driver_user, db
    ):
        """GET /incentives/earnings/pending returns earned bonus after quest completes."""
        _make_program(db, name="PendingTest", trip_target=1, bonus_amount=25.0)
        await db.flush()

        await record_trip_completion(db, driver_id=driver_user.id, ride_id=99, completed_at=NOW)
        await db.flush()

        resp = await client.get(
            "/api/v1/incentives/earnings/pending",
            headers=auth_header(driver_token),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["pending_bonus"] == 25.0
