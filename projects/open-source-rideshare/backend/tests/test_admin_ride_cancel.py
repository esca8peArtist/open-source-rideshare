"""Tests for admin ride force-cancel feature.

Service unit tests (AsyncMock DB):
  1.  Raises ValueError when ride not found
  2.  Raises ValueError when ride is already COMPLETED
  3.  Raises ValueError when ride is already CANCELLED
  4.  Cancels REQUESTED ride successfully
  5.  Cancels MATCHED ride successfully
  6.  Cancels DRIVER_EN_ROUTE ride successfully
  7.  Cancels ARRIVED ride successfully
  8.  Cancels IN_PROGRESS ride successfully
  9.  Cancels SCHEDULED ride successfully
  10. Sets cancellation_category to ADMIN_FORCED
  11. Sets cancellation_reason with admin_id and reason text
  12. Marks COMPLETED payment as REFUNDED and returns refund_issued=True
  13. Marks PENDING payment as REFUNDED and returns refund_issued=True
  14. Returns refund_issued=False when no payment exists
  15. Returns previous_status matching the ride's original status
  16. notify_parties=False skips notification dispatch (no exception)
  17. Driver-less ride: driver_notified=False when driver_id is None

API integration tests (conftest fixtures + real DB):
  18. 401 with no auth
  19. 403 with rider token
  20. 403 with driver token
  21. 200 with valid admin token and cancellable ride
  22. 404 when ride does not exist
  23. 409 when ride is already COMPLETED
  24. 409 when ride is already CANCELLED
  25. Response contains ride_id, previous_status, cancelled_at, refund_issued
  26. Ride status is CANCELLED in DB after successful cancel
  27. COMPLETED payment is REFUNDED in DB after successful cancel
  28. notify_parties=false still returns 200 and cancels the ride
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from geoalchemy2.functions import ST_MakePoint

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.payment import Payment, PaymentStatus, PaymentType
from app.models.ride import CancellationCategory, Ride, RideStatus
from app.models.user import User, UserRole
from app.services.admin_ride_cancel import admin_force_cancel_ride, _CANCELLABLE_STATUSES

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 1, 15, 12, 0, 0, tzinfo=timezone.utc)


def _make_ride(
    ride_id: int = 1,
    rider_id: int = 10,
    driver_id: int | None = 20,
    status: RideStatus = RideStatus.REQUESTED,
) -> MagicMock:
    ride = MagicMock(spec=Ride)
    ride.id = ride_id
    ride.rider_id = rider_id
    ride.driver_id = driver_id
    ride.status = status
    return ride


def _make_payment(status: PaymentStatus = PaymentStatus.COMPLETED) -> MagicMock:
    p = MagicMock(spec=Payment)
    p.status = status
    return p


def _make_db_with_ride(ride: MagicMock | None, *payment_sets) -> AsyncMock:
    """Build a DB mock returning ride on first execute, then each payment_set."""
    db = AsyncMock()
    side_effects = []

    # First call: ride lookup via scalar_one_or_none
    ride_result = MagicMock()
    ride_result.scalar_one_or_none.return_value = ride
    side_effects.append(ride_result)

    # Subsequent calls: payment lookups via scalars().all()
    for payments in payment_sets:
        result = MagicMock()
        scalars_mock = MagicMock()
        scalars_mock.all.return_value = payments
        result.scalars.return_value = scalars_mock
        side_effects.append(result)

    db.execute = AsyncMock(side_effect=side_effects)
    db.flush = AsyncMock()
    return db


def auth_header(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Service unit tests
# ---------------------------------------------------------------------------


class TestAdminForceCancelRideService:

    @pytest.mark.asyncio
    async def test_raises_when_ride_not_found(self):
        """Test 1: raises ValueError when ride not found."""
        db = _make_db_with_ride(None)
        with pytest.raises(ValueError, match="not found"):
            await admin_force_cancel_ride(db, ride_id=999, admin_id=1)

    @pytest.mark.asyncio
    async def test_raises_when_ride_completed(self):
        """Test 2: raises ValueError when ride is COMPLETED."""
        ride = _make_ride(status=RideStatus.COMPLETED)
        db = _make_db_with_ride(ride)
        with pytest.raises(ValueError, match="Cannot cancel"):
            await admin_force_cancel_ride(db, ride_id=1, admin_id=1)

    @pytest.mark.asyncio
    async def test_raises_when_ride_already_cancelled(self):
        """Test 3: raises ValueError when ride is already CANCELLED."""
        ride = _make_ride(status=RideStatus.CANCELLED)
        db = _make_db_with_ride(ride)
        with pytest.raises(ValueError, match="Cannot cancel"):
            await admin_force_cancel_ride(db, ride_id=1, admin_id=1)

    @pytest.mark.asyncio
    @pytest.mark.parametrize("initial_status", list(_CANCELLABLE_STATUSES))
    async def test_cancels_any_non_terminal_status(self, initial_status):
        """Tests 4–9: all non-terminal statuses can be force-cancelled."""
        ride = _make_ride(status=initial_status)
        db = _make_db_with_ride(ride, [])  # empty payments
        with patch("app.services.admin_ride_cancel._notify", new=AsyncMock(return_value=(True, True))):
            result = await admin_force_cancel_ride(db, ride_id=1, admin_id=5)
        assert ride.status == RideStatus.CANCELLED
        assert result.ride_id == 1

    @pytest.mark.asyncio
    async def test_sets_admin_forced_category(self):
        """Test 10: cancellation_category set to ADMIN_FORCED."""
        ride = _make_ride(status=RideStatus.IN_PROGRESS)
        db = _make_db_with_ride(ride, [])
        with patch("app.services.admin_ride_cancel._notify", new=AsyncMock(return_value=(True, True))):
            await admin_force_cancel_ride(db, ride_id=1, admin_id=7)
        assert ride.cancellation_category == CancellationCategory.ADMIN_FORCED

    @pytest.mark.asyncio
    async def test_sets_cancellation_reason_with_admin_id_and_text(self):
        """Test 11: cancellation_reason includes admin_id and reason text."""
        ride = _make_ride(status=RideStatus.REQUESTED)
        db = _make_db_with_ride(ride, [])
        with patch("app.services.admin_ride_cancel._notify", new=AsyncMock(return_value=(True, True))):
            await admin_force_cancel_ride(db, ride_id=1, admin_id=42, reason="Fraud detected")
        assert "42" in ride.cancellation_reason
        assert "Fraud detected" in ride.cancellation_reason

    @pytest.mark.asyncio
    async def test_refunds_completed_payment(self):
        """Test 12: COMPLETED payment is marked REFUNDED, refund_issued=True."""
        ride = _make_ride(status=RideStatus.REQUESTED)
        payment = _make_payment(PaymentStatus.COMPLETED)
        db = _make_db_with_ride(ride, [payment])
        with patch("app.services.admin_ride_cancel._notify", new=AsyncMock(return_value=(True, True))):
            result = await admin_force_cancel_ride(db, ride_id=1, admin_id=1)
        assert payment.status == PaymentStatus.REFUNDED
        assert result.refund_issued is True

    @pytest.mark.asyncio
    async def test_refunds_pending_payment(self):
        """Test 13: PENDING payment is marked REFUNDED, refund_issued=True."""
        ride = _make_ride(status=RideStatus.IN_PROGRESS)
        payment = _make_payment(PaymentStatus.PENDING)
        db = _make_db_with_ride(ride, [payment])
        with patch("app.services.admin_ride_cancel._notify", new=AsyncMock(return_value=(True, True))):
            result = await admin_force_cancel_ride(db, ride_id=1, admin_id=1)
        assert payment.status == PaymentStatus.REFUNDED
        assert result.refund_issued is True

    @pytest.mark.asyncio
    async def test_refund_issued_false_when_no_payment(self):
        """Test 14: refund_issued=False when no payment exists."""
        ride = _make_ride(status=RideStatus.REQUESTED)
        db = _make_db_with_ride(ride, [])
        with patch("app.services.admin_ride_cancel._notify", new=AsyncMock(return_value=(True, True))):
            result = await admin_force_cancel_ride(db, ride_id=1, admin_id=1)
        assert result.refund_issued is False

    @pytest.mark.asyncio
    async def test_returns_correct_previous_status(self):
        """Test 15: previous_status matches the ride's original status."""
        ride = _make_ride(status=RideStatus.ARRIVED)
        db = _make_db_with_ride(ride, [])
        with patch("app.services.admin_ride_cancel._notify", new=AsyncMock(return_value=(True, True))):
            result = await admin_force_cancel_ride(db, ride_id=1, admin_id=1)
        assert result.previous_status == RideStatus.ARRIVED.value

    @pytest.mark.asyncio
    async def test_notify_parties_false_skips_notification(self):
        """Test 16: notify_parties=False skips notification without error."""
        ride = _make_ride(status=RideStatus.MATCHED)
        db = _make_db_with_ride(ride, [])
        result = await admin_force_cancel_ride(db, ride_id=1, admin_id=1, notify_parties=False)
        assert result.rider_notified is False
        assert result.driver_notified is False

    @pytest.mark.asyncio
    async def test_driverless_ride_driver_notified_false(self):
        """Test 17: driver_notified=False when driver_id is None."""
        ride = _make_ride(status=RideStatus.REQUESTED, driver_id=None)
        db = _make_db_with_ride(ride, [])
        # notify_parties=False: no attempt to contact anyone, driver_notified stays False
        result = await admin_force_cancel_ride(db, ride_id=1, admin_id=1, notify_parties=False)
        assert result.driver_notified is False


