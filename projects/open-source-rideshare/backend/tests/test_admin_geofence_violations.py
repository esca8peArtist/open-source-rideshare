"""Tests for admin geofence violations report — GET /admin/geofence/violations."""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models.ride import Ride, RideStatus
from app.schemas.admin import (
    GeofenceViolationEntry,
    GeofenceViolationListResponse,
    GeofenceViolationType,
)

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 4, 18, 12, 0, 0, tzinfo=timezone.utc)


def _make_ride(
    ride_id: int = 1,
    rider_id: int = 10,
    driver_id: int | None = 20,
    status: RideStatus = RideStatus.COMPLETED,
    requested_at: datetime | None = None,
) -> MagicMock:
    ride = MagicMock(spec=Ride)
    ride.id = ride_id
    ride.rider_id = rider_id
    ride.driver_id = driver_id
    ride.status = status
    ride.pickup_address = "123 Main St"
    ride.dropoff_address = "456 Oak Ave"
    ride.requested_at = requested_at or (_NOW - timedelta(hours=1))
    return ride


def _make_row(ride: MagicMock, pickup_covered: bool, dropoff_covered: bool) -> MagicMock:
    """Simulate a SQLAlchemy Row with Ride, pickup_covered, dropoff_covered attributes."""
    row = MagicMock()
    row.Ride = ride
    row.pickup_covered = pickup_covered
    row.dropoff_covered = dropoff_covered
    return row


def _make_db(
    service_area_count: int = 2,
    total_violations: int = 0,
    rows: list | None = None,
) -> AsyncMock:
    """Build an AsyncMock db that returns the supplied values for each successive execute() call.

    Call order expected by the endpoint:
      1. COUNT active service areas  → scalar()
      2. COUNT matching rides        → scalar()
      3. Paginated rows              → .all()
    """
    db = AsyncMock()

    # Build result mocks for each execute call
    sa_count_result = MagicMock()
    sa_count_result.scalar.return_value = service_area_count

    violation_count_result = MagicMock()
    violation_count_result.scalar.return_value = total_violations

    rows_result = MagicMock()
    rows_result.all.return_value = rows or []

    # Successive execute() calls return each mock in order
    db.execute = AsyncMock(side_effect=[sa_count_result, violation_count_result, rows_result])
    return db


def _make_db_no_sa() -> AsyncMock:
    """DB mock for the zero active service areas fast-path (only one execute call)."""
    db = AsyncMock()
    sa_count_result = MagicMock()
    sa_count_result.scalar.return_value = 0
    db.execute = AsyncMock(return_value=sa_count_result)
    return db


# ---------------------------------------------------------------------------
# Import helpers under test
# ---------------------------------------------------------------------------

from app.api.v1.admin import _classify_violation


# ---------------------------------------------------------------------------
# _classify_violation
# ---------------------------------------------------------------------------


class TestClassifyViolation:
    def test_both_uncovered_returns_both_outside(self):
        result = _classify_violation(pickup_covered=False, dropoff_covered=False)
        assert result == GeofenceViolationType.BOTH_OUTSIDE

    def test_pickup_uncovered_only_returns_pickup_outside(self):
        result = _classify_violation(pickup_covered=False, dropoff_covered=True)
        assert result == GeofenceViolationType.PICKUP_OUTSIDE

    def test_dropoff_uncovered_only_returns_dropoff_outside(self):
        result = _classify_violation(pickup_covered=True, dropoff_covered=False)
        assert result == GeofenceViolationType.DROPOFF_OUTSIDE

    def test_both_covered_never_expected_but_returns_dropoff_outside(self):
        # Edge case: should never reach the endpoint for a fully-covered ride,
        # but the function itself should not raise.
        result = _classify_violation(pickup_covered=True, dropoff_covered=True)
        # The function defaults to DROPOFF_OUTSIDE when only dropoff is "uncovered",
        # but since both are covered it reaches the final return — still valid enum.
        assert result in GeofenceViolationType.__members__.values()

    def test_return_type_is_geofence_violation_type(self):
        result = _classify_violation(pickup_covered=False, dropoff_covered=False)
        assert isinstance(result, GeofenceViolationType)

    def test_both_outside_value(self):
        assert GeofenceViolationType.BOTH_OUTSIDE == "both_outside"

    def test_pickup_outside_value(self):
        assert GeofenceViolationType.PICKUP_OUTSIDE == "pickup_outside"

    def test_dropoff_outside_value(self):
        assert GeofenceViolationType.DROPOFF_OUTSIDE == "dropoff_outside"


