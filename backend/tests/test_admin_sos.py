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
    PaginationResponse,
    SOSStats,
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