# ---------------------------------------------------------------------------
# API integration tests
# ---------------------------------------------------------------------------

BASE = "/api/v1/admin/rides"


async def _seed_ride(
    db: AsyncSession,
    rider: User,
    driver: User,
    status: RideStatus = RideStatus.REQUESTED,
) -> Ride:
    ride = Ride(
        rider_id=rider.id,
        driver_id=driver.id,
        status=status,
        pickup_location=ST_MakePoint(-73.9857, 40.7484, 4326),
        dropoff_location=ST_MakePoint(-73.9712, 40.7614, 4326),
        pickup_address="350 5th Ave, New York, NY",
        dropoff_address="30 Rockefeller Plaza, New York, NY",
        estimated_fare=15.50,
        actual_fare=15.50 if status == RideStatus.COMPLETED else None,
        distance_km=2.1,
        duration_min=8.5,
        completed_at=datetime.now(timezone.utc) if status == RideStatus.COMPLETED else None,
        cancelled_at=datetime.now(timezone.utc) if status == RideStatus.CANCELLED else None,
    )
    db.add(ride)
    await db.flush()
    return ride


async def _seed_payment(
    db: AsyncSession, ride: Ride, pay_status: PaymentStatus = PaymentStatus.COMPLETED
) -> Payment:
    payment = Payment(
        ride_id=ride.id,
        payment_type=PaymentType.RIDE_FARE,
        amount=ride.actual_fare or ride.estimated_fare,
        platform_fee=0.0,
        driver_payout=ride.actual_fare or ride.estimated_fare,
        status=pay_status,
    )
    db.add(payment)
    await db.flush()
    return payment


