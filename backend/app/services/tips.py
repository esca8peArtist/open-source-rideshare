"""Tip service — submit, validate, and retrieve driver tips.

Riders may tip their driver within 48 hours of ride completion.
Tips are stored as integer cents (e.g. 500 = $5.00) and processed
through Stripe when credentials are configured; otherwise the tip
record is created without a PaymentIntent for offline/test environments.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

import stripe as stripe_lib
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.ride import Ride, RideStatus
from app.models.tip import TipRecord, TipStatus

if TYPE_CHECKING:
    from app.models.user import User

logger = logging.getLogger(__name__)

# Riders may tip up to this many hours after ride completion.
TIP_WINDOW_HOURS = 48

# Accepted tip range in cents.
TIP_MIN_CENTS = 50
TIP_MAX_CENTS = 5000


class TipError(Exception):
    """Raised for expected business-rule violations during tip submission."""

    def __init__(self, message: str, status_code: int = 409) -> None:
        super().__init__(message)
        self.status_code = status_code


async def submit_tip(
    db: AsyncSession,
    ride_id: int,
    rider_user: "User",
    amount_cents: int,
    message: str | None = None,
) -> TipRecord:
    """Submit a tip from a rider to the driver of a completed ride.

    Validates:
    - Ride exists and is completed.
    - The requesting user is the rider for that ride.
    - No tip has already been submitted for this ride.
    - amount_cents is within the allowed range (50–5000).
    - Ride was completed within the last 48 hours.

    If OPENRIDE_STRIPE_SECRET_KEY is set, creates a Stripe PaymentIntent
    for the tip amount and stores the intent ID. Without credentials the
    tip record is saved with status=pending and no intent ID — suitable
    for development and testing.

    Args:
        db: Active async database session.
        ride_id: ID of the ride being tipped.
        rider_user: Authenticated User submitting the tip.
        amount_cents: Tip amount in integer cents (50–5000).
        message: Optional thank-you note from rider to driver.

    Returns:
        The newly created TipRecord.

    Raises:
        TipError: On any business-rule violation (ride not found, wrong
            rider, duplicate tip, bad amount, window expired).
    """
    # --- validation ---
    if amount_cents < TIP_MIN_CENTS or amount_cents > TIP_MAX_CENTS:
        raise TipError(
            f"Tip amount must be between ${TIP_MIN_CENTS / 100:.2f} and ${TIP_MAX_CENTS / 100:.2f}",
            status_code=422,
        )

    result = await db.execute(select(Ride).where(Ride.id == ride_id))
    ride = result.scalar_one_or_none()

    if not ride:
        raise TipError("Ride not found", status_code=404)

    if ride.rider_id != rider_user.id:
        raise TipError("Only the rider for this ride can submit a tip", status_code=403)

    if ride.status != RideStatus.COMPLETED:
        raise TipError("Tips can only be submitted for completed rides", status_code=409)

    if ride.completed_at is None:
        raise TipError("Ride completion time is unavailable", status_code=409)

    # Normalise timezone: completed_at may be tz-aware or naive depending on DB driver.
    completed_at = ride.completed_at
    if completed_at.tzinfo is None:
        completed_at = completed_at.replace(tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    if now - completed_at > timedelta(hours=TIP_WINDOW_HOURS):
        raise TipError(
            f"Tips must be submitted within {TIP_WINDOW_HOURS} hours of ride completion",
            status_code=409,
        )

    # Duplicate check
    existing_result = await db.execute(
        select(TipRecord).where(TipRecord.ride_id == ride_id)
    )
    if existing_result.scalar_one_or_none():
        raise TipError("A tip has already been submitted for this ride", status_code=409)

    # --- create record ---
    tip = TipRecord(
        ride_id=ride_id,
        driver_id=ride.driver_id,
        rider_id=rider_user.id,
        amount_cents=amount_cents,
        thank_you_message=message,
        status=TipStatus.PENDING,
    )
    db.add(tip)
    await db.flush()  # populate tip.id before Stripe call

    # --- Stripe charge (graceful degradation when key is absent) ---
    stripe_intent_id: str | None = None
    if settings.stripe_secret_key:
        try:
            stripe_lib.api_key = settings.stripe_secret_key
            intent = stripe_lib.PaymentIntent.create(
                amount=amount_cents,
                currency="usd",
                metadata={
                    "ride_id": str(ride_id),
                    "driver_id": str(ride.driver_id),
                    "rider_id": str(rider_user.id),
                    "type": "tip",
                },
                automatic_payment_methods={"enabled": True},
            )
            stripe_intent_id = intent.id
            tip.stripe_payment_intent_id = stripe_intent_id
        except Exception:
            logger.exception(
                "Stripe error creating tip intent for ride %d — tip saved without intent",
                ride_id,
            )
    else:
        logger.debug(
            "OPENRIDE_STRIPE_SECRET_KEY not set; tip for ride %d saved without PaymentIntent",
            ride_id,
        )

    await db.commit()
    await db.refresh(tip)

    # --- driver notification (fire-and-forget) ---
    try:
        await _notify_driver_tip(db, tip)
    except Exception:
        logger.exception("Failed to send tip notification for ride %d", ride_id)

    logger.info(
        "Tip of %d cents submitted for ride %d (driver %d, intent %s)",
        amount_cents,
        ride_id,
        ride.driver_id,
        stripe_intent_id or "none",
    )
    return tip


async def get_tip_for_ride(db: AsyncSession, ride_id: int) -> TipRecord | None:
    """Return the TipRecord for a ride, or None if no tip has been submitted.

    Args:
        db: Active async database session.
        ride_id: ID of the ride to look up.

    Returns:
        TipRecord or None.
    """
    result = await db.execute(
        select(TipRecord).where(TipRecord.ride_id == ride_id)
    )
    return result.scalar_one_or_none()


async def _notify_driver_tip(db: AsyncSession, tip: TipRecord) -> None:
    """Send a push and SMS notification to the driver about the tip received.

    Uses the notification_events pattern: fire-and-forget, failures are
    logged but never raised to avoid disrupting the tip flow.

    Args:
        db: Active async database session.
        tip: The newly created TipRecord.
    """
    from app.services.notification_events import _get_user_contact
    from app.services.notifications import (
        Notification,
        NotificationChannel,
        NotificationType,
        send_notification,
    )

    amount_dollars = tip.amount_cents / 100
    phone, email = await _get_user_contact(db, tip.driver_id)

    notification = Notification(
        user_id=tip.driver_id,
        type=NotificationType.PAYMENT_RECEIVED,
        title="You received a tip!",
        body=f"You received a ${amount_dollars:.2f} tip for ride #{tip.ride_id}.",
        channels=[NotificationChannel.PUSH, NotificationChannel.SMS],
        data={"ride_id": tip.ride_id, "tip_id": tip.id, "amount_cents": tip.amount_cents},
        ride_id=tip.ride_id,
    )
    await send_notification(notification, db=db, phone=phone, email=email)