# ---------------------------------------------------------------------------
# Schema: GeofenceViolationEntry
# ---------------------------------------------------------------------------


class TestGeofenceViolationEntry:
    def test_required_fields(self):
        entry = GeofenceViolationEntry(
            ride_id=1,
            rider_id=10,
            pickup_address="123 Main St",
            dropoff_address="456 Oak Ave",
            violation_type=GeofenceViolationType.PICKUP_OUTSIDE,
            status="completed",
            requested_at=_NOW,
        )
        assert entry.ride_id == 1
        assert entry.rider_id == 10
        assert entry.violation_type == GeofenceViolationType.PICKUP_OUTSIDE

    def test_driver_id_defaults_none(self):
        entry = GeofenceViolationEntry(
            ride_id=2,
            rider_id=11,
            pickup_address="A",
            dropoff_address="B",
            violation_type=GeofenceViolationType.DROPOFF_OUTSIDE,
            status="requested",
            requested_at=_NOW,
        )
        assert entry.driver_id is None

    def test_driver_id_can_be_set(self):
        entry = GeofenceViolationEntry(
            ride_id=3,
            rider_id=12,
            driver_id=99,
            pickup_address="A",
            dropoff_address="B",
            violation_type=GeofenceViolationType.BOTH_OUTSIDE,
            status="in_progress",
            requested_at=_NOW,
        )
        assert entry.driver_id == 99

    def test_violation_type_both_outside(self):
        entry = GeofenceViolationEntry(
            ride_id=4,
            rider_id=13,
            pickup_address="A",
            dropoff_address="B",
            violation_type=GeofenceViolationType.BOTH_OUTSIDE,
            status="completed",
            requested_at=_NOW,
        )
        assert entry.violation_type == "both_outside"


# ---------------------------------------------------------------------------
# Schema: GeofenceViolationListResponse
# ---------------------------------------------------------------------------


class TestGeofenceViolationListResponse:
    def test_empty_response(self):
        resp = GeofenceViolationListResponse(
            violations=[], total=0, page=1, per_page=20, service_areas_active=3
        )
        assert resp.violations == []
        assert resp.total == 0
        assert resp.service_areas_active == 3

    def test_total_reflects_db_count_not_page_size(self):
        entry = GeofenceViolationEntry(
            ride_id=1,
            rider_id=10,
            pickup_address="A",
            dropoff_address="B",
            violation_type=GeofenceViolationType.PICKUP_OUTSIDE,
            status="completed",
            requested_at=_NOW,
        )
        resp = GeofenceViolationListResponse(
            violations=[entry], total=500, page=2, per_page=20, service_areas_active=5
        )
        assert resp.total == 500
        assert len(resp.violations) == 1

    def test_pagination_fields_preserved(self):
        resp = GeofenceViolationListResponse(
            violations=[], total=0, page=3, per_page=50, service_areas_active=1
        )
        assert resp.page == 3
        assert resp.per_page == 50

    def test_service_areas_active_zero(self):
        resp = GeofenceViolationListResponse(
            violations=[], total=0, page=1, per_page=20, service_areas_active=0
        )
        assert resp.service_areas_active == 0


# ---------------------------------------------------------------------------
# Endpoint: list_geofence_violations
# ---------------------------------------------------------------------------


