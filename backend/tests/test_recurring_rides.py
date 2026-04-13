"""Tests for recurring rides (commute scheduling).

Covers model, enum, schema validation, service logic, ride generation,
scheduler integration, and API endpoints.
"""

from datetime import date, datetime, time, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.recurring_ride import RecurringRide, RecurringRideStatus
from app.models.ride import Ride, RideStatus
from app.schemas.recurring_ride import (
    GeneratedRideSummary,
    RecurringRideCreate,
    RecurringRideDetailResponse,
    RecurringRideListResponse,
    RecurringRideResponse,
    RecurringRideUpdate,
)
from app.services.recurring_rides import (
    GENERATION_HORIZON_HOURS,
    MAX_RECURRING_RIDES_PER_USER,
    RecurringRideLimitError,
    RecurringRideNotFoundError,
    RecurringRideStateError,
    _next_occurrence_dates,
    cancel_recurring_ride,
    create_recurring_ride,
    generate_rides_from_recurring,
    get_recurring_ride,
    get_upcoming_generated_rides,
    list_recurring_rides,
    pause_recurring_ride,
    resume_recurring_ride,
    update_recurring_ride,
)


# ===========================================================================
# RecurringRide Model Tests
# ===========================================================================


class TestRecurringRideModel:
    def test_table_name(self):
        assert RecurringRide.__tablename__ == "recurring_rides"

    def test_has_rider_id_column(self):
        cols = {c.name for c in RecurringRide.__table__.columns}
        assert "rider_id" in cols

    def test_has_pickup_location_column(self):
        cols = {c.name for c in RecurringRide.__table__.columns}
        assert "pickup_location" in cols

    def test_has_dropoff_location_column(self):
        cols = {c.name for c in RecurringRide.__table__.columns}
        assert "dropoff_location" in cols

    def test_has_pickup_address_column(self):
        cols = {c.name for c in RecurringRide.__table__.columns}
        assert "pickup_address" in cols

    def test_has_dropoff_address_column(self):
        cols = {c.name for c in RecurringRide.__table__.columns}
        assert "dropoff_address" in cols

    def test_has_days_of_week_column(self):
        cols = {c.name for c in RecurringRide.__table__.columns}
        assert "days_of_week" in cols

    def test_has_pickup_time_column(self):
        cols = {c.name for c in RecurringRide.__table__.columns}
        assert "pickup_time" in cols

    def test_has_timezone_column(self):
        cols = {c.name for c in RecurringRide.__table__.columns}
        assert "timezone" in cols

    def test_has_status_column(self):
        cols = {c.name for c in RecurringRide.__table__.columns}
        assert "status" in cols

    def test_has_label_column(self):
        cols = {c.name for c in RecurringRide.__table__.columns}
        assert "label" in cols

    def test_has_last_generated_date_column(self):
        cols = {c.name for c in RecurringRide.__table__.columns}
        assert "last_generated_date" in cols

    def test_has_created_at_column(self):
        cols = {c.name for c in RecurringRide.__table__.columns}
        assert "created_at" in cols

    def test_has_updated_at_column(self):
        cols = {c.name for c in RecurringRide.__table__.columns}
        assert "updated_at" in cols

    def test_has_saved_location_columns(self):
        cols = {c.name for c in RecurringRide.__table__.columns}
        assert "pickup_saved_location_id" in cols
        assert "dropoff_saved_location_id" in cols

    def test_rider_id_is_indexed(self):
        col = RecurringRide.__table__.columns["rider_id"]
        assert col.index is True

    def test_rider_id_has_fk(self):
        col = RecurringRide.__table__.columns["rider_id"]
        fk_targets = [fk.target_fullname for fk in col.foreign_keys]
        assert "users.id" in fk_targets

    def test_label_is_nullable(self):
        col = RecurringRide.__table__.columns["label"]
        assert col.nullable is True

    def test_last_generated_date_is_nullable(self):
        col = RecurringRide.__table__.columns["last_generated_date"]
        assert col.nullable is True


# ===========================================================================
# Ride Model — recurring_ride_id Column Tests
# ===========================================================================


class TestRideRecurringColumn:
    def test_ride_has_recurring_ride_id(self):
        cols = {c.name for c in Ride.__table__.columns}
        assert "recurring_ride_id" in cols

    def test_recurring_ride_id_is_nullable(self):
        col = Ride.__table__.columns["recurring_ride_id"]
        assert col.nullable is True

    def test_recurring_ride_id_is_indexed(self):
        col = Ride.__table__.columns["recurring_ride_id"]
        assert col.index is True

    def test_recurring_ride_id_has_fk(self):
        col = Ride.__table__.columns["recurring_ride_id"]
        fk_targets = [fk.target_fullname for fk in col.foreign_keys]
        assert "recurring_rides.id" in fk_targets


# ===========================================================================
# RecurringRideStatus Enum Tests
# ===========================================================================


