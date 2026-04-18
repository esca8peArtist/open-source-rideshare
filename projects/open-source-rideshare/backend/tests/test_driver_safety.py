"""Tests for driver emergency safety features.

POST   /drivers/me/panic
GET    /drivers/me/panic/{alert_id}
DELETE /drivers/me/panic/{alert_id}
GET    /admin/driver-panic-alerts
POST   /admin/driver-panic-alerts/{alert_id}/resolve

Coverage
--------
Schemas
  - DriverPanicAlertStatus: ACTIVE, RESOLVED, FALSE_ALARM
  - TriggerDriverPanicRequest: valid with and without location
  - DriverPanicAlertResponse: all fields present
  - AdminResolveDriverPanicRequest: optional resolution_notes
  - DriverPanicAlertListResponse: total and items

Service: trigger_driver_panic
  - creates alert with ACTIVE status
  - stores ride_id, driver_id, rider_id correctly
  - stores optional lat/lng
  - assigns unique UUID ids
  - raises ValueError if ACTIVE alert already exists for ride
  - second alert on different ride succeeds

Service: get_driver_panic_alert
  - returns alert for correct owner
  - returns None for wrong owner (404 guard)
  - returns None for nonexistent id

Service: cancel_driver_panic_alert
  - within 30s -> FALSE_ALARM
  - after 30s -> RESOLVED
  - raises PermissionError for wrong owner
  - raises ValueError if alert not ACTIVE

Service: admin_list_active_driver_panic_alerts
  - empty when no alerts
  - only returns ACTIVE alerts (not RESOLVED/FALSE_ALARM)
  - sorted oldest-first
  - pagination skip and limit

Service: admin_resolve_driver_panic_alert
  - sets RESOLVED status
  - stores admin_id as resolved_by
  - stores resolution_notes
  - raises KeyError for nonexistent alert
  - raises ValueError if already resolved

Service: list_driver_panic_alerts
  - returns empty list for new driver
  - returns all alerts newest-first

Router: post_trigger_driver_panic
  - 400 when no active ride
  - 400 when service raises ValueError (duplicate)
  - 201 on success

Router: get_driver_panic_alert_endpoint
  - 404 when service returns None
  - 200 on success

Router: delete_cancel_driver_panic_alert
  - 404 when PermissionError
  - 400 when ValueError
  - 200 on success

Router: admin_get_active_driver_panic_alerts
  - returns DriverPanicAlertListResponse

Router: admin_post_resolve_driver_panic_alert
  - 404 on KeyError
  - 400 on ValueError
  - 200 on success

End-to-end: trigger -> admin_list shows it -> admin_resolve -> resolved
"""
from __future__ import annotations

import pytest
from datetime import datetime, timedelta, timezone
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch

from pydantic import ValidationError

