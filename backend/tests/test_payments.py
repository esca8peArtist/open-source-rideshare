from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import app.models.user  # noqa: F401 — ensures User mapper is registered
import app.models.driver  # noqa: F401 — ensures DriverProfile mapper is registered
import app.models.ride  # noqa: F401 — ensures Ride mapper is registered
from app.models.payment import Payment, PaymentStatus
from app.services.payments import (
    add_tip,
    create_payment_intent,
    handle_payment_failed,
    handle_payment_succeeded,
)


def _make_ride(ride_id=1, rider_id=10, driver_id=20, actual_fare=21.25):
    ride = MagicMock()
    ride.id = ride_id
    ride.rider_id = rider_id
    ride.driver_id = driver_id
    ride.actual_fare = actual_fare
    return ride


def _make_db_session(existing_payment=None):
    db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = existing_payment
    db.execute = AsyncMock(return_value=result)
    db.commit = AsyncMock()
    db.add = MagicMock()
    return db


class TestCreatePaymentIntent:
    @pytest.mark.asyncio
    async def test_creates_intent_and_payment_record(self):
        ride = _make_ride(actual_fare=21.25)
        db = _make_db_session(existing_payment=None)

        mock_intent = MagicMock()
        mock_intent.id = "pi_test_123"
        mock_intent.client_secret = "pi_test_123_secret_abc"

        with patch("app.services.payments.stripe") as mock_stripe:
            mock_stripe.PaymentIntent.create.return_value = mock_intent
            result = await create_payment_intent(ride, db)

        assert result["client_secret"] == "pi_test_123_secret_abc"
        assert result["payment_intent_id"] == "pi_test_123"
        assert result["status"] == "pending"

        mock_stripe.PaymentIntent.create.assert_called_once_with(
            amount=2125,
            currency="usd",
            metadata={
                "ride_id": "1",
                "rider_id": "10",
                "driver_id": "20",
            },
            automatic_payment_methods={"enabled": True},
        )

        db.add.assert_called_once()
        payment_arg = db.add.call_args[0][0]
        assert isinstance(payment_arg, Payment)
        assert payment_arg.ride_id == 1
        assert payment_arg.stripe_payment_intent_id == "pi_test_123"
        assert payment_arg.amount == 21.25
        assert payment_arg.platform_fee == 0.0
        assert payment_arg.driver_payout == 21.25

    @pytest.mark.asyncio
    async def test_returns_existing_if_already_has_intent(self):
        existing = MagicMock()
        existing.stripe_payment_intent_id = "pi_existing_456"
        existing.status = PaymentStatus.PENDING

        ride = _make_ride()
        db = _make_db_session(existing_payment=existing)

        result = await create_payment_intent(ride, db)

        assert result["payment_intent_id"] == "pi_existing_456"
        assert result["status"] == "pending"
        assert result["client_secret"] is None
        db.add.assert_not_called()

    @pytest.mark.asyncio
    async def test_rounds_amount_to_cents(self):
        ride = _make_ride(actual_fare=10.999)
        db = _make_db_session(existing_payment=None)

        mock_intent = MagicMock()
        mock_intent.id = "pi_round"
        mock_intent.client_secret = "secret"

        with patch("app.services.payments.stripe") as mock_stripe:
            mock_stripe.PaymentIntent.create.return_value = mock_intent
            await create_payment_intent(ride, db)

        call_args = mock_stripe.PaymentIntent.create.call_args
        assert call_args[1]["amount"] == 1100


class TestHandlePaymentSucceeded:
    @pytest.mark.asyncio
    async def test_marks_payment_completed(self):
        payment = MagicMock()
        payment.ride_id = 1
        payment.stripe_payment_intent_id = "pi_success"
        payment.status = PaymentStatus.PENDING

        db = _make_db_session(existing_payment=payment)

        pi_data = {"id": "pi_success", "metadata": {"ride_id": "1"}}
        await handle_payment_succeeded(pi_data, db)

        assert payment.status == PaymentStatus.COMPLETED
        db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_handles_missing_payment_gracefully(self):
        db = _make_db_session(existing_payment=None)

        pi_data = {"id": "pi_unknown", "metadata": {}}
        await handle_payment_succeeded(pi_data, db)

        db.commit.assert_not_awaited()


class TestHandlePaymentFailed:
    @pytest.mark.asyncio
    async def test_marks_payment_failed(self):
        payment = MagicMock()
        payment.ride_id = 1
        payment.stripe_payment_intent_id = "pi_fail"
        payment.status = PaymentStatus.PENDING

        db = _make_db_session(existing_payment=payment)

        pi_data = {"id": "pi_fail"}
        await handle_payment_failed(pi_data, db)

        assert payment.status == PaymentStatus.FAILED
        db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_handles_missing_payment_gracefully(self):
        db = _make_db_session(existing_payment=None)

        pi_data = {"id": "pi_unknown"}
        await handle_payment_failed(pi_data, db)

        db.commit.assert_not_awaited()