class TestRecurringRideStatus:
    def test_active_value(self):
        assert RecurringRideStatus.ACTIVE == "active"

    def test_paused_value(self):
        assert RecurringRideStatus.PAUSED == "paused"

    def test_cancelled_value(self):
        assert RecurringRideStatus.CANCELLED == "cancelled"

    def test_all_statuses(self):
        values = {s.value for s in RecurringRideStatus}
        assert values == {"active", "paused", "cancelled"}


# ===========================================================================
# Schema Validation — RecurringRideCreate
# ===========================================================================


class TestRecurringRideCreateSchema:
    def test_valid_weekday_commute(self):
        ride = RecurringRideCreate(
            pickup={"lat": 40.7128, "lng": -74.0060},
            dropoff={"lat": 40.7580, "lng": -73.9855},
            pickup_address="123 Main St",
            dropoff_address="456 Broadway",
            days_of_week=[0, 1, 2, 3, 4],
            pickup_time="08:00",
            timezone="America/New_York",
        )
        assert ride.days_of_week == [0, 1, 2, 3, 4]
        assert ride.pickup_time == time(8, 0)
        assert ride.timezone == "America/New_York"

    def test_single_day(self):
        ride = RecurringRideCreate(
            pickup={"lat": 40.0, "lng": -74.0},
            dropoff={"lat": 41.0, "lng": -73.0},
            pickup_address="A",
            dropoff_address="B",
            days_of_week=[6],
            pickup_time="09:30",
        )
        assert ride.days_of_week == [6]

    def test_all_seven_days(self):
        ride = RecurringRideCreate(
            pickup={"lat": 40.0, "lng": -74.0},
            dropoff={"lat": 41.0, "lng": -73.0},
            pickup_address="A",
            dropoff_address="B",
            days_of_week=[0, 1, 2, 3, 4, 5, 6],
            pickup_time="07:00",
        )
        assert len(ride.days_of_week) == 7

    def test_days_are_deduplicated_and_sorted(self):
        ride = RecurringRideCreate(
            pickup={"lat": 40.0, "lng": -74.0},
            dropoff={"lat": 41.0, "lng": -73.0},
            pickup_address="A",
            dropoff_address="B",
            days_of_week=[4, 2, 0, 2, 4],
            pickup_time="08:00",
        )
        assert ride.days_of_week == [0, 2, 4]

    def test_empty_days_rejected(self):
        with pytest.raises(ValueError, match="At least one day"):
            RecurringRideCreate(
                pickup={"lat": 40.0, "lng": -74.0},
                dropoff={"lat": 41.0, "lng": -73.0},
                pickup_address="A",
                dropoff_address="B",
                days_of_week=[],
                pickup_time="08:00",
            )

    def test_invalid_day_number_rejected(self):
        with pytest.raises(ValueError, match="Invalid day of week: 7"):
            RecurringRideCreate(
                pickup={"lat": 40.0, "lng": -74.0},
                dropoff={"lat": 41.0, "lng": -73.0},
                pickup_address="A",
                dropoff_address="B",
                days_of_week=[0, 7],
                pickup_time="08:00",
            )

    def test_negative_day_rejected(self):
        with pytest.raises(ValueError, match="Invalid day of week: -1"):
            RecurringRideCreate(
                pickup={"lat": 40.0, "lng": -74.0},
                dropoff={"lat": 41.0, "lng": -73.0},
                pickup_address="A",
                dropoff_address="B",
                days_of_week=[-1],
                pickup_time="08:00",
            )

    def test_default_timezone_is_utc(self):
        ride = RecurringRideCreate(
            pickup={"lat": 40.0, "lng": -74.0},
            dropoff={"lat": 41.0, "lng": -73.0},
            pickup_address="A",
            dropoff_address="B",
            days_of_week=[0],
            pickup_time="08:00",
        )
        assert ride.timezone == "UTC"

    def test_accessibility_default_false(self):
        ride = RecurringRideCreate(
            pickup={"lat": 40.0, "lng": -74.0},
            dropoff={"lat": 41.0, "lng": -73.0},
            pickup_address="A",
            dropoff_address="B",
            days_of_week=[0],
            pickup_time="08:00",
        )
        assert ride.accessibility_required is False

    def test_label_optional(self):
        ride = RecurringRideCreate(
            pickup={"lat": 40.0, "lng": -74.0},
            dropoff={"lat": 41.0, "lng": -73.0},
            pickup_address="A",
            dropoff_address="B",
            days_of_week=[0],
            pickup_time="08:00",
        )
        assert ride.label is None

    def test_label_provided(self):
        ride = RecurringRideCreate(
            pickup={"lat": 40.0, "lng": -74.0},
            dropoff={"lat": 41.0, "lng": -73.0},
            pickup_address="A",
            dropoff_address="B",
            days_of_week=[0],
            pickup_time="08:00",
            label="Morning commute",
        )
        assert ride.label == "Morning commute"

    def test_saved_location_ids_optional(self):
        ride = RecurringRideCreate(
            pickup={"lat": 40.0, "lng": -74.0},
            dropoff={"lat": 41.0, "lng": -73.0},
            pickup_address="A",
            dropoff_address="B",
            days_of_week=[0],
            pickup_time="08:00",
            pickup_saved_location_id=1,
            dropoff_saved_location_id=2,
        )
        assert ride.pickup_saved_location_id == 1
        assert ride.dropoff_saved_location_id == 2

    def test_empty_timezone_rejected(self):
        with pytest.raises(ValueError, match="Invalid timezone"):
            RecurringRideCreate(
                pickup={"lat": 40.0, "lng": -74.0},
                dropoff={"lat": 41.0, "lng": -73.0},
                pickup_address="A",
                dropoff_address="B",
                days_of_week=[0],
                pickup_time="08:00",
                timezone="",
            )


