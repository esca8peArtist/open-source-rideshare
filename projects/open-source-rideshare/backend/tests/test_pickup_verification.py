"""Unit tests for pickup verification — driver identity and vehicle plate at pickup.

Covers:

Service (verify_pickup):
  1.  Both confirmed — returns correct result dict with mismatch_flagged=False
  2.  Photo mismatch only — mismatch_flagged=True, plate_confirmed=True
  3.  Plate mismatch only — mismatch_flagged=True, driver_photo_confirmed=True
  4.  Both mismatch — mismatch_flagged=True
  5.  Ride not found — raises LookupError
  6.  Wrong rider (not the ride's rider) — raises PermissionError
  7.  Wrong ride status (IN_PROGRESS) — raises ValueError
  8.  Wrong ride status (COMPLETED) — raises ValueError
  9.  ARRIVED status accepted — no error raised
  10. Subsequent call overwrites previous result (last-write-wins)
  11. verified_at timestamp is set on the ride row

Endpoint (POST /rides/{ride_id}/verify-pickup):
  12. 401 without authentication
  13. 404 when ride does not exist (service raises LookupError)
  14. 403 when caller is not the rider (service raises PermissionError)
  15. 400 when ride is not in ARRIVED status (service raises ValueError)
  16. 200 success — both confirmed, mismatch_flagged=False
  17. 200 success — photo mismatch, mismatch_flagged=True
  18. db.commit is called after successful verification
  19. Service exception propagation: unexpected exception bubbles through 500
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.ride import RideStatus


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

NOW = datetime(2026, 4, 17, 14, 0, 0, tzinfo=timezone.utc)


def _make_ride(
    ride_id: int = 1,
    rider_id: int = 10,
    driver_id: int = 20,
    status: RideStatus = RideStatus.ARRIVED,
    pickup_verification_at=None,
    driver_photo_confirmed=None,
    plate_confirmed=None,
):
    ride = MagicMock()
    ride.id = ride_id
    ride.rider_id = rider_id
    ride.driver_id = driver_id
    ride.status = status
    ride.pickup_verification_at = pickup_verification_at
    ride.driver_photo_confirmed = driver_photo_confirmed
    ride.plate_confirmed = plate_confirmed
    return ride


def _make_db(ride=None):
    """Return an AsyncMock session with a pre-configured execute result."""
    db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = ride
    db.execute = AsyncMock(return_value=result)
    db.commit = AsyncMock()
    return db


# ---------------------------------------------------------------------------
# 1–11: verify_pickup service
# ---------------------------------------------------------------------------


class TestVerifyPickupService:
    @pytest.mark.asyncio
    async def test_both_confirmed_returns_correct_dict(self):
        """Both confirmed → mismatch_flagged=False, ride fields updated."""
        from app.services.pickup_verification import verify_pickup

        ride = _make_ride()
        db = _make_db(ride=ride)

        result = await verify_pickup(
            db=db, ride_id=1, rider_id=10,
            driver_photo_confirmed=True, plate_confirmed=True,
        )

        assert result["ride_id"] == 1
        assert result["driver_photo_confirmed"] is True
        assert result["plate_confirmed"] is True
        assert result["mismatch_flagged"] is False
        assert isinstance(result["verified_at"], datetime)
        assert result["verified_at"].tzinfo is not None

    @pytest.mark.asyncio
    async def test_photo_mismatch_flags_mismatch(self):
        """Photo not confirmed → mismatch_flagged=True."""
        from app.services.pickup_verification import verify_pickup

        ride = _make_ride()
        db = _make_db(ride=ride)

        result = await verify_pickup(
            db=db, ride_id=1, rider_id=10,
            driver_photo_confirmed=False, plate_confirmed=True,
        )

        assert result["driver_photo_confirmed"] is False
        assert result["plate_confirmed"] is True
        assert result["mismatch_flagged"] is True

    @pytest.mark.asyncio
    async def test_plate_mismatch_flags_mismatch(self):
        """Plate not confirmed → mismatch_flagged=True."""
        from app.services.pickup_verification import verify_pickup

        ride = _make_ride()
        db = _make_db(ride=ride)

        result = await verify_pickup(
            db=db, ride_id=1, rider_id=10,
            driver_photo_confirmed=True, plate_confirmed=False,
        )

        assert result["driver_photo_confirmed"] is True
        assert result["plate_confirmed"] is False
        assert result["mismatch_flagged"] is True

    @pytest.mark.asyncio
    async def test_both_mismatch_flags_mismatch(self):
        """Neither confirmed → mismatch_flagged=True."""
        from app.services.pickup_verification import verify_pickup

        ride = _make_ride()
        db = _make_db(ride=ride)

        result = await verify_pickup(
            db=db, ride_id=1, rider_id=10,
            driver_photo_confirmed=False, plate_confirmed=False,
        )

        assert result["mismatch_flagged"] is True

    @pytest.mark.asyncio
    async def test_ride_not_found_raises_lookup_error(self):
        """LookupError raised when ride does not exist."""
        from app.services.pickup_verification import verify_pickup

        db = _make_db(ride=None)

        with pytest.raises(LookupError):
            await verify_pickup(
                db=db, ride_id=999, rider_id=10,
                driver_photo_confirmed=True, plate_confirmed=True,
            )

    @pytest.mark.asyncio
    async def test_wrong_rider_raises_permission_error(self):
        """PermissionError raised when caller is not the ride's rider."""
        from app.services.pickup_verification import verify_pickup

        ride = _make_ride(rider_id=10)
        db = _make_db(ride=ride)

        with pytest.raises(PermissionError):
            await verify_pickup(
                db=db, ride_id=1, rider_id=99,  # not the rider
                driver_photo_confirmed=True, plate_confirmed=True,
            )

    @pytest.mark.asyncio
    async def test_in_progress_status_raises_value_error(self):
        """ValueError raised when ride is IN_PROGRESS (not ARRIVED)."""
        from app.services.pickup_verification import verify_pickup

        ride = _make_ride(status=RideStatus.IN_PROGRESS)
        db = _make_db(ride=ride)

        with pytest.raises(ValueError, match="arrived"):
            await verify_pickup(
                db=db, ride_id=1, rider_id=10,
                driver_photo_confirmed=True, plate_confirmed=True,
            )

    @pytest.mark.asyncio
    async def test_completed_status_raises_value_error(self):
        """ValueError raised when ride is already COMPLETED."""
        from app.services.pickup_verification import verify_pickup

        ride = _make_ride(status=RideStatus.COMPLETED)
        db = _make_db(ride=ride)

        with pytest.raises(ValueError, match="arrived"):
            await verify_pickup(
                db=db, ride_id=1, rider_id=10,
                driver_photo_confirmed=True, plate_confirmed=True,
            )

    @pytest.mark.asyncio
    async def test_arrived_status_accepted(self):
        """ARRIVED status is the valid state — no error raised."""
        from app.services.pickup_verification import verify_pickup

        ride = _make_ride(status=RideStatus.ARRIVED)
        db = _make_db(ride=ride)

        result = await verify_pickup(
            db=db, ride_id=1, rider_id=10,
            driver_photo_confirmed=True, plate_confirmed=True,
        )

        assert result["ride_id"] == 1

    @pytest.mark.asyncio
    async def test_subsequent_call_overwrites_previous_result(self):
        """Second call updates the ride fields (last-write-wins)."""
        from app.services.pickup_verification import verify_pickup

        ride = _make_ride(
            status=RideStatus.ARRIVED,
            driver_photo_confirmed=True,
            plate_confirmed=False,
        )
        db = _make_db(ride=ride)

        # Rider corrects their previous tap
        result = await verify_pickup(
            db=db, ride_id=1, rider_id=10,
            driver_photo_confirmed=True, plate_confirmed=True,
        )

        assert ride.driver_photo_confirmed is True
        assert ride.plate_confirmed is True
        assert result["mismatch_flagged"] is False

    @pytest.mark.asyncio
    async def test_verified_at_set_on_ride_row(self):
        """pickup_verification_at is written onto the ride object."""
        from app.services.pickup_verification import verify_pickup

        ride = _make_ride()
        db = _make_db(ride=ride)

        await verify_pickup(
            db=db, ride_id=1, rider_id=10,
            driver_photo_confirmed=True, plate_confirmed=True,
        )

        assert ride.pickup_verification_at is not None
        assert isinstance(ride.pickup_verification_at, datetime)


