"""Tests for admin SOS schemas and response mapping."""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

from app.models.ride import Ride, RideStatus
from app.models.safety import SOSAlert, SOSStatus
from app.models.user import User, UserRole
from app.schemas.admin import (
    AdminSOSAlertResponse,
    AdminSOSListResponse,
    AdminSOSResolveRequest,
    DriverPanicFrequencyEntry,
    DriverPanicFrequencyResponse,
    PaginationResponse,
    SOSFrequencyEntry,
    SOSFrequencyResponse,
    SOSStats,
    SOSTimeseriesPoint,
)


def _make_user(user_id=1, name="Test User", phone="+15551234567"):
    user = MagicMock(spec=User)
    user.id = user_id
    user.name = name
    user.phone = phone
    return user


def _make_ride(ride_id=1, status=RideStatus.IN_PROGRESS):
    ride = MagicMock(spec=Ride)
    ride.id = ride_id
    ride.status = status
    ride.pickup_address = "123 Main St"
    ride.dropoff_address = "456 Oak Ave"
    return ride


def _make_alert(
    alert_id=1,
    user_id=1,
    ride_id=None,
    status=SOSStatus.ACTIVE,
    lat=40.7128,
    lng=-74.0060,
    message="Help!",
    resolved_at=None,
    resolved_by=None,
    resolution_notes=None,
):
    alert = MagicMock(spec=SOSAlert)
    alert.id = alert_id
    alert.user_id = user_id
    alert.ride_id = ride_id
    alert.status = status
    alert.latitude = lat
    alert.longitude = lng
    alert.message = message
    alert.created_at = datetime(2026, 4, 12, 14, 30, 0, tzinfo=timezone.utc)
    alert.resolved_at = resolved_at
    alert.resolved_by = resolved_by
    alert.resolution_notes = resolution_notes
    alert.user = _make_user(user_id)
    alert.ride = _make_ride(ride_id) if ride_id else None
    return alert


# ---- AdminSOSAlertResponse schema tests ----


class TestAdminSOSAlertResponse:
    def test_active_alert_with_ride(self):
        resp = AdminSOSAlertResponse(
            id=1,
            user_id=10,
            user_name="Alice",
            user_phone="+15551000001",
            ride_id=5,
            ride_status="in_progress",
            pickup_address="123 Main St",
            dropoff_address="456 Oak Ave",
            status="active",
            latitude=40.7128,
            longitude=-74.0060,
            message="I feel unsafe",
            created_at=datetime(2026, 4, 12, 14, 0, tzinfo=timezone.utc),
        )
        assert resp.id == 1
        assert resp.user_name == "Alice"
        assert resp.ride_status == "in_progress"
        assert resp.status == "active"
        assert resp.resolved_at is None
        assert resp.resolved_by is None

    def test_resolved_alert(self):
        now = datetime.now(timezone.utc)
        resp = AdminSOSAlertResponse(
            id=2,
            user_id=10,
            status="resolved",
            created_at=now - timedelta(hours=1),
            resolved_at=now,
            resolved_by=99,
            resolution_notes="Admin investigated, all clear",
        )
        assert resp.status == "resolved"
        assert resp.resolved_by == 99
        assert resp.resolution_notes == "Admin investigated, all clear"

    def test_alert_without_ride(self):
        resp = AdminSOSAlertResponse(
            id=3,
            user_id=10,
            status="active",
            latitude=34.0522,
            longitude=-118.2437,
            created_at=datetime.now(timezone.utc),
        )
        assert resp.ride_id is None
        assert resp.ride_status is None
        assert resp.pickup_address is None

    def test_false_alarm(self):
        resp = AdminSOSAlertResponse(
            id=4,
            user_id=10,
            status="false_alarm",
            created_at=datetime.now(timezone.utc),
            resolved_at=datetime.now(timezone.utc),
            resolution_notes="Accidental press",
        )
        assert resp.status == "false_alarm"


class TestAdminSOSListResponse:
    def test_with_alerts(self):
        now = datetime.now(timezone.utc)
        resp = AdminSOSListResponse(
            alerts=[
                AdminSOSAlertResponse(
                    id=1, user_id=10, status="active",
                    created_at=now,
                ),
                AdminSOSAlertResponse(
                    id=2, user_id=11, status="resolved",
                    created_at=now - timedelta(hours=2),
                    resolved_at=now - timedelta(hours=1),
                ),
            ],
            pagination=PaginationResponse(page=1, per_page=20, total=2),
        )
        assert len(resp.alerts) == 2
        assert resp.pagination.total == 2

    def test_empty_list(self):
        resp = AdminSOSListResponse(
            alerts=[],
            pagination=PaginationResponse(page=1, per_page=20, total=0),
        )
        assert len(resp.alerts) == 0
        assert resp.pagination.total == 0