# ===========================================================================
# Schema Validation — RecurringRideUpdate
# ===========================================================================


class TestRecurringRideUpdateSchema:
    def test_all_fields_optional(self):
        update = RecurringRideUpdate()
        data = update.model_dump(exclude_unset=True)
        assert data == {}

    def test_partial_update_days(self):
        update = RecurringRideUpdate(days_of_week=[0, 1, 2])
        assert update.days_of_week == [0, 1, 2]

    def test_partial_update_time(self):
        update = RecurringRideUpdate(pickup_time="09:00")
        assert update.pickup_time == time(9, 0)

    def test_partial_update_label(self):
        update = RecurringRideUpdate(label="Evening gym")
        assert update.label == "Evening gym"

    def test_invalid_days_rejected(self):
        with pytest.raises(ValueError, match="Invalid day of week"):
            RecurringRideUpdate(days_of_week=[8])

    def test_empty_days_rejected(self):
        with pytest.raises(ValueError, match="At least one day"):
            RecurringRideUpdate(days_of_week=[])

    def test_none_days_accepted(self):
        update = RecurringRideUpdate(days_of_week=None)
        assert update.days_of_week is None

    def test_update_location(self):
        update = RecurringRideUpdate(
            pickup={"lat": 41.0, "lng": -73.0},
            pickup_address="New pickup",
        )
        assert update.pickup.lat == 41.0
        assert update.pickup_address == "New pickup"


# ===========================================================================
# Schema — RecurringRideResponse
# ===========================================================================


class TestRecurringRideResponseSchema:
    def test_from_attributes(self):
        assert RecurringRideResponse.model_config.get("from_attributes") is True

    def test_all_fields_present(self):
        fields = set(RecurringRideResponse.model_fields.keys())
        expected = {
            "id", "rider_id", "pickup_address", "dropoff_address",
            "days_of_week", "pickup_time", "timezone",
            "accessibility_required", "status", "label",
            "last_generated_date", "created_at", "updated_at",
        }
        assert expected == fields

    def test_serialization(self):
        now = datetime.now(timezone.utc)
        resp = RecurringRideResponse(
            id=1,
            rider_id=10,
            pickup_address="Home",
            dropoff_address="Work",
            days_of_week=[0, 1, 2, 3, 4],
            pickup_time=time(8, 0),
            timezone="UTC",
            accessibility_required=False,
            status="active",
            label="Commute",
            last_generated_date=None,
            created_at=now,
            updated_at=now,
        )
        assert resp.id == 1
        assert resp.status == "active"


class TestRecurringRideDetailResponseSchema:
    def test_inherits_from_response(self):
        assert issubclass(RecurringRideDetailResponse, RecurringRideResponse)

    def test_has_upcoming_rides_field(self):
        assert "upcoming_rides" in RecurringRideDetailResponse.model_fields

    def test_default_empty_upcoming(self):
        now = datetime.now(timezone.utc)
        resp = RecurringRideDetailResponse(
            id=1,
            rider_id=10,
            pickup_address="Home",
            dropoff_address="Work",
            days_of_week=[0],
            pickup_time=time(8, 0),
            timezone="UTC",
            accessibility_required=False,
            status="active",
            label=None,
            last_generated_date=None,
            created_at=now,
            updated_at=now,
        )
        assert resp.upcoming_rides == []


class TestGeneratedRideSummarySchema:
    def test_fields(self):
        fields = set(GeneratedRideSummary.model_fields.keys())
        assert fields == {"ride_id", "status", "scheduled_for"}

    def test_serialization(self):
        now = datetime.now(timezone.utc)
        s = GeneratedRideSummary(ride_id=5, status="scheduled", scheduled_for=now)
        assert s.ride_id == 5


class TestRecurringRideListResponseSchema:
    def test_fields(self):
        fields = set(RecurringRideListResponse.model_fields.keys())
        assert fields == {"recurring_rides", "total"}


# ===========================================================================
# Service Tests — CRUD
# ===========================================================================


def _make_simple_db():
    """Create a mock async DB session."""
    db = AsyncMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    db.delete = AsyncMock()
    return db


def _make_scalars_db(items):
    """Mock DB that returns a list via .scalars().all()."""
    db = _make_simple_db()
    scalars_mock = MagicMock()
    scalars_mock.all.return_value = items
    result = MagicMock()
    result.scalars.return_value = scalars_mock
    db.execute = AsyncMock(return_value=result)
    return db


