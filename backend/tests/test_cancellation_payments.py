"""Unit tests for cancellation fee collection — Stripe payment integration."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import app.models.user  # noqa: F401
import app.models.driver  # noqa: F401
import app.models.ride  # noqa: F401
from app.models.payment import Payment, PaymentStatus, PaymentType
from app.services.payments import create_cancellation_payment_intent


def _make_db_session(existing_payment=None):
    db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = existing_payment
    db.execute = AsyncMock(return_value=result)
    db.commit = AsyncMock()
    db.add = MagicMock()
    return db


class TestCreateCancellationPaymentIntent:
    @pytest.mark.asyncio
    async def test_zero_fee_returns_no_payment_required(self):
        db = AsyncMock()
        result = await create_cancellation_payment_intent(
            ride_id=1, rider_id=10, driver_id=20, cancellation_fee=0.0, db=db,
        )
        assert result["payment_required"] is False
        assert result["cancellation_fee"] == 0.0
        db.execute.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_negative_fee_returns_no_payment_required(self):
        db = AsyncMock()
        result = await create_cancellation_payment_intent(
            ride_id=1, rider_id=10, driver_id=20, cancellation_fee=-1.0, db=db,
        )
        assert result["payment_required"] is False

    @pytest.mark.asyncio
    async def test_creates_intent_and_payment_record(self):
        db = _make_db_session(existing_payment=None)

        mock_intent = MagicMock()
        mock_intent.id = "pi_cancel_123"
        mock_intent.client_secret = "pi_cancel_123_secret_abc"

        with patch("app.services.payments.stripe") as mock_stripe:
            mock_stripe.PaymentIntent.create.return_value = mock_intent
            result = await create_cancellation_payment_intent(
                ride_id=1, rider_id=10, driver_id=20, cancellation_fee=3.00, db=db,
            )

        assert result["client_secret"] == "pi_cancel_123_secret_abc"
        assert result["payment_intent_id"] == "pi_cancel_123"
        assert result["cancellation_fee"] == 3.00
        assert result["payment_required"] is True
        assert result["status"] == "pending"

        mock_stripe.PaymentIntent.create.assert_called_once_with(
            amount=300,
            currency="usd",
            metadata={
                "ride_id": "1",
                "rider_id": "10",
                "driver_id": "20",
                "type": "cancellation_fee",
            },
            automatic_payment_methods={"enabled": True},
        )

        db.add.assert_called_once()
        payment_arg = db.add.call_args[0][0]
        assert isinstance(payment_arg, Payment)
        assert payment_arg.ride_id == 1
        assert payment_arg.payment_type == PaymentType.CANCELLATION_FEE
        assert payment_arg.amount == 3.00
        assert payment_arg.platform_fee == 0.0
        assert payment_arg.driver_payout == 3.00
        assert payment_arg.status == PaymentStatus.PENDING

    @pytest.mark.asyncio
    async def test_returns_existing_if_already_has_intent(self):
        existing = MagicMock()
        existing.stripe_payment_intent_id = "pi_cancel_existing"
        existing.amount = 5.00
        existing.status = PaymentStatus.PENDING

        db = _make_db_session(existing_payment=existing)

        result = await create_cancellation_payment_intent(
            ride_id=1, rider_id=10, driver_id=20, cancellation_fee=5.00, db=db,
        )

        assert result["payment_intent_id"] == "pi_cancel_existing"
        assert result["cancellation_fee"] == 5.00
        assert result["payment_required"] is True
        assert result["client_secret"] is None
        db.add.assert_not_called()

    @pytest.mark.asyncio
    async def test_driver_gets_full_cancellation_fee(self):
        db = _make_db_session(existing_payment=None)

        mock_intent = MagicMock()
        mock_intent.id = "pi_cancel_full"
        mock_intent.client_secret = "secret"

        with patch("app.services.payments.stripe") as mock_stripe:
            mock_stripe.PaymentIntent.create.return_value = mock_intent
            await create_cancellation_payment_intent(
                ride_id=1, rider_id=10, driver_id=20, cancellation_fee=5.00, db=db,
            )

        payment_arg = db.add.call_args[0][0]
        assert payment_arg.driver_payout == 5.00
        assert payment_arg.platform_fee == 0.0

    @pytest.mark.asyncio
    async def test_rounds_fee_to_cents(self):
        db = _make_db_session(existing_payment=None)

        mock_intent = MagicMock()
        mock_intent.id = "pi_cancel_round"
        mock_intent.client_secret = "secret"

        with patch("app.services.payments.stripe") as mock_stripe:
            mock_stripe.PaymentIntent.create.return_value = mock_intent
            await create_cancellation_payment_intent(
                ride_id=1, rider_id=10, driver_id=20, cancellation_fee=3.999, db=db,
            )

        call_args = mock_stripe.PaymentIntent.create.call_args
        assert call_args[1]["amount"] == 400

    @pytest.mark.asyncio
    async def test_handles_none_driver_id(self):
        db = _make_db_session(existing_payment=None)

        mock_intent = MagicMock()
        mock_intent.id = "pi_cancel_nodriver"
        mock_intent.client_secret = "secret"

        with patch("app.services.payments.stripe") as mock_stripe:
            mock_stripe.PaymentIntent.create.return_value = mock_intent
            result = await create_cancellation_payment_intent(
                ride_id=1, rider_id=10, driver_id=None, cancellation_fee=3.00, db=db,
            )

        assert result["payment_required"] is True
        call_args = mock_stripe.PaymentIntent.create.call_args
        assert call_args[1]["metadata"]["driver_id"] == ""

    @pytest.mark.asyncio
    async def test_metadata_includes_cancellation_type(self):
        db = _make_db_session(existing_payment=None)

        mock_intent = MagicMock()
        mock_intent.id = "pi_cancel_meta"
        mock_intent.client_secret = "secret"

        with patch("app.services.payments.stripe") as mock_stripe:
            mock_stripe.PaymentIntent.create.return_value = mock_intent
            await create_cancellation_payment_intent(
                ride_id=42, rider_id=10, driver_id=20, cancellation_fee=3.00, db=db,
            )

        call_args = mock_stripe.PaymentIntent.create.call_args
        assert call_args[1]["metadata"]["type"] == "cancellation_fee"
        assert call_args[1]["metadata"]["ride_id"] == "42"


class TestPaymentTypeEnum:
    def test_ride_fare_value(self):
        assert PaymentType.RIDE_FARE.value == "ride_fare"

    def test_cancellation_fee_value(self):
        assert PaymentType.CANCELLATION_FEE.value == "cancellation_fee"


class TestPaymentModelCancellationType:
    def test_payment_with_cancellation_type(self):
        payment = Payment(
            ride_id=1,
            payment_type=PaymentType.CANCELLATION_FEE,
            amount=3.00,
            platform_fee=0.0,
            driver_payout=3.00,
        )
        assert payment.payment_type == PaymentType.CANCELLATION_FEE

    def test_payment_default_type_is_ride_fare_at_column_level(self):
        """The DB column default is RIDE_FARE — verified by checking the column definition."""
        col = Payment.__table__.columns["payment_type"]
        assert col.default.arg == PaymentType.RIDE_FARE
