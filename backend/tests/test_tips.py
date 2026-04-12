"""Tests for the driver tipping feature.

Covers:
- submit_tip service: success, duplicate, non-completed ride, 48h window,
  amount out of range, wrong rider, Stripe graceful degradation
- get_tip_for_ride service
- POST /rides/{ride_id}/tip endpoint
- GET  /rides/{ride_id}/tip endpoint (rider, driver, wrong user)
- GET  /drivers/me/tips endpoint (pagination, non-driver rejected)
- GET  /admin/tips endpoint (filters, non-admin rejected)

All tests mock the database via AsyncMock / MagicMock to avoid requiring
a live database, consistent with the pattern in test_payments.py.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.ride import RideStatus
from app.models.tip import TipRecord, TipStatus
from app.models.user import UserRole
from app.services.tips import TIP_MAX_CENTS, TIP_MIN_CENTS, TIP_WINDOW_HOURS, TipError, submit_tip, get_tip_for_ride


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _make_ride(
    ride_id: int = 1,
    rider_id: int = 10,
    driver_id: int = 20,
    status: RideStatus = RideStatus.COMPLETED,
    completed_at: datetime | None = None,
) -> MagicMock:
    ride = MagicMock()
    ride.id = ride_id
    ride.rider_id = rider_id
    ride.driver_id = driver_id
    ride.status = status
    ride.completed_at = completed_at if completed_at is not None else _utcnow() - timedelta(hours=1)
    return ride


def _make_rider(user_id: int = 10, role: UserRole = UserRole.RIDER) -> MagicMock:
    user = MagicMock()
    user.id = user_id
    user.role = role
    return user


def _make_tip(
    tip_id: int = 1,
    ride_id: int = 1,
    driver_id: int = 20,
    rider_id: int = 10,
    amount_cents: int = 500,
    status: TipStatus = TipStatus.PENDING,
) -> MagicMock:
    tip = MagicMock(spec=TipRecord)
    tip.id = tip_id
    tip.ride_id = ride_id
    tip.driver_id = driver_id
    tip.rider_id = rider_id
    tip.amount_cents = amount_cents
    tip.status = status
    tip.created_at = _utcnow()
    tip.stripe_payment_intent_id = None
    return tip


def _make_db(ride: MagicMock | None = None, existing_tip: MagicMock | None = None) -> AsyncMock:
    """Build a two-query db mock: first returns ride, second returns tip (or None)."""
    db = AsyncMock()

    ride_result = MagicMock()
    ride_result.scalar_one_or_none.return_value = ride

    tip_result = MagicMock()
    tip_result.scalar_one_or_none.return_value = existing_tip

    db.execute = AsyncMock(side_effect=[ride_result, tip_result])
    db.commit = AsyncMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.refresh = AsyncMock()
    return db


# ---------------------------------------------------------------------------
# submit_tip — service unit tests
# ---------------------------------------------------------------------------


class TestSubmitTipAmountValidation:
    @pytest.mark.asyncio
    async def test_rejects_amount_below_minimum(self):
        rider = _make_rider()
        db = AsyncMock()

        with pytest.raises(TipError) as exc_info:
            await submit_tip(db, ride_id=1, rider_user=rider, amount_cents=49)
        assert exc_info.value.status_code == 422
        assert "0.50" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_rejects_amount_above_maximum(self):
        rider = _make_rider()
        db = AsyncMock()

        with pytest.raises(TipError) as exc_info:
            await submit_tip(db, ride_id=1, rider_user=rider, amount_cents=5001)
        assert exc_info.value.status_code == 422
        assert "50.00" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_accepts_minimum_amount(self):
        ride = _make_ride()
        db = _make_db(ride=ride, existing_tip=None)

        with patch("app.services.tips.settings") as mock_settings, \
             patch("app.services.tips._notify_driver_tip", new_callable=AsyncMock):
            mock_settings.stripe_secret_key = ""
            await submit_tip(db, ride_id=1, rider_user=_make_rider(), amount_cents=TIP_MIN_CENTS)

        db.add.assert_called_once()
        added = db.add.call_args[0][0]
        assert added.amount_cents == TIP_MIN_CENTS

    @pytest.mark.asyncio
    async def test_accepts_maximum_amount(self):
        ride = _make_ride()
        db = _make_db(ride=ride, existing_tip=None)

        with patch("app.services.tips.settings") as mock_settings, \
             patch("app.services.tips._notify_driver_tip", new_callable=AsyncMock):
            mock_settings.stripe_secret_key = ""
            await submit_tip(db, ride_id=1, rider_user=_make_rider(), amount_cents=TIP_MAX_CENTS)

        added = db.add.call_args[0][0]
        assert added.amount_cents == TIP_MAX_CENTS


class TestSubmitTipRideValidation:
    @pytest.mark.asyncio
    async def test_rejects_when_ride_not_found(self):
        db = AsyncMock()
        no_ride_result = MagicMock()
        no_ride_result.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(return_value=no_ride_result)

        with pytest.raises(TipError) as exc_info:
            await submit_tip(db, ride_id=99, rider_user=_make_rider(), amount_cents=500)
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_rejects_non_completed_ride(self):
        ride = _make_ride(status=RideStatus.IN_PROGRESS)
        db = _make_db(ride=ride)

        with pytest.raises(TipError) as exc_info:
            await submit_tip(db, ride_id=1, rider_user=_make_rider(), amount_cents=500)
        assert exc_info.value.status_code == 409
        assert "completed" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_rejects_wrong_rider(self):
        ride = _make_ride(rider_id=10)
        db = _make_db(ride=ride)
        wrong_rider = _make_rider(user_id=99)

        with pytest.raises(TipError) as exc_info:
            await submit_tip(db, ride_id=1, rider_user=wrong_rider, amount_cents=500)
        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_rejects_duplicate_tip(self):
        ride = _make_ride()
        existing_tip = _make_tip()
        db = _make_db(ride=ride, existing_tip=existing_tip)

        with pytest.raises(TipError) as exc_info:
            await submit_tip(db, ride_id=1, rider_user=_make_rider(), amount_cents=500)
        assert exc_info.value.status_code == 409
        assert "already" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_rejects_tip_after_48h_window(self):
        completed_at = _utcnow() - timedelta(hours=TIP_WINDOW_HOURS + 1)
        ride = _make_ride(completed_at=completed_at)
        db = _make_db(ride=ride, existing_tip=None)

        with pytest.raises(TipError) as exc_info:
            await submit_tip(db, ride_id=1, rider_user=_make_rider(), amount_cents=500)
        assert exc_info.value.status_code == 409
        assert "48" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_accepts_tip_just_within_window(self):
        # 47h 59m ago — still within window
        completed_at = _utcnow() - timedelta(hours=TIP_WINDOW_HOURS - 1)
        ride = _make_ride(completed_at=completed_at)
        db = _make_db(ride=ride, existing_tip=None)

        with patch("app.services.tips.settings") as mock_settings, \
             patch("app.services.tips._notify_driver_tip", new_callable=AsyncMock):
            mock_settings.stripe_secret_key = ""
            await submit_tip(db, ride_id=1, rider_user=_make_rider(), amount_cents=500)

        db.add.assert_called_once()


class TestSubmitTipSuccess:
    @pytest.mark.asyncio
    async def test_creates_tip_record_without_stripe(self):
        ride = _make_ride()
        db = _make_db(ride=ride, existing_tip=None)

        with patch("app.services.tips.settings") as mock_settings, \
             patch("app.services.tips._notify_driver_tip", new_callable=AsyncMock):
            mock_settings.stripe_secret_key = ""
            await submit_tip(
                db,
                ride_id=1,
                rider_user=_make_rider(),
                amount_cents=750,
                message="Great ride!",
            )

        db.add.assert_called_once()
        tip_arg = db.add.call_args[0][0]
        assert isinstance(tip_arg, TipRecord)
        assert tip_arg.amount_cents == 750
        assert tip_arg.thank_you_message == "Great ride!"
        assert tip_arg.ride_id == 1
        assert tip_arg.rider_id == 10
        assert tip_arg.driver_id == 20
        assert tip_arg.status == TipStatus.PENDING
        db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_creates_stripe_intent_when_key_configured(self):
        ride = _make_ride()
        db = _make_db(ride=ride, existing_tip=None)

        mock_intent = MagicMock()
        mock_intent.id = "pi_tip_abc123"
        mock_intent.client_secret = "pi_tip_abc123_secret"

        with patch("app.services.tips.settings") as mock_settings, \
             patch("app.services.tips._notify_driver_tip", new_callable=AsyncMock), \
             patch("app.services.tips.stripe_lib") as mock_stripe:
            mock_settings.stripe_secret_key = "sk_test_fakekey"
            mock_stripe.PaymentIntent.create.return_value = mock_intent

            await submit_tip(db, ride_id=1, rider_user=_make_rider(), amount_cents=500)

        mock_stripe.PaymentIntent.create.assert_called_once_with(
            amount=500,
            currency="usd",
            metadata={
                "ride_id": "1",
                "driver_id": "20",
                "rider_id": "10",
                "type": "tip",
            },
            automatic_payment_methods={"enabled": True},
        )
        tip_arg = db.add.call_args[0][0]
        assert tip_arg.stripe_payment_intent_id == "pi_tip_abc123"

    @pytest.mark.asyncio
    async def test_graceful_when_stripe_raises(self):
        """Tip is saved even if Stripe call fails."""
        ride = _make_ride()
        db = _make_db(ride=ride, existing_tip=None)

        with patch("app.services.tips.settings") as mock_settings, \
             patch("app.services.tips._notify_driver_tip", new_callable=AsyncMock), \
             patch("app.services.tips.stripe_lib") as mock_stripe:
            mock_settings.stripe_secret_key = "sk_test_fakekey"
            mock_stripe.PaymentIntent.create.side_effect = Exception("Stripe unavailable")

            # Should not raise — tip is saved without intent ID
            await submit_tip(db, ride_id=1, rider_user=_make_rider(), amount_cents=500)

        db.add.assert_called_once()
        db.commit.assert_awaited_once()
        tip_arg = db.add.call_args[0][0]
        # stripe_payment_intent_id was never set because the call failed before assignment
        assert tip_arg.stripe_payment_intent_id is None

    @pytest.mark.asyncio
    async def test_sends_driver_notification(self):
        ride = _make_ride()
        db = _make_db(ride=ride, existing_tip=None)

        with patch("app.services.tips.settings") as mock_settings, \
             patch("app.services.tips._notify_driver_tip", new_callable=AsyncMock) as mock_notify:
            mock_settings.stripe_secret_key = ""
            await submit_tip(db, ride_id=1, rider_user=_make_rider(), amount_cents=500)

        mock_notify.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_tip_notification_failure_does_not_raise(self):
        """Notification errors must not bubble up through submit_tip."""
        ride = _make_ride()
        db = _make_db(ride=ride, existing_tip=None)

        with patch("app.services.tips.settings") as mock_settings, \
             patch("app.services.tips._notify_driver_tip", new_callable=AsyncMock) as mock_notify:
            mock_settings.stripe_secret_key = ""
            mock_notify.side_effect = Exception("Push provider down")

            # Should complete without raising
            await submit_tip(db, ride_id=1, rider_user=_make_rider(), amount_cents=500)

        db.commit.assert_awaited_once()


# ---------------------------------------------------------------------------
# get_tip_for_ride
# ---------------------------------------------------------------------------


class TestGetTipForRide:
    @pytest.mark.asyncio
    async def test_returns_tip_when_found(self):
        tip = _make_tip()
        db = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = tip
        db.execute = AsyncMock(return_value=result_mock)

        found = await get_tip_for_ride(db, ride_id=1)
        assert found is tip

    @pytest.mark.asyncio
    async def test_returns_none_when_not_found(self):
        db = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(return_value=result_mock)

        found = await get_tip_for_ride(db, ride_id=999)
        assert found is None


# ---------------------------------------------------------------------------
# API endpoint tests — using the HTTP client with DB override
# ---------------------------------------------------------------------------


def _make_tip_orm(
    tip_id: int = 1,
    ride_id: int = 1,
    driver_id: int = 20,
    rider_id: int = 10,
    amount_cents: int = 500,
    status: TipStatus = TipStatus.PENDING,
) -> MagicMock:
    """Build a mock that looks like a TipRecord ORM object for endpoint tests."""
    tip = MagicMock()
    tip.id = tip_id
    tip.ride_id = ride_id
    tip.driver_id = driver_id
    tip.rider_id = rider_id
    tip.amount_cents = amount_cents
    tip.status = status
    tip.created_at = _utcnow()
    return tip


class TestCreateTipEndpoint:
    @pytest.mark.asyncio
    async def test_submit_tip_success(self, client, rider, rider_token, driver_user):
        """Happy-path: rider submits a valid tip."""
        tip_record = _make_tip_orm(rider_id=rider.id, driver_id=driver_user.id)

        with patch("app.api.v1.tips.submit_tip", new_callable=AsyncMock, return_value=tip_record):
            resp = await client.post(
                "/api/v1/rides/1/tip",
                json={"amount_cents": 500},
                headers={"Authorization": f"Bearer {rider_token}"},
            )

        assert resp.status_code == 201
        body = resp.json()
        assert body["amount_cents"] == 500

    @pytest.mark.asyncio
    async def test_submit_tip_duplicate_returns_409(self, client, rider, rider_token):
        with patch(
            "app.api.v1.tips.submit_tip",
            new_callable=AsyncMock,
            side_effect=TipError("A tip has already been submitted for this ride", status_code=409),
        ):
            resp = await client.post(
                "/api/v1/rides/1/tip",
                json={"amount_cents": 500},
                headers={"Authorization": f"Bearer {rider_token}"},
            )

        assert resp.status_code == 409
        assert "already" in resp.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_submit_tip_non_completed_ride_returns_409(self, client, rider, rider_token):
        with patch(
            "app.api.v1.tips.submit_tip",
            new_callable=AsyncMock,
            side_effect=TipError("Tips can only be submitted for completed rides", status_code=409),
        ):
            resp = await client.post(
                "/api/v1/rides/1/tip",
                json={"amount_cents": 500},
                headers={"Authorization": f"Bearer {rider_token}"},
            )

        assert resp.status_code == 409
        assert "completed" in resp.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_submit_tip_after_window_returns_409(self, client, rider, rider_token):
        with patch(
            "app.api.v1.tips.submit_tip",
            new_callable=AsyncMock,
            side_effect=TipError("Tips must be submitted within 48 hours of ride completion", status_code=409),
        ):
            resp = await client.post(
                "/api/v1/rides/1/tip",
                json={"amount_cents": 500},
                headers={"Authorization": f"Bearer {rider_token}"},
            )

        assert resp.status_code == 409
        assert "48" in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_submit_tip_amount_below_min_returns_422(self, client, rider, rider_token):
        resp = await client.post(
            "/api/v1/rides/1/tip",
            json={"amount_cents": 49},
            headers={"Authorization": f"Bearer {rider_token}"},
        )
        # Pydantic rejects before service is called
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_submit_tip_amount_above_max_returns_422(self, client, rider, rider_token):
        resp = await client.post(
            "/api/v1/rides/1/tip",
            json={"amount_cents": 5001},
            headers={"Authorization": f"Bearer {rider_token}"},
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_submit_tip_wrong_rider_returns_403(self, client, rider, rider_token):
        with patch(
            "app.api.v1.tips.submit_tip",
            new_callable=AsyncMock,
            side_effect=TipError("Only the rider for this ride can submit a tip", status_code=403),
        ):
            resp = await client.post(
                "/api/v1/rides/1/tip",
                json={"amount_cents": 500},
                headers={"Authorization": f"Bearer {rider_token}"},
            )

        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_submit_tip_unauthenticated_returns_403(self, client):
        resp = await client.post("/api/v1/rides/1/tip", json={"amount_cents": 500})
        assert resp.status_code in (401, 403)


class TestGetRideTipEndpoint:
    @pytest.mark.asyncio
    async def test_rider_can_view_tip(self, client, rider, rider_token, driver_user, db):
        from app.models.ride import Ride

        # Insert ride owned by rider
        ride = Ride(
            rider_id=rider.id,
            driver_id=driver_user.id,
            status=RideStatus.COMPLETED,
            pickup_location="SRID=4326;POINT(-73.9857 40.7484)",
            dropoff_location="SRID=4326;POINT(-73.9857 40.7484)",
            pickup_address="A",
            dropoff_address="B",
            estimated_fare=15.0,
            actual_fare=15.0,
        )
        db.add(ride)
        await db.flush()

        tip = TipRecord(
            ride_id=ride.id,
            driver_id=driver_user.id,
            rider_id=rider.id,
            amount_cents=300,
            status=TipStatus.PENDING,
        )
        db.add(tip)
        await db.flush()

        resp = await client.get(
            f"/api/v1/rides/{ride.id}/tip",
            headers={"Authorization": f"Bearer {rider_token}"},
        )
        assert resp.status_code == 200
        assert resp.json()["amount_cents"] == 300

    @pytest.mark.asyncio
    async def test_driver_can_view_their_tip(self, client, rider, driver_user, driver_token, db):
        from app.models.ride import Ride

        ride = Ride(
            rider_id=rider.id,
            driver_id=driver_user.id,
            status=RideStatus.COMPLETED,
            pickup_location="SRID=4326;POINT(-73.9857 40.7484)",
            dropoff_location="SRID=4326;POINT(-73.9857 40.7484)",
            pickup_address="A",
            dropoff_address="B",
            estimated_fare=15.0,
            actual_fare=15.0,
        )
        db.add(ride)
        await db.flush()

        tip = TipRecord(
            ride_id=ride.id,
            driver_id=driver_user.id,
            rider_id=rider.id,
            amount_cents=400,
            status=TipStatus.PENDING,
        )
        db.add(tip)
        await db.flush()

        resp = await client.get(
            f"/api/v1/rides/{ride.id}/tip",
            headers={"Authorization": f"Bearer {driver_token}"},
        )
        assert resp.status_code == 200
        assert resp.json()["amount_cents"] == 400

    @pytest.mark.asyncio
    async def test_unrelated_user_cannot_view_tip(self, client, rider, driver_user, db):
        """A rider who didn't take this ride should get 403."""
        from app.models.ride import Ride
        from app.services.auth import create_access_token, hash_password
        from app.models.user import User

        # Create a second rider (stranger)
        stranger = User(
            phone="+15559001234",
            name="Stranger",
            email="stranger@test.com",
            password_hash=hash_password("pass"),
            role=UserRole.RIDER,
            is_active=True,
        )
        db.add(stranger)
        await db.flush()
        stranger_token = create_access_token(stranger.id, stranger.role.value)

        ride = Ride(
            rider_id=rider.id,
            driver_id=driver_user.id,
            status=RideStatus.COMPLETED,
            pickup_location="SRID=4326;POINT(-73.9857 40.7484)",
            dropoff_location="SRID=4326;POINT(-73.9857 40.7484)",
            pickup_address="A",
            dropoff_address="B",
            estimated_fare=15.0,
            actual_fare=15.0,
        )
        db.add(ride)
        await db.flush()

        tip = TipRecord(
            ride_id=ride.id,
            driver_id=driver_user.id,
            rider_id=rider.id,
            amount_cents=500,
            status=TipStatus.PENDING,
        )
        db.add(tip)
        await db.flush()

        resp = await client.get(
            f"/api/v1/rides/{ride.id}/tip",
            headers={"Authorization": f"Bearer {stranger_token}"},
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_returns_404_when_no_tip(self, client, rider, rider_token, driver_user, db):
        from app.models.ride import Ride

        ride = Ride(
            rider_id=rider.id,
            driver_id=driver_user.id,
            status=RideStatus.COMPLETED,
            pickup_location="SRID=4326;POINT(-73.9857 40.7484)",
            dropoff_location="SRID=4326;POINT(-73.9857 40.7484)",
            pickup_address="A",
            dropoff_address="B",
            estimated_fare=15.0,
            actual_fare=15.0,
        )
        db.add(ride)
        await db.flush()

        resp = await client.get(
            f"/api/v1/rides/{ride.id}/tip",
            headers={"Authorization": f"Bearer {rider_token}"},
        )
        assert resp.status_code == 404


class TestDriverMyTipsEndpoint:
    @pytest.mark.asyncio
    async def test_driver_can_list_tips(self, client, driver_user, driver_token, rider, db):
        from app.models.ride import Ride

        ride = Ride(
            rider_id=rider.id,
            driver_id=driver_user.id,
            status=RideStatus.COMPLETED,
            pickup_location="SRID=4326;POINT(-73.9857 40.7484)",
            dropoff_location="SRID=4326;POINT(-73.9857 40.7484)",
            pickup_address="A",
            dropoff_address="B",
            estimated_fare=10.0,
            actual_fare=10.0,
        )
        db.add(ride)
        await db.flush()

        tip = TipRecord(
            ride_id=ride.id,
            driver_id=driver_user.id,
            rider_id=rider.id,
            amount_cents=200,
            status=TipStatus.PENDING,
        )
        db.add(tip)
        await db.flush()

        resp = await client.get(
            "/api/v1/drivers/me/tips",
            headers={"Authorization": f"Bearer {driver_token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert any(t["amount_cents"] == 200 for t in data)

    @pytest.mark.asyncio
    async def test_rider_cannot_access_driver_tips_endpoint(self, client, rider_token):
        resp = await client.get(
            "/api/v1/drivers/me/tips",
            headers={"Authorization": f"Bearer {rider_token}"},
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_pagination_limit_and_offset(self, client, driver_user, driver_token, rider, db):
        from app.models.ride import Ride

        # Insert 3 tips
        for i in range(3):
            ride = Ride(
                rider_id=rider.id,
                driver_id=driver_user.id,
                status=RideStatus.COMPLETED,
                pickup_location="SRID=4326;POINT(-73.9857 40.7484)",
                dropoff_location="SRID=4326;POINT(-73.9857 40.7484)",
                pickup_address="A",
                dropoff_address="B",
                estimated_fare=10.0,
                actual_fare=10.0,
            )
            db.add(ride)
            await db.flush()
            tip = TipRecord(
                ride_id=ride.id,
                driver_id=driver_user.id,
                rider_id=rider.id,
                amount_cents=100 * (i + 1),
                status=TipStatus.PENDING,
            )
            db.add(tip)
            await db.flush()

        resp = await client.get(
            "/api/v1/drivers/me/tips?limit=2&offset=0",
            headers={"Authorization": f"Bearer {driver_token}"},
        )
        assert resp.status_code == 200
        assert len(resp.json()) <= 2


class TestAdminTipsEndpoint:
    @pytest.mark.asyncio
    async def test_admin_can_list_all_tips(self, client, admin_user, admin_token, rider, driver_user, db):
        from app.models.ride import Ride

        ride = Ride(
            rider_id=rider.id,
            driver_id=driver_user.id,
            status=RideStatus.COMPLETED,
            pickup_location="SRID=4326;POINT(-73.9857 40.7484)",
            dropoff_location="SRID=4326;POINT(-73.9857 40.7484)",
            pickup_address="A",
            dropoff_address="B",
            estimated_fare=12.0,
            actual_fare=12.0,
        )
        db.add(ride)
        await db.flush()

        tip = TipRecord(
            ride_id=ride.id,
            driver_id=driver_user.id,
            rider_id=rider.id,
            amount_cents=1000,
            status=TipStatus.PENDING,
        )
        db.add(tip)
        await db.flush()

        resp = await client.get(
            "/api/v1/admin/tips",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert any(t["amount_cents"] == 1000 for t in data)

    @pytest.mark.asyncio
    async def test_non_admin_cannot_access_admin_tips(self, client, rider_token):
        resp = await client.get(
            "/api/v1/admin/tips",
            headers={"Authorization": f"Bearer {rider_token}"},
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_admin_tips_filter_by_driver(self, client, admin_token, rider, driver_user, db):
        from app.models.ride import Ride

        ride = Ride(
            rider_id=rider.id,
            driver_id=driver_user.id,
            status=RideStatus.COMPLETED,
            pickup_location="SRID=4326;POINT(-73.9857 40.7484)",
            dropoff_location="SRID=4326;POINT(-73.9857 40.7484)",
            pickup_address="A",
            dropoff_address="B",
            estimated_fare=10.0,
            actual_fare=10.0,
        )
        db.add(ride)
        await db.flush()

        tip = TipRecord(
            ride_id=ride.id,
            driver_id=driver_user.id,
            rider_id=rider.id,
            amount_cents=600,
            status=TipStatus.PENDING,
        )
        db.add(tip)
        await db.flush()

        resp = await client.get(
            f"/api/v1/admin/tips?driver_id={driver_user.id}",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert all(t["driver_id"] == driver_user.id for t in data)

    @pytest.mark.asyncio
    async def test_admin_tips_filter_by_status(self, client, admin_token, rider, driver_user, db):
        from app.models.ride import Ride

        ride = Ride(
            rider_id=rider.id,
            driver_id=driver_user.id,
            status=RideStatus.COMPLETED,
            pickup_location="SRID=4326;POINT(-73.9857 40.7484)",
            dropoff_location="SRID=4326;POINT(-73.9857 40.7484)",
            pickup_address="A",
            dropoff_address="B",
            estimated_fare=10.0,
            actual_fare=10.0,
        )
        db.add(ride)
        await db.flush()

        tip = TipRecord(
            ride_id=ride.id,
            driver_id=driver_user.id,
            rider_id=rider.id,
            amount_cents=250,
            status=TipStatus.COMPLETED,
        )
        db.add(tip)
        await db.flush()

        resp = await client.get(
            "/api/v1/admin/tips?status=completed",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert all(t["status"] == "completed" for t in data)


# ---------------------------------------------------------------------------
# Graceful Stripe degradation (no credentials configured)
# ---------------------------------------------------------------------------


class TestStripeGracefulDegradation:
    @pytest.mark.asyncio
    async def test_tip_saved_without_stripe_key(self):
        """When OPENRIDE_STRIPE_SECRET_KEY is empty, tip is stored without intent ID."""
        ride = _make_ride()
        db = _make_db(ride=ride, existing_tip=None)

        with patch("app.services.tips.settings") as mock_settings, \
             patch("app.services.tips._notify_driver_tip", new_callable=AsyncMock):
            mock_settings.stripe_secret_key = ""  # no key
            await submit_tip(db, ride_id=1, rider_user=_make_rider(), amount_cents=500)

        tip_arg = db.add.call_args[0][0]
        assert tip_arg.stripe_payment_intent_id is None
        assert tip_arg.status == TipStatus.PENDING
        db.commit.assert_awaited_once()