def _make_scalar_one_db(value):
    """Mock DB that returns a single value via .scalar_one_or_none()."""
    db = _make_simple_db()
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    db.execute = AsyncMock(return_value=result)
    return db


def _make_recurring_ride(**kwargs):
    """Create a mock RecurringRide object."""
    defaults = {
        "id": 1,
        "rider_id": 10,
        "pickup_address": "Home",
        "dropoff_address": "Work",
        "days_of_week": [0, 1, 2, 3, 4],
        "pickup_time": time(8, 0),
        "timezone": "UTC",
        "accessibility_required": False,
        "status": RecurringRideStatus.ACTIVE,
        "label": "Morning commute",
        "last_generated_date": None,
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
        "pickup_location": b"mock",
        "dropoff_location": b"mock",
        "pickup_saved_location_id": None,
        "dropoff_saved_location_id": None,
    }
    defaults.update(kwargs)
    ride = MagicMock(spec=RecurringRide)
    for k, v in defaults.items():
        setattr(ride, k, v)
    return ride


class TestCreateRecurringRide:
    @pytest.mark.asyncio
    async def test_create_success(self):
        db = _make_scalars_db([])  # No existing recurring rides

        with patch("app.services.recurring_rides.ST_MakePoint") as mock_point:
            mock_point.return_value = b"point_bytes"
            ride = await create_recurring_ride(
                rider_id=10,
                pickup_lat=40.7128,
                pickup_lng=-74.006,
                dropoff_lat=40.758,
                dropoff_lng=-73.985,
                pickup_address="Home",
                dropoff_address="Work",
                days_of_week=[0, 1, 2, 3, 4],
                pickup_time=time(8, 0),
                tz="America/New_York",
                db=db,
                label="Morning commute",
            )

        db.add.assert_called_once()
        db.commit.assert_called_once()
        db.refresh.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_respects_limit(self):
        existing = [_make_recurring_ride(id=i) for i in range(MAX_RECURRING_RIDES_PER_USER)]
        db = _make_scalars_db(existing)

        with pytest.raises(RecurringRideLimitError, match="Maximum"):
            await create_recurring_ride(
                rider_id=10,
                pickup_lat=40.0,
                pickup_lng=-74.0,
                dropoff_lat=41.0,
                dropoff_lng=-73.0,
                pickup_address="A",
                dropoff_address="B",
                days_of_week=[0],
                pickup_time=time(8, 0),
                tz="UTC",
                db=db,
            )

    @pytest.mark.asyncio
    async def test_create_with_accessibility(self):
        db = _make_scalars_db([])

        with patch("app.services.recurring_rides.ST_MakePoint") as mock_point:
            mock_point.return_value = b"point_bytes"
            ride = await create_recurring_ride(
                rider_id=10,
                pickup_lat=40.0,
                pickup_lng=-74.0,
                dropoff_lat=41.0,
                dropoff_lng=-73.0,
                pickup_address="A",
                dropoff_address="B",
                days_of_week=[0],
                pickup_time=time(8, 0),
                tz="UTC",
                db=db,
                accessibility_required=True,
            )

        db.add.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_with_saved_locations(self):
        db = _make_scalars_db([])

        with patch("app.services.recurring_rides.ST_MakePoint") as mock_point:
            mock_point.return_value = b"point_bytes"
            ride = await create_recurring_ride(
                rider_id=10,
                pickup_lat=40.0,
                pickup_lng=-74.0,
                dropoff_lat=41.0,
                dropoff_lng=-73.0,
                pickup_address="A",
                dropoff_address="B",
                days_of_week=[0],
                pickup_time=time(8, 0),
                tz="UTC",
                db=db,
                pickup_saved_location_id=1,
                dropoff_saved_location_id=2,
            )

        db.add.assert_called_once()


class TestGetRecurringRide:
    @pytest.mark.asyncio
    async def test_get_found(self):
        ride = _make_recurring_ride()
        db = _make_scalar_one_db(ride)
        result = await get_recurring_ride(1, 10, db)
        assert result == ride

    @pytest.mark.asyncio
    async def test_get_not_found(self):
        db = _make_scalar_one_db(None)
        with pytest.raises(RecurringRideNotFoundError, match="not found"):
            await get_recurring_ride(999, 10, db)

    @pytest.mark.asyncio
    async def test_get_wrong_rider(self):
        db = _make_scalar_one_db(None)  # Query includes rider_id filter
        with pytest.raises(RecurringRideNotFoundError):
            await get_recurring_ride(1, 999, db)


class TestListRecurringRides:
    @pytest.mark.asyncio
    async def test_list_returns_rides(self):
        rides = [_make_recurring_ride(id=1), _make_recurring_ride(id=2)]
        db = _make_scalars_db(rides)
        result = await list_recurring_rides(10, db)
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_list_empty(self):
        db = _make_scalars_db([])
        result = await list_recurring_rides(10, db)
        assert result == []


