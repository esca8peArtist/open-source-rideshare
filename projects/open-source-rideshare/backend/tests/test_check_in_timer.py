"""Tests for the rider safety check-in timer feature.

POST   /api/v1/riders/me/check-in-timer          — start timer
GET    /api/v1/riders/me/check-in-timer          — get active timer
POST   /api/v1/riders/me/check-in-timer/confirm  — confirm safe
DELETE /api/v1/riders/me/check-in-timer          — cancel timer
GET    /api/v1/riders/me/check-in-timer/history  — list past timers

Coverage
--------
Schema: StartCheckInTimerRequest
  - duration_minutes validated: 5–120 inclusive
  - notes is optional
Schema: CheckInTimerResponse
  - all fields present
  - minutes_remaining present for ACTIVE, None for terminal states

Service: start_timer
  - creates record with correct expiry (now + duration_minutes)
  - status is ACTIVE on creation
  - notes are stored
  - raises ValueError if rider already has an ACTIVE timer
  - raises ValueError for duration < 5 or > 120
  - two different riders can each have one ACTIVE timer

Service: get_active_timer
  - returns None when no active timer exists
  - returns active timer with minutes_remaining
  - lazily expires overdue timer (returns None, sets status=expired)

Service: confirm_timer
  - transitions ACTIVE → CONFIRMED
  - sets confirmed_at
  - raises LookupError when no active timer

Service: cancel_timer
  - transitions ACTIVE → CANCELLED
  - sets cancelled_at
  - raises LookupError when no active timer

Service: expire_if_due
  - returns None when timer not expired
  - expires overdue timer and sets expired_notified_at

Service: list_timers
  - returns all timers newest-first
  - pagination (skip/limit)
  - filters to rider's own timers

Service: _reset_store
  - clears all records and resets ID counter

Router: POST /riders/me/check-in-timer
  - 201 with CheckInTimerResponse
  - 409 if active timer already exists

Router: GET /riders/me/check-in-timer
  - 200 when active timer exists with minutes_remaining
  - 404 when no active timer

Router: POST /riders/me/check-in-timer/confirm
  - 200 with confirmed status
  - 404 when no active timer

Router: DELETE /riders/me/check-in-timer
  - 200 with cancelled status
  - 404 when no active timer

Router: GET /riders/me/check-in-timer/history
  - 200 list of all timers for rider
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

from app.schemas.check_in_timer import CheckInTimerResponse, CheckInTimerStatus, StartCheckInTimerRequest
from app.services.check_in_timer import (
    _reset_store,
    _timers,
    cancel_timer,
    confirm_timer,
    expire_if_due,
    get_active_timer,
    list_timers,
    start_timer,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_user(user_id: int = 1, role: str = "rider") -> MagicMock:
    user = MagicMock()
    user.id = user_id
    user.role = MagicMock()
    user.role.value = role
    user.is_active = True
    return user


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def reset_store():
    _reset_store()
    yield
    _reset_store()


@pytest.fixture()
def rider_user():
    return _make_user(user_id=10, role="rider")


@pytest.fixture()
def client(rider_user):
    from fastapi.testclient import TestClient
    from app.main import app
    from app.api.deps import get_current_user

    app.dependency_overrides[get_current_user] = lambda: rider_user
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------


class TestCheckInTimerSchemas:
    def test_request_valid_min_duration(self):
        req = StartCheckInTimerRequest(duration_minutes=5)
        assert req.duration_minutes == 5

    def test_request_valid_max_duration(self):
        req = StartCheckInTimerRequest(duration_minutes=120)
        assert req.duration_minutes == 120

    def test_request_duration_below_min_raises(self):
        with pytest.raises(Exception):
            StartCheckInTimerRequest(duration_minutes=4)

    def test_request_duration_above_max_raises(self):
        with pytest.raises(Exception):
            StartCheckInTimerRequest(duration_minutes=121)

    def test_request_notes_optional(self):
        req = StartCheckInTimerRequest(duration_minutes=30)
        assert req.notes is None

    def test_request_notes_stored(self):
        req = StartCheckInTimerRequest(duration_minutes=30, notes="heading home")
        assert req.notes == "heading home"

    def test_response_has_required_fields(self):
        now = _now()
        obj = CheckInTimerResponse(
            id=1,
            rider_id=10,
            duration_minutes=30,
            status=CheckInTimerStatus.ACTIVE,
            started_at=now,
            expires_at=now + timedelta(minutes=30),
            minutes_remaining=29.5,
        )
        assert obj.id == 1
        assert obj.status == CheckInTimerStatus.ACTIVE
        assert obj.minutes_remaining == 29.5

    def test_response_optional_fields_default_none(self):
        now = _now()
        obj = CheckInTimerResponse(
            id=1,
            rider_id=10,
            duration_minutes=30,
            status=CheckInTimerStatus.ACTIVE,
            started_at=now,
            expires_at=now + timedelta(minutes=30),
        )
        assert obj.notes is None
        assert obj.confirmed_at is None
        assert obj.cancelled_at is None
        assert obj.expired_notified_at is None


# ---------------------------------------------------------------------------
# Service: start_timer
# ---------------------------------------------------------------------------


class TestStartTimer:
    def test_creates_record_with_active_status(self):
        rec = start_timer(rider_id=1, duration_minutes=30)
        assert rec["status"] == "active"
        assert rec["rider_id"] == 1
        assert rec["duration_minutes"] == 30

    def test_expiry_is_duration_from_now(self):
        before = _now()
        rec = start_timer(rider_id=1, duration_minutes=15)
        after = _now()
        delta = rec["expires_at"] - rec["started_at"]
        assert timedelta(minutes=14, seconds=59) < delta <= timedelta(minutes=15, seconds=1)
        assert before <= rec["started_at"] <= after

    def test_notes_are_stored(self):
        rec = start_timer(rider_id=1, duration_minutes=30, notes="test note")
        assert rec["notes"] == "test note"

    def test_notes_default_none(self):
        rec = start_timer(rider_id=1, duration_minutes=30)
        assert rec["notes"] is None

    def test_minutes_remaining_positive(self):
        rec = start_timer(rider_id=1, duration_minutes=30)
        assert rec["minutes_remaining"] is not None
        assert rec["minutes_remaining"] > 0

    def test_raises_if_active_timer_exists(self):
        start_timer(rider_id=1, duration_minutes=30)
        with pytest.raises(ValueError, match="already have an active"):
            start_timer(rider_id=1, duration_minutes=10)

    def test_raises_for_duration_below_5(self):
        with pytest.raises(ValueError, match="between 5 and 120"):
            start_timer(rider_id=1, duration_minutes=4)

    def test_raises_for_duration_above_120(self):
        with pytest.raises(ValueError, match="between 5 and 120"):
            start_timer(rider_id=1, duration_minutes=121)

    def test_different_riders_are_independent(self):
        r1 = start_timer(rider_id=1, duration_minutes=30)
        r2 = start_timer(rider_id=2, duration_minutes=20)
        assert r1["id"] != r2["id"]
        assert r1["rider_id"] == 1
        assert r2["rider_id"] == 2

    def test_id_increments(self):
        r1 = start_timer(rider_id=1, duration_minutes=30)
        # Complete first timer so we can start another
        confirm_timer(rider_id=1)
        r2 = start_timer(rider_id=1, duration_minutes=10)
        assert r2["id"] == r1["id"] + 1

    def test_can_start_after_confirming(self):
        start_timer(rider_id=1, duration_minutes=30)
        confirm_timer(rider_id=1)
        rec = start_timer(rider_id=1, duration_minutes=15)
        assert rec["status"] == "active"

    def test_can_start_after_cancelling(self):
        start_timer(rider_id=1, duration_minutes=30)
        cancel_timer(rider_id=1)
        rec = start_timer(rider_id=1, duration_minutes=15)
        assert rec["status"] == "active"


# ---------------------------------------------------------------------------
# Service: get_active_timer
# ---------------------------------------------------------------------------


class TestGetActiveTimer:
    def test_returns_none_when_no_timer(self):
        assert get_active_timer(rider_id=1) is None

    def test_returns_active_timer(self):
        start_timer(rider_id=1, duration_minutes=30)
        rec = get_active_timer(rider_id=1)
        assert rec is not None
        assert rec["status"] == "active"
        assert rec["minutes_remaining"] is not None

    def test_returns_none_after_confirm(self):
        start_timer(rider_id=1, duration_minutes=30)
        confirm_timer(rider_id=1)
        assert get_active_timer(rider_id=1) is None

    def test_returns_none_after_cancel(self):
        start_timer(rider_id=1, duration_minutes=30)
        cancel_timer(rider_id=1)
        assert get_active_timer(rider_id=1) is None

    def test_lazy_expiry_returns_none_for_expired_timer(self):
        start_timer(rider_id=1, duration_minutes=30)
        # Wind back the expiry
        for rec in _timers.values():
            rec["expires_at"] = _now() - timedelta(seconds=1)
        result = get_active_timer(rider_id=1)
        assert result is None

    def test_lazy_expiry_sets_status_to_expired(self):
        start_timer(rider_id=1, duration_minutes=30)
        for rec in _timers.values():
            rec["expires_at"] = _now() - timedelta(seconds=1)
        get_active_timer(rider_id=1)
        for rec in _timers.values():
            assert rec["status"] == "expired"

    def test_lazy_expiry_sets_expired_notified_at(self):
        start_timer(rider_id=1, duration_minutes=30)
        for rec in _timers.values():
            rec["expires_at"] = _now() - timedelta(seconds=1)
        get_active_timer(rider_id=1)
        for rec in _timers.values():
            assert rec["expired_notified_at"] is not None

    def test_does_not_return_other_riders_timer(self):
        start_timer(rider_id=2, duration_minutes=30)
        assert get_active_timer(rider_id=1) is None


# ---------------------------------------------------------------------------
# Service: confirm_timer
# ---------------------------------------------------------------------------


class TestConfirmTimer:
    def test_transitions_to_confirmed(self):
        start_timer(rider_id=1, duration_minutes=30)
        rec = confirm_timer(rider_id=1)
        assert rec["status"] == "confirmed"

    def test_sets_confirmed_at(self):
        before = _now()
        start_timer(rider_id=1, duration_minutes=30)
        rec = confirm_timer(rider_id=1)
        assert rec["confirmed_at"] is not None
        assert rec["confirmed_at"] >= before

    def test_minutes_remaining_is_none_after_confirm(self):
        start_timer(rider_id=1, duration_minutes=30)
        rec = confirm_timer(rider_id=1)
        assert rec["minutes_remaining"] is None

    def test_raises_when_no_active_timer(self):
        with pytest.raises(LookupError, match="No active check-in timer"):
            confirm_timer(rider_id=1)

    def test_raises_after_already_confirmed(self):
        start_timer(rider_id=1, duration_minutes=30)
        confirm_timer(rider_id=1)
        with pytest.raises(LookupError):
            confirm_timer(rider_id=1)

    def test_raises_when_expired(self):
        start_timer(rider_id=1, duration_minutes=30)
        for rec in _timers.values():
            rec["expires_at"] = _now() - timedelta(seconds=1)
        with pytest.raises(LookupError):
            confirm_timer(rider_id=1)


# ---------------------------------------------------------------------------
# Service: cancel_timer
# ---------------------------------------------------------------------------


class TestCancelTimer:
    def test_transitions_to_cancelled(self):
        start_timer(rider_id=1, duration_minutes=30)
        rec = cancel_timer(rider_id=1)
        assert rec["status"] == "cancelled"

    def test_sets_cancelled_at(self):
        before = _now()
        start_timer(rider_id=1, duration_minutes=30)
        rec = cancel_timer(rider_id=1)
        assert rec["cancelled_at"] is not None
        assert rec["cancelled_at"] >= before

    def test_minutes_remaining_is_none_after_cancel(self):
        start_timer(rider_id=1, duration_minutes=30)
        rec = cancel_timer(rider_id=1)
        assert rec["minutes_remaining"] is None

    def test_raises_when_no_active_timer(self):
        with pytest.raises(LookupError, match="No active check-in timer"):
            cancel_timer(rider_id=1)

    def test_raises_after_already_cancelled(self):
        start_timer(rider_id=1, duration_minutes=30)
        cancel_timer(rider_id=1)
        with pytest.raises(LookupError):
            cancel_timer(rider_id=1)


# ---------------------------------------------------------------------------
# Service: expire_if_due
# ---------------------------------------------------------------------------


class TestExpireIfDue:
    def test_returns_none_when_not_expired(self):
        start_timer(rider_id=1, duration_minutes=30)
        result = expire_if_due(rider_id=1)
        assert result is None

    def test_returns_expired_record(self):
        start_timer(rider_id=1, duration_minutes=30)
        for rec in _timers.values():
            rec["expires_at"] = _now() - timedelta(seconds=1)
        result = expire_if_due(rider_id=1)
        assert result is not None
        assert result["status"] == "expired"
        assert result["expired_notified_at"] is not None

    def test_returns_none_when_no_timer(self):
        assert expire_if_due(rider_id=1) is None


# ---------------------------------------------------------------------------
# Service: list_timers
# ---------------------------------------------------------------------------


class TestListTimers:
    def test_returns_empty_when_no_timers(self):
        assert list_timers(rider_id=1) == []

    def test_returns_all_timers_newest_first(self):
        start_timer(rider_id=1, duration_minutes=30)
        confirm_timer(rider_id=1)
        start_timer(rider_id=1, duration_minutes=15)
        results = list_timers(rider_id=1)
        assert len(results) == 2
        assert results[0]["started_at"] >= results[1]["started_at"]

    def test_filters_to_rider(self):
        start_timer(rider_id=1, duration_minutes=30)
        start_timer(rider_id=2, duration_minutes=20)
        results = list_timers(rider_id=1)
        assert len(results) == 1
        assert results[0]["rider_id"] == 1

    def test_pagination_skip(self):
        start_timer(rider_id=1, duration_minutes=30)
        confirm_timer(rider_id=1)
        start_timer(rider_id=1, duration_minutes=15)
        results = list_timers(rider_id=1, skip=1, limit=10)
        assert len(results) == 1

    def test_pagination_limit(self):
        start_timer(rider_id=1, duration_minutes=30)
        confirm_timer(rider_id=1)
        start_timer(rider_id=1, duration_minutes=15)
        results = list_timers(rider_id=1, skip=0, limit=1)
        assert len(results) == 1


# ---------------------------------------------------------------------------
# Service: _reset_store
# ---------------------------------------------------------------------------


class TestResetStore:
    def test_clears_all_records(self):
        start_timer(rider_id=1, duration_minutes=30)
        _reset_store()
        assert _timers == {}

    def test_resets_id_counter(self):
        start_timer(rider_id=1, duration_minutes=30)
        _reset_store()
        rec = start_timer(rider_id=1, duration_minutes=30)
        assert rec["id"] == 1


# ---------------------------------------------------------------------------
# Router tests
# ---------------------------------------------------------------------------


class TestCheckInTimerRouter:
    def test_post_creates_timer_201(self, client):
        resp = client.post(
            "/api/v1/riders/me/check-in-timer",
            json={"duration_minutes": 30},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["status"] == "active"
        assert data["duration_minutes"] == 30
        assert "expires_at" in data
        assert data["minutes_remaining"] is not None

    def test_post_stores_notes(self, client):
        resp = client.post(
            "/api/v1/riders/me/check-in-timer",
            json={"duration_minutes": 20, "notes": "heading home"},
        )
        assert resp.status_code == 201
        assert resp.json()["notes"] == "heading home"

    def test_post_409_when_active_timer_exists(self, client):
        client.post("/api/v1/riders/me/check-in-timer", json={"duration_minutes": 30})
        resp = client.post("/api/v1/riders/me/check-in-timer", json={"duration_minutes": 10})
        assert resp.status_code == 409

    def test_post_invalid_duration_422(self, client):
        resp = client.post("/api/v1/riders/me/check-in-timer", json={"duration_minutes": 200})
        assert resp.status_code == 422

    def test_get_timer_200_when_active(self, client):
        client.post("/api/v1/riders/me/check-in-timer", json={"duration_minutes": 30})
        resp = client.get("/api/v1/riders/me/check-in-timer")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "active"
        assert data["minutes_remaining"] is not None

    def test_get_timer_404_when_none(self, client):
        resp = client.get("/api/v1/riders/me/check-in-timer")
        assert resp.status_code == 404

    def test_confirm_returns_confirmed_status(self, client):
        client.post("/api/v1/riders/me/check-in-timer", json={"duration_minutes": 30})
        resp = client.post("/api/v1/riders/me/check-in-timer/confirm")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "confirmed"
        assert data["confirmed_at"] is not None
        assert data["minutes_remaining"] is None

    def test_confirm_404_when_no_active_timer(self, client):
        resp = client.post("/api/v1/riders/me/check-in-timer/confirm")
        assert resp.status_code == 404

    def test_confirm_then_get_returns_404(self, client):
        client.post("/api/v1/riders/me/check-in-timer", json={"duration_minutes": 30})
        client.post("/api/v1/riders/me/check-in-timer/confirm")
        resp = client.get("/api/v1/riders/me/check-in-timer")
        assert resp.status_code == 404

    def test_delete_returns_cancelled_status(self, client):
        client.post("/api/v1/riders/me/check-in-timer", json={"duration_minutes": 30})
        resp = client.delete("/api/v1/riders/me/check-in-timer")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "cancelled"
        assert data["cancelled_at"] is not None

    def test_delete_404_when_no_active_timer(self, client):
        resp = client.delete("/api/v1/riders/me/check-in-timer")
        assert resp.status_code == 404

    def test_delete_then_get_returns_404(self, client):
        client.post("/api/v1/riders/me/check-in-timer", json={"duration_minutes": 30})
        client.delete("/api/v1/riders/me/check-in-timer")
        resp = client.get("/api/v1/riders/me/check-in-timer")
        assert resp.status_code == 404

    def test_history_returns_all_timers(self, client):
        client.post("/api/v1/riders/me/check-in-timer", json={"duration_minutes": 30})
        client.post("/api/v1/riders/me/check-in-timer/confirm")
        client.post("/api/v1/riders/me/check-in-timer", json={"duration_minutes": 15})
        resp = client.get("/api/v1/riders/me/check-in-timer/history")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2

    def test_history_empty_when_none(self, client):
        resp = client.get("/api/v1/riders/me/check-in-timer/history")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_history_pagination(self, client):
        client.post("/api/v1/riders/me/check-in-timer", json={"duration_minutes": 30})
        client.post("/api/v1/riders/me/check-in-timer/confirm")
        client.post("/api/v1/riders/me/check-in-timer", json={"duration_minutes": 15})
        resp = client.get("/api/v1/riders/me/check-in-timer/history?skip=0&limit=1")
        assert resp.status_code == 200
        assert len(resp.json()) == 1

    def test_can_restart_after_confirm(self, client):
        client.post("/api/v1/riders/me/check-in-timer", json={"duration_minutes": 30})
        client.post("/api/v1/riders/me/check-in-timer/confirm")
        resp = client.post("/api/v1/riders/me/check-in-timer", json={"duration_minutes": 15})
        assert resp.status_code == 201
        assert resp.json()["status"] == "active"

    def test_can_restart_after_cancel(self, client):
        client.post("/api/v1/riders/me/check-in-timer", json={"duration_minutes": 30})
        client.delete("/api/v1/riders/me/check-in-timer")
        resp = client.post("/api/v1/riders/me/check-in-timer", json={"duration_minutes": 10})
        assert resp.status_code == 201
        assert resp.json()["status"] == "active"
