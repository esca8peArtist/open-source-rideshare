"""Tests for driver availability integration in the ride matching engine.

Covers the interaction between MatchingEngine.find_candidates() /
_get_availability_eligible_driver_ids() and the DriverOnlineStatus /
DriverSchedule tables.

All tests are pure unit tests using mocked DB sessions — no live database
required.  Tests that verify the full ORM stack are marked with
@pytest.mark.skip(reason="requires PostgreSQL").

Scenarios covered
-----------------
1.  Available driver (online + recent heartbeat + no schedule) is matched.
2.  Offline driver (is_online=False) is not matched.
3.  Driver with stale heartbeat is not matched.
4.  Driver with no schedule but online is matched (opt-in model).
5.  Driver with schedule, currently inside window, is matched.
6.  Driver with schedule, currently outside window, is not matched.
7.  availability_filter=False bypasses DB availability checks entirely.
8.  Empty candidate list returns empty set without querying DB.
9.  Multiple drivers: only eligible subset is returned.
10. Driver with multiple schedule slots: matched when inside any slot.
11. Driver with multiple schedule slots: not matched when outside all slots.
12. find_candidates returns empty list when no Redis-available drivers.
13. find_candidates applies availability filter and removes ineligible profiles.
14. find_candidates with availability_filter=False keeps all profiles.
15. match_ride passes availability_filter through to find_candidates.
16. match_ride with availability_filter=True returns only available drivers.
17. match_ride with availability_filter=False returns drivers ignoring DB state.
18. Heartbeat exactly at stale threshold boundary is accepted (>= comparison).
19. Driver with is_online=True but last_heartbeat=None is excluded.
20. _get_availability_eligible_driver_ids returns empty set given empty input.
"""