class TestPauseRecurringRide:
    @pytest.mark.asyncio
    async def test_pause_active_ride(self):
        ride = _make_recurring_ride(status=RecurringRideStatus.ACTIVE)
        db = _make_scalar_one_db(ride)
        result = await pause_recurring_ride(1, 10, db)
        assert ride.status == RecurringRideStatus.PAUSED
        db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_pause_already_paused_raises(self):
        ride = _make_recurring_ride(status=RecurringRideStatus.PAUSED)
        db = _make_scalar_one_db(ride)
        with pytest.raises(RecurringRideStateError, match="only pause active"):
            await pause_recurring_ride(1, 10, db)

    @pytest.mark.asyncio
    async def test_pause_cancelled_raises(self):
        ride = _make_recurring_ride(status=RecurringRideStatus.CANCELLED)
        db = _make_scalar_one_db(ride)
        with pytest.raises(RecurringRideStateError, match="only pause active"):
            await pause_recurring_ride(1, 10, db)


class TestResumeRecurringRide:
    @pytest.mark.asyncio
    async def test_resume_paused_ride(self):
        ride = _make_recurring_ride(status=RecurringRideStatus.PAUSED)
        db = _make_scalar_one_db(ride)
        result = await resume_recurring_ride(1, 10, db)
        assert ride.status == RecurringRideStatus.ACTIVE
        db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_resume_active_raises(self):
        ride = _make_recurring_ride(status=RecurringRideStatus.ACTIVE)
        db = _make_scalar_one_db(ride)
        with pytest.raises(RecurringRideStateError, match="only resume paused"):
            await resume_recurring_ride(1, 10, db)


class TestCancelRecurringRide:
    @pytest.mark.asyncio
    async def test_cancel_active_ride(self):
        ride = _make_recurring_ride(status=RecurringRideStatus.ACTIVE)
        db = _make_scalar_one_db(ride)
        result = await cancel_recurring_ride(1, 10, db)
        assert ride.status == RecurringRideStatus.CANCELLED
        db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_cancel_paused_ride(self):
        ride = _make_recurring_ride(status=RecurringRideStatus.PAUSED)
        db = _make_scalar_one_db(ride)
        result = await cancel_recurring_ride(1, 10, db)
        assert ride.status == RecurringRideStatus.CANCELLED

    @pytest.mark.asyncio
    async def test_cancel_already_cancelled_raises(self):
        ride = _make_recurring_ride(status=RecurringRideStatus.CANCELLED)
        db = _make_scalar_one_db(ride)
        with pytest.raises(RecurringRideStateError, match="already cancelled"):
            await cancel_recurring_ride(1, 10, db)


class TestUpdateRecurringRide:
    @pytest.mark.asyncio
    async def test_update_days(self):
        ride = _make_recurring_ride(status=RecurringRideStatus.ACTIVE)
        db = _make_scalar_one_db(ride)
        result = await update_recurring_ride(
            1, 10, db,
            days_of_week=[0, 2, 4],
        )
        assert ride.days_of_week == [0, 2, 4]
        assert ride.last_generated_date is None  # Reset on update
        db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_update_time(self):
        ride = _make_recurring_ride(status=RecurringRideStatus.ACTIVE)
        db = _make_scalar_one_db(ride)
        result = await update_recurring_ride(
            1, 10, db,
            pickup_time=time(9, 30),
        )
        assert ride.pickup_time == time(9, 30)

    @pytest.mark.asyncio
    async def test_update_label(self):
        ride = _make_recurring_ride(status=RecurringRideStatus.ACTIVE)
        db = _make_scalar_one_db(ride)
        result = await update_recurring_ride(
            1, 10, db,
            label="Evening class",
        )
        assert ride.label == "Evening class"

    @pytest.mark.asyncio
    async def test_update_cancelled_raises(self):
        ride = _make_recurring_ride(status=RecurringRideStatus.CANCELLED)
        db = _make_scalar_one_db(ride)
        with pytest.raises(RecurringRideStateError, match="Cannot update a cancelled"):
            await update_recurring_ride(1, 10, db, label="New")

    @pytest.mark.asyncio
    async def test_update_location(self):
        ride = _make_recurring_ride(status=RecurringRideStatus.ACTIVE)
        db = _make_scalar_one_db(ride)
        with patch("app.services.recurring_rides.ST_MakePoint") as mock_point:
            mock_point.return_value = b"new_point"
            result = await update_recurring_ride(
                1, 10, db,
                pickup_lat=41.0,
                pickup_lng=-73.0,
                pickup_address="New Pickup",
            )
        assert ride.pickup_address == "New Pickup"

    @pytest.mark.asyncio
    async def test_update_resets_generation_tracking(self):
        ride = _make_recurring_ride(
            status=RecurringRideStatus.ACTIVE,
            last_generated_date=datetime.now(timezone.utc),
        )
        db = _make_scalar_one_db(ride)
        await update_recurring_ride(1, 10, db, label="Changed")
        assert ride.last_generated_date is None


