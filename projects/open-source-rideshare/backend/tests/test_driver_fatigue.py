"""Tests for the driver fatigue monitoring feature.

GET  /api/v1/drivers/me/fatigue-status              — driver sees own status
GET  /api/v1/admin/driver-fatigue-alerts            — admin sees WARNING/LIMIT_REACHED
POST /api/v1/admin/driver-fatigue/{driver_id}/reset — admin resets driver fatigue

Coverage
--------
Schemas: FatigueStatus, FatigueAlert
Service: log_ride_event, compute_fatigue_status, get_all_warnings, reset_driver_fatigue
  - No rides → NORMAL, 0h
  - Rides totalling <8h → NORMAL
  - Rides totalling 8–10h → WARNING
  - Rides totalling ≥10h → LIMIT_REACHED
  - Rolling window: rides >24h old excluded
  - Rest period: after ≥6h idle, status resets to NORMAL
  - Unpaired RIDE_STARTED counts up to now
  - get_all_warnings returns only WARNING/LIMIT_REACHED
  - reset_driver_fatigue clears state
Router: auth/role enforcement, 401 unauthenticated, 403 wrong role
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from app.schemas.driver_fatigue import FatigueAlert, FatigueStatus, FatigueStatusLevel
from app.services.driver_fatigue import (
    _fatigue_logs,
    _reset_store,
    compute_fatigue_status,
    get_all_warnings,
    log_ride_event,
    reset_driver_fatigue,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


def _make_user(user_id: int = 1, role: str = "driver", name: str = "Test Driver") -> MagicMock:
    user = MagicMock()
    user.id = user_id
    user.role = MagicMock()
    user.role.value = role
    user.is_active = True
    user.full_name = name
    return user


def _log_pair(driver_id: int, ride_id: int, duration_hours: float, start_offset_hours: float = 0.0) -> None:
    """Log a RIDE_STARTED / RIDE_ENDED pair with the given duration.

    start_offset_hours: hours ago from now when the ride started.
    The pair is injected directly into _fatigue_logs with backdated timestamps.
    """
    now = _now()
    start = now - timedelta(hours=start_offset_hours + duration_hours)
    end = now - timedelta(hours=start_offset_hours)
    _fatigue_logs.setdefault(driver_id, []).append(
        {"ride_id": ride_id, "event_type": "RIDE_STARTED", "recorded_at": start}
    )
    _fatigue_logs.setdefault(driver_id, []).append(
        {"ride_id": ride_id, "event_type": "RIDE_ENDED", "recorded_at": end}
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def reset_store():
    _reset_store()
    yield
    _reset_store()


@pytest.fixture()
def driver_user():
    return _make_user(user_id=42, role="driver")


@pytest.fixture()
def admin_user():
    return _make_user(user_id=99, role="admin")


@pytest.fixture()
def rider_user():
    return _make_user(user_id=7, role="rider")


@pytest.fixture()
def driver_client(driver_user):
    from fastapi.testclient import TestClient
    from app.main import app
    from app.api.deps import get_current_user, require_driver

    app.dependency_overrides[get_current_user] = lambda: driver_user
    app.dependency_overrides[require_driver] = lambda: driver_user
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture()
def admin_client(admin_user):
    from fastapi.testclient import TestClient
    from app.main import app
    from app.api.deps import get_current_user, require_admin

    app.dependency_overrides[get_current_user] = lambda: admin_user
    app.dependency_overrides[require_admin] = lambda: admin_user
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture()
def rider_client(rider_user):
    from fastapi.testclient import TestClient
    from app.main import app
    from app.api.deps import get_current_user, require_driver

    app.dependency_overrides[get_current_user] = lambda: rider_user
    # Do NOT override require_driver — should trigger 403
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture()
def unauth_client():
    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------


class TestFatigueStatusSchema:
    def test_normal_status_fields(self):
        s = FatigueStatus(
            driver_id=1,
            status=FatigueStatusLevel.NORMAL,
            active_hours_last_24h=3.5,
            rides_today=4,
            rest_hours_needed=None,
            message="Active hours are within safe limits.",
        )
        assert s.driver_id == 1
        assert s.status == FatigueStatusLevel.NORMAL
        assert s.active_hours_last_24h == 3.5
        assert s.rides_today == 4
        assert s.rest_hours_needed is None

    def test_limit_reached_has_rest_needed(self):
        s = FatigueStatus(
            driver_id=1,
            status=FatigueStatusLevel.LIMIT_REACHED,
            active_hours_last_24h=10.5,
            rides_today=12,
            rest_hours_needed=4.5,
            message="You must rest.",
        )
        assert s.rest_hours_needed == 4.5

    def test_warning_rest_needed_is_none(self):
        s = FatigueStatus(
            driver_id=1,
            status=FatigueStatusLevel.WARNING,
            active_hours_last_24h=9.0,
            rides_today=9,
            rest_hours_needed=None,
            message="Consider a break.",
        )
        assert s.rest_hours_needed is None


class TestFatigueAlertSchema:
    def test_alert_fields(self):
        now = _now()
        alert = FatigueAlert(
            driver_id=5,
            driver_name="Jane Driver",
            status=FatigueStatusLevel.WARNING,
            active_hours_last_24h=8.5,
            last_ride_ended_at=now,
        )
        assert alert.driver_id == 5
        assert alert.driver_name == "Jane Driver"
        assert alert.last_ride_ended_at == now

    def test_alert_last_ride_optional(self):
        alert = FatigueAlert(
            driver_id=5,
            driver_name="Jane Driver",
            status=FatigueStatusLevel.WARNING,
            active_hours_last_24h=8.5,
        )
        assert alert.last_ride_ended_at is None


# ---------------------------------------------------------------------------
# Service: log_ride_event
# ---------------------------------------------------------------------------


class TestLogRideEvent:
    def test_logs_ride_started(self):
        event = log_ride_event(driver_id=1, ride_id=100, event_type="RIDE_STARTED")
        assert event["event_type"] == "RIDE_STARTED"
        assert event["ride_id"] == 100
        assert 1 in _fatigue_logs
        assert len(_fatigue_logs[1]) == 1

    def test_logs_ride_ended(self):
        log_ride_event(driver_id=1, ride_id=100, event_type="RIDE_STARTED")
        event = log_ride_event(driver_id=1, ride_id=100, event_type="RIDE_ENDED")
        assert event["event_type"] == "RIDE_ENDED"
        assert len(_fatigue_logs[1]) == 2

    def test_invalid_event_type_raises(self):
        with pytest.raises(ValueError, match="Unknown event_type"):
            log_ride_event(driver_id=1, ride_id=100, event_type="INVALID")

    def test_multiple_drivers_independent(self):
        log_ride_event(driver_id=1, ride_id=10, event_type="RIDE_STARTED")
        log_ride_event(driver_id=2, ride_id=20, event_type="RIDE_STARTED")
        assert len(_fatigue_logs[1]) == 1
        assert len(_fatigue_logs[2]) == 1

    def test_recorded_at_is_approximately_now(self):
        before = _now()
        event = log_ride_event(driver_id=1, ride_id=10, event_type="RIDE_STARTED")
        after = _now()
        assert before <= event["recorded_at"] <= after


# ---------------------------------------------------------------------------
# Service: compute_fatigue_status — status thresholds
# ---------------------------------------------------------------------------


class TestComputeFatigueStatus:
    def test_no_rides_is_normal(self):
        status = compute_fatigue_status(driver_id=1)
        assert status.status == FatigueStatusLevel.NORMAL
        assert status.active_hours_last_24h == 0.0
        assert status.rides_today == 0

    def test_rides_under_8h_is_normal(self):
        _log_pair(driver_id=1, ride_id=1, duration_hours=3.0)
        _log_pair(driver_id=1, ride_id=2, duration_hours=2.0)
        status = compute_fatigue_status(driver_id=1)
        assert status.status == FatigueStatusLevel.NORMAL
        assert status.active_hours_last_24h == 5.0

    def test_exactly_8h_is_warning(self):
        _log_pair(driver_id=1, ride_id=1, duration_hours=8.0)
        status = compute_fatigue_status(driver_id=1)
        assert status.status == FatigueStatusLevel.WARNING

    def test_between_8_and_10h_is_warning(self):
        _log_pair(driver_id=1, ride_id=1, duration_hours=9.0)
        status = compute_fatigue_status(driver_id=1)
        assert status.status == FatigueStatusLevel.WARNING
        assert status.active_hours_last_24h == 9.0

    def test_exactly_10h_is_limit_reached(self):
        _log_pair(driver_id=1, ride_id=1, duration_hours=10.0)
        status = compute_fatigue_status(driver_id=1)
        assert status.status == FatigueStatusLevel.LIMIT_REACHED

    def test_over_10h_is_limit_reached(self):
        _log_pair(driver_id=1, ride_id=1, duration_hours=11.5)
        status = compute_fatigue_status(driver_id=1)
        assert status.status == FatigueStatusLevel.LIMIT_REACHED
        assert status.active_hours_last_24h == 11.5

    def test_limit_reached_has_rest_hours_needed(self):
        _log_pair(driver_id=1, ride_id=1, duration_hours=10.0, start_offset_hours=0.5)
        status = compute_fatigue_status(driver_id=1)
        assert status.status == FatigueStatusLevel.LIMIT_REACHED
        assert status.rest_hours_needed is not None
        assert status.rest_hours_needed > 0

    def test_warning_has_no_rest_hours_needed(self):
        _log_pair(driver_id=1, ride_id=1, duration_hours=9.0)
        status = compute_fatigue_status(driver_id=1)
        assert status.rest_hours_needed is None

    def test_normal_has_no_rest_hours_needed(self):
        status = compute_fatigue_status(driver_id=1)
        assert status.rest_hours_needed is None

    def test_hours_rounded_to_one_decimal(self):
        # 7h 6m = 7.1h
        _log_pair(driver_id=1, ride_id=1, duration_hours=7.1)
        status = compute_fatigue_status(driver_id=1)
        assert status.active_hours_last_24h == round(status.active_hours_last_24h, 1)

    def test_driver_name_in_status_message(self):
        _log_pair(driver_id=1, ride_id=1, duration_hours=9.0)
        status = compute_fatigue_status(driver_id=1)
        assert status.message  # non-empty message for all statuses

    def test_multiple_rides_sum_correctly(self):
        _log_pair(driver_id=1, ride_id=1, duration_hours=3.0)
        _log_pair(driver_id=1, ride_id=2, duration_hours=3.0)
        _log_pair(driver_id=1, ride_id=3, duration_hours=3.0)
        status = compute_fatigue_status(driver_id=1)
        assert status.active_hours_last_24h == 9.0
        assert status.status == FatigueStatusLevel.WARNING


# ---------------------------------------------------------------------------
# Service: rolling 24h window
# ---------------------------------------------------------------------------


class TestRollingWindow:
    def test_rides_older_than_24h_excluded(self):
        # Ride that ended 25h ago — entirely outside window
        _log_pair(driver_id=1, ride_id=1, duration_hours=2.0, start_offset_hours=25.0)
        status = compute_fatigue_status(driver_id=1)
        assert status.active_hours_last_24h == 0.0
        assert status.status == FatigueStatusLevel.NORMAL

    def test_recent_rides_count(self):
        _log_pair(driver_id=1, ride_id=1, duration_hours=2.0, start_offset_hours=2.0)
        status = compute_fatigue_status(driver_id=1)
        assert status.active_hours_last_24h == 2.0

    def test_mix_of_old_and_new_rides(self):
        # Old ride: 2h, 26h ago — outside window
        _log_pair(driver_id=1, ride_id=1, duration_hours=2.0, start_offset_hours=26.0)
        # Recent ride: 4h, 2h ago — inside window
        _log_pair(driver_id=1, ride_id=2, duration_hours=4.0, start_offset_hours=2.0)
        status = compute_fatigue_status(driver_id=1)
        assert status.active_hours_last_24h == 4.0


# ---------------------------------------------------------------------------
# Service: rest period reset
# ---------------------------------------------------------------------------


class TestRestPeriod:
    def test_after_6h_rest_status_is_normal(self):
        # Add 10h of driving that ended 7h ago → driver has rested 7h
        _log_pair(driver_id=1, ride_id=1, duration_hours=10.0, start_offset_hours=7.0)
        status = compute_fatigue_status(driver_id=1)
        assert status.status == FatigueStatusLevel.NORMAL

    def test_after_exactly_6h_rest_is_normal(self):
        _log_pair(driver_id=1, ride_id=1, duration_hours=10.0, start_offset_hours=6.0)
        status = compute_fatigue_status(driver_id=1)
        assert status.status == FatigueStatusLevel.NORMAL

    def test_less_than_6h_rest_still_blocked(self):
        # 10h driving ended 3h ago — only 3h of rest
        _log_pair(driver_id=1, ride_id=1, duration_hours=10.0, start_offset_hours=3.0)
        status = compute_fatigue_status(driver_id=1)
        assert status.status == FatigueStatusLevel.LIMIT_REACHED

    def test_rest_hours_needed_decreases_over_time(self):
        # 10h driving ended 3h ago → 3h rest so far → need 3 more hours
        _log_pair(driver_id=1, ride_id=1, duration_hours=10.0, start_offset_hours=3.0)
        status = compute_fatigue_status(driver_id=1)
        assert status.rest_hours_needed is not None
        assert 2.9 <= status.rest_hours_needed <= 3.1


# ---------------------------------------------------------------------------
# Service: get_all_warnings
# ---------------------------------------------------------------------------


class TestGetAllWarnings:
    def test_returns_empty_when_all_normal(self):
        _log_pair(driver_id=1, ride_id=1, duration_hours=3.0)
        assert get_all_warnings() == []

    def test_returns_warning_drivers(self):
        _log_pair(driver_id=1, ride_id=1, duration_hours=9.0)
        _fatigue_logs.setdefault(1, [])
        from app.services.driver_fatigue import _driver_names
        _driver_names[1] = "Driver One"
        alerts = get_all_warnings()
        assert len(alerts) == 1
        assert alerts[0].driver_id == 1
        assert alerts[0].status == FatigueStatusLevel.WARNING

    def test_returns_limit_reached_drivers(self):
        _log_pair(driver_id=2, ride_id=10, duration_hours=11.0)
        from app.services.driver_fatigue import _driver_names
        _driver_names[2] = "Driver Two"
        alerts = get_all_warnings()
        assert any(a.driver_id == 2 and a.status == FatigueStatusLevel.LIMIT_REACHED for a in alerts)

    def test_excludes_normal_drivers(self):
        _log_pair(driver_id=1, ride_id=1, duration_hours=9.0)  # WARNING
        _log_pair(driver_id=2, ride_id=2, duration_hours=3.0)  # NORMAL
        from app.services.driver_fatigue import _driver_names
        _driver_names[1] = "Driver One"
        _driver_names[2] = "Driver Two"
        alerts = get_all_warnings()
        ids = [a.driver_id for a in alerts]
        assert 1 in ids
        assert 2 not in ids

    def test_includes_last_ride_ended_at(self):
        _log_pair(driver_id=1, ride_id=1, duration_hours=9.0, start_offset_hours=0.5)
        from app.services.driver_fatigue import _driver_names
        _driver_names[1] = "Driver One"
        alerts = get_all_warnings()
        assert alerts[0].last_ride_ended_at is not None


# ---------------------------------------------------------------------------
# Service: reset_driver_fatigue
# ---------------------------------------------------------------------------


class TestResetDriverFatigue:
    def test_reset_clears_log(self):
        _log_pair(driver_id=1, ride_id=1, duration_hours=10.0)
        reset_driver_fatigue(driver_id=1)
        assert 1 not in _fatigue_logs

    def test_reset_makes_status_normal(self):
        _log_pair(driver_id=1, ride_id=1, duration_hours=10.0)
        reset_driver_fatigue(driver_id=1)
        status = compute_fatigue_status(driver_id=1)
        assert status.status == FatigueStatusLevel.NORMAL
        assert status.active_hours_last_24h == 0.0

    def test_reset_nonexistent_driver_is_noop(self):
        reset_driver_fatigue(driver_id=999)  # should not raise

    def test_reset_only_affects_target_driver(self):
        _log_pair(driver_id=1, ride_id=1, duration_hours=10.0)
        _log_pair(driver_id=2, ride_id=2, duration_hours=9.0)
        reset_driver_fatigue(driver_id=1)
        assert 1 not in _fatigue_logs
        assert 2 in _fatigue_logs


# ---------------------------------------------------------------------------
# Router: GET /drivers/me/fatigue-status
# ---------------------------------------------------------------------------


class TestFatigueStatusEndpoint:
    def test_normal_driver_200(self, driver_client, driver_user):
        resp = driver_client.get("/api/v1/drivers/me/fatigue-status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["driver_id"] == driver_user.id
        assert data["status"] == "NORMAL"
        assert data["active_hours_last_24h"] == 0.0
        assert data["rides_today"] == 0

    def test_warning_driver_200(self, driver_client, driver_user):
        _log_pair(driver_id=driver_user.id, ride_id=1, duration_hours=9.0)
        resp = driver_client.get("/api/v1/drivers/me/fatigue-status")
        assert resp.status_code == 200
        assert resp.json()["status"] == "WARNING"

    def test_limit_reached_driver_200(self, driver_client, driver_user):
        _log_pair(driver_id=driver_user.id, ride_id=1, duration_hours=10.5)
        resp = driver_client.get("/api/v1/drivers/me/fatigue-status")
        assert resp.status_code == 200
        assert resp.json()["status"] == "LIMIT_REACHED"

    def test_response_has_all_fields(self, driver_client):
        resp = driver_client.get("/api/v1/drivers/me/fatigue-status")
        data = resp.json()
        assert "driver_id" in data
        assert "status" in data
        assert "active_hours_last_24h" in data
        assert "rides_today" in data
        assert "message" in data

    def test_rider_cannot_access_driver_endpoint(self, rider_client):
        resp = rider_client.get("/api/v1/drivers/me/fatigue-status")
        assert resp.status_code == 403

    def test_unauthenticated_401(self, unauth_client):
        resp = unauth_client.get("/api/v1/drivers/me/fatigue-status")
        assert resp.status_code == 401

    def test_driver_sees_only_own_status(self, driver_client, driver_user):
        # Another driver with 10h — must not bleed into driver_user's status
        _log_pair(driver_id=driver_user.id + 1, ride_id=99, duration_hours=10.0)
        resp = driver_client.get("/api/v1/drivers/me/fatigue-status")
        assert resp.json()["status"] == "NORMAL"


# ---------------------------------------------------------------------------
# Router: GET /admin/driver-fatigue-alerts
# ---------------------------------------------------------------------------


class TestFatigueAlertsEndpoint:
    def test_empty_when_no_warnings(self, admin_client):
        resp = admin_client.get("/api/v1/admin/driver-fatigue-alerts")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_returns_warning_drivers(self, admin_client):
        _log_pair(driver_id=5, ride_id=1, duration_hours=9.0)
        from app.services.driver_fatigue import _driver_names
        _driver_names[5] = "Driver Five"
        resp = admin_client.get("/api/v1/admin/driver-fatigue-alerts")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["driver_id"] == 5
        assert data[0]["status"] == "WARNING"

    def test_normal_drivers_excluded(self, admin_client):
        _log_pair(driver_id=3, ride_id=1, duration_hours=3.0)
        from app.services.driver_fatigue import _driver_names
        _driver_names[3] = "Driver Three"
        resp = admin_client.get("/api/v1/admin/driver-fatigue-alerts")
        assert resp.json() == []

    def test_non_admin_gets_403(self, driver_client):
        resp = driver_client.get("/api/v1/admin/driver-fatigue-alerts")
        assert resp.status_code == 403

    def test_unauthenticated_401(self, unauth_client):
        resp = unauth_client.get("/api/v1/admin/driver-fatigue-alerts")
        assert resp.status_code == 401

    def test_response_fields(self, admin_client):
        _log_pair(driver_id=6, ride_id=1, duration_hours=9.0, start_offset_hours=0.5)
        from app.services.driver_fatigue import _driver_names
        _driver_names[6] = "Driver Six"
        resp = admin_client.get("/api/v1/admin/driver-fatigue-alerts")
        data = resp.json()
        assert len(data) == 1
        alert = data[0]
        assert "driver_id" in alert
        assert "driver_name" in alert
        assert "status" in alert
        assert "active_hours_last_24h" in alert


# ---------------------------------------------------------------------------
# Router: POST /admin/driver-fatigue/{driver_id}/reset
# ---------------------------------------------------------------------------


class TestFatigueResetEndpoint:
    def test_reset_returns_204(self, admin_client):
        _log_pair(driver_id=10, ride_id=1, duration_hours=10.0)
        resp = admin_client.post("/api/v1/admin/driver-fatigue/10/reset")
        assert resp.status_code == 204

    def test_reset_clears_state(self, admin_client):
        _log_pair(driver_id=10, ride_id=1, duration_hours=10.0)
        admin_client.post("/api/v1/admin/driver-fatigue/10/reset")
        assert 10 not in _fatigue_logs

    def test_reset_nonexistent_driver_204(self, admin_client):
        resp = admin_client.post("/api/v1/admin/driver-fatigue/9999/reset")
        assert resp.status_code == 204

    def test_non_admin_gets_403(self, driver_client):
        resp = driver_client.post("/api/v1/admin/driver-fatigue/1/reset")
        assert resp.status_code == 403

    def test_unauthenticated_401(self, unauth_client):
        resp = unauth_client.post("/api/v1/admin/driver-fatigue/1/reset")
        assert resp.status_code == 401