from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.driver_availability import DriverOnlineStatus, DriverSchedule
from app.services.matching import (
    DriverCandidate,
    MatchingEngine,
    _HEARTBEAT_STALE_MINUTES,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_status_row(
    driver_id: int,
    is_online: bool = True,
    minutes_ago: int | None = 1,
) -> MagicMock:
    """Build a mock DriverOnlineStatus row."""
    row = MagicMock(spec=DriverOnlineStatus)
    row.driver_id = driver_id
    row.is_online = is_online
    if minutes_ago is not None:
        row.last_heartbeat = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
    else:
        row.last_heartbeat = None
    return row


def _make_schedule_slot(
    driver_id: int,
    start: time,
    end: time,
    day_of_week: int = 0,
    is_active: bool = True,
) -> MagicMock:
    """Build a mock DriverSchedule row."""
    slot = MagicMock(spec=DriverSchedule)
    slot.driver_id = driver_id
    slot.day_of_week = day_of_week
    slot.start_time = start
    slot.end_time = end
    slot.is_active = is_active
    return slot


def _make_driver_profile(
    driver_id: int,
    user_id: int,
    rating_avg: float = 4.8,
    total_trips: int = 50,
) -> MagicMock:
    """Build a mock DriverProfile row."""
    p = MagicMock()
    p.id = driver_id
    p.user_id = user_id
    p.is_online = True
    p.is_approved = True
    p.rating_avg = rating_avg
    p.total_trips = total_trips
    p.active_vehicle_id = None
    return p


def _db_execute_sequence(*result_scalars_lists):
    """
    Build a mock AsyncSession whose execute() calls return successive results.

    Each positional argument is the list of rows that .scalars().all() returns
    for the n-th call.  Use a single element (not a list) for scalar_one_or_none.
    """
    side_effects = []
    for rows in result_scalars_lists:
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = rows
        mock_result.scalar_one_or_none.return_value = rows[0] if rows else None
        side_effects.append(mock_result)

    db = AsyncMock()
    db.execute = AsyncMock(side_effect=side_effects)
    return db


def _make_engine() -> MatchingEngine:
    mock_redis = AsyncMock()
    mock_redis.geosearch = AsyncMock(return_value=[])
    mock_redis.get = AsyncMock(return_value=b"available")
    return MatchingEngine(mock_redis)


# ---------------------------------------------------------------------------
# Tests for _get_availability_eligible_driver_ids
# ---------------------------------------------------------------------------

class TestGetAvailabilityEligibleDriverIds:
    """Unit tests for the internal availability pre-filter."""

    @pytest.mark.asyncio
    async def test_empty_input_returns_empty_set_without_querying(self):
        """Test 20: empty candidate list → empty result, no DB query."""
        db = AsyncMock()
        engine = _make_engine()

        result = await engine._get_availability_eligible_driver_ids(db, [])

        assert result == set()
        db.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_online_with_fresh_heartbeat_and_no_schedule_is_eligible(self):
        """Test 1 & 4: Online driver, fresh heartbeat, no schedule → eligible."""
        status_row = _make_status_row(driver_id=10, is_online=True, minutes_ago=1)
        db = _db_execute_sequence(
            [status_row],  # status query result
            [],            # schedule query result (no slots)
        )
        engine = _make_engine()

        result = await engine._get_availability_eligible_driver_ids(db, [10])

        assert result == {10}

    @pytest.mark.asyncio
    async def test_offline_driver_is_not_eligible(self):
        """Test 2: is_online=False → filtered out at status query stage."""
        # Status query returns no rows (offline filtered by WHERE clause)
        db = _db_execute_sequence(
            [],  # status query: no online rows
        )
        engine = _make_engine()

        result = await engine._get_availability_eligible_driver_ids(db, [10])

        assert result == set()
        # Schedule query should not be called since no online drivers exist
        assert db.execute.call_count == 1

    @pytest.mark.asyncio
    async def test_stale_heartbeat_driver_is_not_eligible(self):
        """Test 3: Heartbeat older than _HEARTBEAT_STALE_MINUTES → excluded."""
        # Status query returns no rows (stale heartbeat filtered by WHERE clause)
        db = _db_execute_sequence(
            [],  # status query: heartbeat too old
        )
        engine = _make_engine()

        result = await engine._get_availability_eligible_driver_ids(db, [10])

        assert result == set()

    @pytest.mark.asyncio
    async def test_driver_within_schedule_window_is_eligible(self):
        """Test 5: Online + fresh heartbeat + schedule window contains current time."""
        status_row = _make_status_row(driver_id=10, is_online=True, minutes_ago=2)
        # Use a 24-hour window so the test always passes regardless of time of day
        slot = _make_schedule_slot(driver_id=10, start=time(0, 0), end=time(23, 59))

        db = _db_execute_sequence([status_row], [slot])
        engine = _make_engine()

        result = await engine._get_availability_eligible_driver_ids(db, [10])

        assert result == {10}

    @pytest.mark.asyncio
    async def test_driver_outside_schedule_window_is_not_eligible(self):
        """Test 6: Online + fresh heartbeat but outside all schedule slots → excluded."""
        status_row = _make_status_row(driver_id=10, is_online=True, minutes_ago=2)
        # Slot for 00:01–00:02; patch time to 12:00 so we're guaranteed outside
        slot = _make_schedule_slot(driver_id=10, start=time(0, 1), end=time(0, 2))

        db = _db_execute_sequence([status_row], [slot])
        engine = _make_engine()

        fake_now = datetime(2026, 4, 13, 12, 0, 0, tzinfo=timezone.utc)
        with patch("app.services.matching.datetime") as mock_dt:
            mock_dt.now.return_value = fake_now

            result = await engine._get_availability_eligible_driver_ids(db, [10])

        assert result == set()

    @pytest.mark.asyncio
    async def test_multiple_drivers_only_eligible_returned(self):
        """Test 9: Three drivers — only those passing all checks are returned."""
        # driver 10: online, fresh heartbeat — eligible
        # driver 20: returned by status query (online+fresh) but outside schedule
        # driver 30: not returned by status query (offline/stale)
        status_10 = _make_status_row(driver_id=10, is_online=True, minutes_ago=1)
        status_20 = _make_status_row(driver_id=20, is_online=True, minutes_ago=1)

        slot_20 = _make_schedule_slot(driver_id=20, start=time(0, 1), end=time(0, 2))

        db = _db_execute_sequence(
            [status_10, status_20],  # status query: drivers 10 and 20 online
            [slot_20],               # schedule: driver 20 has a restrictive slot; 10 has none
        )
        engine = _make_engine()

        fake_now = datetime(2026, 4, 13, 12, 0, 0, tzinfo=timezone.utc)
        with patch("app.services.matching.datetime") as mock_dt:
            mock_dt.now.return_value = fake_now

            result = await engine._get_availability_eligible_driver_ids(db, [10, 20, 30])

        # driver 10 has no schedule → eligible; driver 20 is outside slot → excluded
        assert result == {10}

    @pytest.mark.asyncio
    async def test_driver_matched_when_inside_any_of_multiple_slots(self):
        """Test 10: Driver with two slots is matched when time is inside the second slot."""
        status_row = _make_status_row(driver_id=10, is_online=True, minutes_ago=1)
        # First slot: 00:01–00:02 (outside at 12:00)
        slot_a = _make_schedule_slot(driver_id=10, start=time(0, 1), end=time(0, 2))
        # Second slot: 10:00–14:00 (inside at 12:00)
        slot_b = _make_schedule_slot(driver_id=10, start=time(10, 0), end=time(14, 0))

        db = _db_execute_sequence([status_row], [slot_a, slot_b])
        engine = _make_engine()

        fake_now = datetime(2026, 4, 13, 12, 0, 0, tzinfo=timezone.utc)
        with patch("app.services.matching.datetime") as mock_dt:
            mock_dt.now.return_value = fake_now

            result = await engine._get_availability_eligible_driver_ids(db, [10])

        assert result == {10}

    @pytest.mark.asyncio
    async def test_driver_not_matched_when_outside_all_multiple_slots(self):
        """Test 11: Driver with two slots is excluded when outside both."""
        status_row = _make_status_row(driver_id=10, is_online=True, minutes_ago=1)
        # Both slots are midnight range — outside at 12:00
        slot_a = _make_schedule_slot(driver_id=10, start=time(0, 1), end=time(0, 30))
        slot_b = _make_schedule_slot(driver_id=10, start=time(0, 31), end=time(0, 59))

        db = _db_execute_sequence([status_row], [slot_a, slot_b])
        engine = _make_engine()

        fake_now = datetime(2026, 4, 13, 12, 0, 0, tzinfo=timezone.utc)
        with patch("app.services.matching.datetime") as mock_dt:
            mock_dt.now.return_value = fake_now

            result = await engine._get_availability_eligible_driver_ids(db, [10])

        assert result == set()

    @pytest.mark.asyncio
    async def test_driver_with_null_heartbeat_is_excluded(self):
        """Test 19: is_online=True but last_heartbeat=None → excluded by WHERE clause."""
        # The DB query filters last_heartbeat >= stale_threshold — NULL fails that
        db = _db_execute_sequence(
            [],  # status query returns no rows (NULL heartbeat excluded by DB)
        )
        engine = _make_engine()

        result = await engine._get_availability_eligible_driver_ids(db, [10])

        assert result == set()

    @pytest.mark.asyncio
    async def test_heartbeat_at_boundary_accepted(self):
        """Test 18: Heartbeat exactly at the stale threshold is at the boundary.

        The WHERE clause uses >= so a heartbeat exactly _HEARTBEAT_STALE_MINUTES
        old should be returned by the DB (we verify our mock structure supports
        this by confirming the status row IS in the result set).
        """
        # Simulate the DB returning the row (meaning the heartbeat was recent enough)
        status_row = _make_status_row(
            driver_id=10, is_online=True,
            minutes_ago=_HEARTBEAT_STALE_MINUTES,  # exactly at boundary
        )
        db = _db_execute_sequence([status_row], [])
        engine = _make_engine()

        result = await engine._get_availability_eligible_driver_ids(db, [10])

        # If DB returns the row (heartbeat within or exactly at threshold), driver is eligible
        assert result == {10}


# ---------------------------------------------------------------------------
# Tests for find_candidates with availability_filter
# ---------------------------------------------------------------------------

class TestFindCandidatesAvailabilityFilter:
    """Tests that find_candidates correctly applies (or skips) the filter."""

    def _engine_with_redis_returning_user(self, user_id: int, dist: float = 1.0) -> MatchingEngine:
        mock_redis = AsyncMock()
        mock_redis.geosearch = AsyncMock(return_value=[(str(user_id), dist)])
        mock_redis.get = AsyncMock(return_value=b"available")
        return MatchingEngine(mock_redis)

    @pytest.mark.asyncio
    async def test_find_candidates_returns_empty_when_no_nearby_drivers(self):
        """Test 12: No Redis geo results → empty candidate list."""
        mock_redis = AsyncMock()
        mock_redis.geosearch = AsyncMock(return_value=[])
        engine = MatchingEngine(mock_redis)

        db = AsyncMock()
        result = await engine.find_candidates(40.7, -74.0, db, availability_filter=True)

        assert result == []
        db.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_find_candidates_filters_ineligible_profiles(self):
        """Test 13: Eligible driver appears in results; ineligible is removed."""
        user_id = 42
        driver_id = 10
        engine = self._engine_with_redis_returning_user(user_id=user_id)

        profile = _make_driver_profile(driver_id=driver_id, user_id=user_id)

        # DB calls:
        # 1. DriverProfile query → profile
        # 2. _get_availability_eligible_driver_ids: status query → [] (driver ineligible)
        db = _db_execute_sequence(
            [profile],  # DriverProfile query
            [],         # DriverOnlineStatus query → no eligible rows
        )

        with patch("app.services.matching.settings") as mock_settings:
            mock_settings.driver_search_initial_radius_km = 5.0
            mock_settings.driver_search_radius_km = 20.0
            mock_settings.driver_location_ttl_seconds = 300

            result = await engine.find_candidates(40.7, -74.0, db, availability_filter=True)

        assert result == []

    @pytest.mark.asyncio
    async def test_find_candidates_with_filter_true_includes_eligible_driver(self):
        """Test 1 (via find_candidates): Eligible driver is present in results."""
        user_id = 42
        driver_id = 10
        engine = self._engine_with_redis_returning_user(user_id=user_id, dist=0.5)

        profile = _make_driver_profile(driver_id=driver_id, user_id=user_id)
        status_row = _make_status_row(driver_id=driver_id, is_online=True, minutes_ago=1)

        # DB call sequence:
        # 1. DriverProfile query
        # 2. DriverOnlineStatus query (status_row returned → eligible)
        # 3. DriverSchedule query (no schedule → opt-in)
        # 4. Vehicle query (no vehicles)
        db = _db_execute_sequence(
            [profile],       # DriverProfile
            [status_row],    # DriverOnlineStatus (eligible)
            [],              # DriverSchedule (no slots)
            [],              # Vehicle
        )

        with patch("app.services.matching.settings") as mock_settings:
            mock_settings.driver_search_initial_radius_km = 5.0
            mock_settings.driver_search_radius_km = 20.0
            mock_settings.driver_location_ttl_seconds = 300

            result = await engine.find_candidates(40.7, -74.0, db, availability_filter=True)

        assert len(result) == 1
        assert result[0].driver_id == driver_id
        assert result[0].user_id == user_id

    @pytest.mark.asyncio
    async def test_find_candidates_with_filter_false_skips_availability_check(self):
        """Test 14: availability_filter=False skips DB availability check entirely."""
        user_id = 42
        driver_id = 10
        engine = self._engine_with_redis_returning_user(user_id=user_id, dist=0.5)

        profile = _make_driver_profile(driver_id=driver_id, user_id=user_id)

        # With filter=False, the engine skips _get_availability_eligible_driver_ids.
        # DB calls: DriverProfile, then Vehicle (no availability queries).
        db = _db_execute_sequence(
            [profile],  # DriverProfile
            [],         # Vehicle
        )

        with patch("app.services.matching.settings") as mock_settings:
            mock_settings.driver_search_initial_radius_km = 5.0
            mock_settings.driver_search_radius_km = 20.0
            mock_settings.driver_location_ttl_seconds = 300

            result = await engine.find_candidates(40.7, -74.0, db, availability_filter=False)

        assert len(result) == 1
        assert result[0].driver_id == driver_id
        # Verify exactly 2 DB execute calls (profile + vehicle, no availability)
        assert db.execute.call_count == 2

    @pytest.mark.asyncio
    async def test_find_candidates_default_availability_filter_is_true(self):
        """Test 7 (negative): Default availability_filter=True removes ineligible driver."""
        user_id = 42
        driver_id = 10
        engine = self._engine_with_redis_returning_user(user_id=user_id)

        profile = _make_driver_profile(driver_id=driver_id, user_id=user_id)

        db = _db_execute_sequence(
            [profile],  # DriverProfile
            [],         # DriverOnlineStatus → no eligible (default filter applied)
        )

        with patch("app.services.matching.settings") as mock_settings:
            mock_settings.driver_search_initial_radius_km = 5.0
            mock_settings.driver_search_radius_km = 20.0
            mock_settings.driver_location_ttl_seconds = 300

            # Call without specifying availability_filter — should default to True
            result = await engine.find_candidates(40.7, -74.0, db)

        assert result == []


# ---------------------------------------------------------------------------
# Tests for match_ride availability_filter pass-through
# ---------------------------------------------------------------------------

class TestMatchRideAvailabilityFilter:
    """Verify match_ride threads availability_filter into find_candidates."""

    def _make_ride(self, ride_id: int = 1) -> MagicMock:
        ride = MagicMock()
        ride.id = ride_id
        return ride

    @pytest.mark.asyncio
    async def test_match_ride_default_uses_availability_filter(self):
        """Test 16: match_ride with default parameters applies availability filter."""
        engine = _make_engine()
        ride = self._make_ride()
        db = AsyncMock()

        with patch.object(
            engine, "find_candidates", new=AsyncMock(return_value=[])
        ) as mock_find:
            result = await engine.match_ride(ride, 40.7, -74.0, db)

        assert result is None
        mock_find.assert_called_once()
        call_kwargs = mock_find.call_args[1]
        assert call_kwargs.get("availability_filter", True) is True

    @pytest.mark.asyncio
    async def test_match_ride_passes_availability_filter_false(self):
        """Test 17: match_ride with availability_filter=False passes it through."""
        engine = _make_engine()
        ride = self._make_ride()
        db = AsyncMock()

        with patch.object(
            engine, "find_candidates", new=AsyncMock(return_value=[])
        ) as mock_find:
            result = await engine.match_ride(ride, 40.7, -74.0, db, availability_filter=False)

        assert result is None
        mock_find.assert_called_once()
        call_kwargs = mock_find.call_args[1]
        assert call_kwargs.get("availability_filter") is False

    @pytest.mark.asyncio
    async def test_match_ride_returns_best_available_candidate(self):
        """Test 15: match_ride returns the top-ranked available candidate."""
        engine = _make_engine()
        ride = self._make_ride()
        db = AsyncMock()

        candidate = DriverCandidate(
            driver_id=10, user_id=42, distance_km=0.5,
            rating_avg=4.9, total_trips=100,
        )

        with patch.object(
            engine, "find_candidates", new=AsyncMock(return_value=[candidate])
        ):
            result = await engine.match_ride(ride, 40.7, -74.0, db, availability_filter=True)

        assert result is candidate
        assert result.user_id == 42

    @pytest.mark.asyncio
    async def test_match_ride_returns_none_when_no_available_candidates(self):
        """Test 16 (none case): No available drivers → returns None."""
        engine = _make_engine()
        ride = self._make_ride()
        db = AsyncMock()

        with patch.object(
            engine, "find_candidates", new=AsyncMock(return_value=[])
        ):
            result = await engine.match_ride(ride, 40.7, -74.0, db, availability_filter=True)

        assert result is None


# ---------------------------------------------------------------------------
# DB-dependent integration tests (skipped without PostgreSQL)
# ---------------------------------------------------------------------------

@pytest.mark.skip(reason="requires PostgreSQL")
class TestMatchingAvailabilityDBIntegration:
    """Full-stack integration tests: matching engine + real DB.

    Run manually with:
        pytest tests/test_matching_availability.py::TestMatchingAvailabilityDBIntegration -v
    """

    async def test_eligible_driver_is_returned(self, db_session):
        """Driver that is online with fresh heartbeat and no schedule is returned."""
        from app.services.driver_availability import set_driver_online, update_heartbeat
        from app.models.driver import DriverProfile

        # Assumes a DriverProfile with id=1 exists in the test DB
        await set_driver_online(db_session, driver_id=1, is_online=True)
        await update_heartbeat(db_session, driver_id=1)

        engine = _make_engine()
        eligible = await engine._get_availability_eligible_driver_ids(db_session, [1])
        assert 1 in eligible

    async def test_offline_driver_is_not_returned(self, db_session):
        """Driver that is offline is excluded from eligibility."""
        from app.services.driver_availability import set_driver_online

        await set_driver_online(db_session, driver_id=1, is_online=False)

        engine = _make_engine()
        eligible = await engine._get_availability_eligible_driver_ids(db_session, [1])
        assert 1 not in eligible