# ===========================================================================
# Service Tests — Occurrence Calculation
# ===========================================================================


class TestNextOccurrenceDates:
    def test_weekday_commute_generates_dates(self):
        # Monday through Friday
        with patch("app.services.recurring_rides.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 4, 13, 6, 0, tzinfo=timezone.utc)  # Monday 6am
            mock_dt.combine = datetime.combine
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)

            dates = _next_occurrence_dates(
                days_of_week=[0, 1, 2, 3, 4],
                pickup_time=time(8, 0),
                tz_name="UTC",
                from_date=date(2026, 4, 13),
                horizon_hours=24,
            )
        # Should include Monday (today) at 8am UTC
        assert len(dates) >= 1

    def test_weekend_only(self):
        dates = _next_occurrence_dates(
            days_of_week=[5, 6],  # Saturday, Sunday
            pickup_time=time(10, 0),
            tz_name="UTC",
            from_date=date(2026, 4, 13),  # Monday
            horizon_hours=168,  # 7 days
        )
        for d in dates:
            assert d.weekday() in [5, 6]

    def test_empty_when_no_matching_days_in_horizon(self):
        # Only Sunday, but from_date is Monday and horizon is 24h
        dates = _next_occurrence_dates(
            days_of_week=[6],
            pickup_time=time(8, 0),
            tz_name="UTC",
            from_date=date(2026, 4, 13),  # Monday
            horizon_hours=24,
        )
        # Sunday is 6 days away, well outside 24h horizon
        assert len(dates) == 0

    def test_respects_horizon(self):
        dates = _next_occurrence_dates(
            days_of_week=[0, 1, 2, 3, 4, 5, 6],
            pickup_time=time(8, 0),
            tz_name="UTC",
            from_date=date(2026, 4, 13),
            horizon_hours=48,
        )
        now = datetime.now(timezone.utc)
        horizon_end = now + timedelta(hours=48)
        for d in dates:
            assert d <= horizon_end

    def test_past_times_skipped(self):
        # If today's pickup_time is already past, skip it
        dates = _next_occurrence_dates(
            days_of_week=[0, 1, 2, 3, 4, 5, 6],
            pickup_time=time(0, 1),  # 12:01 AM — very early
            tz_name="UTC",
            from_date=date.today(),
            horizon_hours=24,
        )
        now = datetime.now(timezone.utc)
        for d in dates:
            assert d > now


# ===========================================================================
# Service Tests — Ride Generation
# ===========================================================================


class TestGetUpcomingGeneratedRides:
    @pytest.mark.asyncio
    async def test_returns_upcoming_rides(self):
        mock_ride = MagicMock(spec=Ride)
        mock_ride.id = 100
        mock_ride.status = RideStatus.SCHEDULED
        mock_ride.scheduled_for = datetime.now(timezone.utc) + timedelta(hours=2)

        db = _make_scalars_db([mock_ride])
        result = await get_upcoming_generated_rides(1, db)
        assert len(result) == 1
        assert result[0].id == 100

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_rides(self):
        db = _make_scalars_db([])
        result = await get_upcoming_generated_rides(1, db)
        assert result == []