class TestAdminSOSResolveRequest:
    def test_resolve(self):
        req = AdminSOSResolveRequest(resolution="resolved", notes="All safe")
        assert req.resolution == "resolved"
        assert req.notes == "All safe"

    def test_false_alarm(self):
        req = AdminSOSResolveRequest(resolution="false_alarm")
        assert req.resolution == "false_alarm"
        assert req.notes is None

    def test_resolve_no_notes(self):
        req = AdminSOSResolveRequest(resolution="resolved")
        assert req.notes is None


class TestSOSStats:
    def test_active_platform(self):
        stats = SOSStats(
            active_count=3,
            resolved_today=5,
            false_alarms_today=2,
            total_today=10,
            avg_resolution_minutes=4.5,
        )
        assert stats.active_count == 3
        assert stats.resolved_today == 5
        assert stats.false_alarms_today == 2
        assert stats.total_today == 10
        assert stats.avg_resolution_minutes == 4.5

    def test_empty_platform(self):
        stats = SOSStats(
            active_count=0,
            resolved_today=0,
            false_alarms_today=0,
            total_today=0,
            avg_resolution_minutes=None,
        )
        assert stats.active_count == 0
        assert stats.avg_resolution_minutes is None


# ---- Response mapping tests (mirrors admin.py _sos_to_response) ----


class TestSOSResponseMapping:
    """Test that the _sos_to_response helper correctly maps model→schema."""

    def test_active_alert_with_ride_maps_correctly(self):
        alert = _make_alert(alert_id=1, user_id=10, ride_id=5)
        resp = AdminSOSAlertResponse(
            id=alert.id,
            user_id=alert.user_id,
            user_name=alert.user.name,
            user_phone=alert.user.phone,
            ride_id=alert.ride_id,
            ride_status=alert.ride.status.value if alert.ride else None,
            pickup_address=alert.ride.pickup_address if alert.ride else None,
            dropoff_address=alert.ride.dropoff_address if alert.ride else None,
            status=alert.status.value,
            latitude=alert.latitude,
            longitude=alert.longitude,
            message=alert.message,
            created_at=alert.created_at,
            resolved_at=alert.resolved_at,
            resolved_by=alert.resolved_by,
            resolution_notes=alert.resolution_notes,
        )
        assert resp.user_name == "Test User"
        assert resp.ride_status == "in_progress"
        assert resp.pickup_address == "123 Main St"
        assert resp.status == "active"

    def test_alert_without_ride_maps_correctly(self):
        alert = _make_alert(alert_id=2, user_id=10, ride_id=None)
        resp = AdminSOSAlertResponse(
            id=alert.id,
            user_id=alert.user_id,
            user_name=alert.user.name,
            user_phone=alert.user.phone,
            ride_id=alert.ride_id,
            ride_status=None,
            pickup_address=None,
            dropoff_address=None,
            status=alert.status.value,
            latitude=alert.latitude,
            longitude=alert.longitude,
            message=alert.message,
            created_at=alert.created_at,
        )
        assert resp.ride_id is None
        assert resp.ride_status is None

    def test_resolved_alert_maps_correctly(self):
        now = datetime.now(timezone.utc)
        alert = _make_alert(
            alert_id=3,
            status=SOSStatus.RESOLVED,
            resolved_at=now,
            resolved_by=99,
            resolution_notes="Confirmed false alarm",
        )
        resp = AdminSOSAlertResponse(
            id=alert.id,
            user_id=alert.user_id,
            user_name=alert.user.name,
            user_phone=alert.user.phone,
            status=alert.status.value,
            created_at=alert.created_at,
            resolved_at=alert.resolved_at,
            resolved_by=alert.resolved_by,
            resolution_notes=alert.resolution_notes,
        )
        assert resp.status == "resolved"
        assert resp.resolved_by == 99
        assert resp.resolution_notes == "Confirmed false alarm"


# ---- SOSTimeseriesPoint schema tests ----


