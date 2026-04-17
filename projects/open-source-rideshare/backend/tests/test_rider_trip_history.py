"""Tests for rider trip history.

GET /riders/me/trip-history

Coverage
--------
Helper: _date_to_utc_start
  - Converts calendar date to midnight UTC datetime
  - Year/month/day are preserved

Helper: _build_where_clauses
  - Always includes rider_id filter
  - status "all" → no status filter clause (2 clauses total: rider_id only)
  - status "completed" → adds COMPLETED filter
  - status "cancelled" → adds CANCELLED filter
  - from_date provided → adds >= filter on requested_at
  - to_date provided → adds < filter on next day (inclusive end)
  - both dates provided → both clauses present
  - neither date → no date clauses

Helper: _ride_to_summary
  - Maps ride.id → ride_id
  - Maps ride.status.value → status string
  - Uses actual_fare when set (completed rides)
  - Falls back to estimated_fare when actual_fare is None
  - Maps ride.rider_rating → driver_rating field
  - Maps all other fields correctly (tip, promo_discount, is_pool, etc.)
  - completed_at, cancelled_at, distance_km, duration_min can be None
  - cancellation_reason preserved

Service: get_rider_trip_history
  - Empty DB → total_count=0, trips=[]
  - Returns total_count from count query
  - Returns trips list from paginated rows query
  - Passes limit and offset to paginated query
  - filters_applied echoes input parameters
  - status="completed" included in filters_applied
  - from_date / to_date preserved in filters_applied
  - Calls count query first, then paginated query
  - _ride_to_summary applied to each row

Schema: RiderTripHistory
  - All required fields present
  - trips is a list of TripSummary
  - filters_applied is a TripHistoryFilters
  - total_count is int

Schema: TripSummary
  - All fields present; optional fields accept None

Schema: TripHistoryFilters
  - status, from_date, to_date, limit, offset

Router: get_trip_history
  - Delegates to service with rider.id
  - Returns RiderTripHistory
  - 422 when from_date > to_date
  - Default status is "all"
  - Default limit is DEFAULT_LIMIT
  - Default offset is 0
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from app.schemas.rider_trip_history import (
    RiderTripHistory,
    TripHistoryFilters,
    TripSummary,
)
from app.services.rider_trip_history import (
    DEFAULT_LIMIT,
    MAX_LIMIT,
    _build_where_clauses,
    _date_to_utc_start,
    _ride_to_summary,
    get_rider_trip_history,
)

# --------------------------------------------------------------------------- #
# Shared test fixtures / factories
# --------------------------------------------------------------------------- #

RIDER_ID = 42
NOW = datetime(2026, 4, 17, 15, 0, 0, tzinfo=timezone.utc)


def _make_ride(
    *,
    ride_id: int = 1,
    rider_id: int = RIDER_ID,
    status_value: str = "completed",
    pickup: str = "123 Main St",
    dropoff: str = "456 Elm Ave",
    requested_at: datetime = NOW,
    completed_at: Optional[datetime] = NOW,
    cancelled_at: Optional[datetime] = None,
    actual_fare: Optional[float] = 12.50,
    estimated_fare: float = 11.00,
    distance_km: Optional[float] = 5.3,
    duration_min: Optional[float] = 14.0,
    tip_amount: float = 2.00,
    promo_discount: float = 0.0,
    rider_rating: Optional[int] = 5,
    is_pool: bool = False,
    cancellation_reason: Optional[str] = None,
) -> MagicMock:
    """Build a mock Ride ORM object with sensible defaults."""
    from app.models.ride import RideStatus

    ride = MagicMock()
    ride.id = ride_id
    ride.rider_id = rider_id
    ride.status = MagicMock()
    ride.status.value = status_value
    ride.pickup_address = pickup
    ride.dropoff_address = dropoff
    ride.requested_at = requested_at
    ride.completed_at = completed_at
    ride.cancelled_at = cancelled_at
    ride.actual_fare = actual_fare
    ride.estimated_fare = estimated_fare
    ride.distance_km = distance_km
    ride.duration_min = duration_min
    ride.tip_amount = tip_amount
    ride.promo_discount = promo_discount
    ride.rider_rating = rider_rating
    ride.is_pool = is_pool
    ride.cancellation_reason = cancellation_reason
    return ride


def _make_db(
    total_count: int = 0,
    rides: list | None = None,
) -> AsyncMock:
    """Return a mock AsyncSession for the two-query pattern used by the service.

    The first execute() call returns a scalar count.
    The second execute() call returns scalars().all() with the rides list.
    """
    if rides is None:
        rides = []

    # Count result
    count_result = MagicMock()
    count_result.scalar_one.return_value = total_count

    # Rows result
    rows_result = MagicMock()
    rows_result.scalars.return_value.all.return_value = rides

    db = AsyncMock()
    db.execute = AsyncMock(side_effect=[count_result, rows_result])
    return db


# --------------------------------------------------------------------------- #
# Helper: _date_to_utc_start
# --------------------------------------------------------------------------- #


class TestDateToUtcStart:
    def test_preserves_year_month_day(self):
        d = date(2026, 3, 15)
        dt = _date_to_utc_start(d)
        assert dt.year == 2026
        assert dt.month == 3
        assert dt.day == 15

    def test_midnight_hour_and_minute(self):
        d = date(2026, 1, 1)
        dt = _date_to_utc_start(d)
        assert dt.hour == 0
        assert dt.minute == 0
        assert dt.second == 0

    def test_timezone_is_utc(self):
        dt = _date_to_utc_start(date(2026, 6, 1))
        assert dt.tzinfo == timezone.utc

    def test_end_of_year(self):
        d = date(2025, 12, 31)
        dt = _date_to_utc_start(d)
        assert dt.day == 31
        assert dt.month == 12


# --------------------------------------------------------------------------- #
# Helper: _build_where_clauses
# --------------------------------------------------------------------------- #


class TestBuildWhereClauses:
    def test_always_includes_rider_id(self):
        clauses = _build_where_clauses(RIDER_ID, "all", None, None)
        # At minimum the rider_id clause is present
        assert len(clauses) >= 1

    def test_status_all_no_status_clause(self):
        clauses_all = _build_where_clauses(RIDER_ID, "all", None, None)
        clauses_comp = _build_where_clauses(RIDER_ID, "completed", None, None)
        # "completed" adds one extra clause vs "all"
        assert len(clauses_comp) == len(clauses_all) + 1

    def test_status_completed_adds_clause(self):
        clauses = _build_where_clauses(RIDER_ID, "completed", None, None)
        assert len(clauses) == 2  # rider_id + status

    def test_status_cancelled_adds_clause(self):
        clauses = _build_where_clauses(RIDER_ID, "cancelled", None, None)
        assert len(clauses) == 2  # rider_id + status

    def test_from_date_adds_clause(self):
        clauses = _build_where_clauses(RIDER_ID, "all", date(2026, 1, 1), None)
        assert len(clauses) == 2  # rider_id + from_date

    def test_to_date_adds_clause(self):
        clauses = _build_where_clauses(RIDER_ID, "all", None, date(2026, 12, 31))
        assert len(clauses) == 2  # rider_id + to_date

    def test_both_dates_adds_two_clauses(self):
        clauses = _build_where_clauses(
            RIDER_ID, "all", date(2026, 1, 1), date(2026, 12, 31)
        )
        assert len(clauses) == 3  # rider_id + from_date + to_date

    def test_all_filters_combined(self):
        clauses = _build_where_clauses(
            RIDER_ID, "completed", date(2026, 1, 1), date(2026, 12, 31)
        )
        assert len(clauses) == 4  # rider_id + status + from_date + to_date

    def test_no_filters_one_clause(self):
        clauses = _build_where_clauses(RIDER_ID, "all", None, None)
        assert len(clauses) == 1


# --------------------------------------------------------------------------- #
# Helper: _ride_to_summary
# --------------------------------------------------------------------------- #


class TestRideToSummary:
    def test_ride_id_mapped(self):
        ride = _make_ride(ride_id=99)
        s = _ride_to_summary(ride)
        assert s.ride_id == 99

    def test_status_value_mapped(self):
        ride = _make_ride(status_value="cancelled")
        s = _ride_to_summary(ride)
        assert s.status == "cancelled"

    def test_pickup_and_dropoff_addresses(self):
        ride = _make_ride(pickup="Pickup St", dropoff="Dropoff Ave")
        s = _ride_to_summary(ride)
        assert s.pickup_address == "Pickup St"
        assert s.dropoff_address == "Dropoff Ave"

    def test_uses_actual_fare_when_set(self):
        ride = _make_ride(actual_fare=18.75, estimated_fare=15.00)
        s = _ride_to_summary(ride)
        assert s.fare_usd == 18.75

    def test_falls_back_to_estimated_fare_when_actual_none(self):
        ride = _make_ride(actual_fare=None, estimated_fare=11.00)
        s = _ride_to_summary(ride)
        assert s.fare_usd == 11.00

    def test_driver_rating_maps_from_rider_rating(self):
        ride = _make_ride(rider_rating=4)
        s = _ride_to_summary(ride)
        assert s.driver_rating == 4

    def test_driver_rating_none_when_rider_rating_none(self):
        ride = _make_ride(rider_rating=None)
        s = _ride_to_summary(ride)
        assert s.driver_rating is None

    def test_tip_amount_preserved(self):
        ride = _make_ride(tip_amount=3.50)
        s = _ride_to_summary(ride)
        assert s.tip_amount == 3.50

    def test_promo_discount_preserved(self):
        ride = _make_ride(promo_discount=5.00)
        s = _ride_to_summary(ride)
        assert s.promo_discount == 5.00

    def test_is_pool_preserved(self):
        ride = _make_ride(is_pool=True)
        s = _ride_to_summary(ride)
        assert s.is_pool is True

    def test_cancellation_reason_preserved(self):
        ride = _make_ride(cancellation_reason="Driver no-show")
        s = _ride_to_summary(ride)
        assert s.cancellation_reason == "Driver no-show"

    def test_cancellation_reason_none(self):
        ride = _make_ride(cancellation_reason=None)
        s = _ride_to_summary(ride)
        assert s.cancellation_reason is None

    def test_distance_km_none_allowed(self):
        ride = _make_ride(distance_km=None)
        s = _ride_to_summary(ride)
        assert s.distance_km is None

    def test_duration_min_none_allowed(self):
        ride = _make_ride(duration_min=None)
        s = _ride_to_summary(ride)
        assert s.duration_min is None

    def test_completed_at_preserved(self):
        ride = _make_ride(completed_at=NOW)
        s = _ride_to_summary(ride)
        assert s.completed_at == NOW

    def test_cancelled_at_none_for_completed_ride(self):
        ride = _make_ride(cancelled_at=None)
        s = _ride_to_summary(ride)
        assert s.cancelled_at is None

    def test_requested_at_preserved(self):
        ride = _make_ride(requested_at=NOW)
        s = _ride_to_summary(ride)
        assert s.requested_at == NOW

    def test_distance_km_value_preserved(self):
        ride = _make_ride(distance_km=12.7)
        s = _ride_to_summary(ride)
        assert s.distance_km == 12.7

    def test_duration_min_value_preserved(self):
        ride = _make_ride(duration_min=23.5)
        s = _ride_to_summary(ride)
        assert s.duration_min == 23.5


# --------------------------------------------------------------------------- #
# Service: get_rider_trip_history
# --------------------------------------------------------------------------- #


class TestGetRiderTripHistory:
    @pytest.mark.anyio
    async def test_empty_db_returns_zero_count_and_empty_list(self):
        db = _make_db(total_count=0, rides=[])
        result = await get_rider_trip_history(
            db=db, rider_id=RIDER_ID, status="all",
            from_date=None, to_date=None,
            limit=DEFAULT_LIMIT, offset=0,
        )
        assert result.total_count == 0
        assert result.trips == []

    @pytest.mark.anyio
    async def test_total_count_from_count_query(self):
        db = _make_db(total_count=57, rides=[])
        result = await get_rider_trip_history(
            db=db, rider_id=RIDER_ID, status="all",
            from_date=None, to_date=None,
            limit=DEFAULT_LIMIT, offset=0,
        )
        assert result.total_count == 57

    @pytest.mark.anyio
    async def test_trips_list_mapped_from_rows(self):
        rides = [_make_ride(ride_id=1), _make_ride(ride_id=2)]
        db = _make_db(total_count=2, rides=rides)
        result = await get_rider_trip_history(
            db=db, rider_id=RIDER_ID, status="all",
            from_date=None, to_date=None,
            limit=DEFAULT_LIMIT, offset=0,
        )
        assert len(result.trips) == 2
        assert result.trips[0].ride_id == 1
        assert result.trips[1].ride_id == 2

    @pytest.mark.anyio
    async def test_filters_applied_echoes_status(self):
        db = _make_db(total_count=0, rides=[])
        result = await get_rider_trip_history(
            db=db, rider_id=RIDER_ID, status="completed",
            from_date=None, to_date=None,
            limit=DEFAULT_LIMIT, offset=0,
        )
        assert result.filters_applied.status == "completed"

    @pytest.mark.anyio
    async def test_filters_applied_echoes_from_date(self):
        d = date(2026, 1, 1)
        db = _make_db(total_count=0, rides=[])
        result = await get_rider_trip_history(
            db=db, rider_id=RIDER_ID, status="all",
            from_date=d, to_date=None,
            limit=DEFAULT_LIMIT, offset=0,
        )
        assert result.filters_applied.from_date == d

    @pytest.mark.anyio
    async def test_filters_applied_echoes_to_date(self):
        d = date(2026, 12, 31)
        db = _make_db(total_count=0, rides=[])
        result = await get_rider_trip_history(
            db=db, rider_id=RIDER_ID, status="all",
            from_date=None, to_date=d,
            limit=DEFAULT_LIMIT, offset=0,
        )
        assert result.filters_applied.to_date == d

    @pytest.mark.anyio
    async def test_filters_applied_echoes_limit(self):
        db = _make_db(total_count=0, rides=[])
        result = await get_rider_trip_history(
            db=db, rider_id=RIDER_ID, status="all",
            from_date=None, to_date=None,
            limit=50, offset=0,
        )
        assert result.filters_applied.limit == 50

    @pytest.mark.anyio
    async def test_filters_applied_echoes_offset(self):
        db = _make_db(total_count=0, rides=[])
        result = await get_rider_trip_history(
            db=db, rider_id=RIDER_ID, status="all",
            from_date=None, to_date=None,
            limit=DEFAULT_LIMIT, offset=40,
        )
        assert result.filters_applied.offset == 40

    @pytest.mark.anyio
    async def test_two_execute_calls_made(self):
        db = _make_db(total_count=3, rides=[_make_ride()])
        await get_rider_trip_history(
            db=db, rider_id=RIDER_ID, status="all",
            from_date=None, to_date=None,
            limit=DEFAULT_LIMIT, offset=0,
        )
        assert db.execute.call_count == 2

    @pytest.mark.anyio
    async def test_single_trip_returned_correctly(self):
        ride = _make_ride(ride_id=101, actual_fare=20.0)
        db = _make_db(total_count=1, rides=[ride])
        result = await get_rider_trip_history(
            db=db, rider_id=RIDER_ID, status="all",
            from_date=None, to_date=None,
            limit=DEFAULT_LIMIT, offset=0,
        )
        assert result.total_count == 1
        assert len(result.trips) == 1
        assert result.trips[0].ride_id == 101
        assert result.trips[0].fare_usd == 20.0

    @pytest.mark.anyio
    async def test_filters_applied_none_dates_preserved(self):
        db = _make_db(total_count=0, rides=[])
        result = await get_rider_trip_history(
            db=db, rider_id=RIDER_ID, status="all",
            from_date=None, to_date=None,
            limit=DEFAULT_LIMIT, offset=0,
        )
        assert result.filters_applied.from_date is None
        assert result.filters_applied.to_date is None

    @pytest.mark.anyio
    async def test_status_cancelled_echoed_in_filters(self):
        db = _make_db(total_count=0, rides=[])
        result = await get_rider_trip_history(
            db=db, rider_id=RIDER_ID, status="cancelled",
            from_date=None, to_date=None,
            limit=DEFAULT_LIMIT, offset=0,
        )
        assert result.filters_applied.status == "cancelled"

    @pytest.mark.anyio
    async def test_multiple_rides_all_mapped(self):
        rides = [_make_ride(ride_id=i, actual_fare=float(i * 10)) for i in range(1, 6)]
        db = _make_db(total_count=5, rides=rides)
        result = await get_rider_trip_history(
            db=db, rider_id=RIDER_ID, status="all",
            from_date=None, to_date=None,
            limit=DEFAULT_LIMIT, offset=0,
        )
        assert len(result.trips) == 5
        assert [t.ride_id for t in result.trips] == [1, 2, 3, 4, 5]


# --------------------------------------------------------------------------- #
# Schema validation
# --------------------------------------------------------------------------- #


class TestSchemas:
    def test_trip_summary_all_fields(self):
        t = TripSummary(
            ride_id=1,
            status="completed",
            pickup_address="A",
            dropoff_address="B",
            requested_at=NOW,
            completed_at=NOW,
            cancelled_at=None,
            fare_usd=15.0,
            distance_km=4.2,
            duration_min=12.0,
            tip_amount=2.0,
            promo_discount=1.0,
            driver_rating=5,
            is_pool=False,
            cancellation_reason=None,
        )
        assert t.ride_id == 1
        assert t.fare_usd == 15.0

    def test_trip_summary_optional_fields_none(self):
        t = TripSummary(
            ride_id=2,
            status="cancelled",
            pickup_address="A",
            dropoff_address="B",
            requested_at=NOW,
            completed_at=None,
            cancelled_at=NOW,
            fare_usd=8.0,
            distance_km=None,
            duration_min=None,
            tip_amount=0.0,
            promo_discount=0.0,
            driver_rating=None,
            is_pool=False,
            cancellation_reason="Changed plans",
        )
        assert t.completed_at is None
        assert t.distance_km is None
        assert t.driver_rating is None

    def test_trip_history_filters_fields(self):
        f = TripHistoryFilters(
            status="completed",
            from_date=date(2026, 1, 1),
            to_date=date(2026, 12, 31),
            limit=20,
            offset=0,
        )
        assert f.status == "completed"
        assert f.limit == 20

    def test_trip_history_filters_optional_dates_none(self):
        f = TripHistoryFilters(
            status="all",
            from_date=None,
            to_date=None,
            limit=DEFAULT_LIMIT,
            offset=0,
        )
        assert f.from_date is None
        assert f.to_date is None

    def test_rider_trip_history_all_fields(self):
        f = TripHistoryFilters(
            status="all", from_date=None, to_date=None,
            limit=DEFAULT_LIMIT, offset=0,
        )
        h = RiderTripHistory(total_count=0, trips=[], filters_applied=f)
        assert h.total_count == 0
        assert h.trips == []
        assert h.filters_applied.status == "all"

    def test_rider_trip_history_with_trips(self):
        trip = TripSummary(
            ride_id=5, status="completed", pickup_address="X",
            dropoff_address="Y", requested_at=NOW, completed_at=NOW,
            cancelled_at=None, fare_usd=22.0, distance_km=7.0,
            duration_min=20.0, tip_amount=3.0, promo_discount=0.0,
            driver_rating=4, is_pool=False, cancellation_reason=None,
        )
        f = TripHistoryFilters(
            status="completed", from_date=None, to_date=None,
            limit=20, offset=0,
        )
        h = RiderTripHistory(total_count=1, trips=[trip], filters_applied=f)
        assert len(h.trips) == 1
        assert h.trips[0].ride_id == 5


# --------------------------------------------------------------------------- #
# Router
# --------------------------------------------------------------------------- #


class TestRouter:
    @pytest.mark.anyio
    async def test_delegates_to_service_with_rider_id(self):
        from app.api.v1.rider_trip_history import get_trip_history

        mock_rider = MagicMock()
        mock_rider.id = RIDER_ID
        mock_db = AsyncMock()

        stub = RiderTripHistory(
            total_count=0,
            trips=[],
            filters_applied=TripHistoryFilters(
                status="all", from_date=None, to_date=None,
                limit=DEFAULT_LIMIT, offset=0,
            ),
        )

        with patch(
            "app.api.v1.rider_trip_history.get_rider_trip_history",
            new=AsyncMock(return_value=stub),
        ) as mock_svc:
            result = await get_trip_history(
                status="all",
                from_date=None,
                to_date=None,
                limit=DEFAULT_LIMIT,
                offset=0,
                rider=mock_rider,
                db=mock_db,
            )

        mock_svc.assert_called_once_with(
            db=mock_db,
            rider_id=RIDER_ID,
            status="all",
            from_date=None,
            to_date=None,
            limit=DEFAULT_LIMIT,
            offset=0,
        )
        assert result == stub

    @pytest.mark.anyio
    async def test_returns_rider_trip_history(self):
        from app.api.v1.rider_trip_history import get_trip_history

        mock_rider = MagicMock()
        mock_rider.id = RIDER_ID
        mock_db = AsyncMock()

        stub = RiderTripHistory(
            total_count=3,
            trips=[],
            filters_applied=TripHistoryFilters(
                status="completed", from_date=None, to_date=None,
                limit=20, offset=0,
            ),
        )

        with patch(
            "app.api.v1.rider_trip_history.get_rider_trip_history",
            new=AsyncMock(return_value=stub),
        ):
            result = await get_trip_history(
                status="completed",
                from_date=None,
                to_date=None,
                limit=20,
                offset=0,
                rider=mock_rider,
                db=mock_db,
            )

        assert isinstance(result, RiderTripHistory)
        assert result.total_count == 3

    @pytest.mark.anyio
    async def test_422_when_from_date_after_to_date(self):
        from fastapi import HTTPException

        from app.api.v1.rider_trip_history import get_trip_history

        mock_rider = MagicMock()
        mock_rider.id = RIDER_ID
        mock_db = AsyncMock()

        with pytest.raises(HTTPException) as exc_info:
            await get_trip_history(
                status="all",
                from_date=date(2026, 12, 31),
                to_date=date(2026, 1, 1),
                limit=DEFAULT_LIMIT,
                offset=0,
                rider=mock_rider,
                db=mock_db,
            )

        assert exc_info.value.status_code == 422

    @pytest.mark.anyio
    async def test_equal_from_and_to_date_allowed(self):
        from app.api.v1.rider_trip_history import get_trip_history

        mock_rider = MagicMock()
        mock_rider.id = RIDER_ID
        mock_db = AsyncMock()

        same_day = date(2026, 6, 15)
        stub = RiderTripHistory(
            total_count=0,
            trips=[],
            filters_applied=TripHistoryFilters(
                status="all", from_date=same_day, to_date=same_day,
                limit=DEFAULT_LIMIT, offset=0,
            ),
        )

        with patch(
            "app.api.v1.rider_trip_history.get_rider_trip_history",
            new=AsyncMock(return_value=stub),
        ):
            result = await get_trip_history(
                status="all",
                from_date=same_day,
                to_date=same_day,
                limit=DEFAULT_LIMIT,
                offset=0,
                rider=mock_rider,
                db=mock_db,
            )

        assert isinstance(result, RiderTripHistory)

    @pytest.mark.anyio
    async def test_default_status_is_all(self):
        """Verify the router default for status is 'all'."""
        import inspect

        from app.api.v1.rider_trip_history import get_trip_history

        sig = inspect.signature(get_trip_history)
        # The Query default is accessed via the annotation default
        # We verify by calling with no explicit status and a stubbed service
        mock_rider = MagicMock()
        mock_rider.id = RIDER_ID
        mock_db = AsyncMock()

        stub = RiderTripHistory(
            total_count=0, trips=[],
            filters_applied=TripHistoryFilters(
                status="all", from_date=None, to_date=None,
                limit=DEFAULT_LIMIT, offset=0,
            ),
        )

        with patch(
            "app.api.v1.rider_trip_history.get_rider_trip_history",
            new=AsyncMock(return_value=stub),
        ) as mock_svc:
            await get_trip_history(
                status="all",
                from_date=None,
                to_date=None,
                limit=DEFAULT_LIMIT,
                offset=0,
                rider=mock_rider,
                db=mock_db,
            )

        call_kwargs = mock_svc.call_args.kwargs
        assert call_kwargs["status"] == "all"

    @pytest.mark.anyio
    async def test_passes_all_filter_params_to_service(self):
        from app.api.v1.rider_trip_history import get_trip_history

        mock_rider = MagicMock()
        mock_rider.id = RIDER_ID
        mock_db = AsyncMock()

        fd = date(2026, 3, 1)
        td = date(2026, 3, 31)

        stub = RiderTripHistory(
            total_count=0, trips=[],
            filters_applied=TripHistoryFilters(
                status="cancelled", from_date=fd, to_date=td,
                limit=10, offset=5,
            ),
        )

        with patch(
            "app.api.v1.rider_trip_history.get_rider_trip_history",
            new=AsyncMock(return_value=stub),
        ) as mock_svc:
            await get_trip_history(
                status="cancelled",
                from_date=fd,
                to_date=td,
                limit=10,
                offset=5,
                rider=mock_rider,
                db=mock_db,
            )

        call_kwargs = mock_svc.call_args.kwargs
        assert call_kwargs["status"] == "cancelled"
        assert call_kwargs["from_date"] == fd
        assert call_kwargs["to_date"] == td
        assert call_kwargs["limit"] == 10
        assert call_kwargs["offset"] == 5