class TestGenerateRidesFromRecurring:
    @pytest.mark.asyncio
    async def test_generates_rides_for_active_template(self):
        template = _make_recurring_ride(
            status=RecurringRideStatus.ACTIVE,
            days_of_week=[0, 1, 2, 3, 4, 5, 6],  # Every day
            pickup_time=time(8, 0),
            timezone="UTC",
            last_generated_date=None,
        )

        # First execute returns active templates, second returns existing scheduled rides
        db = _make_simple_db()
        call_count = {"n": 0}

        async def execute_side_effect(stmt):
            call_count["n"] += 1
            result = MagicMock()
            if call_count["n"] == 1:
                # Active templates
                scalars_mock = MagicMock()
                scalars_mock.all.return_value = [template]
                result.scalars.return_value = scalars_mock
            else:
                # Existing scheduled ride times
                result.all.return_value = []
            return result

        db.execute = AsyncMock(side_effect=execute_side_effect)

        now = datetime(2026, 4, 13, 6, 0, tzinfo=timezone.utc)  # Monday 6am
        with patch("app.services.recurring_rides._next_occurrence_dates") as mock_dates:
            # Return one occurrence
            occurrence = datetime(2026, 4, 13, 8, 0, tzinfo=timezone.utc)
            mock_dates.return_value = [occurrence]
            with patch("app.services.recurring_rides.check_overlap") as mock_overlap:
                mock_overlap.return_value = MagicMock(valid=True)
                count = await generate_rides_from_recurring(db, now=now)

        assert count == 1
        db.add.assert_called_once()
        db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_skips_paused_templates(self):
        # No active templates
        db = _make_scalars_db([])
        count = await generate_rides_from_recurring(db)
        assert count == 0
        db.commit.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_overlapping_rides(self):
        template = _make_recurring_ride(
            status=RecurringRideStatus.ACTIVE,
            days_of_week=[0, 1, 2, 3, 4, 5, 6],
            pickup_time=time(8, 0),
            timezone="UTC",
            last_generated_date=None,
        )

        db = _make_simple_db()
        call_count = {"n": 0}

        async def execute_side_effect(stmt):
            call_count["n"] += 1
            result = MagicMock()
            if call_count["n"] == 1:
                scalars_mock = MagicMock()
                scalars_mock.all.return_value = [template]
                result.scalars.return_value = scalars_mock
            else:
                result.all.return_value = []
            return result

        db.execute = AsyncMock(side_effect=execute_side_effect)

        with patch("app.services.recurring_rides._next_occurrence_dates") as mock_dates:
            occurrence = datetime(2026, 4, 13, 8, 0, tzinfo=timezone.utc)
            mock_dates.return_value = [occurrence]
            with patch("app.services.recurring_rides.check_overlap") as mock_overlap:
                mock_overlap.return_value = MagicMock(valid=False)
                count = await generate_rides_from_recurring(db)

        assert count == 0
        db.add.assert_not_called()

    @pytest.mark.asyncio
    async def test_updates_last_generated_date(self):
        template = _make_recurring_ride(
            status=RecurringRideStatus.ACTIVE,
            days_of_week=[0],
            pickup_time=time(8, 0),
            timezone="UTC",
            last_generated_date=None,
        )

        db = _make_simple_db()
        call_count = {"n": 0}

        async def execute_side_effect(stmt):
            call_count["n"] += 1
            result = MagicMock()
            if call_count["n"] == 1:
                scalars_mock = MagicMock()
                scalars_mock.all.return_value = [template]
                result.scalars.return_value = scalars_mock
            else:
                result.all.return_value = []
            return result

        db.execute = AsyncMock(side_effect=execute_side_effect)

        occurrence = datetime(2026, 4, 13, 8, 0, tzinfo=timezone.utc)
        with patch("app.services.recurring_rides._next_occurrence_dates") as mock_dates:
            mock_dates.return_value = [occurrence]
            with patch("app.services.recurring_rides.check_overlap") as mock_overlap:
                mock_overlap.return_value = MagicMock(valid=True)
                await generate_rides_from_recurring(db)

        assert template.last_generated_date is not None


# ===========================================================================
# Scheduler Integration Tests
# ===========================================================================


class TestSchedulerIntegration:
    @pytest.mark.asyncio
    async def test_generate_recurring_rides_function_exists(self):
        """Verify that generate_recurring_rides is defined in the dispatch scheduler."""
        from app.services.dispatch_scheduler import generate_recurring_rides
        assert callable(generate_recurring_rides)

    def test_scheduler_loop_calls_generate_recurring(self):
        """Verify the scheduler loop source code includes recurring ride generation."""
        import inspect
        from app.services.dispatch_scheduler import _scheduler_loop
        source = inspect.getsource(_scheduler_loop)
        assert "generate_recurring_rides" in source


# ===========================================================================
# API Endpoint Tests
# ===========================================================================


def _mock_user(user_id=10):
    user = MagicMock()
    user.id = user_id
    user.role = "rider"
    return user


