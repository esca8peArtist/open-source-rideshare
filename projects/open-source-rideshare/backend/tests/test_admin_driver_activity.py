"""Unit tests for GET /admin/drivers/activity."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models.driver import DriverProfile
from app.models.user import User, UserRole
from app.schemas.admin import DriverActivityListResponse


NOW = datetime(2026, 4, 18, 12, 0, 0, tzinfo=timezone.utc)


def _make_user(user_id=1, name="Test Driver"):
    u = MagicMock(spec=User)
    u.id = user_id
    u.name = name
    u.role = UserRole.DRIVER
    return u


def _make_profile(
    profile_id=1,
    user_id=1,
    name="Test Driver",
    is_online=False,
    is_approved=True,
    rating_avg=4.5,
    total_trips=10,
):
    p = MagicMock(spec=DriverProfile)
    p.id = profile_id
    p.user_id = user_id
    p.is_online = is_online
    p.is_approved = is_approved
    p.rating_avg = rating_avg
    p.total_trips = total_trips
    p.user = _make_user(user_id, name)
    return p


def _make_admin():
    a = MagicMock(spec=User)
    a.id = 99
    a.role = UserRole.ADMIN
    return a


def _scalar_result(value):
    """Mock result where .scalar() returns value."""
    r = MagicMock()
    r.scalar.return_value = value
    return r


def _scalars_result(items):
    """Mock result for unique().scalars().all()."""
    scalars = MagicMock()
    scalars.all.return_value = items
    r = MagicMock()
    r.scalars.return_value = scalars
    r.unique.return_value = r
    r.all.return_value = items
    return r


def _rows_result(rows):
    """Mock result where .all() returns a list of row objects."""
    r = MagicMock()
    r.all.return_value = rows
    return r


def _make_trip_row(driver_id, cnt):
    row = MagicMock()
    row.driver_id = driver_id
    row.cnt = cnt
    return row


def _make_shift_row(driver_id, mins):
    row = MagicMock()
    row.driver_id = driver_id
    row.mins = mins
    return row


def _make_last_trip_row(driver_id, last_at):
    row = MagicMock()
    row.driver_id = driver_id
    row.last_at = last_at
    return row


def _mock_db(execute_side_effects):
    db = AsyncMock()
    db.execute = AsyncMock(side_effect=execute_side_effects)
    db.commit = AsyncMock()
    return db


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestDriverActivityDashboard:
    @pytest.mark.asyncio
    async def test_empty_returns_empty_list(self):
        from app.api.v1.admin import driver_activity_dashboard

        db = _mock_db([
            _scalar_result(0),          # count query
            _scalars_result([]),         # profiles query
        ])

        result = await driver_activity_dashboard(
            is_online=None, is_approved=None, page=1, per_page=50,
            db=db, _admin=_make_admin(),
        )

        assert isinstance(result, DriverActivityListResponse)
        assert result.drivers == []
        assert result.pagination.total == 0

    @pytest.mark.asyncio
    async def test_driver_with_no_recent_activity(self):
        from app.api.v1.admin import driver_activity_dashboard

        profile = _make_profile(1, 1)

        db = _mock_db([
            _scalar_result(1),              # count
            _scalars_result([profile]),     # profiles
            _rows_result([]),               # trips_7d
            _rows_result([]),               # trips_30d
            _rows_result([]),               # shift_7d
            _rows_result([]),               # shift_30d
            _rows_result([]),               # last_trip
        ])

        result = await driver_activity_dashboard(
            is_online=None, is_approved=None, page=1, per_page=50,
            db=db, _admin=_make_admin(),
        )

        assert len(result.drivers) == 1
        entry = result.drivers[0]
        assert entry.driver_id == 1
        assert entry.user_id == 1
        assert entry.driver_name == "Test Driver"
        assert entry.trips_7d == 0
        assert entry.trips_30d == 0
        assert entry.shift_hours_7d == 0.0
        assert entry.shift_hours_30d == 0.0
        assert entry.last_trip_at is None

    @pytest.mark.asyncio
    async def test_driver_trip_counts_7d_and_30d(self):
        from app.api.v1.admin import driver_activity_dashboard

        profile = _make_profile(1, 1)

        db = _mock_db([
            _scalar_result(1),
            _scalars_result([profile]),
            _rows_result([_make_trip_row(1, 5)]),    # trips_7d
            _rows_result([_make_trip_row(1, 22)]),   # trips_30d
            _rows_result([]),                         # shift_7d
            _rows_result([]),                         # shift_30d
            _rows_result([]),                         # last_trip
        ])

        result = await driver_activity_dashboard(
            is_online=None, is_approved=None, page=1, per_page=50,
            db=db, _admin=_make_admin(),
        )

        entry = result.drivers[0]
        assert entry.trips_7d == 5
        assert entry.trips_30d == 22

    @pytest.mark.asyncio
    async def test_driver_shift_hours(self):
        from app.api.v1.admin import driver_activity_dashboard

        profile = _make_profile(1, 1)

        db = _mock_db([
            _scalar_result(1),
            _scalars_result([profile]),
            _rows_result([]),                                   # trips_7d
            _rows_result([]),                                   # trips_30d
            _rows_result([_make_shift_row(1, 120.0)]),          # shift_7d: 2 hours
            _rows_result([_make_shift_row(1, 600.0)]),          # shift_30d: 10 hours
            _rows_result([]),                                   # last_trip
        ])

        result = await driver_activity_dashboard(
            is_online=None, is_approved=None, page=1, per_page=50,
            db=db, _admin=_make_admin(),
        )

        entry = result.drivers[0]
        assert entry.shift_hours_7d == 2.0
        assert entry.shift_hours_30d == 10.0

    @pytest.mark.asyncio
    async def test_last_trip_at_populated(self):
        from app.api.v1.admin import driver_activity_dashboard

        profile = _make_profile(1, 1)
        last = datetime(2026, 4, 17, 10, 0, tzinfo=timezone.utc)

        db = _mock_db([
            _scalar_result(1),
            _scalars_result([profile]),
            _rows_result([]),
            _rows_result([]),
            _rows_result([]),
            _rows_result([]),
            _rows_result([_make_last_trip_row(1, last)]),
        ])

        result = await driver_activity_dashboard(
            is_online=None, is_approved=None, page=1, per_page=50,
            db=db, _admin=_make_admin(),
        )

        assert result.drivers[0].last_trip_at == last

    @pytest.mark.asyncio
    async def test_multiple_drivers_aggregated_independently(self):
        from app.api.v1.admin import driver_activity_dashboard

        p1 = _make_profile(1, 1, name="Alice")
        p2 = _make_profile(2, 2, name="Bob")

        db = _mock_db([
            _scalar_result(2),
            _scalars_result([p1, p2]),
            _rows_result([_make_trip_row(1, 3), _make_trip_row(2, 7)]),   # trips_7d
            _rows_result([_make_trip_row(1, 12), _make_trip_row(2, 30)]), # trips_30d
            _rows_result([_make_shift_row(1, 60.0)]),                      # shift_7d: only Alice
            _rows_result([_make_shift_row(1, 240.0), _make_shift_row(2, 120.0)]),  # shift_30d
            _rows_result([_make_last_trip_row(2, NOW)]),                   # last_trip: only Bob
        ])

        result = await driver_activity_dashboard(
            is_online=None, is_approved=None, page=1, per_page=50,
            db=db, _admin=_make_admin(),
        )

        assert len(result.drivers) == 2
        alice = result.drivers[0]
        bob = result.drivers[1]

        assert alice.driver_name == "Alice"
        assert alice.trips_7d == 3
        assert alice.trips_30d == 12
        assert alice.shift_hours_7d == 1.0
        assert alice.shift_hours_30d == 4.0
        assert alice.last_trip_at is None

        assert bob.driver_name == "Bob"
        assert bob.trips_7d == 7
        assert bob.trips_30d == 30
        assert bob.shift_hours_7d == 0.0
        assert bob.shift_hours_30d == 2.0
        assert bob.last_trip_at == NOW

    @pytest.mark.asyncio
    async def test_pagination_metadata(self):
        from app.api.v1.admin import driver_activity_dashboard

        db = _mock_db([
            _scalar_result(105),     # total = 105 drivers
            _scalars_result([]),     # page 3 of 50 — beyond range, empty
        ])

        result = await driver_activity_dashboard(
            is_online=None, is_approved=None, page=3, per_page=50,
            db=db, _admin=_make_admin(),
        )

        assert result.pagination.total == 105
        assert result.pagination.page == 3
        assert result.pagination.per_page == 50

    @pytest.mark.asyncio
    async def test_profile_fields_passed_through(self):
        from app.api.v1.admin import driver_activity_dashboard

        profile = _make_profile(
            profile_id=7, user_id=42, name="Carol",
            is_online=True, is_approved=True,
            rating_avg=4.8, total_trips=150,
        )

        db = _mock_db([
            _scalar_result(1),
            _scalars_result([profile]),
            _rows_result([]),
            _rows_result([]),
            _rows_result([]),
            _rows_result([]),
            _rows_result([]),
        ])

        result = await driver_activity_dashboard(
            is_online=None, is_approved=None, page=1, per_page=50,
            db=db, _admin=_make_admin(),
        )

        entry = result.drivers[0]
        assert entry.driver_id == 7
        assert entry.user_id == 42
        assert entry.driver_name == "Carol"
        assert entry.is_online is True
        assert entry.is_approved is True
        assert entry.rating_avg == 4.8
        assert entry.total_trips == 150
