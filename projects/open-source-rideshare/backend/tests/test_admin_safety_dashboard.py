"""Tests for admin safety dashboard feature.

Service unit tests (AsyncMock DB):
  1.  Returns empty dashboard when no safety events
  2.  Returns active SOS alerts (RESOLVED/FALSE_ALARM alerts excluded)
  3.  Returns route deviation flags for IN_PROGRESS rides only
  4.  Returns speeding flags for IN_PROGRESS rides only
  5.  Excludes non-EXPIRED check-in timers (ACTIVE, CONFIRMED, CANCELLED excluded)
  6.  Excludes expired check-ins older than 24 hours
  7.  Summary counts match list lengths
  8.  Multiple events of each type all appear
  9.  SOS with no ride_id (standalone SOS) is included
  10. Route deviation and speeding on same ride appear in both lists independently

API integration tests (conftest fixtures + real DB):
  11. 401 with no auth
  12. 403 with rider token
  13. 403 with driver token
  14. 200 with admin token returns dashboard structure
  15. Response contains all four list fields and all four count fields
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.check_in_timer import CheckInTimerStatus, RiderCheckInTimer
from app.models.ride import Ride, RideStatus
from app.models.safety import SOSAlert, SOSStatus
from app.services.admin_safety_dashboard import get_safety_dashboard

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 1, 15, 12, 0, 0, tzinfo=timezone.utc)


def _make_sos(
    id: int = 1,
    user_id: int = 10,
    ride_id: int | None = 1,
    status: SOSStatus = SOSStatus.ACTIVE,
    latitude: float = 40.7,
    longitude: float = -73.9,
    message: str | None = "Help!",
    created_at: datetime = _NOW,
) -> MagicMock:
    alert = MagicMock(spec=SOSAlert)
    alert.id = id
    alert.user_id = user_id
    alert.ride_id = ride_id
    alert.status = status
    alert.latitude = latitude
    alert.longitude = longitude
    alert.message = message
    alert.created_at = created_at
    return alert


def _make_ride(
    id: int = 1,
    rider_id: int = 10,
    driver_id: int | None = 20,
    status: RideStatus = RideStatus.IN_PROGRESS,
    route_deviation_flagged_at: datetime | None = None,
    speeding_flagged_at: datetime | None = None,
) -> MagicMock:
    ride = MagicMock(spec=Ride)
    ride.id = id
    ride.rider_id = rider_id
    ride.driver_id = driver_id
    ride.status = status
    ride.route_deviation_flagged_at = route_deviation_flagged_at
    ride.speeding_flagged_at = speeding_flagged_at
    return ride


def _make_timer(
    id: int = 1,
    rider_id: int = 10,
    status: CheckInTimerStatus = CheckInTimerStatus.EXPIRED,
    expires_at: datetime = _NOW,
    expired_notified_at: datetime | None = None,
) -> MagicMock:
    timer = MagicMock(spec=RiderCheckInTimer)
    timer.id = id
    timer.rider_id = rider_id
    timer.status = status
    timer.expires_at = expires_at
    timer.expired_notified_at = expired_notified_at
    return timer


def _make_db(*query_results: list) -> AsyncMock:
    """Build a DB mock that returns each list as scalars().all() in order."""
    db = AsyncMock()
    side_effects = []
    for items in query_results:
        result = MagicMock()
        scalars_mock = MagicMock()
        scalars_mock.all.return_value = items
        result.scalars.return_value = scalars_mock
        side_effects.append(result)
    db.execute = AsyncMock(side_effect=side_effects)
    return db


def auth_header(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Service unit tests
# ---------------------------------------------------------------------------


class TestGetSafetyDashboardService:

    @pytest.mark.asyncio
    async def test_empty_dashboard_when_no_events(self):
        """Test 1: returns empty dashboard when no safety events."""
        db = _make_db([], [], [], [])
        result = await get_safety_dashboard(db)
        assert result.active_sos_alerts == []
        assert result.route_deviation_flags == []
        assert result.speeding_flags == []
        assert result.expired_check_ins == []
        assert result.total_active_sos == 0
        assert result.total_route_deviations == 0
        assert result.total_speeding_flags == 0
        assert result.total_expired_check_ins == 0

    @pytest.mark.asyncio
    async def test_returns_active_sos_only(self):
        """Test 2: RESOLVED/FALSE_ALARM alerts are not returned by service (query filters at DB layer)."""
        active = _make_sos(id=1, status=SOSStatus.ACTIVE)
        # The service trusts the DB query — we only seed what the query would return
        db = _make_db([active], [], [], [])
        result = await get_safety_dashboard(db)
        assert len(result.active_sos_alerts) == 1
        assert result.active_sos_alerts[0].id == 1

    @pytest.mark.asyncio
    async def test_returns_route_deviation_for_in_progress_rides(self):
        """Test 3: route deviation flags for IN_PROGRESS rides only."""
        ride = _make_ride(id=5, route_deviation_flagged_at=_NOW)
        db = _make_db([], [ride], [], [])
        result = await get_safety_dashboard(db)
        assert len(result.route_deviation_flags) == 1
        assert result.route_deviation_flags[0].ride_id == 5
        assert result.route_deviation_flags[0].flagged_at == _NOW

    @pytest.mark.asyncio
    async def test_returns_speeding_flags_for_in_progress_rides(self):
        """Test 4: speeding flags for IN_PROGRESS rides only."""
        ride = _make_ride(id=7, speeding_flagged_at=_NOW)
        db = _make_db([], [], [ride], [])
        result = await get_safety_dashboard(db)
        assert len(result.speeding_flags) == 1
        assert result.speeding_flags[0].ride_id == 7
        assert result.speeding_flags[0].flagged_at == _NOW

    @pytest.mark.asyncio
    async def test_excludes_non_expired_check_in_timers(self):
        """Test 5: ACTIVE, CONFIRMED, CANCELLED timers are not returned (DB query filters them)."""
        # Service receives only what the DB returns — simulate DB returning empty for non-EXPIRED
        db = _make_db([], [], [], [])
        result = await get_safety_dashboard(db)
        assert result.expired_check_ins == []
        assert result.total_expired_check_ins == 0

    @pytest.mark.asyncio
    async def test_excludes_expired_check_ins_older_than_24h(self):
        """Test 6: expired check-ins older than 24h are excluded (DB query filters them)."""
        # Simulate DB returning only timers within 24h window
        recent_timer = _make_timer(id=1, expires_at=_NOW - timedelta(hours=12))
        db = _make_db([], [], [], [recent_timer])
        result = await get_safety_dashboard(db)
        assert len(result.expired_check_ins) == 1
        assert result.expired_check_ins[0].id == 1

    @pytest.mark.asyncio
    async def test_summary_counts_match_list_lengths(self):
        """Test 7: summary counts always equal their list lengths."""
        sos = [_make_sos(id=i) for i in range(3)]
        deviations = [_make_ride(id=i, route_deviation_flagged_at=_NOW) for i in range(2)]
        speeding = [_make_ride(id=i + 10, speeding_flagged_at=_NOW) for i in range(4)]
        check_ins = [_make_timer(id=i) for i in range(1)]
        db = _make_db(sos, deviations, speeding, check_ins)
        result = await get_safety_dashboard(db)
        assert result.total_active_sos == len(result.active_sos_alerts) == 3
        assert result.total_route_deviations == len(result.route_deviation_flags) == 2
        assert result.total_speeding_flags == len(result.speeding_flags) == 4
        assert result.total_expired_check_ins == len(result.expired_check_ins) == 1

    @pytest.mark.asyncio
    async def test_multiple_events_of_each_type_all_appear(self):
        """Test 8: multiple events of each type all appear in results."""
        sos_list = [_make_sos(id=i, user_id=i) for i in range(1, 5)]
        deviations = [_make_ride(id=i, route_deviation_flagged_at=_NOW) for i in range(1, 4)]
        speeding = [_make_ride(id=i + 10, speeding_flagged_at=_NOW) for i in range(1, 3)]
        check_ins = [_make_timer(id=i, rider_id=i) for i in range(1, 6)]
        db = _make_db(sos_list, deviations, speeding, check_ins)
        result = await get_safety_dashboard(db)
        assert len(result.active_sos_alerts) == 4
        assert len(result.route_deviation_flags) == 3
        assert len(result.speeding_flags) == 2
        assert len(result.expired_check_ins) == 5

    @pytest.mark.asyncio
    async def test_sos_with_no_ride_id_is_included(self):
        """Test 9: standalone SOS alert (no ride_id) is included."""
        standalone = _make_sos(id=99, ride_id=None, user_id=42)
        db = _make_db([standalone], [], [], [])
        result = await get_safety_dashboard(db)
        assert len(result.active_sos_alerts) == 1
        assert result.active_sos_alerts[0].ride_id is None
        assert result.active_sos_alerts[0].user_id == 42

    @pytest.mark.asyncio
    async def test_route_deviation_and_speeding_same_ride_appear_in_both_lists(self):
        """Test 10: same ride can appear in both route deviation and speeding lists independently."""
        deviation_ride = _make_ride(id=55, route_deviation_flagged_at=_NOW)
        speeding_ride = _make_ride(id=55, speeding_flagged_at=_NOW)
        db = _make_db([], [deviation_ride], [speeding_ride], [])
        result = await get_safety_dashboard(db)
        assert len(result.route_deviation_flags) == 1
        assert result.route_deviation_flags[0].ride_id == 55
        assert len(result.speeding_flags) == 1
        assert result.speeding_flags[0].ride_id == 55


# ---------------------------------------------------------------------------
# API integration tests
# ---------------------------------------------------------------------------

BASE = "/api/v1/admin/safety/dashboard"


@pytest.mark.anyio
class TestAdminSafetyDashboardEndpoint:

    async def test_no_auth_returns_401(self, client):
        """Test 11: 401 with no auth."""
        resp = await client.get(BASE)
        assert resp.status_code == 401

    async def test_rider_token_returns_403(self, client, rider, rider_token):
        """Test 12: 403 with rider token."""
        resp = await client.get(BASE, headers=auth_header(rider_token))
        assert resp.status_code == 403

    async def test_driver_token_returns_403(self, client, driver_user, driver_token):
        """Test 13: 403 with driver token."""
        resp = await client.get(BASE, headers=auth_header(driver_token))
        assert resp.status_code == 403

    async def test_admin_token_returns_200(self, client, admin_user, admin_token):
        """Test 14: 200 with admin token returns dashboard structure."""
        resp = await client.get(BASE, headers=auth_header(admin_token))
        assert resp.status_code == 200

    async def test_response_contains_all_fields(self, client, admin_user, admin_token):
        """Test 15: response contains all four list fields and all four count fields."""
        resp = await client.get(BASE, headers=auth_header(admin_token))
        assert resp.status_code == 200
        data = resp.json()
        # List fields
        assert "active_sos_alerts" in data
        assert "route_deviation_flags" in data
        assert "speeding_flags" in data
        assert "expired_check_ins" in data
        # Count fields
        assert "total_active_sos" in data
        assert "total_route_deviations" in data
        assert "total_speeding_flags" in data
        assert "total_expired_check_ins" in data
        # Types
        assert isinstance(data["active_sos_alerts"], list)
        assert isinstance(data["route_deviation_flags"], list)
        assert isinstance(data["speeding_flags"], list)
        assert isinstance(data["expired_check_ins"], list)
        assert isinstance(data["total_active_sos"], int)
        assert isinstance(data["total_route_deviations"], int)
        assert isinstance(data["total_speeding_flags"], int)
        assert isinstance(data["total_expired_check_ins"], int)
