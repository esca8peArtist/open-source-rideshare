import logging
from typing import Any

import stripe
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.payment import Payment, PaymentStatus, PaymentType
from app.models.ride import Ride, RideStatus

logger = logging.getLogger(__name__)

stripe.api_key = settings.stripe_secret_key


async def create_payment_intent(
    ride: Ride, db: AsyncSession
) -> dict[str, Any]:
    amount_cents = int(round(ride.actual_fare * 100))
    platform_fee_cents = int(round(amount_cents * 0.00))  # zero-commission model

    result = await db.execute(
        select(Payment).where(
            Payment.ride_id == ride.id,
            Payment.payment_type == PaymentType.RIDE_FARE,
        )
    )
    existing = result.scalar_one_or_none()
    if existing and existing.stripe_payment_intent_id:
        return {
            "client_secret": None,
            "payment_intent_id": existing.stripe_payment_intent_id,
            "status": existing.status.value,
        }

    intent = stripe.PaymentIntent.create(
        amount=amount_cents,
        currency="usd",
        metadata={
            "ride_id": str(ride.id),
            "rider_id": str(ride.rider_id),
            "driver_id": str(ride.driver_id),
        },
        automatic_payment_methods={"enabled": True},
    )

    driver_payout = ride.actual_fare
    platform_fee = 0.0

    if existing:
        existing.stripe_payment_intent_id = intent.id
        existing.amount = ride.actual_fare
        existing.platform_fee = platform_fee
        existing.driver_payout = driver_payout
    else:
        payment = Payment(
            ride_id=ride.id,
            payment_type=PaymentType.RIDE_FARE,
            stripe_payment_intent_id=intent.id,
            amount=ride.actual_fare,
            platform_fee=platform_fee,
            driver_payout=driver_payout,
            status=PaymentStatus.PENDING,
        )
        db.add(payment)

    await db.commit()

    return {
        "client_secret": intent.client_secret,
        "payment_intent_id": intent.id,
        "status": "pending",
    }


async def handle_payment_succeeded(
    payment_intent: dict, db: AsyncSession
) -> None:
    pi_id = payment_intent["id"]
    ride_id = payment_intent.get("metadata", {}).get("ride_id")

    result = await db.execute(
        select(Payment).where(Payment.stripe_payment_intent_id == pi_id)
    )
    payment = result.scalar_one_or_none()

    if not payment:
        if ride_id:
            result = await db.execute(
                select(Payment).where(Payment.ride_id == int(ride_id))
            )
            payment = result.scalar_one_or_none()

    if not payment:
        logger.warning("Payment record not found for intent %s", pi_id)
        return

    payment.status = PaymentStatus.COMPLETED
    if not payment.stripe_payment_intent_id:
        payment.stripe_payment_intent_id = pi_id
    await db.commit()

    logger.info("Payment completed for ride %d (intent %s)", payment.ride_id, pi_id)

    # Send payment notification
    try:
        from app.services.notification_events import notify_payment_received
        ride_result = await db.execute(
            select(Payment.ride_id).where(Payment.id == payment.id)
        )
        from app.models.ride import Ride
        ride_q = await db.execute(select(Ride.rider_id).where(Ride.id == payment.ride_id))
        rider_row = ride_q.one_or_none()
        if rider_row:
            await notify_payment_received(
                db, user_id=rider_row.rider_id, ride_id=payment.ride_id,
                amount=payment.amount,
            )
    except Exception:
        logger.exception("Failed to send payment notification for ride %d", payment.ride_id)


async def handle_payment_failed(
    payment_intent: dict, db: AsyncSession
) -> None:
    pi_id = payment_intent["id"]

    result = await db.execute(
        select(Payment).where(Payment.stripe_payment_intent_id == pi_id)
    )
    payment = result.scalar_one_or_none()

    if not payment:
        logger.warning("Payment record not found for failed intent %s", pi_id)
        return

    payment.status = PaymentStatus.FAILED
    await db.commit()

    logger.info("Payment failed for ride %d (intent %s)", payment.ride_id, pi_id)


