"""Notification event dispatchers for ride lifecycle.

Thin wrappers that look up user contact info, resolve templates, and
call the notification service. These are designed to be fire-and-forget:
failures are logged but never raise — ride operations must not fail
because a notification couldn't be sent.

Usage from any endpoint or service:
    from app.services.notification_events import notify_ride_matched
    await notify_ride_matched(db, rider_id=1, ride_id=42, driver_name="Alice")
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from app.services.notifications import (
    NotificationType,
    send_ride_notification,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


async def _get_user_contact(db: AsyncSession, user_id: int) -> tuple[str | None, str | None]:
    """Fetch phone and email for a user. Returns (phone, email)."""
    try:
        from sqlalchemy import select
        from app.models.user import User

        result = await db.execute(select(User.phone, User.email).where(User.id == user_id))
        row = result.one_or_none()
        if row:
            return row.phone, row.email
    except Exception:
        logger.exception("Failed to fetch contact info for user %d", user_id)
    return None, None


async def notify_ride_matched(
    db: AsyncSession,
    rider_id: int,
    ride_id: int,
    driver_name: str = "",
    eta_minutes: int | None = None,
) -> None:
    """Notify rider that a driver has been matched."""
    try:
        phone, email = await _get_user_contact(db, rider_id)
        await send_ride_notification(
            user_id=rider_id,
            type=NotificationType.RIDE_MATCHED,
            ride_id=ride_id,
            db=db,
            phone=phone,
            email=email,
            driver_name=driver_name,
            **({"eta_minutes": eta_minutes} if eta_minutes else {}),
        )
    except Exception:
        logger.exception("Failed to send ride_matched notification for ride %d", ride_id)


async def notify_ride_cancelled(
    db: AsyncSession,
    user_id: int,
    ride_id: int,
    cancelled_by: str = "",
    reason: str = "",
) -> None:
    """Notify a user that a ride has been cancelled."""
    try:
        phone, email = await _get_user_contact(db, user_id)
        await send_ride_notification(
            user_id=user_id,
            type=NotificationType.RIDE_CANCELLED,
            ride_id=ride_id,
            db=db,
            phone=phone,
            email=email,
            cancelled_by=cancelled_by,
            reason=reason,
        )
    except Exception:
        logger.exception("Failed to send ride_cancelled notification for ride %d", ride_id)


async def notify_ride_completed(
    db: AsyncSession,
    rider_id: int,
    ride_id: int,
    fare: float | str = "",
) -> None:
    """Notify rider that the ride is complete."""
    try:
        phone, email = await _get_user_contact(db, rider_id)
        await send_ride_notification(
            user_id=rider_id,
            type=NotificationType.RIDE_COMPLETED,
            ride_id=ride_id,
            db=db,
            phone=phone,
            email=email,
            fare=fare,
        )
    except Exception:
        logger.exception("Failed to send ride_completed notification for ride %d", ride_id)


async def notify_driver_en_route(
    db: AsyncSession,
    rider_id: int,
    ride_id: int,
    driver_name: str = "",
    eta_minutes: int | None = None,
) -> None:
    """Notify rider that the driver is on the way."""
    try:
        phone, email = await _get_user_contact(db, rider_id)
        await send_ride_notification(
            user_id=rider_id,
            type=NotificationType.DRIVER_EN_ROUTE,
            ride_id=ride_id,
            db=db,
            phone=phone,
            email=email,
            driver_name=driver_name,
            **({"eta_minutes": eta_minutes} if eta_minutes else {}),
        )
    except Exception:
        logger.exception("Failed to send driver_en_route notification for ride %d", ride_id)


async def notify_driver_arrived(
    db: AsyncSession,
    rider_id: int,
    ride_id: int,
    driver_name: str = "",
) -> None:
    """Notify rider that the driver has arrived."""
    try:
        phone, email = await _get_user_contact(db, rider_id)
        await send_ride_notification(
            user_id=rider_id,
            type=NotificationType.DRIVER_ARRIVED,
            ride_id=ride_id,
            db=db,
            phone=phone,
            email=email,
            driver_name=driver_name,
        )
    except Exception:
        logger.exception("Failed to send driver_arrived notification for ride %d", ride_id)


async def notify_payment_received(
    db: AsyncSession,
    user_id: int,
    ride_id: int,
    amount: float | str = "",
) -> None:
    """Notify user that payment was processed."""
    try:
        phone, email = await _get_user_contact(db, user_id)
        await send_ride_notification(
            user_id=user_id,
            type=NotificationType.PAYMENT_RECEIVED,
            ride_id=ride_id,
            db=db,
            phone=phone,
            email=email,
            amount=amount,
        )
    except Exception:
        logger.exception("Failed to send payment_received notification for ride %d", ride_id)


async def notify_sos_alert(
    db: AsyncSession,
    user_id: int,
    ride_id: int | None = None,
    user_name: str = "",
) -> None:
    """Notify admins/emergency contacts about an SOS alert."""
    try:
        phone, email = await _get_user_contact(db, user_id)
        await send_ride_notification(
            user_id=user_id,
            type=NotificationType.SOS_ALERT,
            ride_id=ride_id or 0,
            db=db,
            phone=phone,
            email=email,
            user_name=user_name,
        )
    except Exception:
        logger.exception("Failed to send SOS notification for user %d", user_id)


async def notify_rating_received(
    db: AsyncSession,
    user_id: int,
    ride_id: int,
    rating: float | int | str = "",
) -> None:
    """Notify user that they received a rating."""
    try:
        phone, email = await _get_user_contact(db, user_id)
        await send_ride_notification(
            user_id=user_id,
            type=NotificationType.RATING_RECEIVED,
            ride_id=ride_id,
            db=db,
            phone=phone,
            email=email,
            rating=rating,
        )
    except Exception:
        logger.exception("Failed to send rating_received notification for ride %d", ride_id)


async def notify_payout_completed(
    db: AsyncSession,
    driver_id: int,
    amount: float | str = "",
    period: str = "",
) -> None:
    """Notify driver that a payout has been deposited."""
    try:
        phone, email = await _get_user_contact(db, driver_id)
        await send_ride_notification(
            user_id=driver_id,
            type=NotificationType.PAYOUT_COMPLETED,
            ride_id=0,
            db=db,
            phone=phone,
            email=email,
            amount=amount,
            period=period,
        )
    except Exception:
        logger.exception("Failed to send payout_completed notification for driver %d", driver_id)
