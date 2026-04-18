"""Tests for pre-ride boarding verification.

Coverage
--------
Service layer (boarding_verification.py):
  generate_pin:
    - succeeds when ride status is ARRIVED
    - succeeds when ride status is DRIVER_EN_ROUTE
    - fails when ride status is not allowed (e.g., REQUESTED, IN_PROGRESS, COMPLETED)
    - fails when a verification already exists for the ride
    - regenerating PIN overwrites previous one
    - returns PIN of expected length (4 digits)

  get_pin:
    - returns None when no PIN generated yet
    - returns record with expired=False for a fresh PIN
    - returns record with expired=True for an expired PIN

  confirm_boarding:
    - correct PIN → confirmed=True, pin_match=True, no alert
    - wrong PIN → confirmed=False, pin_match=False, alert created
    - no active PIN → confirmed=False, pin_match=False, alert created
    - expired PIN → treated as no PIN (mismatch)
    - confirmed_driver_name and confirmed_plate stored
    - notes stored
    - second confirmation raises ValueError

  get_verification:
    - returns None when no verification submitted
    - returns the record after confirm_boarding

  admin_list_mismatch_alerts:
    - empty when no mismatches
    - returns unresolved alerts by default
    - includes resolved when include_resolved=True

  admin_resolve_mismatch_alert:
    - marks alert resolved
    - raises KeyError for unknown alert_id
    - raises ValueError for already-resolved alert

Schema tests (boarding_verification schemas):
  - BoardingPinResponse round-trips correctly
  - ConfirmBoardingRequest validates pin_entered length
  - BoardingVerificationResponse includes all fields

HTTP endpoint tests:
  POST /rides/{ride_id}/boarding-pin:
    - 201 when driver generates PIN for ARRIVED ride
    - 400 when ride status not allowed
    - 400 when verification already exists
    - 403 when non-driver calls
    - 404 when ride not found

  GET /rides/{ride_id}/boarding-pin:
    - 200 returns PIN for participant
    - 404 when no PIN generated

  POST /rides/{ride_id}/boarding-verification:
    - 201 when rider submits correct PIN
    - 201 when rider submits wrong PIN (mismatch alert created, alert_id set)
    - 400 when verification already exists
    - 403 when non-rider calls

  GET /rides/{ride_id}/boarding-verification:
    - 200 returns record
    - 404 when not submitted yet
    - 403 when non-participant calls

  GET /admin/boarding-mismatch-alerts:
    - 200 returns unresolved alerts

  POST /admin/boarding-mismatch-alerts/{alert_id}/resolve:
    - 200 resolves alert
    - 404 unknown alert
    - 400 already resolved
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import app.services.boarding_verification as svc
from app.schemas.boarding_verification import (
    BoardingPinResponse,
    BoardingVerificationResponse,
    ConfirmBoardingRequest,
    MismatchAlertListResponse,
    MismatchAlertResponse,
    ResolveMismatchAlertRequest,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


def _make_user(user_id: int, role: str = "rider") -> MagicMock:
    u = MagicMock()
    u.id = user_id
    u.role = MagicMock()
    u.role.value = role
    u.is_active = True
    return u


def _make_ride(
    ride_id: int,
    driver_id: int = 20,
    rider_id: int = 10,
    status: str = "arrived",
) -> MagicMock:
    r = MagicMock()
    r.id = ride_id
    r.driver_id = driver_id
    r.rider_id = rider_id
    r.status = MagicMock()
    r.status.value = status
    return r


def _scalar_one_or_none(ride):
    result = MagicMock()
    result.scalar_one_or_none.return_value = ride
    return result


# ---------------------------------------------------------------------------
# Service layer tests
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def reset():
    svc._reset_store()
    yield
    svc._reset_store()


class TestGeneratePin:
    def test_generates_pin_for_arrived_ride(self):
        record = svc.generate_pin(ride_id=1, driver_id=20, ride_status="arrived")
        assert record["pin"] is not None
        assert len(record["pin"]) == 4
        assert record["pin"].isdigit()

    def test_generates_pin_for_driver_en_route(self):
        record = svc.generate_pin(ride_id=2, driver_id=20, ride_status="driver_en_route")
        assert record["pin"] is not None

    def test_fails_for_requested_status(self):
        with pytest.raises(ValueError, match="DRIVER_EN_ROUTE or ARRIVED"):
            svc.generate_pin(ride_id=3, driver_id=20, ride_status="requested")

    def test_fails_for_in_progress_status(self):
        with pytest.raises(ValueError):
            svc.generate_pin(ride_id=4, driver_id=20, ride_status="in_progress")

    def test_fails_for_completed_status(self):
        with pytest.raises(ValueError):
            svc.generate_pin(ride_id=5, driver_id=20, ride_status="completed")

    def test_fails_when_verification_already_exists(self):
        svc.generate_pin(ride_id=6, driver_id=20, ride_status="arrived")
        svc.confirm_boarding(
            ride_id=6, rider_id=10, pin_entered="0000",
            confirmed_driver_name=None, confirmed_plate=None, notes=None,
        )
        with pytest.raises(ValueError, match="already been completed"):
            svc.generate_pin(ride_id=6, driver_id=20, ride_status="arrived")

    def test_regenerating_overwrites_previous_pin(self):
        first = svc.generate_pin(ride_id=7, driver_id=20, ride_status="arrived")
        second = svc.generate_pin(ride_id=7, driver_id=20, ride_status="arrived")
        assert second["generated_at"] >= first["generated_at"]
        # New record replaces old — get_pin returns the latest
        current = svc.get_pin(7)
        assert current["pin"] == second["pin"]

    def test_stores_driver_id(self):
        record = svc.generate_pin(ride_id=8, driver_id=99, ride_status="arrived")
        assert record["driver_id"] == 99

    def test_expires_at_is_15_minutes_after_generation(self):
        record = svc.generate_pin(ride_id=9, driver_id=20, ride_status="arrived")
        delta = record["expires_at"] - record["generated_at"]
        assert abs(delta.total_seconds() - 900) < 2  # 15 minutes ± 2s


class TestGetPin:
    def test_returns_none_when_no_pin(self):
        assert svc.get_pin(999) is None

    def test_returns_record_with_expired_false_for_fresh_pin(self):
        svc.generate_pin(ride_id=1, driver_id=20, ride_status="arrived")
        record = svc.get_pin(1)
        assert record is not None
        assert record["expired"] is False
        assert len(record["pin"]) == 4

    def test_returns_expired_true_for_expired_pin(self):
        svc.generate_pin(ride_id=1, driver_id=20, ride_status="arrived")
        # Backdate the expires_at
        svc._active_pins[1]["expires_at"] = _now() - timedelta(seconds=1)
        record = svc.get_pin(1)
        assert record["expired"] is True


class TestConfirmBoarding:
    def test_correct_pin_sets_confirmed_true(self):
        gen = svc.generate_pin(ride_id=1, driver_id=20, ride_status="arrived")
        record = svc.confirm_boarding(
            ride_id=1, rider_id=10, pin_entered=gen["pin"],
            confirmed_driver_name="Alex", confirmed_plate="ABC-1234", notes=None,
        )
        assert record["confirmed"] is True
        assert record["pin_match"] is True
        assert record["alert_id"] is None

    def test_correct_pin_stores_confirmed_fields(self):
        gen = svc.generate_pin(ride_id=1, driver_id=20, ride_status="arrived")
        record = svc.confirm_boarding(
            ride_id=1, rider_id=10, pin_entered=gen["pin"],
            confirmed_driver_name="Alex Driver", confirmed_plate="XY-999", notes="All good",
        )
        assert record["confirmed_driver_name"] == "Alex Driver"
        assert record["confirmed_plate"] == "XY-999"
        assert record["notes"] == "All good"

    def test_wrong_pin_sets_confirmed_false(self):
        svc.generate_pin(ride_id=1, driver_id=20, ride_status="arrived")
        record = svc.confirm_boarding(
            ride_id=1, rider_id=10, pin_entered="0000",
            confirmed_driver_name=None, confirmed_plate=None, notes=None,
        )
        assert record["confirmed"] is False
        assert record["pin_match"] is False

    def test_wrong_pin_creates_alert(self):
        svc.generate_pin(ride_id=1, driver_id=20, ride_status="arrived")
        record = svc.confirm_boarding(
            ride_id=1, rider_id=10, pin_entered="0000",
            confirmed_driver_name=None, confirmed_plate=None, notes=None,
        )
        assert record["alert_id"] is not None
        alerts = svc.admin_list_mismatch_alerts()
        assert len(alerts) == 1
        assert alerts[0]["ride_id"] == 1

    def test_no_active_pin_creates_mismatch(self):
        record = svc.confirm_boarding(
            ride_id=1, rider_id=10, pin_entered="1234",
            confirmed_driver_name=None, confirmed_plate=None, notes=None,
        )
        assert record["confirmed"] is False
        assert record["alert_id"] is not None

    def test_expired_pin_treated_as_no_pin(self):
        svc.generate_pin(ride_id=1, driver_id=20, ride_status="arrived")
        svc._active_pins[1]["expires_at"] = _now() - timedelta(seconds=1)
        record = svc.confirm_boarding(
            ride_id=1, rider_id=10, pin_entered=svc._active_pins[1]["pin"],
            confirmed_driver_name=None, confirmed_plate=None, notes=None,
        )
        assert record["confirmed"] is False

    def test_second_confirmation_raises_value_error(self):
        gen = svc.generate_pin(ride_id=1, driver_id=20, ride_status="arrived")
        svc.confirm_boarding(
            ride_id=1, rider_id=10, pin_entered=gen["pin"],
            confirmed_driver_name=None, confirmed_plate=None, notes=None,
        )
        with pytest.raises(ValueError, match="already been recorded"):
            svc.confirm_boarding(
                ride_id=1, rider_id=10, pin_entered=gen["pin"],
                confirmed_driver_name=None, confirmed_plate=None, notes=None,
            )

    def test_stores_rider_and_driver_ids(self):
        gen = svc.generate_pin(ride_id=1, driver_id=55, ride_status="arrived")
        record = svc.confirm_boarding(
            ride_id=1, rider_id=77, pin_entered=gen["pin"],
            confirmed_driver_name=None, confirmed_plate=None, notes=None,
        )
        assert record["rider_id"] == 77
        assert record["driver_id"] == 55

    def test_record_has_verified_at_timestamp(self):
        gen = svc.generate_pin(ride_id=1, driver_id=20, ride_status="arrived")
        before = _now()
        record = svc.confirm_boarding(
            ride_id=1, rider_id=10, pin_entered=gen["pin"],
            confirmed_driver_name=None, confirmed_plate=None, notes=None,
        )
        after = _now()
        assert before <= record["verified_at"] <= after

    def test_id_increments_across_rides(self):
        gen1 = svc.generate_pin(ride_id=1, driver_id=20, ride_status="arrived")
        gen2 = svc.generate_pin(ride_id=2, driver_id=20, ride_status="arrived")
        r1 = svc.confirm_boarding(
            ride_id=1, rider_id=10, pin_entered=gen1["pin"],
            confirmed_driver_name=None, confirmed_plate=None, notes=None,
        )
        r2 = svc.confirm_boarding(
            ride_id=2, rider_id=10, pin_entered=gen2["pin"],
            confirmed_driver_name=None, confirmed_plate=None, notes=None,
        )
        assert r2["id"] > r1["id"]


class TestGetVerification:
    def test_returns_none_when_no_verification(self):
        assert svc.get_verification(999) is None

    def test_returns_record_after_confirmation(self):
        gen = svc.generate_pin(ride_id=1, driver_id=20, ride_status="arrived")
        svc.confirm_boarding(
            ride_id=1, rider_id=10, pin_entered=gen["pin"],
            confirmed_driver_name=None, confirmed_plate=None, notes=None,
        )
        record = svc.get_verification(1)
        assert record is not None
        assert record["ride_id"] == 1
        assert record["confirmed"] is True


class TestAdminMismatchAlerts:
    def test_empty_by_default(self):
        alerts = svc.admin_list_mismatch_alerts()
        assert alerts == []

    def test_unresolved_alert_appears(self):
        svc.generate_pin(ride_id=1, driver_id=20, ride_status="arrived")
        svc.confirm_boarding(
            ride_id=1, rider_id=10, pin_entered="0000",
            confirmed_driver_name=None, confirmed_plate=None, notes=None,
        )
        alerts = svc.admin_list_mismatch_alerts()
        assert len(alerts) == 1
        assert not alerts[0]["resolved"]

    def test_resolved_excluded_by_default(self):
        svc.generate_pin(ride_id=1, driver_id=20, ride_status="arrived")
        svc.confirm_boarding(
            ride_id=1, rider_id=10, pin_entered="0000",
            confirmed_driver_name=None, confirmed_plate=None, notes=None,
        )
        alert_id = svc._next_alert_id - 1
        svc.admin_resolve_mismatch_alert(alert_id, resolution_notes="Investigated")
        assert svc.admin_list_mismatch_alerts() == []

    def test_resolved_included_when_flag_set(self):
        svc.generate_pin(ride_id=1, driver_id=20, ride_status="arrived")
        svc.confirm_boarding(
            ride_id=1, rider_id=10, pin_entered="0000",
            confirmed_driver_name=None, confirmed_plate=None, notes=None,
        )
        alert_id = svc._next_alert_id - 1
        svc.admin_resolve_mismatch_alert(alert_id, resolution_notes=None)
        alerts = svc.admin_list_mismatch_alerts(include_resolved=True)
        assert len(alerts) == 1
        assert alerts[0]["resolved"] is True

    def test_multiple_alerts_ordered_by_created_at(self):
        for ride_id in (1, 2, 3):
            svc.confirm_boarding(
                ride_id=ride_id, rider_id=10, pin_entered="0000",
                confirmed_driver_name=None, confirmed_plate=None, notes=None,
            )
        alerts = svc.admin_list_mismatch_alerts()
        ids = [a["id"] for a in alerts]
        assert ids == sorted(ids)


class TestAdminResolveMismatchAlert:
    def test_resolves_alert(self):
        svc.confirm_boarding(
            ride_id=1, rider_id=10, pin_entered="0000",
            confirmed_driver_name=None, confirmed_plate=None, notes=None,
        )
        alert_id = svc._next_alert_id - 1
        result = svc.admin_resolve_mismatch_alert(alert_id, resolution_notes="All clear")
        assert result["resolved"] is True
        assert result["resolution_notes"] == "All clear"
        assert "resolved_at" in result

    def test_raises_key_error_for_unknown_id(self):
        with pytest.raises(KeyError):
            svc.admin_resolve_mismatch_alert(999, resolution_notes=None)

    def test_raises_value_error_when_already_resolved(self):
        svc.confirm_boarding(
            ride_id=1, rider_id=10, pin_entered="0000",
            confirmed_driver_name=None, confirmed_plate=None, notes=None,
        )
        alert_id = svc._next_alert_id - 1
        svc.admin_resolve_mismatch_alert(alert_id, resolution_notes=None)
        with pytest.raises(ValueError, match="already resolved"):
            svc.admin_resolve_mismatch_alert(alert_id, resolution_notes=None)


# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------

class TestBoardingPinResponseSchema:
    def test_round_trip(self):
        now = _now()
        schema = BoardingPinResponse(
            ride_id=1,
            pin="4321",
            generated_at=now,
            expires_at=now + timedelta(minutes=15),
            expired=False,
        )
        assert schema.ride_id == 1
        assert schema.pin == "4321"
        assert schema.expired is False


class TestConfirmBoardingRequestSchema:
    def test_valid_request(self):
        req = ConfirmBoardingRequest(
            pin_entered="5678",
            confirmed_driver_name="Jane",
            confirmed_plate="ZZ-001",
            notes="OK",
        )
        assert req.pin_entered == "5678"

    def test_empty_pin_raises(self):
        with pytest.raises(Exception):
            ConfirmBoardingRequest(pin_entered="")

    def test_optional_fields_default_none(self):
        req = ConfirmBoardingRequest(pin_entered="1234")
        assert req.confirmed_driver_name is None
        assert req.confirmed_plate is None
        assert req.notes is None


class TestBoardingVerificationResponseSchema:
    def test_all_fields_present(self):
        now = _now()
        schema = BoardingVerificationResponse(
            id=1,
            ride_id=5,
            rider_id=10,
            driver_id=20,
            pin_match=True,
            confirmed=True,
            confirmed_driver_name="Bob",
            confirmed_plate="AA-123",
            notes=None,
            verified_at=now,
            alert_id=None,
        )
        assert schema.confirmed is True
        assert schema.alert_id is None


# ---------------------------------------------------------------------------
# HTTP endpoint tests
# ---------------------------------------------------------------------------

class TestBoardingPinHTTP:
    @pytest.fixture(autouse=True)
    def reset_between_tests(self):
        svc._reset_store()
        yield
        svc._reset_store()

    def _make_db(self, ride):
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_scalar_one_or_none(ride))
        return db

    @pytest.fixture()
    def driver(self):
        return _make_user(user_id=20, role="driver")

    @pytest.fixture()
    def rider(self):
        return _make_user(user_id=10, role="rider")

    @pytest.fixture()
    def arrived_ride(self):
        return _make_ride(ride_id=1, driver_id=20, rider_id=10, status="arrived")

    @pytest.fixture()
    def client(self, driver, rider, arrived_ride):
        from fastapi.testclient import TestClient
        from app.main import app
        from app.api.deps import get_current_user, get_db

        async def override_db():
            yield self._make_db(arrived_ride)

        app.dependency_overrides[get_current_user] = lambda: driver
        app.dependency_overrides[get_db] = override_db
        with TestClient(app) as c:
            yield c
        app.dependency_overrides.clear()

    def test_generate_pin_returns_201(self, client):
        resp = client.post("/api/v1/rides/1/boarding-pin")
        assert resp.status_code == 201

    def test_generate_pin_response_has_pin(self, client):
        resp = client.post("/api/v1/rides/1/boarding-pin")
        data = resp.json()
        assert "pin" in data
        assert len(data["pin"]) == 4
        assert data["pin"].isdigit()

    def test_generate_pin_400_wrong_status(self, driver):
        from fastapi.testclient import TestClient
        from app.main import app
        from app.api.deps import get_current_user, get_db

        requested_ride = _make_ride(ride_id=2, driver_id=20, rider_id=10, status="requested")

        async def override_db():
            yield self._make_db(requested_ride)

        app.dependency_overrides[get_current_user] = lambda: driver
        app.dependency_overrides[get_db] = override_db
        with TestClient(app) as c:
            resp = c.post("/api/v1/rides/2/boarding-pin")
        app.dependency_overrides.clear()
        assert resp.status_code == 400

    def test_generate_pin_403_wrong_driver(self, arrived_ride):
        from fastapi.testclient import TestClient
        from app.main import app
        from app.api.deps import get_current_user, get_db

        other_driver = _make_user(user_id=99, role="driver")

        async def override_db():
            yield self._make_db(arrived_ride)

        app.dependency_overrides[get_current_user] = lambda: other_driver
        app.dependency_overrides[get_db] = override_db
        with TestClient(app) as c:
            resp = c.post("/api/v1/rides/1/boarding-pin")
        app.dependency_overrides.clear()
        assert resp.status_code == 403

    def test_generate_pin_404_ride_not_found(self, driver):
        from fastapi.testclient import TestClient
        from app.main import app
        from app.api.deps import get_current_user, get_db

        async def override_db():
            yield self._make_db(None)  # ride not found

        app.dependency_overrides[get_current_user] = lambda: driver
        app.dependency_overrides[get_db] = override_db
        with TestClient(app) as c:
            resp = c.post("/api/v1/rides/999/boarding-pin")
        app.dependency_overrides.clear()
        assert resp.status_code == 404

    def test_get_pin_404_when_no_pin(self, rider, arrived_ride):
        from fastapi.testclient import TestClient
        from app.main import app
        from app.api.deps import get_current_user, get_db

        async def override_db():
            yield self._make_db(arrived_ride)

        app.dependency_overrides[get_current_user] = lambda: rider
        app.dependency_overrides[get_db] = override_db
        with TestClient(app) as c:
            resp = c.get("/api/v1/rides/1/boarding-pin")
        app.dependency_overrides.clear()
        assert resp.status_code == 404

    def test_get_pin_200_after_generation(self, arrived_ride):
        from fastapi.testclient import TestClient
        from app.main import app
        from app.api.deps import get_current_user, get_db

        driver = _make_user(user_id=20, role="driver")
        rider = _make_user(user_id=10, role="rider")

        async def override_db():
            yield self._make_db(arrived_ride)

        # Generate as driver
        app.dependency_overrides[get_current_user] = lambda: driver
        app.dependency_overrides[get_db] = override_db
        with TestClient(app) as c:
            c.post("/api/v1/rides/1/boarding-pin")

        # Fetch as rider
        app.dependency_overrides[get_current_user] = lambda: rider
        app.dependency_overrides[get_db] = override_db
        with TestClient(app) as c:
            resp = c.get("/api/v1/rides/1/boarding-pin")
        app.dependency_overrides.clear()
        assert resp.status_code == 200
        assert "pin" in resp.json()


class TestBoardingVerificationHTTP:
    @pytest.fixture(autouse=True)
    def reset_between_tests(self):
        svc._reset_store()
        yield
        svc._reset_store()

    def _make_db(self, ride):
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_scalar_one_or_none(ride))
        return db

    @pytest.fixture()
    def ride(self):
        return _make_ride(ride_id=1, driver_id=20, rider_id=10, status="arrived")

    def test_confirm_boarding_201_pin_match(self, ride):
        from fastapi.testclient import TestClient
        from app.main import app
        from app.api.deps import get_current_user, get_db

        driver = _make_user(user_id=20, role="driver")
        rider = _make_user(user_id=10, role="rider")

        async def override_db():
            yield self._make_db(ride)

        # Generate PIN
        app.dependency_overrides[get_current_user] = lambda: driver
        app.dependency_overrides[get_db] = override_db
        with TestClient(app) as c:
            pin_resp = c.post("/api/v1/rides/1/boarding-pin")
        pin = pin_resp.json()["pin"]

        # Confirm with correct PIN
        app.dependency_overrides[get_current_user] = lambda: rider
        with TestClient(app) as c:
            resp = c.post(
                "/api/v1/rides/1/boarding-verification",
                json={"pin_entered": pin},
            )
        app.dependency_overrides.clear()
        assert resp.status_code == 201
        data = resp.json()
        assert data["confirmed"] is True
        assert data["pin_match"] is True
        assert data["alert_id"] is None

    def test_confirm_boarding_201_pin_mismatch_creates_alert(self, ride):
        from fastapi.testclient import TestClient
        from app.main import app
        from app.api.deps import get_current_user, get_db

        driver = _make_user(user_id=20, role="driver")
        rider = _make_user(user_id=10, role="rider")

        async def override_db():
            yield self._make_db(ride)

        app.dependency_overrides[get_current_user] = lambda: driver
        app.dependency_overrides[get_db] = override_db
        with TestClient(app) as c:
            c.post("/api/v1/rides/1/boarding-pin")

        app.dependency_overrides[get_current_user] = lambda: rider
        with TestClient(app) as c:
            resp = c.post(
                "/api/v1/rides/1/boarding-verification",
                json={"pin_entered": "0000"},
            )
        app.dependency_overrides.clear()
        assert resp.status_code == 201
        data = resp.json()
        assert data["confirmed"] is False
        assert data["alert_id"] is not None

    def test_confirm_boarding_400_already_verified(self, ride):
        from fastapi.testclient import TestClient
        from app.main import app
        from app.api.deps import get_current_user, get_db

        driver = _make_user(user_id=20, role="driver")
        rider = _make_user(user_id=10, role="rider")

        async def override_db():
            yield self._make_db(ride)

        app.dependency_overrides[get_current_user] = lambda: driver
        app.dependency_overrides[get_db] = override_db
        with TestClient(app) as c:
            pin = c.post("/api/v1/rides/1/boarding-pin").json()["pin"]

        app.dependency_overrides[get_current_user] = lambda: rider
        with TestClient(app) as c:
            c.post("/api/v1/rides/1/boarding-verification", json={"pin_entered": pin})
            resp = c.post("/api/v1/rides/1/boarding-verification", json={"pin_entered": pin})
        app.dependency_overrides.clear()
        assert resp.status_code == 400

    def test_confirm_boarding_403_non_rider(self, ride):
        from fastapi.testclient import TestClient
        from app.main import app
        from app.api.deps import get_current_user, get_db

        other = _make_user(user_id=99)

        async def override_db():
            yield self._make_db(ride)

        app.dependency_overrides[get_current_user] = lambda: other
        app.dependency_overrides[get_db] = override_db
        with TestClient(app) as c:
            resp = c.post("/api/v1/rides/1/boarding-verification", json={"pin_entered": "1234"})
        app.dependency_overrides.clear()
        assert resp.status_code == 403

    def test_get_verification_404_before_submission(self, ride):
        from fastapi.testclient import TestClient
        from app.main import app
        from app.api.deps import get_current_user, get_db

        rider = _make_user(user_id=10)

        async def override_db():
            yield self._make_db(ride)

        app.dependency_overrides[get_current_user] = lambda: rider
        app.dependency_overrides[get_db] = override_db
        with TestClient(app) as c:
            resp = c.get("/api/v1/rides/1/boarding-verification")
        app.dependency_overrides.clear()
        assert resp.status_code == 404

    def test_get_verification_200_after_submission(self, ride):
        from fastapi.testclient import TestClient
        from app.main import app
        from app.api.deps import get_current_user, get_db

        driver = _make_user(user_id=20, role="driver")
        rider = _make_user(user_id=10, role="rider")

        async def override_db():
            yield self._make_db(ride)

        app.dependency_overrides[get_current_user] = lambda: driver
        app.dependency_overrides[get_db] = override_db
        with TestClient(app) as c:
            pin = c.post("/api/v1/rides/1/boarding-pin").json()["pin"]

        app.dependency_overrides[get_current_user] = lambda: rider
        with TestClient(app) as c:
            c.post("/api/v1/rides/1/boarding-verification", json={"pin_entered": pin})
            resp = c.get("/api/v1/rides/1/boarding-verification")
        app.dependency_overrides.clear()
        assert resp.status_code == 200
        data = resp.json()
        assert data["confirmed"] is True
        assert data["ride_id"] == 1

    def test_get_verification_403_non_participant(self, ride):
        from fastapi.testclient import TestClient
        from app.main import app
        from app.api.deps import get_current_user, get_db

        outsider = _make_user(user_id=999)

        async def override_db():
            yield self._make_db(ride)

        app.dependency_overrides[get_current_user] = lambda: outsider
        app.dependency_overrides[get_db] = override_db
        with TestClient(app) as c:
            resp = c.get("/api/v1/rides/1/boarding-verification")
        app.dependency_overrides.clear()
        assert resp.status_code == 403


class TestAdminMismatchAlertsHTTP:
    @pytest.fixture(autouse=True)
    def reset_between_tests(self):
        svc._reset_store()
        yield
        svc._reset_store()

    @pytest.fixture()
    def admin_user(self):
        return _make_user(user_id=1, role="admin")

    def test_list_alerts_200_empty(self, admin_user):
        from fastapi.testclient import TestClient
        from app.main import app
        from app.api.deps import require_admin

        app.dependency_overrides[require_admin] = lambda: admin_user
        with TestClient(app) as c:
            resp = c.get("/api/v1/admin/boarding-mismatch-alerts")
        app.dependency_overrides.clear()
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 0
        assert data["alerts"] == []

    def test_list_alerts_200_with_mismatch(self, admin_user):
        from fastapi.testclient import TestClient
        from app.main import app
        from app.api.deps import require_admin

        svc.confirm_boarding(
            ride_id=1, rider_id=10, pin_entered="0000",
            confirmed_driver_name=None, confirmed_plate=None, notes=None,
        )
        app.dependency_overrides[require_admin] = lambda: admin_user
        with TestClient(app) as c:
            resp = c.get("/api/v1/admin/boarding-mismatch-alerts")
        app.dependency_overrides.clear()
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["alerts"][0]["ride_id"] == 1

    def test_resolve_alert_200(self, admin_user):
        from fastapi.testclient import TestClient
        from app.main import app
        from app.api.deps import require_admin

        svc.confirm_boarding(
            ride_id=1, rider_id=10, pin_entered="0000",
            confirmed_driver_name=None, confirmed_plate=None, notes=None,
        )
        alert_id = svc._next_alert_id - 1

        app.dependency_overrides[require_admin] = lambda: admin_user
        with TestClient(app) as c:
            resp = c.post(
                f"/api/v1/admin/boarding-mismatch-alerts/{alert_id}/resolve",
                json={"resolution_notes": "Verified with driver — false alarm"},
            )
        app.dependency_overrides.clear()
        assert resp.status_code == 200
        data = resp.json()
        assert data["resolved"] is True
        assert data["resolution_notes"] == "Verified with driver — false alarm"

    def test_resolve_alert_404_unknown(self, admin_user):
        from fastapi.testclient import TestClient
        from app.main import app
        from app.api.deps import require_admin

        app.dependency_overrides[require_admin] = lambda: admin_user
        with TestClient(app) as c:
            resp = c.post("/api/v1/admin/boarding-mismatch-alerts/999/resolve", json={})
        app.dependency_overrides.clear()
        assert resp.status_code == 404

    def test_resolve_alert_400_already_resolved(self, admin_user):
        from fastapi.testclient import TestClient
        from app.main import app
        from app.api.deps import require_admin

        svc.confirm_boarding(
            ride_id=1, rider_id=10, pin_entered="0000",
            confirmed_driver_name=None, confirmed_plate=None, notes=None,
        )
        alert_id = svc._next_alert_id - 1
        svc.admin_resolve_mismatch_alert(alert_id, resolution_notes=None)

        app.dependency_overrides[require_admin] = lambda: admin_user
        with TestClient(app) as c:
            resp = c.post(
                f"/api/v1/admin/boarding-mismatch-alerts/{alert_id}/resolve",
                json={},
            )
        app.dependency_overrides.clear()
        assert resp.status_code == 400