async def add_tip(
    ride_id: int, tip_amount: float, db: AsyncSession
) -> dict[str, Any]:
    if tip_amount <= 0:
        return {"error": "Tip amount must be positive"}

    result = await db.execute(
        select(Payment).where(
            Payment.ride_id == ride_id,
            Payment.payment_type == PaymentType.RIDE_FARE,
        )
    )
    payment = result.scalar_one_or_none()

    if not payment:
        return {"error": "No payment found for this ride"}

    if payment.status != PaymentStatus.COMPLETED:
        return {"error": "Can only tip after payment is completed"}

    if payment.tip_stripe_payment_intent_id:
        return {"error": "Tip already submitted for this ride"}

    tip_cents = int(round(tip_amount * 100))

    from app.models.ride import Ride
    result = await db.execute(select(Ride).where(Ride.id == ride_id))
    ride = result.scalar_one_or_none()

    intent = stripe.PaymentIntent.create(
        amount=tip_cents,
        currency="usd",
        metadata={
            "ride_id": str(ride_id),
            "driver_id": str(ride.driver_id) if ride else "",
            "type": "tip",
        },
        automatic_payment_methods={"enabled": True},
    )

    payment.tip_amount = tip_amount
    payment.tip_stripe_payment_intent_id = intent.id
    payment.driver_payout = payment.driver_payout + tip_amount
    if ride:
        ride.tip_amount = tip_amount
    await db.commit()

    logger.info("Tip of $%.2f added for ride %d (intent %s)", tip_amount, ride_id, intent.id)
    return {
        "client_secret": intent.client_secret,
        "tip_payment_intent_id": intent.id,
        "tip_amount": tip_amount,
        "new_driver_payout": payment.driver_payout,
    }


async def process_refund(
    ride_id: int, db: AsyncSession
) -> dict[str, Any]:
    result = await db.execute(
        select(Payment).where(
            Payment.ride_id == ride_id,
            Payment.payment_type == PaymentType.RIDE_FARE,
        )
    )
    payment = result.scalar_one_or_none()

    if not payment:
        return {"error": "No payment found for this ride"}

    if payment.status != PaymentStatus.COMPLETED:
        return {"error": f"Cannot refund payment in {payment.status.value} state"}

    refund = stripe.Refund.create(payment_intent=payment.stripe_payment_intent_id)

    payment.status = PaymentStatus.REFUNDED
    await db.commit()

    logger.info("Refund issued for ride %d: %s", ride_id, refund.id)
    return {"refund_id": refund.id, "status": "refunded"}


async def create_cancellation_payment_intent(
    ride_id: int,
    rider_id: int,
    driver_id: int | None,
    cancellation_fee: float,
    db: AsyncSession,
) -> dict[str, Any]:
    """Create a Stripe PaymentIntent for a cancellation fee.

    Returns the client_secret so the frontend can complete payment.
    The full fee goes to the driver (zero-commission model).
    """
    if cancellation_fee <= 0:
        return {"cancellation_fee": 0.0, "payment_required": False}

    # Check for existing cancellation payment on this ride
    result = await db.execute(
        select(Payment).where(
            Payment.ride_id == ride_id,
            Payment.payment_type == PaymentType.CANCELLATION_FEE,
        )
    )
    existing = result.scalar_one_or_none()
    if existing and existing.stripe_payment_intent_id:
        return {
            "client_secret": None,
            "payment_intent_id": existing.stripe_payment_intent_id,
            "cancellation_fee": existing.amount,
            "payment_required": True,
            "status": existing.status.value,
        }

    amount_cents = int(round(cancellation_fee * 100))

    intent = stripe.PaymentIntent.create(
        amount=amount_cents,
        currency="usd",
        metadata={
            "ride_id": str(ride_id),
            "rider_id": str(rider_id),
            "driver_id": str(driver_id) if driver_id else "",
            "type": "cancellation_fee",
        },
        automatic_payment_methods={"enabled": True},
    )

    payment = Payment(
        ride_id=ride_id,
        payment_type=PaymentType.CANCELLATION_FEE,
        stripe_payment_intent_id=intent.id,
        amount=cancellation_fee,
        platform_fee=0.0,
        driver_payout=cancellation_fee,  # 100% to driver
        status=PaymentStatus.PENDING,
    )
    db.add(payment)
    await db.commit()

    logger.info(
        "Cancellation fee payment intent created for ride %d: $%.2f (intent %s)",
        ride_id, cancellation_fee, intent.id,
    )

    return {
        "client_secret": intent.client_secret,
        "payment_intent_id": intent.id,
        "cancellation_fee": cancellation_fee,
        "payment_required": True,
        "status": "pending",
    }