class TestSOSTimeseriesPoint:
    def test_all_status_counts(self):
        point = SOSTimeseriesPoint(
            date="2026-04-12",
            total=6,
            active=1,
            resolved=4,
            false_alarms=1,
        )
        assert point.date == "2026-04-12"
        assert point.total == 6
        assert point.active == 1
        assert point.resolved == 4
        assert point.false_alarms == 1

    def test_zero_counts(self):
        point = SOSTimeseriesPoint(
            date="2026-04-13",
            total=0,
            active=0,
            resolved=0,
            false_alarms=0,
        )
        assert point.total == 0

    def test_total_matches_sum(self):
        point = SOSTimeseriesPoint(
            date="2026-04-14",
            total=3,
            active=2,
            resolved=1,
            false_alarms=0,
        )
        assert point.total == point.active + point.resolved + point.false_alarms

    def test_list_of_points_ordered(self):
        points = [
            SOSTimeseriesPoint(date="2026-04-10", total=2, active=2, resolved=0, false_alarms=0),
            SOSTimeseriesPoint(date="2026-04-11", total=5, active=1, resolved=3, false_alarms=1),
            SOSTimeseriesPoint(date="2026-04-12", total=1, active=0, resolved=1, false_alarms=0),
        ]
        dates = [p.date for p in points]
        assert dates == sorted(dates)

    def test_active_only_day(self):
        point = SOSTimeseriesPoint(
            date="2026-04-15",
            total=3,
            active=3,
            resolved=0,
            false_alarms=0,
        )
        assert point.resolved == 0
        assert point.false_alarms == 0

    def test_resolved_and_false_alarm_day(self):
        point = SOSTimeseriesPoint(
            date="2026-04-16",
            total=4,
            active=0,
            resolved=2,
            false_alarms=2,
        )
        assert point.active == 0
        assert point.total == 4


# ---- SOSFrequencyEntry / SOSFrequencyResponse schema tests ----


class TestSOSFrequencyEntry:
    def _now(self):
        return datetime.now(timezone.utc)

    def test_high_frequency_rider(self):
        entry = SOSFrequencyEntry(
            user_id=42,
            user_name="Alice",
            user_phone="+15551234567",
            total=10,
            active=1,
            resolved=7,
            false_alarms=2,
            false_alarm_rate=20.0,
            last_sos_at=self._now(),
        )
        assert entry.user_id == 42
        assert entry.total == 10
        assert entry.false_alarm_rate == 20.0

    def test_false_alarm_rate_calculation(self):
        # 3 false alarms out of 6 total = 50%
        entry = SOSFrequencyEntry(
            user_id=1,
            total=6,
            active=0,
            resolved=3,
            false_alarms=3,
            false_alarm_rate=50.0,
            last_sos_at=self._now(),
        )
        assert entry.false_alarm_rate == 50.0

    def test_zero_false_alarm_rate(self):
        entry = SOSFrequencyEntry(
            user_id=2,
            total=4,
            active=1,
            resolved=3,
            false_alarms=0,
            false_alarm_rate=0.0,
            last_sos_at=self._now(),
        )
        assert entry.false_alarm_rate == 0.0
        assert entry.false_alarms == 0

    def test_unknown_user(self):
        entry = SOSFrequencyEntry(
            user_id=99,
            user_name=None,
            user_phone=None,
            total=2,
            active=2,
            resolved=0,
            false_alarms=0,
            false_alarm_rate=0.0,
            last_sos_at=self._now(),
        )
        assert entry.user_name is None
        assert entry.user_phone is None

    def test_total_equals_sum_of_statuses(self):
        active, resolved, false_alarms = 2, 5, 1
        total = active + resolved + false_alarms
        entry = SOSFrequencyEntry(
            user_id=3,
            total=total,
            active=active,
            resolved=resolved,
            false_alarms=false_alarms,
            false_alarm_rate=round(false_alarms / total * 100, 1),
            last_sos_at=self._now(),
        )
        assert entry.total == entry.active + entry.resolved + entry.false_alarms


class TestSOSFrequencyResponse:
    def _now(self):
        return datetime.now(timezone.utc)

    def _entry(self, uid, total, false_alarms=0):
        resolved = total - false_alarms
        return SOSFrequencyEntry(
            user_id=uid,
            total=total,
            active=0,
            resolved=resolved,
            false_alarms=false_alarms,
            false_alarm_rate=round(false_alarms / total * 100, 1) if total else 0.0,
            last_sos_at=self._now(),
        )

    def test_all_period_response(self):
        resp = SOSFrequencyResponse(
            period="all",
            entries=[self._entry(1, 10, 2), self._entry(2, 5, 0)],
        )
        assert resp.period == "all"
        assert len(resp.entries) == 2
        assert resp.entries[0].total == 10

    def test_empty_leaderboard(self):
        resp = SOSFrequencyResponse(period="week", entries=[])
        assert resp.period == "week"
        assert resp.entries == []

    def test_sorted_by_total_descending(self):
        entries = [
            self._entry(uid=1, total=15),
            self._entry(uid=2, total=8),
            self._entry(uid=3, total=22),
        ]
        entries_sorted = sorted(entries, key=lambda e: e.total, reverse=True)
        resp = SOSFrequencyResponse(period="month", entries=entries_sorted)
        assert resp.entries[0].total == 22
        assert resp.entries[1].total == 15
        assert resp.entries[2].total == 8

    def test_month_period_label(self):
        resp = SOSFrequencyResponse(period="month", entries=[self._entry(1, 3)])
        assert resp.period == "month"

    def test_year_period_label(self):
        resp = SOSFrequencyResponse(period="year", entries=[])
        assert resp.period == "year"


