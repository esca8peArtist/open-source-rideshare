"""Tests for driver incentive / bonus program system.

Covers models, service logic, and API endpoints.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

from app.models.incentive import DriverIncentiveProgress, IncentiveProgram, ProgressStatus, ProgramType
from app.services.incentives import (
    create_or_get_progress,
    get_active_programs,
    get_driver_progress,
    get_driver_summary,
    mark_bonuses_paid,
    record_trip_completion,
)
from tests.conftest import auth_header


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_program(
    db,
    name: str = "Test Quest",
    program_type: str = ProgramType.QUEST.value,
    bonus_amount: float = 15.0,
    trip_target: int | None = 5,
    start_time: time | None = None,
    end_time: time | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    days_of_week: str | None = None,
    is_active: bool = True,
) -> IncentiveProgram:
    p = IncentiveProgram(
        name=name,
        description="A test program",
        program_type=program_type,
        bonus_amount=bonus_amount,
        trip_target=trip_target,
        start_time=start_time,
        end_time=end_time,
        start_date=start_date or date.today(),
        end_date=end_date,
        days_of_week=days_of_week,
        is_active=is_active,
    )
    db.add(p)
    return p


NOW = datetime(2026, 4, 13, 9, 0, 0, tzinfo=timezone.utc)  # Monday 09:00 UTC


# ---------------------------------------------------------------------------
# Service: get_active_programs
# ---------------------------------------------------------------------------


@pytest.mark.anyio
class TestGetActivePrograms:
    async def test_returns_active_program(self, db):
        make_program(db, name="Active1")
        await db.flush()
        programs = await get_active_programs(db)
        names = [p.name for p in programs]
        assert "Active1" in names

    async def test_excludes_inactive_program(self, db):
        make_program(db, name="Inactive1", is_active=False)
        await db.flush()
        programs = await get_active_programs(db)
        names = [p.name for p in programs]
        assert "Inactive1" not in names

    async def test_excludes_expired_program(self, db):
        make_program(db, name="Expired1", end_date=date(2020, 1, 1))
        await db.flush()
        programs = await get_active_programs(db)
        names = [p.name for p in programs]
        assert "Expired1" not in names

    async def test_includes_ongoing_no_end_date(self, db):
        make_program(db, name="Ongoing1", end_date=None)
        await db.flush()
        programs = await get_active_programs(db)
        names = [p.name for p in programs]
        assert "Ongoing1" in names

    async def test_excludes_future_start_date(self, db):
        make_program(db, name="Future1", start_date=date.today() + timedelta(days=30))
        await db.flush()
        programs = await get_active_programs(db)
        names = [p.name for p in programs]
        assert "Future1" not in names


# ---------------------------------------------------------------------------
# Service: create_or_get_progress
# ---------------------------------------------------------------------------


@pytest.mark.anyio
class TestCreateOrGetProgress:
    async def test_creates_new_progress(self, db, driver_user):
        make_program(db, name="NewProg")
        await db.flush()
        result = await db.execute(
            __import__("sqlalchemy").select(IncentiveProgram).where(IncentiveProgram.name == "NewProg")
        )
        program = result.scalar_one()

        progress = await create_or_get_progress(db, driver_user.id, program.id)
        assert progress.driver_id == driver_user.id
        assert progress.trips_completed == 0
        assert progress.status == ProgressStatus.ACTIVE.value

    async def test_returns_existing_progress(self, db, driver_user):
        make_program(db, name="ExistProg")
        await db.flush()
        from sqlalchemy import select
        result = await db.execute(select(IncentiveProgram).where(IncentiveProgram.name == "ExistProg"))
        program = result.scalar_one()

        p1 = await create_or_get_progress(db, driver_user.id, program.id)
        p2 = await create_or_get_progress(db, driver_user.id, program.id)
        assert p1.id == p2.id


# ---------------------------------------------------------------------------
# Service: record_trip_completion — quest
# ---------------------------------------------------------------------------


@pytest.mark.anyio
class TestRecordTripQuest:
    async def test_quest_increments_trips(self, db, driver_user):
        make_program(db, name="QuestInc", program_type="quest", trip_target=5)
        await db.flush()
        from sqlalchemy import select
        result = await db.execute(select(IncentiveProgram).where(IncentiveProgram.name == "QuestInc"))
        program = result.scalar_one()

        updated = await record_trip_completion(db, driver_user.id, ride_id=1, completed_at=NOW)
        matching = [r for r in updated if r.program_id == program.id]
        assert len(matching) == 1
        assert matching[0].trips_completed == 1
        assert matching[0].status == ProgressStatus.ACTIVE.value

    async def test_quest_completes_at_target(self, db, driver_user):
        make_program(db, name="QuestComplete", program_type="quest", trip_target=3, bonus_amount=20.0)
        await db.flush()
        from sqlalchemy import select
        result = await db.execute(
            select(IncentiveProgram).where(IncentiveProgram.name == "QuestComplete")
        )
        program = result.scalar_one()

        # Record 3 trips
        for i in range(3):
            await record_trip_completion(db, driver_user.id, ride_id=i + 1, completed_at=NOW)

        from sqlalchemy import select
        prog_result = await db.execute(
            select(DriverIncentiveProgress).where(
                DriverIncentiveProgress.driver_id == driver_user.id,
                DriverIncentiveProgress.program_id == program.id,
            )
        )
        progress = prog_result.scalar_one()
        assert progress.trips_completed == 3
        assert progress.status == ProgressStatus.COMPLETED.value
        assert progress.bonus_earned == 20.0

    async def test_quest_respects_time_window(self, db, driver_user):
        """Trip outside the time window should not count toward quest."""
        make_program(
            db,
            name="QuestWindow",
            program_type="quest",
            trip_target=3,
            start_time=time(7, 0),
            end_time=time(8, 0),
        )
        await db.flush()
        from sqlalchemy import select
        result = await db.execute(
            select(IncentiveProgram).where(IncentiveProgram.name == "QuestWindow")
        )
        program = result.scalar_one()

        # NOW is 09:00 — outside the 07:00–08:00 window
        updated = await record_trip_completion(db, driver_user.id, ride_id=1, completed_at=NOW)
        matching = [r for r in updated if r.program_id == program.id]
        assert len(matching) == 0

    async def test_quest_counts_trip_inside_window(self, db, driver_user):
        make_program(
            db,
            name="QuestWindowIn",
            program_type="quest",
            trip_target=3,
            start_time=time(7, 0),
            end_time=time(10, 0),
        )
        await db.flush()
        from sqlalchemy import select
        result = await db.execute(
            select(IncentiveProgram).where(IncentiveProgram.name == "QuestWindowIn")
        )
        program = result.scalar_one()

        # NOW is 09:00 — inside 07:00–10:00
        updated = await record_trip_completion(db, driver_user.id, ride_id=1, completed_at=NOW)
        matching = [r for r in updated if r.program_id == program.id]
        assert len(matching) == 1
        assert matching[0].trips_completed == 1

    async def test_quest_ignores_completed_progress(self, db, driver_user):
        """Further trips after completion should not change bonus_earned."""
        make_program(db, name="QuestDone", program_type="quest", trip_target=1, bonus_amount=10.0)
        await db.flush()
        from sqlalchemy import select
        result = await db.execute(
            select(IncentiveProgram).where(IncentiveProgram.name == "QuestDone")
        )
        program = result.scalar_one()

        await record_trip_completion(db, driver_user.id, ride_id=1, completed_at=NOW)
        await record_trip_completion(db, driver_user.id, ride_id=2, completed_at=NOW)

        prog_result = await db.execute(
            select(DriverIncentiveProgress).where(
                DriverIncentiveProgress.driver_id == driver_user.id,
                DriverIncentiveProgress.program_id == program.id,
            )
        )
        progress = prog_result.scalar_one()
        assert progress.bonus_earned == 10.0  # should not double-count


# ---------------------------------------------------------------------------
# Service: record_trip_completion — peak_hours
# ---------------------------------------------------------------------------


@pytest.mark.anyio
class TestRecordTripPeakHours:
    async def test_peak_hours_accumulates_per_trip(self, db, driver_user):
        make_program(
            db,
            name="PeakAcc",
            program_type="peak_hours",
            bonus_amount=2.50,
            trip_target=None,
        )
        await db.flush()
        from sqlalchemy import select
        result = await db.execute(select(IncentiveProgram).where(IncentiveProgram.name == "PeakAcc"))
        program = result.scalar_one()

        for i in range(3):
            await record_trip_completion(db, driver_user.id, ride_id=i + 1, completed_at=NOW)

        prog_result = await db.execute(
            select(DriverIncentiveProgress).where(
                DriverIncentiveProgress.driver_id == driver_user.id,
                DriverIncentiveProgress.program_id == program.id,
            )
        )
        progress = prog_result.scalar_one()
        assert progress.trips_completed == 3
        assert abs(progress.bonus_earned - 7.50) < 0.01

    async def test_peak_hours_outside_window_skipped(self, db, driver_user):
        make_program(
            db,
            name="PeakWindow",
            program_type="peak_hours",
            bonus_amount=2.0,
            trip_target=None,
            start_time=time(6, 0),
            end_time=time(8, 0),
        )
        await db.flush()
        from sqlalchemy import select
        result = await db.execute(
            select(IncentiveProgram).where(IncentiveProgram.name == "PeakWindow")
        )
        program = result.scalar_one()

        # NOW is 09:00 — outside window
        updated = await record_trip_completion(db, driver_user.id, ride_id=1, completed_at=NOW)
        matching = [r for r in updated if r.program_id == program.id]
        assert len(matching) == 0


# ---------------------------------------------------------------------------
# Service: record_trip_completion — streak
# ---------------------------------------------------------------------------


@pytest.mark.anyio
class TestRecordTripStreak:
    async def test_streak_completes(self, db, driver_user):
        make_program(db, name="StreakComp", program_type="streak", trip_target=3, bonus_amount=25.0)
        await db.flush()
        from sqlalchemy import select
        result = await db.execute(
            select(IncentiveProgram).where(IncentiveProgram.name == "StreakComp")
        )
        program = result.scalar_one()

        for i in range(3):
            await record_trip_completion(db, driver_user.id, ride_id=i + 1, completed_at=NOW)

        prog_result = await db.execute(
            select(DriverIncentiveProgress).where(
                DriverIncentiveProgress.driver_id == driver_user.id,
                DriverIncentiveProgress.program_id == program.id,
            )
        )
        progress = prog_result.scalar_one()
        assert progress.status == ProgressStatus.COMPLETED.value
        assert progress.bonus_earned == 25.0

    async def test_streak_expires_on_cancellation(self, db, driver_user):
        from geoalchemy2.functions import ST_MakePoint
        from app.models.ride import Ride, RideStatus

        make_program(db, name="StreakExp", program_type="streak", trip_target=5, bonus_amount=25.0)
        await db.flush()

        from sqlalchemy import select
        result = await db.execute(
            select(IncentiveProgram).where(IncentiveProgram.name == "StreakExp")
        )
        program = result.scalar_one()

        # Create a progress record first so period_start is set
        progress = await create_or_get_progress(db, driver_user.id, program.id)
        await db.flush()

        # Insert a cancelled ride in the period
        cancelled = Ride(
            rider_id=driver_user.id,
            driver_id=driver_user.id,
            status=RideStatus.CANCELLED,
            pickup_location=ST_MakePoint(-73.9857, 40.7484, 4326),
            dropoff_location=ST_MakePoint(-73.9712, 40.7831, 4326),
            pickup_address="A",
            dropoff_address="B",
            estimated_fare=15.0,
        )
        db.add(cancelled)
        await db.flush()

        updated = await record_trip_completion(db, driver_user.id, ride_id=99, completed_at=NOW)
        matching = [r for r in updated if r.program_id == program.id]
        assert len(matching) == 1
        assert matching[0].status == ProgressStatus.EXPIRED.value


# ---------------------------------------------------------------------------
# Service: get_driver_summary
# ---------------------------------------------------------------------------


@pytest.mark.anyio
class TestGetDriverSummary:
    async def test_summary_with_no_programs(self, db, driver_user):
        summary = await get_driver_summary(db, driver_user.id)
        # No programs added in this test; all from other tests rolled back
        assert isinstance(summary, list)

    async def test_summary_includes_trips_remaining(self, db, driver_user):
        make_program(db, name="SummaryQ", program_type="quest", trip_target=5, bonus_amount=15.0)
        await db.flush()

        summary = await get_driver_summary(db, driver_user.id)
        matching = [s for s in summary if s["program"].name == "SummaryQ"]
        assert len(matching) == 1
        item = matching[0]
        assert item["trips_remaining"] == 5  # No progress yet
        assert item["progress"] is None

    async def test_summary_reflects_partial_progress(self, db, driver_user):
        make_program(db, name="SummaryP", program_type="quest", trip_target=5)
        await db.flush()

        await record_trip_completion(db, driver_user.id, ride_id=1, completed_at=NOW)

        summary = await get_driver_summary(db, driver_user.id)
        matching = [s for s in summary if s["program"].name == "SummaryP"]
        assert len(matching) == 1
        item = matching[0]
        assert item["trips_remaining"] == 4
        assert item["progress"] is not None
        assert item["progress"].trips_completed == 1

    async def test_peak_hours_has_no_trips_remaining(self, db, driver_user):
        make_program(db, name="SummaryPH", program_type="peak_hours", trip_target=None)
        await db.flush()

        summary = await get_driver_summary(db, driver_user.id)
        matching = [s for s in summary if s["program"].name == "SummaryPH"]
        assert len(matching) == 1
        assert matching[0]["trips_remaining"] is None


# ---------------------------------------------------------------------------
# Service: mark_bonuses_paid
# ---------------------------------------------------------------------------


@pytest.mark.anyio
class TestMarkBonusesPaid:
    async def test_marks_completed_as_paid(self, db, driver_user):
        make_program(db, name="PayMe", program_type="quest", trip_target=1, bonus_amount=10.0)
        await db.flush()

        await record_trip_completion(db, driver_user.id, ride_id=1, completed_at=NOW)

        from sqlalchemy import select
        result = await db.execute(
            select(IncentiveProgram).where(IncentiveProgram.name == "PayMe")
        )
        program = result.scalar_one()

        paid = await mark_bonuses_paid(db, driver_user.id, [program.id])
        assert len(paid) == 1
        assert paid[0].status == ProgressStatus.PAID.value
        assert paid[0].paid_at is not None

    async def test_does_not_pay_active_records(self, db, driver_user):
        make_program(db, name="NotReady", program_type="quest", trip_target=10)
        await db.flush()

        await record_trip_completion(db, driver_user.id, ride_id=1, completed_at=NOW)

        from sqlalchemy import select
        result = await db.execute(
            select(IncentiveProgram).where(IncentiveProgram.name == "NotReady")
        )
        program = result.scalar_one()

        paid = await mark_bonuses_paid(db, driver_user.id, [program.id])
        assert len(paid) == 0  # Not completed yet, so nothing paid


# ---------------------------------------------------------------------------
# API: admin CRUD
# ---------------------------------------------------------------------------


@pytest.mark.anyio
class TestAdminProgramCRUD:
    async def test_create_program(self, client: AsyncClient, admin_token):
        resp = await client.post(
            "/api/v1/incentives/admin/programs",
            json={
                "name": "Morning Quest",
                "description": "Complete 5 trips 7–9 AM",
                "program_type": "quest",
                "bonus_amount": 15.0,
                "trip_target": 5,
                "start_time": "07:00:00",
                "end_time": "09:00:00",
                "start_date": str(date.today()),
            },
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "Morning Quest"
        assert data["program_type"] == "quest"
        assert data["bonus_amount"] == 15.0
        assert data["is_active"] is True

    async def test_list_all_programs(self, client: AsyncClient, admin_token):
        await client.post(
            "/api/v1/incentives/admin/programs",
            json={
                "name": "ListProg",
                "program_type": "peak_hours",
                "bonus_amount": 2.0,
                "start_date": str(date.today()),
            },
            headers=auth_header(admin_token),
        )
        resp = await client.get("/api/v1/incentives/admin/programs", headers=auth_header(admin_token))
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        names = [p["name"] for p in data]
        assert "ListProg" in names

    async def test_update_program(self, client: AsyncClient, admin_token):
        create_resp = await client.post(
            "/api/v1/incentives/admin/programs",
            json={
                "name": "UpdateMe",
                "program_type": "quest",
                "bonus_amount": 10.0,
                "trip_target": 5,
                "start_date": str(date.today()),
            },
            headers=auth_header(admin_token),
        )
        program_id = create_resp.json()["id"]

        resp = await client.put(
            f"/api/v1/incentives/admin/programs/{program_id}",
            json={"bonus_amount": 20.0, "description": "Updated!"},
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["bonus_amount"] == 20.0
        assert data["description"] == "Updated!"

    async def test_deactivate_program(self, client: AsyncClient, admin_token):
        create_resp = await client.post(
            "/api/v1/incentives/admin/programs",
            json={
                "name": "DeactMe",
                "program_type": "streak",
                "bonus_amount": 25.0,
                "trip_target": 10,
                "start_date": str(date.today()),
            },
            headers=auth_header(admin_token),
        )
        program_id = create_resp.json()["id"]

        resp = await client.delete(
            f"/api/v1/incentives/admin/programs/{program_id}",
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "deactivated"

    async def test_update_nonexistent_returns_404(self, client: AsyncClient, admin_token):
        resp = await client.put(
            "/api/v1/incentives/admin/programs/99999",
            json={"bonus_amount": 5.0},
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 404

    async def test_deactivate_nonexistent_returns_404(self, client: AsyncClient, admin_token):
        resp = await client.delete(
            "/api/v1/incentives/admin/programs/99999",
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 404

    async def test_non_admin_cannot_create(self, client: AsyncClient, rider_token):
        resp = await client.post(
            "/api/v1/incentives/admin/programs",
            json={
                "name": "Sneaky",
                "program_type": "quest",
                "bonus_amount": 5.0,
                "start_date": str(date.today()),
            },
            headers=auth_header(rider_token),
        )
        assert resp.status_code == 403

    async def test_driver_cannot_access_admin_endpoints(self, client: AsyncClient, driver_token):
        resp = await client.get(
            "/api/v1/incentives/admin/programs",
            headers=auth_header(driver_token),
        )
        assert resp.status_code == 403

    async def test_leaderboard_returns_list(self, client: AsyncClient, admin_token):
        create_resp = await client.post(
            "/api/v1/incentives/admin/programs",
            json={
                "name": "LeaderQ",
                "program_type": "quest",
                "bonus_amount": 15.0,
                "trip_target": 5,
                "start_date": str(date.today()),
            },
            headers=auth_header(admin_token),
        )
        program_id = create_resp.json()["id"]

        resp = await client.get(
            f"/api/v1/incentives/admin/programs/{program_id}/leaderboard",
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)


# ---------------------------------------------------------------------------
# API: driver endpoints
# ---------------------------------------------------------------------------


@pytest.mark.anyio
class TestDriverEndpoints:
    async def test_list_active_programs_for_driver(self, client: AsyncClient, admin_token, driver_token, db):
        make_program(db, name="DriverList", program_type="quest", trip_target=5)
        await db.flush()

        resp = await client.get("/api/v1/incentives/", headers=auth_header(driver_token))
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        names = [item["program"]["name"] for item in data]
        assert "DriverList" in names

    async def test_rider_cannot_access_driver_list(self, client: AsyncClient, rider_token):
        resp = await client.get("/api/v1/incentives/", headers=auth_header(rider_token))
        assert resp.status_code == 403

    async def test_pending_earnings_zero_initially(self, client: AsyncClient, driver_token):
        resp = await client.get("/api/v1/incentives/earnings/pending", headers=auth_header(driver_token))
        assert resp.status_code == 200
        assert resp.json()["pending_bonus"] == 0.0

    async def test_progress_not_found(self, client: AsyncClient, driver_token):
        resp = await client.get(
            "/api/v1/incentives/99999/progress", headers=auth_header(driver_token)
        )
        assert resp.status_code == 404

    async def test_progress_found_after_trip(self, client: AsyncClient, driver_token, driver_user, db):
        make_program(db, name="ProgressTest", program_type="quest", trip_target=5)
        await db.flush()
        from sqlalchemy import select
        result = await db.execute(
            select(IncentiveProgram).where(IncentiveProgram.name == "ProgressTest")
        )
        program = result.scalar_one()

        await record_trip_completion(db, driver_user.id, ride_id=1, completed_at=NOW)

        resp = await client.get(
            f"/api/v1/incentives/{program.id}/progress",
            headers=auth_header(driver_token),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["trips_completed"] == 1
        assert data["program_id"] == program.id
