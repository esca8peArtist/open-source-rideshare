"""Unit tests for admin per-user safety history endpoints.

GET /admin/riders/{rider_id}/safety-history
GET /admin/drivers/{driver_id}/safety-history

Coverage
--------
Schemas
  - RiderSafetyHistoryEntry: all fields populated
  - RiderSafetyHistoryEntry: nullable fields default to None
  - RiderSafetyHistoryResponse: serializes correctly
  - DriverSafetyHistoryEntry: all fields populated
  - DriverSafetyHistoryResponse: serializes correctly

Rider safety history (admin_get_rider_safety_history)
  - Empty history (rider exists, no SOS alerts) -> total=0, items=[]
  - Single active SOS alert -> correct field mapping (created_at -> triggered_at)
  - Multiple alerts -> newest-first order
  - Status filter: active only
  - Status filter: resolved only
  - 404 when rider not found

Driver safety history (admin_get_driver_safety_history)
  - Empty history (driver exists, no panic alerts) -> total=0, items=[]
  - Single ACTIVE panic alert -> correct field mapping
  - Multiple alerts -> newest-first order and correct pagination
  - Status filter: ACTIVE only
  - Status filter: RESOLVED only
  - 404 when driver profile not found
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.schemas.admin import (
    DriverSafetyHistoryEntry,
    DriverSafetyHistoryResponse,
    RiderSafetyHistoryEntry,
    RiderSafetyHistoryResponse,
)

NOW = datetime(2026, 4, 18, 12, 0, 0, tzinfo=timezone.utc)
EARLIER = datetime(2026, 4, 17, 10, 0, 0, tzinfo=timezone.utc)
EARLIEST = datetime(2026, 4, 16, 8, 0, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_admin(admin_id=99):
    from app.models.user import User, UserRole
    a = MagicMock(spec=User)
    a.id = admin_id
    a.role = UserRole.ADMIN
    return a


def _make_user(user_id=1, role="rider"):
    from app.models.user import User
    u = MagicMock(spec=User)
    u.id = user_id
    u.role = role
    return u


def _make_driver_profile(profile_id=10):
    from app.models.driver import DriverProfile
    p = MagicMock(spec=DriverProfile)
    p.id = profile_id
    return p


def _make_sos_alert(
    alert_id=1,
    user_id=5,
    ride_id=None,
    status_value="active",
    lat=40.7128,
    lng=-74.0060,
    message="Help!",
    created_at=NOW,
    resolved_at=None,
    resolved_by=None,
    resolution_notes=None,
):
    from app.models.safety import SOSAlert, SOSStatus
    a = MagicMock(spec=SOSAlert)
    a.id = alert_id
    a.user_id = user_id
    a.ride_id = ride_id
    a.status = SOSStatus(status_value)
    a.latitude = lat
    a.longitude = lng
    a.message = message
    a.created_at = created_at
    a.resolved_at = resolved_at
    a.resolved_by = resolved_by
    a.resolution_notes = resolution_notes
    return a


def _make_panic_alert(
    alert_id="abc-123",
    driver_id=10,
    ride_id=7,
    rider_id=3,
    status="ACTIVE",
    triggered_at=NOW,
    location_lat=None,
    location_lng=None,
    resolved_at=None,
    resolved_by=None,
    resolution_notes=None,
):
    from app.schemas.driver_safety import DriverPanicAlertStatus
    return {
        "id": alert_id,
        "driver_id": driver_id,
        "ride_id": ride_id,
        "rider_id": rider_id,
        "status": DriverPanicAlertStatus(status),
        "triggered_at": triggered_at,
        "location_lat": location_lat,
        "location_lng": location_lng,
        "resolved_at": resolved_at,
        "resolved_by": resolved_by,
        "resolution_notes": resolution_notes,
    }


def _scalar_result(value):
    r = MagicMock()
    r.scalar.return_value = value
    r.scalar_one_or_none.return_value = value
    return r


def _scalars_result(items):
    scalars = MagicMock()
    scalars.all.return_value = items
    r = MagicMock()
    r.scalars.return_value = scalars
    return r


def _mock_db(side_effects):
    db = AsyncMock()
    db.execute = AsyncMock(side_effect=side_effects)
    return db


# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------

class TestSchemas:
    def test_rider_safety_history_entry_all_fields(self):
        entry = RiderSafetyHistoryEntry(
            id=1,
            ride_id=5,
            status="active",
            lat=40.7128,
            lng=-74.0060,
            message="I need help",
            triggered_at=NOW,
            resolved_at=None,
            resolved_by=None,
            resolution_notes=None,
        )
        assert entry.id == 1
        assert entry.ride_id == 5
        assert entry.status == "active"
        assert entry.lat == 40.7128
        assert entry.lng == -74.0060
        assert entry.message == "I need help"
        assert entry.triggered_at == NOW
        assert entry.resolved_at is None

    def test_rider_safety_history_entry_nullable_fields(self):
        entry = RiderSafetyHistoryEntry(
            id=2,
            ride_id=None,
            status="false_alarm",
            lat=None,
            lng=None,
            message=None,
            triggered_at=NOW,
            resolved_at=EARLIER,
            resolved_by=99,
            resolution_notes="User confirmed safe",
        )
        assert entry.ride_id is None
        assert entry.lat is None
        assert entry.lng is None
        assert entry.message is None
        assert entry.resolved_by == 99
        assert entry.resolution_notes == "User confirmed safe"

    def test_rider_safety_history_response_serializes(self):
        resp = RiderSafetyHistoryResponse(
            rider_id=5,
            total=1,
            items=[
                RiderSafetyHistoryEntry(
                    id=1,
                    ride_id=None,
                    status="active",
                    lat=None,
                    lng=None,
                    message=None,
                    triggered_at=NOW,
                    resolved_at=None,
                    resolved_by=None,
                    resolution_notes=None,
                )
            ],
        )
        data = resp.model_dump()
        assert data["rider_id"] == 5
        assert data["total"] == 1
        assert len(data["items"]) == 1

    def test_driver_safety_history_entry_all_fields(self):
        entry = DriverSafetyHistoryEntry(
            id="uuid-abc",
            ride_id=7,
            rider_id=3,
            status="ACTIVE",
            location_lat=40.7,
            location_lng=-74.0,
            triggered_at=NOW,
            resolved_at=None,
            resolved_by=None,
            resolution_notes=None,
        )
        assert entry.id == "uuid-abc"
        assert entry.ride_id == 7
        assert entry.rider_id == 3
        assert entry.status == "ACTIVE"
        assert entry.location_lat == 40.7

    def test_driver_safety_history_response_serializes(self):
        resp = DriverSafetyHistoryResponse(
            driver_id=10,
            total=0,
            items=[],
        )
        data = resp.model_dump()
        assert data["driver_id"] == 10
        assert data["total"] == 0
        assert data["items"] == []


# ---------------------------------------------------------------------------
# Rider safety history endpoint tests
# ---------------------------------------------------------------------------

class TestAdminGetRiderSafetyHistory:
    @pytest.mark.asyncio
    async def test_empty_history_rider_exists(self):
        from app.api.v1.admin import admin_get_rider_safety_history

        db = _mock_db([
            _scalar_result(_make_user(5)),   # rider lookup
            _scalar_result(0),               # count
            _scalars_result([]),             # alerts
        ])

        result = await admin_get_rider_safety_history(
            rider_id=5, skip=0, limit=50, status_filter=None,
            _admin=_make_admin(), db=db,
        )

        assert result.rider_id == 5
        assert result.total == 0
        assert result.items == []

    @pytest.mark.asyncio
    async def test_single_active_sos_alert(self):
        from app.api.v1.admin import admin_get_rider_safety_history

        alert = _make_sos_alert(
            alert_id=1, user_id=5, ride_id=7,
            status_value="active", lat=40.7, lng=-74.0,
            message="Help!", created_at=NOW,
        )

        db = _mock_db([
            _scalar_result(_make_user(5)),
            _scalar_result(1),
            _scalars_result([alert]),
        ])

        result = await admin_get_rider_safety_history(
            rider_id=5, skip=0, limit=50, status_filter=None,
            _admin=_make_admin(), db=db,
        )

        assert result.total == 1
        item = result.items[0]
        assert item.id == 1
        assert item.ride_id == 7
        assert item.status == "active"
        assert item.lat == 40.7
        assert item.lng == -74.0
        assert item.message == "Help!"
        # created_at should be mapped to triggered_at
        assert item.triggered_at == NOW
        assert item.resolved_at is None

    @pytest.mark.asyncio
    async def test_multiple_alerts_newest_first(self):
        from app.api.v1.admin import admin_get_rider_safety_history

        # DB returns newest-first (ORDER BY created_at DESC in query)
        alert_new = _make_sos_alert(alert_id=2, created_at=NOW)
        alert_old = _make_sos_alert(alert_id=1, created_at=EARLIER)

        db = _mock_db([
            _scalar_result(_make_user(5)),
            _scalar_result(2),
            _scalars_result([alert_new, alert_old]),
        ])

        result = await admin_get_rider_safety_history(
            rider_id=5, skip=0, limit=50, status_filter=None,
            _admin=_make_admin(), db=db,
        )

        assert result.total == 2
        assert result.items[0].id == 2
        assert result.items[1].id == 1

    @pytest.mark.asyncio
    async def test_status_filter_active(self):
        from app.api.v1.admin import admin_get_rider_safety_history

        alert = _make_sos_alert(alert_id=3, status_value="active")

        db = _mock_db([
            _scalar_result(_make_user(5)),
            _scalar_result(1),
            _scalars_result([alert]),
        ])

        result = await admin_get_rider_safety_history(
            rider_id=5, skip=0, limit=50, status_filter="active",
            _admin=_make_admin(), db=db,
        )

        assert result.total == 1
        assert result.items[0].status == "active"

    @pytest.mark.asyncio
    async def test_status_filter_resolved(self):
        from app.api.v1.admin import admin_get_rider_safety_history

        alert = _make_sos_alert(
            alert_id=4, status_value="resolved",
            resolved_at=EARLIER, resolved_by=99,
            resolution_notes="All clear",
        )

        db = _mock_db([
            _scalar_result(_make_user(5)),
            _scalar_result(1),
            _scalars_result([alert]),
        ])

        result = await admin_get_rider_safety_history(
            rider_id=5, skip=0, limit=50, status_filter="resolved",
            _admin=_make_admin(), db=db,
        )

        assert result.total == 1
        item = result.items[0]
        assert item.status == "resolved"
        assert item.resolved_by == 99
        assert item.resolution_notes == "All clear"

    @pytest.mark.asyncio
    async def test_404_when_rider_not_found(self):
        from fastapi import HTTPException
        from app.api.v1.admin import admin_get_rider_safety_history

        db = _mock_db([
            _scalar_result(None),  # rider not found
        ])

        with pytest.raises(HTTPException) as exc_info:
            await admin_get_rider_safety_history(
                rider_id=999, skip=0, limit=50, status_filter=None,
                _admin=_make_admin(), db=db,
            )

        assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# Driver safety history endpoint tests
# ---------------------------------------------------------------------------

class TestAdminGetDriverSafetyHistory:
    @pytest.mark.asyncio
    async def test_empty_history_driver_exists(self):
        from app.api.v1.admin import admin_get_driver_safety_history

        db = _mock_db([
            _scalar_result(_make_driver_profile(10)),  # profile lookup
        ])

        with patch(
            "app.services.driver_safety.list_driver_panic_alerts",
            new=AsyncMock(return_value=[]),
        ):
            result = await admin_get_driver_safety_history(
                driver_id=10, skip=0, limit=50, status_filter=None,
                _admin=_make_admin(), db=db,
            )

        assert result.driver_id == 10
        assert result.total == 0
        assert result.items == []

    @pytest.mark.asyncio
    async def test_single_active_panic_alert(self):
        from app.api.v1.admin import admin_get_driver_safety_history

        alert = _make_panic_alert(
            alert_id="uuid-1", driver_id=10, ride_id=7, rider_id=3,
            status="ACTIVE", triggered_at=NOW,
            location_lat=40.7, location_lng=-74.0,
        )

        db = _mock_db([
            _scalar_result(_make_driver_profile(10)),
        ])

        with patch(
            "app.services.driver_safety.list_driver_panic_alerts",
            new=AsyncMock(return_value=[alert]),
        ):
            result = await admin_get_driver_safety_history(
                driver_id=10, skip=0, limit=50, status_filter=None,
                _admin=_make_admin(), db=db,
            )

        assert result.total == 1
        item = result.items[0]
        assert item.id == "uuid-1"
        assert item.ride_id == 7
        assert item.rider_id == 3
        assert item.status == "ACTIVE"
        assert item.location_lat == 40.7
        assert item.location_lng == -74.0
        assert item.triggered_at == NOW
        assert item.resolved_at is None

    @pytest.mark.asyncio
    async def test_multiple_alerts_pagination(self):
        from app.api.v1.admin import admin_get_driver_safety_history

        alerts = [
            _make_panic_alert(alert_id=f"uuid-{i}", driver_id=10, ride_id=i, rider_id=3, triggered_at=NOW - timedelta(hours=i))
            for i in range(5)
        ]

        db = _mock_db([
            _scalar_result(_make_driver_profile(10)),
        ])

        with patch(
            "app.services.driver_safety.list_driver_panic_alerts",
            new=AsyncMock(return_value=alerts),
        ):
            result = await admin_get_driver_safety_history(
                driver_id=10, skip=0, limit=3, status_filter=None,
                _admin=_make_admin(), db=db,
            )

        # Total reflects all alerts, items is limited to page size
        assert result.total == 5
        assert len(result.items) == 3
        assert result.items[0].id == "uuid-0"

    @pytest.mark.asyncio
    async def test_status_filter_active_only(self):
        from app.api.v1.admin import admin_get_driver_safety_history
        from app.schemas.driver_safety import DriverPanicAlertStatus

        alerts = [
            _make_panic_alert(alert_id="a1", status="ACTIVE", triggered_at=NOW),
            _make_panic_alert(alert_id="a2", status="RESOLVED", triggered_at=EARLIER,
                              resolved_at=EARLIER, resolved_by=99),
            _make_panic_alert(alert_id="a3", status="FALSE_ALARM", triggered_at=EARLIEST),
        ]

        db = _mock_db([
            _scalar_result(_make_driver_profile(10)),
        ])

        with patch(
            "app.services.driver_safety.list_driver_panic_alerts",
            new=AsyncMock(return_value=alerts),
        ):
            result = await admin_get_driver_safety_history(
                driver_id=10, skip=0, limit=50, status_filter="ACTIVE",
                _admin=_make_admin(), db=db,
            )

        assert result.total == 1
        assert result.items[0].id == "a1"
        assert result.items[0].status == "ACTIVE"

    @pytest.mark.asyncio
    async def test_status_filter_resolved(self):
        from app.api.v1.admin import admin_get_driver_safety_history

        alerts = [
            _make_panic_alert(alert_id="r1", status="RESOLVED", triggered_at=EARLIER,
                              resolved_at=EARLIER, resolved_by=99, resolution_notes="Handled"),
            _make_panic_alert(alert_id="a1", status="ACTIVE", triggered_at=NOW),
        ]

        db = _mock_db([
            _scalar_result(_make_driver_profile(10)),
        ])

        with patch(
            "app.services.driver_safety.list_driver_panic_alerts",
            new=AsyncMock(return_value=alerts),
        ):
            result = await admin_get_driver_safety_history(
                driver_id=10, skip=0, limit=50, status_filter="RESOLVED",
                _admin=_make_admin(), db=db,
            )

        assert result.total == 1
        item = result.items[0]
        assert item.id == "r1"
        assert item.status == "RESOLVED"
        assert item.resolved_by == 99
        assert item.resolution_notes == "Handled"

    @pytest.mark.asyncio
    async def test_404_when_driver_not_found(self):
        from fastapi import HTTPException
        from app.api.v1.admin import admin_get_driver_safety_history

        db = _mock_db([
            _scalar_result(None),  # driver profile not found
        ])

        with patch(
            "app.services.driver_safety.list_driver_panic_alerts",
            new=AsyncMock(return_value=[]),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await admin_get_driver_safety_history(
                    driver_id=999, skip=0, limit=50, status_filter=None,
                    _admin=_make_admin(), db=db,
                )

        assert exc_info.value.status_code == 404