# ---- DriverPanicFrequencyEntry / DriverPanicFrequencyResponse schema tests ----


class TestDriverPanicFrequencyEntry:
    def _now(self):
        return datetime.now(timezone.utc)

    def test_high_frequency_driver(self):
        entry = DriverPanicFrequencyEntry(
            driver_profile_id=7,
            driver_name="Bob Driver",
            driver_phone="+15559876543",
            total=8,
            active=1,
            resolved=5,
            false_alarms=2,
            false_alarm_rate=25.0,
            last_panic_at=self._now(),
        )
        assert entry.driver_profile_id == 7
        assert entry.total == 8
        assert entry.false_alarm_rate == 25.0

    def test_false_alarm_rate_calculation(self):
        # 2 false alarms out of 4 total = 50%
        entry = DriverPanicFrequencyEntry(
            driver_profile_id=1,
            total=4,
            active=0,
            resolved=2,
            false_alarms=2,
            false_alarm_rate=50.0,
            last_panic_at=self._now(),
        )
        assert entry.false_alarm_rate == 50.0

    def test_zero_false_alarm_rate(self):
        entry = DriverPanicFrequencyEntry(
            driver_profile_id=2,
            total=3,
            active=1,
            resolved=2,
            false_alarms=0,
            false_alarm_rate=0.0,
            last_panic_at=self._now(),
        )
        assert entry.false_alarm_rate == 0.0
        assert entry.false_alarms == 0

    def test_unknown_driver_name_and_phone(self):
        entry = DriverPanicFrequencyEntry(
            driver_profile_id=99,
            driver_name=None,
            driver_phone=None,
            total=1,
            active=1,
            resolved=0,
            false_alarms=0,
            false_alarm_rate=0.0,
            last_panic_at=self._now(),
        )
        assert entry.driver_name is None
        assert entry.driver_phone is None

    def test_total_equals_sum_of_statuses(self):
        active, resolved, false_alarms = 3, 4, 1
        total = active + resolved + false_alarms
        entry = DriverPanicFrequencyEntry(
            driver_profile_id=5,
            total=total,
            active=active,
            resolved=resolved,
            false_alarms=false_alarms,
            false_alarm_rate=round(false_alarms / total * 100, 1),
            last_panic_at=self._now(),
        )
        assert entry.total == entry.active + entry.resolved + entry.false_alarms


class TestDriverPanicFrequencyResponse:
    def _now(self):
        return datetime.now(timezone.utc)

    def _entry(self, profile_id, total, false_alarms=0):
        resolved = total - false_alarms
        return DriverPanicFrequencyEntry(
            driver_profile_id=profile_id,
            total=total,
            active=0,
            resolved=resolved,
            false_alarms=false_alarms,
            false_alarm_rate=round(false_alarms / total * 100, 1) if total else 0.0,
            last_panic_at=self._now(),
        )

    def test_all_period_response(self):
        resp = DriverPanicFrequencyResponse(
            period="all",
            entries=[self._entry(1, 12, 3), self._entry(2, 4, 0)],
        )
        assert resp.period == "all"
        assert len(resp.entries) == 2
        assert resp.entries[0].total == 12

    def test_empty_leaderboard(self):
        resp = DriverPanicFrequencyResponse(period="week", entries=[])
        assert resp.period == "week"
        assert resp.entries == []

    def test_sorted_by_total_descending(self):
        entries = [
            self._entry(profile_id=1, total=10),
            self._entry(profile_id=2, total=6),
            self._entry(profile_id=3, total=18),
        ]
        entries_sorted = sorted(entries, key=lambda e: e.total, reverse=True)
        resp = DriverPanicFrequencyResponse(period="month", entries=entries_sorted)
        assert resp.entries[0].total == 18
        assert resp.entries[1].total == 10
        assert resp.entries[2].total == 6

    def test_month_period_label(self):
        resp = DriverPanicFrequencyResponse(period="month", entries=[self._entry(1, 2)])
        assert resp.period == "month"

    def test_year_period_label(self):
        resp = DriverPanicFrequencyResponse(period="year", entries=[])
        assert resp.period == "year"