class TestListGeofenceViolationsEndpoint:
    @pytest.mark.asyncio
    async def test_no_active_service_areas_returns_empty(self):
        from app.api.v1.admin import list_geofence_violations

        db = _make_db_no_sa()
        result = await list_geofence_violations(db=db, period="month", violation_type="all", page=1, per_page=20)

        assert result.violations == []
        assert result.total == 0
        assert result.service_areas_active == 0
        # Only one DB call should have been made (the SA count)
        assert db.execute.call_count == 1

    @pytest.mark.asyncio
    async def test_no_active_service_areas_pagination_fields_preserved(self):
        from app.api.v1.admin import list_geofence_violations

        db = _make_db_no_sa()
        result = await list_geofence_violations(db=db, period="week", violation_type="all", page=3, per_page=50)

        assert result.page == 3
        assert result.per_page == 50

    @pytest.mark.asyncio
    async def test_returns_pickup_outside_violation(self):
        from app.api.v1.admin import list_geofence_violations

        ride = _make_ride(ride_id=5, rider_id=20, driver_id=30)
        row = _make_row(ride, pickup_covered=False, dropoff_covered=True)
        db = _make_db(service_area_count=2, total_violations=1, rows=[row])

        result = await list_geofence_violations(db=db, period="all", violation_type="all", page=1, per_page=20)

        assert result.total == 1
        assert len(result.violations) == 1
        assert result.violations[0].violation_type == GeofenceViolationType.PICKUP_OUTSIDE
        assert result.violations[0].ride_id == 5
        assert result.violations[0].rider_id == 20

    @pytest.mark.asyncio
    async def test_returns_dropoff_outside_violation(self):
        from app.api.v1.admin import list_geofence_violations

        ride = _make_ride(ride_id=6, rider_id=21)
        row = _make_row(ride, pickup_covered=True, dropoff_covered=False)
        db = _make_db(service_area_count=1, total_violations=1, rows=[row])

        result = await list_geofence_violations(db=db, period="all", violation_type="all", page=1, per_page=20)

        assert result.violations[0].violation_type == GeofenceViolationType.DROPOFF_OUTSIDE

    @pytest.mark.asyncio
    async def test_returns_both_outside_violation(self):
        from app.api.v1.admin import list_geofence_violations

        ride = _make_ride(ride_id=7, rider_id=22, driver_id=None)
        row = _make_row(ride, pickup_covered=False, dropoff_covered=False)
        db = _make_db(service_area_count=3, total_violations=1, rows=[row])

        result = await list_geofence_violations(db=db, period="all", violation_type="all", page=1, per_page=20)

        assert result.violations[0].violation_type == GeofenceViolationType.BOTH_OUTSIDE
        assert result.violations[0].driver_id is None

    @pytest.mark.asyncio
    async def test_mixed_violation_types_classified_correctly(self):
        from app.api.v1.admin import list_geofence_violations

        ride1 = _make_ride(ride_id=10, rider_id=100)
        ride2 = _make_ride(ride_id=11, rider_id=101)
        ride3 = _make_ride(ride_id=12, rider_id=102)
        rows = [
            _make_row(ride1, pickup_covered=False, dropoff_covered=True),
            _make_row(ride2, pickup_covered=True, dropoff_covered=False),
            _make_row(ride3, pickup_covered=False, dropoff_covered=False),
        ]
        db = _make_db(service_area_count=2, total_violations=3, rows=rows)

        result = await list_geofence_violations(db=db, period="all", violation_type="all", page=1, per_page=20)

        assert result.total == 3
        assert len(result.violations) == 3
        types = [v.violation_type for v in result.violations]
        assert GeofenceViolationType.PICKUP_OUTSIDE in types
        assert GeofenceViolationType.DROPOFF_OUTSIDE in types
        assert GeofenceViolationType.BOTH_OUTSIDE in types

    @pytest.mark.asyncio
    async def test_service_areas_active_count_returned(self):
        from app.api.v1.admin import list_geofence_violations

        db = _make_db(service_area_count=7, total_violations=0, rows=[])
        result = await list_geofence_violations(db=db, period="all", violation_type="all", page=1, per_page=20)

        assert result.service_areas_active == 7

    @pytest.mark.asyncio
    async def test_pagination_fields_in_response(self):
        from app.api.v1.admin import list_geofence_violations

        db = _make_db(service_area_count=2, total_violations=55, rows=[])
        result = await list_geofence_violations(db=db, period="month", violation_type="all", page=3, per_page=10)

        assert result.page == 3
        assert result.per_page == 10
        assert result.total == 55

    @pytest.mark.asyncio
    async def test_period_week_does_not_raise(self):
        from app.api.v1.admin import list_geofence_violations

        db = _make_db(service_area_count=1, total_violations=0, rows=[])
        result = await list_geofence_violations(db=db, period="week", violation_type="all", page=1, per_page=20)
        assert result.total == 0

    @pytest.mark.asyncio
    async def test_period_month_does_not_raise(self):
        from app.api.v1.admin import list_geofence_violations

        db = _make_db(service_area_count=1, total_violations=0, rows=[])
        result = await list_geofence_violations(db=db, period="month", violation_type="all", page=1, per_page=20)
        assert result.total == 0

    @pytest.mark.asyncio
    async def test_period_year_does_not_raise(self):
        from app.api.v1.admin import list_geofence_violations

        db = _make_db(service_area_count=1, total_violations=0, rows=[])
        result = await list_geofence_violations(db=db, period="year", violation_type="all", page=1, per_page=20)
        assert result.total == 0

    @pytest.mark.asyncio
    async def test_period_all_does_not_raise(self):
        from app.api.v1.admin import list_geofence_violations

        db = _make_db(service_area_count=1, total_violations=0, rows=[])
        result = await list_geofence_violations(db=db, period="all", violation_type="all", page=1, per_page=20)
        assert result.total == 0

    @pytest.mark.asyncio
    async def test_violation_type_filter_pickup_outside(self):
        from app.api.v1.admin import list_geofence_violations

        ride = _make_ride(ride_id=20, rider_id=200)
        row = _make_row(ride, pickup_covered=False, dropoff_covered=True)
        db = _make_db(service_area_count=2, total_violations=1, rows=[row])

        result = await list_geofence_violations(
            db=db, period="all", violation_type="pickup_outside", page=1, per_page=20
        )
        assert result.total == 1
        assert result.violations[0].violation_type == GeofenceViolationType.PICKUP_OUTSIDE

    @pytest.mark.asyncio
    async def test_violation_type_filter_dropoff_outside(self):
        from app.api.v1.admin import list_geofence_violations

        ride = _make_ride(ride_id=21, rider_id=201)
        row = _make_row(ride, pickup_covered=True, dropoff_covered=False)
        db = _make_db(service_area_count=2, total_violations=1, rows=[row])

        result = await list_geofence_violations(
            db=db, period="all", violation_type="dropoff_outside", page=1, per_page=20
        )
        assert result.total == 1
        assert result.violations[0].violation_type == GeofenceViolationType.DROPOFF_OUTSIDE

    @pytest.mark.asyncio
    async def test_violation_type_filter_both_outside(self):
        from app.api.v1.admin import list_geofence_violations

        ride = _make_ride(ride_id=22, rider_id=202)
        row = _make_row(ride, pickup_covered=False, dropoff_covered=False)
        db = _make_db(service_area_count=2, total_violations=1, rows=[row])

        result = await list_geofence_violations(
            db=db, period="all", violation_type="both_outside", page=1, per_page=20
        )
        assert result.total == 1
        assert result.violations[0].violation_type == GeofenceViolationType.BOTH_OUTSIDE

    @pytest.mark.asyncio
    async def test_empty_page_returns_empty_violations_list(self):
        from app.api.v1.admin import list_geofence_violations

        db = _make_db(service_area_count=2, total_violations=100, rows=[])
        result = await list_geofence_violations(db=db, period="all", violation_type="all", page=99, per_page=20)

        assert result.violations == []
        assert result.total == 100

    @pytest.mark.asyncio
    async def test_ride_fields_mapped_correctly(self):
        from app.api.v1.admin import list_geofence_violations

        ride = _make_ride(ride_id=99, rider_id=55, driver_id=66, status=RideStatus.IN_PROGRESS)
        ride.pickup_address = "789 Elm St"
        ride.dropoff_address = "321 Pine Rd"
        ride.requested_at = _NOW - timedelta(hours=3)
        row = _make_row(ride, pickup_covered=False, dropoff_covered=True)
        db = _make_db(service_area_count=1, total_violations=1, rows=[row])

        result = await list_geofence_violations(db=db, period="all", violation_type="all", page=1, per_page=20)

        v = result.violations[0]
        assert v.ride_id == 99
        assert v.rider_id == 55
        assert v.driver_id == 66
        assert v.pickup_address == "789 Elm St"
        assert v.dropoff_address == "321 Pine Rd"
        assert v.status == "in_progress"
        assert v.requested_at == _NOW - timedelta(hours=3)