class TestAddTip:
    @pytest.mark.asyncio
    async def test_adds_tip_and_creates_intent(self):
        payment = MagicMock()
        payment.ride_id = 1
        payment.status = PaymentStatus.COMPLETED
        payment.tip_stripe_payment_intent_id = None
        payment.driver_payout = 21.25

        ride = MagicMock()
        ride.id = 1
        ride.driver_id = 20

        db = AsyncMock()
        result1 = MagicMock()
        result1.scalar_one_or_none.return_value = payment
        result2 = MagicMock()
        result2.scalar_one_or_none.return_value = ride
        db.execute = AsyncMock(side_effect=[result1, result2])
        db.commit = AsyncMock()

        mock_intent = MagicMock()
        mock_intent.id = "pi_tip_123"
        mock_intent.client_secret = "pi_tip_123_secret"

        with patch("app.services.payments.stripe") as mock_stripe:
            mock_stripe.PaymentIntent.create.return_value = mock_intent
            result = await add_tip(1, 5.00, db)

        assert result["tip_payment_intent_id"] == "pi_tip_123"
        assert result["tip_amount"] == 5.00
        assert result["new_driver_payout"] == 26.25
        assert payment.tip_amount == 5.00
        assert payment.tip_stripe_payment_intent_id == "pi_tip_123"
        assert ride.tip_amount == 5.00

        mock_stripe.PaymentIntent.create.assert_called_once_with(
            amount=500,
            currency="usd",
            metadata={"ride_id": "1", "driver_id": "20", "type": "tip"},
            automatic_payment_methods={"enabled": True},
        )

    @pytest.mark.asyncio
    async def test_rejects_zero_tip(self):
        db = AsyncMock()
        result = await add_tip(1, 0, db)
        assert result["error"] == "Tip amount must be positive"

    @pytest.mark.asyncio
    async def test_rejects_negative_tip(self):
        db = AsyncMock()
        result = await add_tip(1, -3.00, db)
        assert result["error"] == "Tip amount must be positive"

    @pytest.mark.asyncio
    async def test_rejects_tip_before_payment_completed(self):
        payment = MagicMock()
        payment.status = PaymentStatus.PENDING
        payment.tip_stripe_payment_intent_id = None

        db = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = payment
        db.execute = AsyncMock(return_value=result_mock)

        result = await add_tip(1, 5.00, db)
        assert result["error"] == "Can only tip after payment is completed"

    @pytest.mark.asyncio
    async def test_rejects_duplicate_tip(self):
        payment = MagicMock()
        payment.status = PaymentStatus.COMPLETED
        payment.tip_stripe_payment_intent_id = "pi_already_tipped"

        db = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = payment
        db.execute = AsyncMock(return_value=result_mock)

        result = await add_tip(1, 5.00, db)
        assert result["error"] == "Tip already submitted for this ride"

    @pytest.mark.asyncio
    async def test_rejects_tip_with_no_payment(self):
        db = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(return_value=result_mock)

        result = await add_tip(1, 5.00, db)
        assert result["error"] == "No payment found for this ride"

    @pytest.mark.asyncio
    async def test_tip_rounds_to_cents(self):
        payment = MagicMock()
        payment.ride_id = 1
        payment.status = PaymentStatus.COMPLETED
        payment.tip_stripe_payment_intent_id = None
        payment.driver_payout = 10.0

        ride = MagicMock()
        ride.id = 1
        ride.driver_id = 20

        db = AsyncMock()
        result1 = MagicMock()
        result1.scalar_one_or_none.return_value = payment
        result2 = MagicMock()
        result2.scalar_one_or_none.return_value = ride
        db.execute = AsyncMock(side_effect=[result1, result2])
        db.commit = AsyncMock()

        mock_intent = MagicMock()
        mock_intent.id = "pi_tip_round"
        mock_intent.client_secret = "secret"

        with patch("app.services.payments.stripe") as mock_stripe:
            mock_stripe.PaymentIntent.create.return_value = mock_intent
            await add_tip(1, 3.999, db)

        call_args = mock_stripe.PaymentIntent.create.call_args
        assert call_args[1]["amount"] == 400


class TestZeroCommission:
    @pytest.mark.asyncio
    async def test_driver_gets_full_fare(self):
        ride = _make_ride(actual_fare=50.0)
        db = _make_db_session(existing_payment=None)

        mock_intent = MagicMock()
        mock_intent.id = "pi_zc"
        mock_intent.client_secret = "secret"

        with patch("app.services.payments.stripe") as mock_stripe:
            mock_stripe.PaymentIntent.create.return_value = mock_intent
            await create_payment_intent(ride, db)

        payment_arg = db.add.call_args[0][0]
        assert payment_arg.driver_payout == 50.0
        assert payment_arg.platform_fee == 0.0
