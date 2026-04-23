"""Admin ride force-cancel service.

Allows admins to cancel any non-terminal ride — including IN_PROGRESS rides
that regular users cannot cancel. Use cases: safety incident response, fraud
intervention, dispatcher override.

Business rules:
- Works on SCHEDULED, REQUESTED, MATCHED, DRIVER_EN_ROUTE, ARRIVED, IN_PROGRESS
- No cancellation fee to either party — admin override is never the rider's fault
- Any COMPLETED or PENDING payment for the ride is marked REFUNDED
- Rider and driver are notified (fire-and-forget, failures logged not raised)
- cancellation_reason stores "Admin <admin_id>: <reason>" for the audit log
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.payment import Payment, PaymentStatus
from app.models.ride import CancellationCategory, Ride, RideStatus
from app.schemas.admin_ride_cancel import AdminRideCancelResponse

logger = logging.getLogger(__name__)

_CANCELLABLE_STATUSES = frozenset({
    RideStatus.SCHEDULED,
    RideStatus.REQUESTED,
    RideStatus.MATCHED,
    RideStatus.DRIVER_EN_ROUTE,
    RideStatus.ARRIVED,
    RideStatus.IN_PROGRESS,
})


async def admin_force_cancel_ride(
    db: AsyncSession,
    ride_id: int,
    admin_id: int,
    reason: str = "",
    notify_parties: bool = True,
) -> AdminRideCancelResponse:
    """Force-cancel a ride as an admin. Raises ValueError for invalid states."""
    result = await db.execute(select(Ride).where(Ride.id == ride_id))
    ride = result.scalar_one_or_none()
    if ride is None:
        raise ValueError(f"Ride {ride_id} not found")

    if ride.status not in _CANCELLABLE_STATUSES:
        raise ValueError(
            f"Cannot cancel ride {ride_id}: status is '{ride.status.value}' — "
            "only non-terminal rides can be admin-cancelled"
        )

    previous_status = ride.status.value
    now = datetime.now(timezone.utc)

    ride.status = RideStatus.CANCELLED
    ride.cancellation_category = CancellationCategory.ADMIN_FORCED
    ride.cancelled_at = now
    audit_note = f"Admin {admin_id}"
    if reason:
        audit_note += f": {reason}"
    ride.cancellation_reason = audit_note

    # Refund any completed or pending payment for this ride
    refund_issued = await _issue_refund(db, ride_id)

    await db.flush()

    rider_notified = False
    driver_notified = False
    if notify_parties:
        rider_notified, driver_notified = await _notify(db, ride, reason)

    return AdminRideCancelResponse(
        ride_id=ride_id,
        previous_status=previous_status,
        cancelled_at=now,
        refund_issued=refund_issued,
        rider_notified=rider_notified,
        driver_notified=driver_notified,
    )


async def _issue_refund(db: AsyncSession, ride_id: int) -> bool:
    """Mark any active payment for the ride as REFUNDED. Returns True if a payment was found."""
    result = await db.execute(
        select(Payment).where(
            Payment.ride_id == ride_id,
            Payment.status.in_([PaymentStatus.COMPLETED, PaymentStatus.PENDING]),
        )
    )
    payments = list(result.scalars().all())
    if not payments:
        return False
    for payment in payments:
        payment.status = PaymentStatus.REFUNDED
    await db.flush()
    return True


async def _notify(
    db: AsyncSession,
    ride: Ride,
    reason: str,
) -> tuple[bool, bool]:
    """Send RIDE_CANCELLED notifications to rider and driver. Never raises."""
    from app.services.notification_events import _get_user_contact
    from app.services.notifications import NotificationType, send_ride_notification

    extra = dict(
        cancelled_by="Admin",
        cancellation_category=CancellationCategory.ADMIN_FORCED.value,
        reason=reason,
    )

    rider_ok = False
    try:
        phone, email = await _get_user_contact(db, ride.rider_id)
        rider_ok = await send_ride_notification(
            user_id=ride.rider_id,
            type=NotificationType.RIDE_CANCELLED,
            ride_id=ride.id,
            db=db,
            phone=phone,
            email=email,
            **extra,
        )
    except Exception:
        logger.exception("Failed to notify rider %d of admin cancellation of ride %d", ride.rider_id, ride.id)

    driver_ok = False
    if ride.driver_id is not None:
        try:
            phone, email = await _get_user_contact(db, ride.driver_id)
            driver_ok = await send_ride_notification(
                user_id=ride.driver_id,
                type=NotificationType.RIDE_CANCELLED,
                ride_id=ride.id,
                db=db,
                phone=phone,
                email=email,
                **extra,
            )
        except Exception:
            logger.exception("Failed to notify driver %d of admin cancellation of ride %d", ride.driver_id, ride.id)

    return rider_ok, driver_ok