from app.schemas.driver_safety import (
    AdminResolveDriverPanicRequest,
    DriverPanicAlertListResponse,
    DriverPanicAlertResponse,
    DriverPanicAlertStatus,
    TriggerDriverPanicRequest,
)
from app.services.driver_safety import (
    _reset_store,
    admin_list_active_driver_panic_alerts,
    admin_resolve_driver_panic_alert,
    cancel_driver_panic_alert,
    get_driver_panic_alert,
    list_driver_panic_alerts,
    trigger_driver_panic,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _utc_now() -> datetime:
    return datetime.now(tz=timezone.utc)


@pytest.fixture(autouse=True)
def reset_driver_safety_store():
    """Ensure a clean store for every test."""
    _reset_store()
    yield
    _reset_store()


def _mock_db() -> AsyncMock:
    return AsyncMock()


# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------


class TestDriverPanicAlertStatusEnum:
    def test_values(self):
        assert DriverPanicAlertStatus.ACTIVE == "ACTIVE"
        assert DriverPanicAlertStatus.RESOLVED == "RESOLVED"
        assert DriverPanicAlertStatus.FALSE_ALARM == "FALSE_ALARM"


class TestTriggerDriverPanicRequest:
    def test_valid_no_location(self):
        req = TriggerDriverPanicRequest()
        assert req.location_lat is None
        assert req.location_lng is None

    def test_valid_with_location(self):
        req = TriggerDriverPanicRequest(location_lat=40.7128, location_lng=-74.0060)
        assert req.location_lat == pytest.approx(40.7128)
        assert req.location_lng == pytest.approx(-74.0060)


class TestDriverPanicAlertResponse:
    def test_all_fields(self):
        now = _utc_now()
        resp = DriverPanicAlertResponse(
            id="abc-123",
            ride_id=10,
            driver_id=1,
            rider_id=2,
            triggered_at=now,
            location_lat=None,
            location_lng=None,
            status=DriverPanicAlertStatus.ACTIVE,
            resolved_at=None,
            resolved_by=None,
            resolution_notes=None,
        )
        assert resp.id == "abc-123"
        assert resp.ride_id == 10
        assert resp.driver_id == 1
        assert resp.rider_id == 2
        assert resp.status == DriverPanicAlertStatus.ACTIVE


class TestAdminResolveDriverPanicRequest:
    def test_optional_notes(self):
        req = AdminResolveDriverPanicRequest()
        assert req.resolution_notes is None

    def test_with_notes(self):
        req = AdminResolveDriverPanicRequest(resolution_notes="Handled by dispatch.")
        assert req.resolution_notes == "Handled by dispatch."

    def test_notes_max_length(self):
        with pytest.raises(ValidationError):
            AdminResolveDriverPanicRequest(resolution_notes="x" * 1001)


# ---------------------------------------------------------------------------
# Service: trigger_driver_panic
# ---------------------------------------------------------------------------


class TestTriggerDriverPanic:
    @pytest.mark.asyncio
    async def test_creates_active_alert(self):
        db = _mock_db()
        alert = await trigger_driver_panic(db, driver_id=1, ride_id=10, rider_id=2)
        assert alert["status"] == DriverPanicAlertStatus.ACTIVE
        assert alert["driver_id"] == 1
        assert alert["ride_id"] == 10
        assert alert["rider_id"] == 2

    @pytest.mark.asyncio
    async def test_stores_location(self):
        db = _mock_db()
        alert = await trigger_driver_panic(
            db, driver_id=1, ride_id=10, rider_id=2,
            location_lat=34.05, location_lng=-118.24,
        )
        assert alert["location_lat"] == pytest.approx(34.05)
        assert alert["location_lng"] == pytest.approx(-118.24)

    @pytest.mark.asyncio
    async def test_assigns_unique_ids(self):
        db = _mock_db()
        a1 = await trigger_driver_panic(db, driver_id=1, ride_id=10, rider_id=2)
        a2 = await trigger_driver_panic(db, driver_id=2, ride_id=11, rider_id=3)
        assert a1["id"] != a2["id"]

    @pytest.mark.asyncio
    async def test_raises_on_duplicate_active_alert_for_same_ride(self):
        db = _mock_db()
        await trigger_driver_panic(db, driver_id=1, ride_id=10, rider_id=2)
        with pytest.raises(ValueError, match="active driver panic alert"):
            await trigger_driver_panic(db, driver_id=1, ride_id=10, rider_id=2)

    @pytest.mark.asyncio
    async def test_second_alert_on_different_ride_succeeds(self):
        db = _mock_db()
        await trigger_driver_panic(db, driver_id=1, ride_id=10, rider_id=2)
        alert = await trigger_driver_panic(db, driver_id=2, ride_id=11, rider_id=3)
        assert alert["status"] == DriverPanicAlertStatus.ACTIVE


# ---------------------------------------------------------------------------
# Service: get_driver_panic_alert
# ---------------------------------------------------------------------------


class TestGetDriverPanicAlert:
    @pytest.mark.asyncio
    async def test_returns_alert_for_correct_owner(self):
        db = _mock_db()
        created = await trigger_driver_panic(db, driver_id=1, ride_id=10, rider_id=2)
        found = await get_driver_panic_alert(db, driver_id=1, alert_id=created["id"])
        assert found is not None
        assert found["id"] == created["id"]

    @pytest.mark.asyncio
    async def test_returns_none_for_wrong_owner(self):
        db = _mock_db()
        created = await trigger_driver_panic(db, driver_id=1, ride_id=10, rider_id=2)
        found = await get_driver_panic_alert(db, driver_id=99, alert_id=created["id"])
        assert found is None

    @pytest.mark.asyncio
    async def test_returns_none_for_nonexistent(self):
        db = _mock_db()
        found = await get_driver_panic_alert(db, driver_id=1, alert_id="does-not-exist")
        assert found is None


# ---------------------------------------------------------------------------
# Service: cancel_driver_panic_alert
# ---------------------------------------------------------------------------


class TestCancelDriverPanicAlert:
    @pytest.mark.asyncio
    async def test_cancel_within_30s_is_false_alarm(self):
        db = _mock_db()
        created = await trigger_driver_panic(db, driver_id=1, ride_id=10, rider_id=2)
        result = await cancel_driver_panic_alert(db, driver_id=1, alert_id=created["id"])
        assert result["status"] == DriverPanicAlertStatus.FALSE_ALARM
        assert result["resolved_at"] is not None

    @pytest.mark.asyncio
    async def test_cancel_after_30s_is_resolved(self):
        db = _mock_db()
        created = await trigger_driver_panic(db, driver_id=1, ride_id=10, rider_id=2)

        from app.services import driver_safety as svc
        past_time = _utc_now() - timedelta(seconds=60)
        svc._driver_panic_alerts[created["id"]]["triggered_at"] = past_time

        result = await cancel_driver_panic_alert(db, driver_id=1, alert_id=created["id"])
        assert result["status"] == DriverPanicAlertStatus.RESOLVED

    @pytest.mark.asyncio
    async def test_raises_permission_error_for_wrong_owner(self):
        db = _mock_db()
        created = await trigger_driver_panic(db, driver_id=1, ride_id=10, rider_id=2)
        with pytest.raises(PermissionError):
            await cancel_driver_panic_alert(db, driver_id=99, alert_id=created["id"])

    @pytest.mark.asyncio
    async def test_raises_value_error_if_not_active(self):
        db = _mock_db()
        created = await trigger_driver_panic(db, driver_id=1, ride_id=10, rider_id=2)
        await cancel_driver_panic_alert(db, driver_id=1, alert_id=created["id"])
        with pytest.raises(ValueError, match="Only ACTIVE alerts"):
            await cancel_driver_panic_alert(db, driver_id=1, alert_id=created["id"])


# ---------------------------------------------------------------------------
# Service: admin_list_active_driver_panic_alerts
# ---------------------------------------------------------------------------


class TestAdminListActiveDriverPanicAlerts:
    @pytest.mark.asyncio
    async def test_empty_when_no_alerts(self):
        db = _mock_db()
        total, items = await admin_list_active_driver_panic_alerts(db)
        assert total == 0
        assert items == []

    @pytest.mark.asyncio
    async def test_only_returns_active(self):
        db = _mock_db()
        created = await trigger_driver_panic(db, driver_id=1, ride_id=10, rider_id=2)
        await cancel_driver_panic_alert(db, driver_id=1, alert_id=created["id"])
        await trigger_driver_panic(db, driver_id=2, ride_id=11, rider_id=3)

        total, items = await admin_list_active_driver_panic_alerts(db)
        assert total == 1
        assert items[0]["driver_id"] == 2

    @pytest.mark.asyncio
    async def test_sorted_oldest_first(self):
        db = _mock_db()
        a1 = await trigger_driver_panic(db, driver_id=1, ride_id=10, rider_id=2)
        a2 = await trigger_driver_panic(db, driver_id=2, ride_id=11, rider_id=3)

        from app.services import driver_safety as svc
        svc._driver_panic_alerts[a1["id"]]["triggered_at"] = _utc_now() - timedelta(seconds=10)
        svc._driver_panic_alerts[a2["id"]]["triggered_at"] = _utc_now()

        _, items = await admin_list_active_driver_panic_alerts(db)
        assert items[0]["id"] == a1["id"]
        assert items[1]["id"] == a2["id"]

    @pytest.mark.asyncio
    async def test_pagination_skip_and_limit(self):
        db = _mock_db()
        for i in range(5):
            await trigger_driver_panic(db, driver_id=i + 1, ride_id=100 + i, rider_id=50 + i)

        total, page = await admin_list_active_driver_panic_alerts(db, skip=2, limit=2)
        assert total == 5
        assert len(page) == 2


# ---------------------------------------------------------------------------
# Service: admin_resolve_driver_panic_alert
# ---------------------------------------------------------------------------


class TestAdminResolveDriverPanicAlert:
    @pytest.mark.asyncio
    async def test_sets_resolved_status(self):
        db = _mock_db()
        created = await trigger_driver_panic(db, driver_id=1, ride_id=10, rider_id=2)
        result = await admin_resolve_driver_panic_alert(db, alert_id=created["id"], admin_id=99)
        assert result["status"] == DriverPanicAlertStatus.RESOLVED
        assert result["resolved_by"] == 99
        assert result["resolved_at"] is not None

    @pytest.mark.asyncio
    async def test_stores_resolution_notes(self):
        db = _mock_db()
        created = await trigger_driver_panic(db, driver_id=1, ride_id=10, rider_id=2)
        result = await admin_resolve_driver_panic_alert(
            db, alert_id=created["id"], admin_id=99, resolution_notes="Police dispatched."
        )
        assert result["resolution_notes"] == "Police dispatched."

    @pytest.mark.asyncio
    async def test_raises_key_error_for_nonexistent(self):
        db = _mock_db()
        with pytest.raises(KeyError):
            await admin_resolve_driver_panic_alert(db, alert_id="no-such-id", admin_id=99)

    @pytest.mark.asyncio
    async def test_raises_value_error_if_already_resolved(self):
        db = _mock_db()
        created = await trigger_driver_panic(db, driver_id=1, ride_id=10, rider_id=2)
        await admin_resolve_driver_panic_alert(db, alert_id=created["id"], admin_id=99)
        with pytest.raises(ValueError, match="Only ACTIVE alerts"):
            await admin_resolve_driver_panic_alert(db, alert_id=created["id"], admin_id=99)


# ---------------------------------------------------------------------------
# Service: list_driver_panic_alerts
# ---------------------------------------------------------------------------


class TestListDriverPanicAlerts:
    @pytest.mark.asyncio
    async def test_empty_for_new_driver(self):
        db = _mock_db()
        alerts = await list_driver_panic_alerts(db, driver_id=1)
        assert alerts == []

    @pytest.mark.asyncio
    async def test_returns_all_statuses_newest_first(self):
        db = _mock_db()
        a1 = await trigger_driver_panic(db, driver_id=1, ride_id=10, rider_id=2)
        a2 = await trigger_driver_panic(db, driver_id=1, ride_id=11, rider_id=3)

        from app.services import driver_safety as svc
        svc._driver_panic_alerts[a1["id"]]["triggered_at"] = _utc_now() - timedelta(seconds=5)
        svc._driver_panic_alerts[a2["id"]]["triggered_at"] = _utc_now()

        alerts = await list_driver_panic_alerts(db, driver_id=1)
        assert len(alerts) == 2
        assert alerts[0]["id"] == a2["id"]  # newest first

    @pytest.mark.asyncio
    async def test_only_returns_this_drivers_alerts(self):
        db = _mock_db()
        await trigger_driver_panic(db, driver_id=1, ride_id=10, rider_id=2)
        await trigger_driver_panic(db, driver_id=2, ride_id=11, rider_id=3)

        alerts = await list_driver_panic_alerts(db, driver_id=1)
        assert len(alerts) == 1
        assert alerts[0]["driver_id"] == 1


# ---------------------------------------------------------------------------
# Router tests
# ---------------------------------------------------------------------------


def _make_mock_ride(ride_id: int = 10, driver_id: int = 1, rider_id: int = 2):
    ride = MagicMock()
    ride.id = ride_id
    ride.driver_id = driver_id
    ride.rider_id = rider_id
    return ride


class TestPostTriggerDriverPanic:
    @pytest.mark.asyncio
    async def test_400_when_no_active_ride(self):
        from fastapi import HTTPException

        driver = MagicMock()
        driver.id = 1

        db = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none = MagicMock(return_value=None)
        db.execute = AsyncMock(return_value=result)

        from app.api.v1.driver_safety import post_trigger_driver_panic
        from app.schemas.driver_safety import TriggerDriverPanicRequest

        body = TriggerDriverPanicRequest()
        with pytest.raises(HTTPException) as exc_info:
            await post_trigger_driver_panic(body=body, driver=driver, db=db)
        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_400_when_duplicate_active_alert(self):
        from fastapi import HTTPException

        db = _mock_db()
        await trigger_driver_panic(db, driver_id=1, ride_id=10, rider_id=2)

        driver = MagicMock()
        driver.id = 1

        ride = _make_mock_ride(ride_id=10, driver_id=1, rider_id=2)
        mock_db = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none = MagicMock(return_value=ride)
        mock_db.execute = AsyncMock(return_value=result)

        from app.api.v1.driver_safety import post_trigger_driver_panic
        from app.schemas.driver_safety import TriggerDriverPanicRequest

        body = TriggerDriverPanicRequest()
        with pytest.raises(HTTPException) as exc_info:
            await post_trigger_driver_panic(body=body, driver=driver, db=mock_db)
        assert exc_info.value.status_code == 400


class TestGetDriverPanicAlertEndpoint:
    @pytest.mark.asyncio
    async def test_404_when_not_found(self):
        from fastapi.testclient import TestClient
        from app.main import app
        from app.api.deps import get_current_user
        from app.db.database import get_db

        driver = MagicMock()
        driver.id = 1
        mock_db = AsyncMock()

        app.dependency_overrides[get_current_user] = lambda: driver
        app.dependency_overrides[get_db] = lambda: mock_db

        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/api/v1/drivers/me/panic/nonexistent-id")
        assert resp.status_code == 404
        app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_200_when_found(self):
        db = _mock_db()
        created = await trigger_driver_panic(db, driver_id=1, ride_id=10, rider_id=2)

        from fastapi.testclient import TestClient
        from app.main import app
        from app.api.deps import get_current_user
        from app.db.database import get_db

        driver = MagicMock()
        driver.id = 1
        mock_db = AsyncMock()

        app.dependency_overrides[get_current_user] = lambda: driver
        app.dependency_overrides[get_db] = lambda: mock_db

        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get(f"/api/v1/drivers/me/panic/{created['id']}")
        assert resp.status_code == 200
        assert resp.json()["id"] == created["id"]
        app.dependency_overrides.clear()


class TestDeleteCancelDriverPanicAlert:
    @pytest.mark.asyncio
    async def test_404_on_permission_error(self):
        from fastapi.testclient import TestClient
        from app.main import app
        from app.api.deps import get_current_user
        from app.db.database import get_db

        driver = MagicMock()
        driver.id = 99
        mock_db = AsyncMock()

        app.dependency_overrides[get_current_user] = lambda: driver
        app.dependency_overrides[get_db] = lambda: mock_db

        client = TestClient(app, raise_server_exceptions=False)
        resp = client.delete("/api/v1/drivers/me/panic/nonexistent-id")
        assert resp.status_code == 404
        app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_400_on_value_error(self):
        db = _mock_db()
        created = await trigger_driver_panic(db, driver_id=1, ride_id=10, rider_id=2)
        await cancel_driver_panic_alert(db, driver_id=1, alert_id=created["id"])

        from fastapi.testclient import TestClient
        from app.main import app
        from app.api.deps import get_current_user
        from app.db.database import get_db

        driver = MagicMock()
        driver.id = 1
        mock_db = AsyncMock()

        app.dependency_overrides[get_current_user] = lambda: driver
        app.dependency_overrides[get_db] = lambda: mock_db

        client = TestClient(app, raise_server_exceptions=False)
        resp = client.delete(f"/api/v1/drivers/me/panic/{created['id']}")
        assert resp.status_code == 400
        app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_200_on_success(self):
        db = _mock_db()
        created = await trigger_driver_panic(db, driver_id=1, ride_id=10, rider_id=2)

        from fastapi.testclient import TestClient
        from app.main import app
        from app.api.deps import get_current_user
        from app.db.database import get_db

        driver = MagicMock()
        driver.id = 1
        mock_db = AsyncMock()

        app.dependency_overrides[get_current_user] = lambda: driver
        app.dependency_overrides[get_db] = lambda: mock_db

        client = TestClient(app, raise_server_exceptions=False)
        resp = client.delete(f"/api/v1/drivers/me/panic/{created['id']}")
        assert resp.status_code == 200
        app.dependency_overrides.clear()


class TestAdminGetActiveDriverPanicAlerts:
    @pytest.mark.asyncio
    async def test_returns_list_response(self):
        db = _mock_db()
        await trigger_driver_panic(db, driver_id=1, ride_id=10, rider_id=2)

        from fastapi.testclient import TestClient
        from app.main import app
        from app.api.deps import require_admin
        from app.db.database import get_db

        admin = MagicMock()
        admin.id = 99
        mock_db = AsyncMock()

        app.dependency_overrides[require_admin] = lambda: admin
        app.dependency_overrides[get_db] = lambda: mock_db

        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/api/v1/admin/driver-panic-alerts")
        assert resp.status_code == 200
        data = resp.json()
        assert "total" in data
        assert "items" in data
        assert data["total"] == 1
        app.dependency_overrides.clear()


class TestAdminPostResolveDriverPanicAlert:
    @pytest.mark.asyncio
    async def test_404_on_key_error(self):
        from fastapi.testclient import TestClient
        from app.main import app
        from app.api.deps import require_admin
        from app.db.database import get_db

        admin = MagicMock()
        admin.id = 99
        mock_db = AsyncMock()

        app.dependency_overrides[require_admin] = lambda: admin
        app.dependency_overrides[get_db] = lambda: mock_db

        client = TestClient(app, raise_server_exceptions=False)
        resp = client.post("/api/v1/admin/driver-panic-alerts/no-such-id/resolve", json={})
        assert resp.status_code == 404
        app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_400_on_value_error(self):
        db = _mock_db()
        created = await trigger_driver_panic(db, driver_id=1, ride_id=10, rider_id=2)
        await admin_resolve_driver_panic_alert(db, alert_id=created["id"], admin_id=99)

        from fastapi.testclient import TestClient
        from app.main import app
        from app.api.deps import require_admin
        from app.db.database import get_db

        admin = MagicMock()
        admin.id = 99
        mock_db = AsyncMock()

        app.dependency_overrides[require_admin] = lambda: admin
        app.dependency_overrides[get_db] = lambda: mock_db

        client = TestClient(app, raise_server_exceptions=False)
        resp = client.post(
            f"/api/v1/admin/driver-panic-alerts/{created['id']}/resolve",
            json={"resolution_notes": "Already done."},
        )
        assert resp.status_code == 400
        app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_200_on_success(self):
        db = _mock_db()
        created = await trigger_driver_panic(db, driver_id=1, ride_id=10, rider_id=2)

        from fastapi.testclient import TestClient
        from app.main import app
        from app.api.deps import require_admin
        from app.db.database import get_db

        admin = MagicMock()
        admin.id = 99
        mock_db = AsyncMock()

        app.dependency_overrides[require_admin] = lambda: admin
        app.dependency_overrides[get_db] = lambda: mock_db

        client = TestClient(app, raise_server_exceptions=False)
        resp = client.post(
            f"/api/v1/admin/driver-panic-alerts/{created['id']}/resolve",
            json={"resolution_notes": "Situation resolved."},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "RESOLVED"
        assert data["resolution_notes"] == "Situation resolved."
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# End-to-end flow
# ---------------------------------------------------------------------------


class TestEndToEndDriverPanicFlow:
    @pytest.mark.asyncio
    async def test_trigger_list_resolve(self):
        db = _mock_db()

        # Trigger
        created = await trigger_driver_panic(db, driver_id=1, ride_id=10, rider_id=2)
        assert created["status"] == DriverPanicAlertStatus.ACTIVE

        # Admin sees it
        total, items = await admin_list_active_driver_panic_alerts(db)
        assert total == 1
        assert items[0]["id"] == created["id"]

        # Admin resolves
        resolved = await admin_resolve_driver_panic_alert(
            db, alert_id=created["id"], admin_id=99, resolution_notes="All clear."
        )
        assert resolved["status"] == DriverPanicAlertStatus.RESOLVED
        assert resolved["resolved_by"] == 99

        # No longer in active list
        total, items = await admin_list_active_driver_panic_alerts(db)
        assert total == 0