class TestCreateEndpoint:
    @pytest.mark.asyncio
    async def test_create_returns_201(self):
        from app.api.v1.recurring_rides import create

        body = RecurringRideCreate(
            pickup={"lat": 40.7128, "lng": -74.006},
            dropoff={"lat": 40.758, "lng": -73.985},
            pickup_address="Home",
            dropoff_address="Work",
            days_of_week=[0, 1, 2, 3, 4],
            pickup_time="08:00",
            timezone="UTC",
            label="Commute",
        )
        user = _mock_user()
        db = AsyncMock()

        mock_ride = _make_recurring_ride()
        with patch(
            "app.api.v1.recurring_rides.create_recurring_ride",
            new_callable=AsyncMock,
            return_value=mock_ride,
        ):
            result = await create(body, user, db)
        assert result == mock_ride

    @pytest.mark.asyncio
    async def test_create_limit_returns_409(self):
        from app.api.v1.recurring_rides import create
        from fastapi import HTTPException

        body = RecurringRideCreate(
            pickup={"lat": 40.0, "lng": -74.0},
            dropoff={"lat": 41.0, "lng": -73.0},
            pickup_address="A",
            dropoff_address="B",
            days_of_week=[0],
            pickup_time="08:00",
        )

        with patch(
            "app.api.v1.recurring_rides.create_recurring_ride",
            new_callable=AsyncMock,
            side_effect=RecurringRideLimitError("Maximum"),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await create(body, _mock_user(), AsyncMock())
            assert exc_info.value.status_code == 409


class TestListEndpoint:
    @pytest.mark.asyncio
    async def test_list_returns_rides(self):
        from app.api.v1.recurring_rides import list_mine

        rides = [_make_recurring_ride(id=1), _make_recurring_ride(id=2)]
        with patch(
            "app.api.v1.recurring_rides.list_recurring_rides",
            new_callable=AsyncMock,
            return_value=rides,
        ):
            result = await list_mine(False, _mock_user(), AsyncMock())
        assert result.total == 2


class TestGetDetailEndpoint:
    @pytest.mark.asyncio
    async def test_get_detail_success(self):
        from app.api.v1.recurring_rides import get_detail

        ride = _make_recurring_ride()
        ride.status = RecurringRideStatus.ACTIVE

        with patch(
            "app.api.v1.recurring_rides.get_recurring_ride",
            new_callable=AsyncMock,
            return_value=ride,
        ):
            with patch(
                "app.api.v1.recurring_rides.get_upcoming_generated_rides",
                new_callable=AsyncMock,
                return_value=[],
            ):
                result = await get_detail(1, _mock_user(), AsyncMock())
        assert result.id == 1
        assert result.upcoming_rides == []

    @pytest.mark.asyncio
    async def test_get_detail_not_found(self):
        from app.api.v1.recurring_rides import get_detail
        from fastapi import HTTPException

        with patch(
            "app.api.v1.recurring_rides.get_recurring_ride",
            new_callable=AsyncMock,
            side_effect=RecurringRideNotFoundError("not found"),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await get_detail(999, _mock_user(), AsyncMock())
            assert exc_info.value.status_code == 404


class TestPauseEndpoint:
    @pytest.mark.asyncio
    async def test_pause_success(self):
        from app.api.v1.recurring_rides import pause

        ride = _make_recurring_ride(status=RecurringRideStatus.PAUSED)
        with patch(
            "app.api.v1.recurring_rides.pause_recurring_ride",
            new_callable=AsyncMock,
            return_value=ride,
        ):
            result = await pause(1, _mock_user(), AsyncMock())
        assert result.status == RecurringRideStatus.PAUSED

    @pytest.mark.asyncio
    async def test_pause_wrong_state(self):
        from app.api.v1.recurring_rides import pause
        from fastapi import HTTPException

        with patch(
            "app.api.v1.recurring_rides.pause_recurring_ride",
            new_callable=AsyncMock,
            side_effect=RecurringRideStateError("already paused"),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await pause(1, _mock_user(), AsyncMock())
            assert exc_info.value.status_code == 409


class TestResumeEndpoint:
    @pytest.mark.asyncio
    async def test_resume_success(self):
        from app.api.v1.recurring_rides import resume

        ride = _make_recurring_ride(status=RecurringRideStatus.ACTIVE)
        with patch(
            "app.api.v1.recurring_rides.resume_recurring_ride",
            new_callable=AsyncMock,
            return_value=ride,
        ):
            result = await resume(1, _mock_user(), AsyncMock())
        assert result.status == RecurringRideStatus.ACTIVE


class TestCancelEndpoint:
    @pytest.mark.asyncio
    async def test_cancel_success(self):
        from app.api.v1.recurring_rides import cancel

        ride = _make_recurring_ride(status=RecurringRideStatus.CANCELLED)
        with patch(
            "app.api.v1.recurring_rides.cancel_recurring_ride",
            new_callable=AsyncMock,
            return_value=ride,
        ):
            result = await cancel(1, _mock_user(), AsyncMock())
        assert result.status == RecurringRideStatus.CANCELLED

    @pytest.mark.asyncio
    async def test_cancel_already_cancelled(self):
        from app.api.v1.recurring_rides import cancel
        from fastapi import HTTPException

        with patch(
            "app.api.v1.recurring_rides.cancel_recurring_ride",
            new_callable=AsyncMock,
            side_effect=RecurringRideStateError("already cancelled"),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await cancel(1, _mock_user(), AsyncMock())
            assert exc_info.value.status_code == 409


class TestUpdateEndpoint:
    @pytest.mark.asyncio
    async def test_update_success(self):
        from app.api.v1.recurring_rides import update

        body = RecurringRideUpdate(label="New label", days_of_week=[0, 2, 4])
        ride = _make_recurring_ride(label="New label", days_of_week=[0, 2, 4])

        with patch(
            "app.api.v1.recurring_rides.update_recurring_ride",
            new_callable=AsyncMock,
            return_value=ride,
        ):
            result = await update(1, body, _mock_user(), AsyncMock())
        assert result.label == "New label"

    @pytest.mark.asyncio
    async def test_update_not_found(self):
        from app.api.v1.recurring_rides import update
        from fastapi import HTTPException

        body = RecurringRideUpdate(label="New")
        with patch(
            "app.api.v1.recurring_rides.update_recurring_ride",
            new_callable=AsyncMock,
            side_effect=RecurringRideNotFoundError("not found"),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await update(999, body, _mock_user(), AsyncMock())
            assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_update_cancelled_returns_409(self):
        from app.api.v1.recurring_rides import update
        from fastapi import HTTPException

        body = RecurringRideUpdate(label="New")
        with patch(
            "app.api.v1.recurring_rides.update_recurring_ride",
            new_callable=AsyncMock,
            side_effect=RecurringRideStateError("Cannot update cancelled"),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await update(1, body, _mock_user(), AsyncMock())
            assert exc_info.value.status_code == 409