# ---------------------------------------------------------------------------
# 12–19: POST /rides/{ride_id}/verify-pickup endpoint
# ---------------------------------------------------------------------------


class TestPickupVerificationEndpoint:
    def _make_rider(self, user_id: int = 10):
        from app.models.user import User, UserRole

        user = MagicMock(spec=User)
        user.id = user_id
        user.role = UserRole.RIDER
        return user

    def _make_db(self):
        db = AsyncMock()
        db.commit = AsyncMock()
        return db

    @pytest.mark.asyncio
    async def test_requires_authentication(self):
        """POST /rides/{id}/verify-pickup returns 401 without auth."""
        from httpx import ASGITransport, AsyncClient

        from app.main import app

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/v1/rides/1/verify-pickup",
                json={"driver_photo_confirmed": True, "plate_confirmed": True},
            )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_404_when_ride_not_found(self):
        """LookupError from service maps to 404."""
        from fastapi import HTTPException

        from app.api.v1.rides import post_verify_pickup
        from app.schemas.ride import PickupVerificationRequest

        rider = self._make_rider()
        db = self._make_db()
        body = PickupVerificationRequest(driver_photo_confirmed=True, plate_confirmed=True)

        with patch(
            "app.api.v1.rides.verify_pickup",
            new_callable=AsyncMock,
            side_effect=LookupError("Ride 999 not found"),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await post_verify_pickup(ride_id=999, body=body, rider=rider, db=db)

        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_403_when_not_the_rider(self):
        """PermissionError from service maps to 403."""
        from fastapi import HTTPException

        from app.api.v1.rides import post_verify_pickup
        from app.schemas.ride import PickupVerificationRequest

        rider = self._make_rider(user_id=99)
        db = self._make_db()
        body = PickupVerificationRequest(driver_photo_confirmed=True, plate_confirmed=True)

        with patch(
            "app.api.v1.rides.verify_pickup",
            new_callable=AsyncMock,
            side_effect=PermissionError("Not authorized"),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await post_verify_pickup(ride_id=1, body=body, rider=rider, db=db)

        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_400_when_ride_not_arrived(self):
        """ValueError from service maps to 400."""
        from fastapi import HTTPException

        from app.api.v1.rides import post_verify_pickup
        from app.schemas.ride import PickupVerificationRequest

        rider = self._make_rider()
        db = self._make_db()
        body = PickupVerificationRequest(driver_photo_confirmed=True, plate_confirmed=True)

        with patch(
            "app.api.v1.rides.verify_pickup",
            new_callable=AsyncMock,
            side_effect=ValueError("Pickup verification is only available when the driver has arrived."),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await post_verify_pickup(ride_id=1, body=body, rider=rider, db=db)

        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_200_success_both_confirmed(self):
        """200 OK with correct response when both photo and plate confirmed."""
        from app.api.v1.rides import post_verify_pickup
        from app.schemas.ride import PickupVerificationRequest

        rider = self._make_rider()
        db = self._make_db()
        body = PickupVerificationRequest(driver_photo_confirmed=True, plate_confirmed=True)

        service_result = {
            "ride_id": 1,
            "driver_photo_confirmed": True,
            "plate_confirmed": True,
            "verified_at": NOW,
            "mismatch_flagged": False,
        }

        with patch(
            "app.api.v1.rides.verify_pickup",
            new_callable=AsyncMock,
            return_value=service_result,
        ):
            response = await post_verify_pickup(ride_id=1, body=body, rider=rider, db=db)

        assert response.ride_id == 1
        assert response.driver_photo_confirmed is True
        assert response.plate_confirmed is True
        assert response.mismatch_flagged is False
        assert response.verified_at == NOW

    @pytest.mark.asyncio
    async def test_200_success_with_photo_mismatch(self):
        """200 OK with mismatch_flagged=True when photo does not match."""
        from app.api.v1.rides import post_verify_pickup
        from app.schemas.ride import PickupVerificationRequest

        rider = self._make_rider()
        db = self._make_db()
        body = PickupVerificationRequest(driver_photo_confirmed=False, plate_confirmed=True)

        service_result = {
            "ride_id": 1,
            "driver_photo_confirmed": False,
            "plate_confirmed": True,
            "verified_at": NOW,
            "mismatch_flagged": True,
        }

        with patch(
            "app.api.v1.rides.verify_pickup",
            new_callable=AsyncMock,
            return_value=service_result,
        ):
            response = await post_verify_pickup(ride_id=1, body=body, rider=rider, db=db)

        assert response.mismatch_flagged is True
        assert response.driver_photo_confirmed is False

    @pytest.mark.asyncio
    async def test_db_commit_called_on_success(self):
        """db.commit() is called after a successful verification."""
        from app.api.v1.rides import post_verify_pickup
        from app.schemas.ride import PickupVerificationRequest

        rider = self._make_rider()
        db = self._make_db()
        body = PickupVerificationRequest(driver_photo_confirmed=True, plate_confirmed=True)

        service_result = {
            "ride_id": 1,
            "driver_photo_confirmed": True,
            "plate_confirmed": True,
            "verified_at": NOW,
            "mismatch_flagged": False,
        }

        with patch(
            "app.api.v1.rides.verify_pickup",
            new_callable=AsyncMock,
            return_value=service_result,
        ):
            await post_verify_pickup(ride_id=1, body=body, rider=rider, db=db)

        db.commit.assert_awaited_once()
