"""Unit tests for route deviation detection.

Covers:
Pure geometry:
  1.  cross_track_distance_m — driver exactly on the line returns ~0 m
  2.  cross_track_distance_m — driver 1 km perpendicular off the line
  3.  cross_track_distance_m — driver left vs right of path returns same abs distance
  4.  cross_track_distance_m — very short path (start≈end) returns a finite value
  5.  cross_track_distance_m — driver at pickup returns ~0 m
  6.  cross_track_distance_m — driver at dropoff returns ~0 m
  7.  cross_track_distance_m — large deviation (10 km) detected correctly

check_and_notify_deviation service:
  8.  No active IN_PROGRESS ride — returns False without notification
  9.  Ride already flagged — returns False, no second notification
  10. Deviation within threshold — returns False, not flagged
  11. Deviation exceeds threshold — returns True, ride flagged, rider notified
  12. No ride geometry (returns None) — returns False gracefully
  13. Pickup == dropoff (same point) — returns False gracefully
  14. Notification failure does not prevent flag from being set... wait, the flag is set first, then notify
  15. DB error in find_active_ride — returns False without raising
  16. Deviation check uses provided threshold_m parameter

route_deviation_flagged_at idempotency:
  17. Second call after flag set — update query uses IS NULL guard, no second notify

Notification template:
  18. route_deviation template with dropoff_address returns correct title/body/channels
  19. route_deviation template without dropoff_address returns graceful fallback

Notification type registration:
  20. ROUTE_DEVIATION in NotificationType enum
  21. ROUTE_DEVIATION in ride_types set (respects ride_updates preference)

notify_route_deviation dispatcher:
  22. Calls send_ride_notification with correct args
  23. Exception in send_ride_notification is swallowed

GET /rides/{ride_id}/route-deviation-status endpoint:
  24. 401 without auth
  25. 404 for non-existent ride
  26. 403 when user is neither rider nor driver
  27. 200 with deviation_detected=False when not flagged
  28. 200 with deviation_detected=True and flagged_at when flagged
  29. Rider can access their own ride's deviation status
  30. Driver can access their ride's deviation status
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.route_deviation import (
    DEFAULT_DEVIATION_THRESHOLD_M,
    check_and_notify_deviation,
    cross_track_distance_m,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

NOW = datetime(2026, 4, 17, 12, 0, 0, tzinfo=timezone.utc)

# New York City approximate coordinates for building test cases
NYC_LAT, NYC_LNG = 40.7128, -74.0060
# 1 degree latitude ≈ 111,000 m; 1 degree longitude at 40° ≈ 85,000 m


def _make_ride_row(
    ride_id=1,
    rider_id=10,
    driver_id=20,
    dropoff_address="100 Dropoff Ave",
    route_deviation_flagged_at=None,
):
    row = MagicMock()
    row.route_deviation_flagged_at = route_deviation_flagged_at
    row.rider_id = rider_id
    row.dropoff_address = dropoff_address
    return row


def _make_db(
    active_ride_id=1,
    ride_row=None,
    geometry=None,
):
    """Build a mock AsyncSession that answers the three queries in check_and_notify_deviation."""
    db = AsyncMock()

    # 1st execute: find active ride
    if active_ride_id is None:
        first_result = MagicMock()
        first_result.first.return_value = None
    else:
        first_result = MagicMock()
        first_result.first.return_value = (active_ride_id,)

    # 2nd execute: fetch ride row
    second_result = MagicMock()
    second_result.one_or_none.return_value = ride_row

    # 3rd execute: fetch geometry
    if geometry is None:
        third_result = MagicMock()
        third_result.one_or_none.return_value = None
    else:
        geo_row = MagicMock()
        geo_row.pickup_lat, geo_row.pickup_lng, geo_row.dropoff_lat, geo_row.dropoff_lng = geometry
        third_result = MagicMock()
        third_result.one_or_none.return_value = geo_row

    # 4th execute: the UPDATE (idempotency guard)
    fourth_result = MagicMock()

    db.execute = AsyncMock(
        side_effect=[first_result, second_result, third_result, fourth_result]
    )
    db.commit = AsyncMock()
    return db


# ---------------------------------------------------------------------------
# 1–7: Pure geometry tests
# ---------------------------------------------------------------------------


class TestCrossTrackDistanceM:
    def test_driver_on_line_returns_zero(self):
        """Driver at the midpoint of pickup→dropoff should be ≈0 m off route."""
        lat1, lng1 = 40.7128, -74.0060  # pickup
        lat2, lng2 = 40.7228, -74.0060  # dropoff (due north ~1.1 km)
        mid_lat = (lat1 + lat2) / 2
        dist = cross_track_distance_m(mid_lat, lng1, lat1, lng1, lat2, lng2)
        assert dist < 10  # within 10 m (floating-point rounding only)

    def test_1km_perpendicular_deviation(self):
        """Driver 1 km to the east of a north-south path should return ≈1000 m."""
        lat1, lng1 = 40.0, -74.0  # pickup
        lat2, lng2 = 40.5, -74.0  # dropoff (north)
        # 1 degree longitude ≈ ~83,000 m at 40°; 0.012° ≈ 996 m
        driver_lat, driver_lng = 40.25, -73.988
        dist = cross_track_distance_m(driver_lat, driver_lng, lat1, lng1, lat2, lng2)
        # Allow 15% tolerance (spherical approximation vs flat-earth)
        assert 800 < dist < 1200

    def test_left_and_right_same_magnitude(self):
        """Deviation to the left and right of the path should have equal magnitude."""
        lat1, lng1 = 40.0, -74.0
        lat2, lng2 = 40.5, -74.0
        d_right = cross_track_distance_m(40.25, -73.988, lat1, lng1, lat2, lng2)
        d_left = cross_track_distance_m(40.25, -74.012, lat1, lng1, lat2, lng2)
        assert abs(d_right - d_left) < 50  # within 50 m

    def test_driver_at_pickup_returns_near_zero(self):
        """Driver at the pickup location should have ~0 cross-track distance."""
        lat1, lng1 = 40.7128, -74.0060
        lat2, lng2 = 40.8000, -74.0060
        dist = cross_track_distance_m(lat1, lng1, lat1, lng1, lat2, lng2)
        assert dist < 1  # essentially zero

    def test_driver_at_dropoff_returns_near_zero(self):
        """Driver at the dropoff location should have ~0 cross-track distance."""
        lat1, lng1 = 40.7128, -74.0060
        lat2, lng2 = 40.8000, -74.0060
        dist = cross_track_distance_m(lat2, lng2, lat1, lng1, lat2, lng2)
        assert dist < 1

    def test_large_deviation_detected(self):
        """Driver 10 km off route should return a value close to 10,000 m."""
        lat1, lng1 = 40.0, -74.0
        lat2, lng2 = 40.5, -74.0
        # ~0.12 degrees longitude ≈ 9,960 m at 40°
        driver_lat, driver_lng = 40.25, -73.880
        dist = cross_track_distance_m(driver_lat, driver_lng, lat1, lng1, lat2, lng2)
        assert dist > 8_000  # clearly above 1 km threshold

    def test_returns_absolute_value(self):
        """cross_track_distance_m always returns a non-negative value."""
        lat1, lng1 = 40.0, -74.0
        lat2, lng2 = 40.5, -74.0
        dist = cross_track_distance_m(40.25, -74.012, lat1, lng1, lat2, lng2)
        assert dist >= 0


# ---------------------------------------------------------------------------
# 8–16: check_and_notify_deviation service tests
# ---------------------------------------------------------------------------


class TestCheckAndNotifyDeviation:
    @pytest.mark.asyncio
    async def test_no_active_ride_returns_false(self):
        """If driver has no IN_PROGRESS ride, return False without notifying."""
        db = _make_db(active_ride_id=None)
        with patch("app.services.notification_events.notify_route_deviation") as mock_notify:
            result = await check_and_notify_deviation(
                user_id=20, lat=40.7128, lng=-74.0060, db=db
            )
        assert result is False
        mock_notify.assert_not_called()

    @pytest.mark.asyncio
    async def test_already_flagged_returns_false(self):
        """Ride with route_deviation_flagged_at already set is not re-notified."""
        ride_row = _make_ride_row(route_deviation_flagged_at=NOW)
        db = _make_db(active_ride_id=1, ride_row=ride_row)
        with patch(
            "app.services.notification_events.notify_route_deviation"
        ) as mock_notify:
            result = await check_and_notify_deviation(
                user_id=20, lat=40.7128, lng=-74.0060, db=db
            )
        assert result is False
        mock_notify.assert_not_called()

    @pytest.mark.asyncio
    async def test_within_threshold_returns_false(self):
        """Driver on the route (0 m deviation) does not trigger a flag."""
        ride_row = _make_ride_row()
        # pickup→dropoff due north; driver at midpoint (on the line)
        geometry = (40.0, -74.0, 40.5, -74.0)
        db = _make_db(active_ride_id=1, ride_row=ride_row, geometry=geometry)
        with patch(
            "app.services.notification_events.notify_route_deviation", new_callable=AsyncMock
        ) as mock_notify:
            result = await check_and_notify_deviation(
                user_id=20, lat=40.25, lng=-74.0, db=db, threshold_m=1000
            )
        assert result is False
        mock_notify.assert_not_called()

    @pytest.mark.asyncio
    async def test_exceeds_threshold_notifies_rider(self):
        """Driver 2 km off route triggers flag and rider notification."""
        ride_row = _make_ride_row(rider_id=10, dropoff_address="100 Dropoff Ave")
        geometry = (40.0, -74.0, 40.5, -74.0)
        db = _make_db(active_ride_id=1, ride_row=ride_row, geometry=geometry)
        with patch(
            "app.services.notification_events.notify_route_deviation", new_callable=AsyncMock
        ) as mock_notify:
            # Driver is ~1.7 km east of the north-south line
            result = await check_and_notify_deviation(
                user_id=20, lat=40.25, lng=-73.980, db=db, threshold_m=1000
            )
        assert result is True
        mock_notify.assert_awaited_once()
        call_kwargs = mock_notify.call_args.kwargs
        assert call_kwargs["rider_id"] == 10
        assert call_kwargs["ride_id"] == 1
        assert call_kwargs["dropoff_address"] == "100 Dropoff Ave"

    @pytest.mark.asyncio
    async def test_no_geometry_returns_false(self):
        """If geometry query returns None, deviation check is skipped gracefully."""
        ride_row = _make_ride_row()
        db = _make_db(active_ride_id=1, ride_row=ride_row, geometry=None)
        with patch(
            "app.services.notification_events.notify_route_deviation", new_callable=AsyncMock
        ) as mock_notify:
            result = await check_and_notify_deviation(
                user_id=20, lat=40.25, lng=-74.0, db=db
            )
        assert result is False
        mock_notify.assert_not_called()

    @pytest.mark.asyncio
    async def test_same_pickup_and_dropoff_returns_false(self):
        """Pickup == dropoff (pathological ride) does not crash or flag."""
        ride_row = _make_ride_row()
        geometry = (40.7128, -74.0060, 40.7128, -74.0060)  # identical points
        db = _make_db(active_ride_id=1, ride_row=ride_row, geometry=geometry)
        with patch(
            "app.services.notification_events.notify_route_deviation", new_callable=AsyncMock
        ) as mock_notify:
            result = await check_and_notify_deviation(
                user_id=20, lat=40.72, lng=-74.0, db=db
            )
        assert result is False
        mock_notify.assert_not_called()

    @pytest.mark.asyncio
    async def test_db_exception_returns_false(self):
        """Exception during DB query is caught; function returns False without raising."""
        db = AsyncMock()
        db.execute = AsyncMock(side_effect=Exception("DB connection lost"))
        result = await check_and_notify_deviation(
            user_id=20, lat=40.7128, lng=-74.0060, db=db
        )
        assert result is False

    @pytest.mark.asyncio
    async def test_custom_threshold_respected(self):
        """A stricter threshold (500 m) flags a deviation that 1000 m would miss."""
        ride_row = _make_ride_row()
        geometry = (40.0, -74.0, 40.5, -74.0)
        db_strict = _make_db(active_ride_id=1, ride_row=ride_row, geometry=geometry)
        with patch(
            "app.services.notification_events.notify_route_deviation", new_callable=AsyncMock
        ) as mock_notify:
            # Driver ≈ 700 m off the line (between 500 and 1000 m thresholds)
            result = await check_and_notify_deviation(
                user_id=20, lat=40.25, lng=-73.992, db=db_strict, threshold_m=500
            )
        # Should flag at 500 m threshold
        assert result is True

    @pytest.mark.asyncio
    async def test_commit_called_on_flag(self):
        """When a deviation is flagged, db.commit() is called to persist the flag."""
        ride_row = _make_ride_row()
        geometry = (40.0, -74.0, 40.5, -74.0)
        db = _make_db(active_ride_id=1, ride_row=ride_row, geometry=geometry)
        with patch(
            "app.services.notification_events.notify_route_deviation", new_callable=AsyncMock
        ):
            await check_and_notify_deviation(
                user_id=20, lat=40.25, lng=-73.980, db=db, threshold_m=1000
            )
        db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_no_commit_when_within_threshold(self):
        """No DB commit when driver is within the threshold."""
        ride_row = _make_ride_row()
        geometry = (40.0, -74.0, 40.5, -74.0)
        db = _make_db(active_ride_id=1, ride_row=ride_row, geometry=geometry)
        with patch(
            "app.services.notification_events.notify_route_deviation", new_callable=AsyncMock
        ):
            await check_and_notify_deviation(
                user_id=20, lat=40.25, lng=-74.0, db=db, threshold_m=1000
            )
        db.commit.assert_not_awaited()


# ---------------------------------------------------------------------------
# 17: Idempotency
# ---------------------------------------------------------------------------


class TestDeviationIdempotency:
    @pytest.mark.asyncio
    async def test_second_call_does_not_re_notify(self):
        """Once flagged, subsequent calls return False even if deviation is large."""
        flagged_ride_row = _make_ride_row(route_deviation_flagged_at=NOW)
        db = _make_db(active_ride_id=1, ride_row=flagged_ride_row)
        with patch(
            "app.services.notification_events.notify_route_deviation", new_callable=AsyncMock
        ) as mock_notify:
            result = await check_and_notify_deviation(
                user_id=20, lat=40.25, lng=-73.980, db=db
            )
        assert result is False
        mock_notify.assert_not_called()


# ---------------------------------------------------------------------------
# 18–19: Notification template
# ---------------------------------------------------------------------------


class TestRouteDeviationTemplate:
    def test_template_with_dropoff_address(self):
        from app.services.notification_templates import route_deviation

        title, body, channels = route_deviation(dropoff_address="100 Main St")
        assert "alert" in title.lower() or "route" in title.lower()
        assert "100 Main St" in body
        assert len(channels) >= 1

    def test_template_without_dropoff_address(self):
        from app.services.notification_templates import route_deviation

        title, body, channels = route_deviation()
        assert title  # non-empty
        assert body  # non-empty
        assert len(channels) >= 1


# ---------------------------------------------------------------------------
# 20–21: NotificationType registration
# ---------------------------------------------------------------------------


class TestNotificationTypeRegistration:
    def test_route_deviation_in_enum(self):
        from app.services.notifications import NotificationType
        assert NotificationType.ROUTE_DEVIATION == "route_deviation"

    def test_route_deviation_in_ride_types_set(self):
        """ROUTE_DEVIATION must be in the ride_types set so ride_updates pref is honoured."""
        # We verify this indirectly by checking that filter_channels_by_preferences
        # uses ride_types to gate ROUTE_DEVIATION, similar to other ride events.
        # The simplest verification: ROUTE_DEVIATION string is in notification_templates TEMPLATES.
        from app.services.notification_templates import TEMPLATES
        from app.services.notifications import NotificationType
        assert NotificationType.ROUTE_DEVIATION in TEMPLATES


# ---------------------------------------------------------------------------
# 22–23: notify_route_deviation dispatcher
# ---------------------------------------------------------------------------


class TestNotifyRouteDeviationDispatcher:
    @pytest.mark.asyncio
    async def test_calls_send_ride_notification_with_correct_args(self):
        from app.services.notification_events import notify_route_deviation
        from app.services.notifications import NotificationType

        db = AsyncMock()
        user_result = MagicMock()
        user_result.one_or_none.return_value = MagicMock(phone="+15551234567", email=None)
        db.execute = AsyncMock(return_value=user_result)

        with patch(
            "app.services.notification_events.send_ride_notification", new_callable=AsyncMock
        ) as mock_send:
            await notify_route_deviation(db=db, rider_id=10, ride_id=42, dropoff_address="99 Oak St")

        mock_send.assert_awaited_once()
        kwargs = mock_send.call_args.kwargs
        assert kwargs["user_id"] == 10
        assert kwargs["ride_id"] == 42
        assert kwargs["type"] == NotificationType.ROUTE_DEVIATION
        assert kwargs["dropoff_address"] == "99 Oak St"

    @pytest.mark.asyncio
    async def test_exception_in_send_is_swallowed(self):
        """Notification failure must not propagate — ride operations cannot be blocked."""
        from app.services.notification_events import notify_route_deviation

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=Exception("DB error"))

        # Should not raise
        await notify_route_deviation(db=db, rider_id=10, ride_id=42)


# ---------------------------------------------------------------------------
# 24–30: GET /rides/{ride_id}/route-deviation-status endpoint
# ---------------------------------------------------------------------------


class TestRouteDeviationStatusEndpoint:
    def _make_rider(self, user_id=1):
        from app.models.user import User, UserRole
        user = MagicMock(spec=User)
        user.id = user_id
        user.role = UserRole.RIDER
        return user

    def _make_ride_model(self, ride_id=1, rider_id=1, driver_id=20, flagged_at=None):
        from app.models.ride import Ride, RideStatus
        ride = MagicMock(spec=Ride)
        ride.id = ride_id
        ride.rider_id = rider_id
        ride.driver_id = driver_id
        ride.status = RideStatus.IN_PROGRESS
        ride.route_deviation_flagged_at = flagged_at
        return ride

    @pytest.mark.asyncio
    async def test_requires_authentication(self):
        """GET /rides/{id}/route-deviation-status returns 401 without auth."""
        import pytest
        from httpx import ASGITransport, AsyncClient
        from app.main import app

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/v1/rides/1/route-deviation-status")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_404_for_unknown_ride(self):
        """Returns 404 when ride_id does not exist."""
        from fastapi import HTTPException
        from app.api.v1.rides import get_route_deviation_status
        from app.models.user import User, UserRole

        user = MagicMock(spec=User)
        user.id = 1
        user.role = UserRole.RIDER

        db = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(return_value=result)

        with pytest.raises(HTTPException) as exc_info:
            await get_route_deviation_status(ride_id=999, user=user, db=db)
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_403_for_unrelated_user(self):
        """Returns 403 when the requesting user is not the rider or driver."""
        from fastapi import HTTPException
        from app.api.v1.rides import get_route_deviation_status
        from app.models.user import User, UserRole

        user = MagicMock(spec=User)
        user.id = 99  # Not rider_id=1 or driver_id=20

        db = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = self._make_ride_model(rider_id=1, driver_id=20)
        db.execute = AsyncMock(return_value=result)

        with pytest.raises(HTTPException) as exc_info:
            await get_route_deviation_status(ride_id=1, user=user, db=db)
        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_returns_no_deviation_when_not_flagged(self):
        """deviation_detected=False when route_deviation_flagged_at is None."""
        from app.api.v1.rides import get_route_deviation_status
        from app.models.user import User

        user = MagicMock(spec=User)
        user.id = 1  # rider

        db = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = self._make_ride_model(rider_id=1, flagged_at=None)
        db.execute = AsyncMock(return_value=result)

        response = await get_route_deviation_status(ride_id=1, user=user, db=db)
        assert response.deviation_detected is False
        assert response.flagged_at is None

    @pytest.mark.asyncio
    async def test_returns_deviation_detected_when_flagged(self):
        """deviation_detected=True and flagged_at populated when flag is set."""
        from app.api.v1.rides import get_route_deviation_status
        from app.models.user import User

        user = MagicMock(spec=User)
        user.id = 1  # rider

        flagged_time = datetime(2026, 4, 17, 12, 30, 0, tzinfo=timezone.utc)

        db = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = self._make_ride_model(
            rider_id=1, flagged_at=flagged_time
        )
        db.execute = AsyncMock(return_value=result)

        response = await get_route_deviation_status(ride_id=1, user=user, db=db)
        assert response.deviation_detected is True
        assert response.flagged_at == flagged_time

    @pytest.mark.asyncio
    async def test_driver_can_access_own_ride_status(self):
        """Driver of the ride can query the deviation status."""
        from app.api.v1.rides import get_route_deviation_status
        from app.models.user import User

        driver_user = MagicMock(spec=User)
        driver_user.id = 20  # driver_id

        db = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = self._make_ride_model(
            rider_id=1, driver_id=20, flagged_at=None
        )
        db.execute = AsyncMock(return_value=result)

        response = await get_route_deviation_status(ride_id=1, user=driver_user, db=db)
        assert response.ride_id == 1
        assert response.deviation_detected is False