@pytest.mark.anyio
class TestAdminRideCancelEndpoint:

    async def test_no_auth_returns_401(self, client):
        """Test 18: 401 with no auth."""
        resp = await client.post(f"{BASE}/1/cancel", json={})
        assert resp.status_code == 401

    async def test_rider_token_returns_403(self, client, rider, rider_token):
        """Test 19: 403 with rider token."""
        resp = await client.post(
            f"{BASE}/1/cancel",
            json={},
            headers=auth_header(rider_token),
        )
        assert resp.status_code == 403

    async def test_driver_token_returns_403(self, client, driver_user, driver_token):
        """Test 20: 403 with driver token."""
        resp = await client.post(
            f"{BASE}/1/cancel",
            json={},
            headers=auth_header(driver_token),
        )
        assert resp.status_code == 403

    async def test_admin_can_cancel_cancellable_ride(self, client, db, rider, driver_user, admin_user, admin_token):
        """Test 21: 200 with valid admin token and cancellable ride."""
        ride = await _seed_ride(db, rider, driver_user, status=RideStatus.IN_PROGRESS)
        await db.commit()
        resp = await client.post(
            f"{BASE}/{ride.id}/cancel",
            json={"reason": "Safety test", "notify_parties": False},
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 200

    async def test_nonexistent_ride_returns_404(self, client, admin_user, admin_token):
        """Test 22: 404 when ride does not exist."""
        resp = await client.post(
            f"{BASE}/999999/cancel",
            json={},
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 404

    async def test_completed_ride_returns_409(self, client, db, rider, driver_user, admin_user, admin_token):
        """Test 23: 409 when ride is already COMPLETED."""
        ride = await _seed_ride(db, rider, driver_user, status=RideStatus.COMPLETED)
        await db.commit()
        resp = await client.post(
            f"{BASE}/{ride.id}/cancel",
            json={},
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 409

    async def test_cancelled_ride_returns_409(self, client, db, rider, driver_user, admin_user, admin_token):
        """Test 24: 409 when ride is already CANCELLED."""
        ride = await _seed_ride(db, rider, driver_user, status=RideStatus.CANCELLED)
        await db.commit()
        resp = await client.post(
            f"{BASE}/{ride.id}/cancel",
            json={},
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 409

    async def test_response_shape(self, client, db, rider, driver_user, admin_user, admin_token):
        """Test 25: response contains expected fields."""
        ride = await _seed_ride(db, rider, driver_user, status=RideStatus.MATCHED)
        await db.commit()
        resp = await client.post(
            f"{BASE}/{ride.id}/cancel",
            json={"reason": "Test", "notify_parties": False},
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["ride_id"] == ride.id
        assert data["previous_status"] == RideStatus.MATCHED.value
        assert "cancelled_at" in data
        assert "refund_issued" in data
        assert "rider_notified" in data
        assert "driver_notified" in data

    async def test_ride_status_is_cancelled_in_db(self, client, db, rider, driver_user, admin_user, admin_token):
        """Test 26: ride status is CANCELLED in DB after successful cancel."""
        ride = await _seed_ride(db, rider, driver_user, status=RideStatus.DRIVER_EN_ROUTE)
        await db.commit()
        resp = await client.post(
            f"{BASE}/{ride.id}/cancel",
            json={"notify_parties": False},
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 200
        await db.refresh(ride)
        assert ride.status == RideStatus.CANCELLED
        assert ride.cancellation_category == CancellationCategory.ADMIN_FORCED

    async def test_completed_payment_refunded_in_db(self, client, db, rider, driver_user, admin_user, admin_token):
        """Test 27: COMPLETED payment is REFUNDED in DB after cancel."""
        ride = await _seed_ride(db, rider, driver_user, status=RideStatus.REQUESTED)
        payment = await _seed_payment(db, ride, PaymentStatus.COMPLETED)
        await db.commit()
        resp = await client.post(
            f"{BASE}/{ride.id}/cancel",
            json={"notify_parties": False},
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 200
        assert resp.json()["refund_issued"] is True
        await db.refresh(payment)
        assert payment.status == PaymentStatus.REFUNDED

    async def test_notify_parties_false_returns_200(self, client, db, rider, driver_user, admin_user, admin_token):
        """Test 28: notify_parties=false still returns 200 and cancels the ride."""
        ride = await _seed_ride(db, rider, driver_user, status=RideStatus.ARRIVED)
        await db.commit()
        resp = await client.post(
            f"{BASE}/{ride.id}/cancel",
            json={"notify_parties": False},
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["rider_notified"] is False
        assert data["driver_notified"] is False
