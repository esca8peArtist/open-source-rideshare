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
    cancellation_category: str = "",
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
            cancellation_category=cancellation_category,
        )
    except Exception:
        logger.exception("Failed to send ride_cancelled notification for ride %d", ride_id)


async def notify_cancellation_confirmation(
    db: AsyncSession,
    user_id: int,
    ride_id: int,
    cancelled_by: str,
    fee: float | str = "",
) -> None:
    """Notify the cancelling party that their cancellation went through."""
    from app.services.notifications import NotificationType
    notification_type = (
        NotificationType.CANCELLATION_CONFIRMATION_RIDER
        if cancelled_by == "rider"
        else NotificationType.CANCELLATION_CONFIRMATION_DRIVER
    )
    try:
        phone, email = await _get_user_contact(db, user_id)
        await send_ride_notification(
            user_id=user_id,
            type=notification_type,
            ride_id=ride_id,
            db=db,
            phone=phone,
            email=email,
            fee=fee,
        )
    except Exception:
        logger.exception("Failed to send cancellation_confirmation notification for ride %d", ride_id)


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


async def notify_emergency_contacts_sos(
    db: AsyncSession,
    user_id: int,
    user_name: str = "",
    ride_id: int | None = None,
    latitude: float | None = None,
    longitude: float | None = None,
) -> None:
    """Send an SOS alert SMS to each of the user's emergency contacts."""
    try:
        from sqlalchemy import select
        from app.models.safety import EmergencyContact

        result = await db.execute(
            select(EmergencyContact).where(EmergencyContact.user_id == user_id)
        )
        contacts = list(result.scalars().all())

        extra: dict = {"user_name": user_name}
        if latitude is not None and longitude is not None:
            extra["latitude"] = latitude
            extra["longitude"] = longitude

        for contact in contacts:
            try:
                await send_ride_notification(
                    user_id=user_id,
                    type=NotificationType.EMERGENCY_CONTACT_SOS,
                    ride_id=ride_id or 0,
                    db=db,
                    phone=contact.phone,
                    email=None,
                    **extra,
                )
            except Exception:
                logger.exception(
                    "Failed to send emergency contact SOS to %s for user %d",
                    contact.phone,
                    user_id,
                )
    except Exception:
        logger.exception("Failed to notify emergency contacts for user %d", user_id)


async def notify_safe_arrival_contacts(
    db: AsyncSession,
    user_id: int,
    user_name: str = "",
    ride_id: int | None = None,
) -> None:
    """Send a safe-arrival SMS to each of the user's emergency contacts."""
    try:
        from sqlalchemy import select
        from app.models.safety import EmergencyContact

        result = await db.execute(
            select(EmergencyContact).where(EmergencyContact.user_id == user_id)
        )
        contacts = list(result.scalars().all())

        for contact in contacts:
            try:
                await send_ride_notification(
                    user_id=user_id,
                    type=NotificationType.SAFE_ARRIVAL_CONTACT,
                    ride_id=ride_id or 0,
                    db=db,
                    phone=contact.phone,
                    email=None,
                    user_name=user_name,
                )
            except Exception:
                logger.exception(
                    "Failed to send safe-arrival notification to %s for user %d",
                    contact.phone,
                    user_id,
                )
    except Exception:
        logger.exception("Failed to notify emergency contacts of safe arrival for user %d", user_id)


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


async def notify_ride_started(
    db: AsyncSession,
    rider_id: int,
    ride_id: int,
    dropoff_address: str = "",
) -> None:
    """Notify rider that their ride has started (IN_PROGRESS)."""
    try:
        phone, email = await _get_user_contact(db, rider_id)
        await send_ride_notification(
            user_id=rider_id,
            type=NotificationType.RIDE_IN_PROGRESS,
            ride_id=ride_id,
            db=db,
            phone=phone,
            email=email,
            dropoff_address=dropoff_address,
        )
    except Exception:
        logger.exception("Failed to send ride_in_progress notification for ride %d", ride_id)


async def notify_driver_assigned(
    db: AsyncSession,
    driver_id: int,
    ride_id: int,
    rider_name: str = "",
    pickup_address: str = "",
) -> None:
    """Notify driver that they have been assigned a new ride."""
    try:
        phone, email = await _get_user_contact(db, driver_id)
        await send_ride_notification(
            user_id=driver_id,
            type=NotificationType.RIDE_ASSIGNED,
            ride_id=ride_id,
            db=db,
            phone=phone,
            email=email,
            rider_name=rider_name,
            pickup_address=pickup_address,
        )
    except Exception:
        logger.exception("Failed to send ride_assigned notification for ride %d", ride_id)


async def notify_ride_completed_driver(
    db: AsyncSession,
    driver_id: int,
    ride_id: int,
    fare: float | str = "",
) -> None:
    """Notify driver that a ride they completed has been processed."""
    try:
        phone, email = await _get_user_contact(db, driver_id)
        await send_ride_notification(
            user_id=driver_id,
            type=NotificationType.RIDE_COMPLETED_DRIVER,
            ride_id=ride_id,
            db=db,
            phone=phone,
            email=email,
            fare=fare,
        )
    except Exception:
        logger.exception("Failed to send ride_completed_driver notification for ride %d", ride_id)


async def notify_route_deviation(
    db: AsyncSession,
    rider_id: int,
    ride_id: int,
    dropoff_address: str = "",
) -> None:
    """Notify rider that the driver has deviated significantly from the expected route."""
    try:
        phone, email = await _get_user_contact(db, rider_id)
        await send_ride_notification(
            user_id=rider_id,
            type=NotificationType.ROUTE_DEVIATION,
            ride_id=ride_id,
            db=db,
            phone=phone,
            email=email,
            dropoff_address=dropoff_address,
        )
    except Exception:
        logger.exception("Failed to send route_deviation notification for ride %d", ride_id)


async def notify_speeding_alert(
    db: AsyncSession,
    rider_id: int,
    ride_id: int,
) -> None:
    """Notify rider that their driver is travelling at an unsafe speed."""
    try:
        phone, email = await _get_user_contact(db, rider_id)
        await send_ride_notification(
            user_id=rider_id,
            type=NotificationType.SPEEDING_ALERT,
            ride_id=ride_id,
            db=db,
            phone=phone,
            email=email,
        )
    except Exception:
        logger.exception("Failed to send speeding_alert notification for ride %d", ride_id)


async def notify_driver_no_show(
    db: AsyncSession,
    rider_id: int,
    ride_id: int,
    wait_minutes: int = 0,
    new_ride_id: int | None = None,
) -> None:
    """Notify rider that their driver did not arrive and the ride has been cancelled.

    If *new_ride_id* is set the message will mention the auto-rebooked replacement ride.
    """
    try:
        phone, email = await _get_user_contact(db, rider_id)
        await send_ride_notification(
            user_id=rider_id,
            type=NotificationType.DRIVER_NO_SHOW,
            ride_id=ride_id,
            db=db,
            phone=phone,
            email=email,
            wait_minutes=wait_minutes,
            new_ride_id=new_ride_id,
        )
    except Exception:
        logger.exception("Failed to send driver_no_show notification for ride %d", ride_id)


async def _send_driver_escalation_notification(
    db: AsyncSession,
    driver_id: int,
    notification_type: NotificationType,
    alert_type: str,
    warning_count: int,
) -> None:
    """Internal helper: sends an escalation notification to a driver (no ride_id)."""
    from app.services.notifications import Notification, send_notification
    from app.services.notification_templates import render

    phone, email = await _get_user_contact(db, driver_id)
    title, body, channels = render(
        notification_type, alert_type=alert_type, warning_count=warning_count
    )
    notification = Notification(
        user_id=driver_id,
        type=notification_type,
        title=title,
        body=body,
        channels=channels,
        data={"alert_type": alert_type, "warning_count": warning_count},
    )
    await send_notification(notification, db=db, phone=phone, email=email)


async def notify_driver_performance_warning(
    db: AsyncSession,
    driver_id: int,
    alert_type: str,
    warning_count: int,
) -> None:
    """Notify a driver of their first escalation warning."""
    try:
        await _send_driver_escalation_notification(
            db,
            driver_id,
            NotificationType.DRIVER_PERFORMANCE_WARNING,
            alert_type,
            warning_count,
        )
    except Exception:
        logger.exception(
            "Failed to send performance_warning notification to driver %d", driver_id
        )


async def notify_driver_performance_final_warning(
    db: AsyncSession,
    driver_id: int,
    alert_type: str,
    warning_count: int,
) -> None:
    """Notify a driver of their final warning before auto-suspension."""
    try:
        await _send_driver_escalation_notification(
            db,
            driver_id,
            NotificationType.DRIVER_PERFORMANCE_FINAL_WARNING,
            alert_type,
            warning_count,
        )
    except Exception:
        logger.exception(
            "Failed to send performance_final_warning notification to driver %d", driver_id
        )


async def notify_scheduled_dispatched(
    db: AsyncSession,
    rider_id: int,
    ride_id: int,
    pickup_address: str = "",
    scheduled_for: str = "",
) -> None:
    """Notify rider that their scheduled ride has entered the dispatch window."""
    try:
        phone, email = await _get_user_contact(db, rider_id)
        await send_ride_notification(
            user_id=rider_id,
            type=NotificationType.RIDE_SCHEDULED_DISPATCHED,
            ride_id=ride_id,
            db=db,
            phone=phone,
            email=email,
            pickup_address=pickup_address,
            scheduled_for=scheduled_for,
        )
    except Exception:
        logger.exception("Failed to send scheduled_dispatched notification for ride %d", ride_id)


async def notify_driver_auto_suspended(
    db: AsyncSession,
    driver_id: int,
    alert_type: str,
    warning_count: int,
) -> None:
    """Notify a driver that their account has been automatically suspended."""
    try:
        await _send_driver_escalation_notification(
            db,
            driver_id,
            NotificationType.DRIVER_AUTO_SUSPENDED,
            alert_type,
            warning_count,
        )
    except Exception:
        logger.exception(
            "Failed to send auto_suspended notification to driver %d", driver_id
        )


async def notify_geofence_exit(
    db: AsyncSession,
    rider_id: int,
    ride_id: int,
) -> None:
    """Notify rider that their driver has left the service area."""
    try:
        phone, email = await _get_user_contact(db, rider_id)
        await send_ride_notification(
            user_id=rider_id,
            type=NotificationType.GEOFENCE_EXIT,
            ride_id=ride_id,
            db=db,
            phone=phone,
            email=email,
        )
    except Exception:
        logger.exception("Failed to send geofence_exit notification for ride %d", ride_id)


async def notify_driver_geofence_exit(
    db: AsyncSession,
    driver_user_id: int,
    ride_id: int,
) -> None:
    """Notify driver that they have left the service area during an active ride."""
    try:
        phone, email = await _get_user_contact(db, driver_user_id)
        await send_ride_notification(
            user_id=driver_user_id,
            type=NotificationType.DRIVER_GEOFENCE_EXIT,
            ride_id=ride_id,
            db=db,
            phone=phone,
            email=email,
        )
    except Exception:
        logger.exception(
            "Failed to send driver_geofence_exit notification for ride %d", ride_id
        )


async def notify_pool_rider_joined(
    db: AsyncSession,
    existing_rider_ids: list[int],
    new_rider_name: str,
    ride_id: int | None = None,
) -> None:
    """Notify all existing pool members that a new rider has joined.

    Sends a push notification to each rider already in the pool (excluding the
    new rider). Fire-and-forget — failures are logged but never raise.
    """
    for rider_id in existing_rider_ids:
        try:
            phone, email = await _get_user_contact(db, rider_id)
            await send_ride_notification(
                user_id=rider_id,
                type=NotificationType.POOL_RIDER_JOINED,
                ride_id=ride_id,
                db=db,
                phone=phone,
                email=email,
                new_rider_name=new_rider_name,
            )
        except Exception:
            logger.exception(
                "Failed to send pool_rider_joined notification to user %d", rider_id
            )


async def notify_trip_share_viewed(
    db: AsyncSession,
    rider_id: int,
    ride_id: int,
) -> None:
    """Notify the rider who shared a trip link that someone viewed it.

    Only fires on the first view (idempotency enforced by the trip share
    service's mark_first_view). Fire-and-forget.
    """
    try:
        phone, email = await _get_user_contact(db, rider_id)
        await send_ride_notification(
            user_id=rider_id,
            type=NotificationType.TRIP_SHARE_VIEWED,
            ride_id=ride_id,
            db=db,
            phone=phone,
            email=email,
        )
    except Exception:
        logger.exception(
            "Failed to send trip_share_viewed notification to rider %d", rider_id
        )


async def notify_dispute_filed(
    db: AsyncSession,
    other_party_id: int,
    ride_id: int,
    dispute_type: str = "a dispute",
) -> None:
    """Notify the other ride participant that a dispute has been filed against them."""
    try:
        phone, email = await _get_user_contact(db, other_party_id)
        await send_ride_notification(
            user_id=other_party_id,
            type=NotificationType.DISPUTE_FILED,
            ride_id=ride_id,
            db=db,
            phone=phone,
            email=email,
            dispute_type=dispute_type,
        )
    except Exception:
        logger.exception(
            "Failed to send dispute_filed notification to user %d for ride %d",
            other_party_id,
            ride_id,
        )


async def notify_dispute_resolved(
    db: AsyncSession,
    filer_id: int,
    ride_id: int,
    outcome: str = "resolved",
) -> None:
    """Notify the dispute filer that their dispute has been resolved by an admin."""
    try:
        phone, email = await _get_user_contact(db, filer_id)
        await send_ride_notification(
            user_id=filer_id,
            type=NotificationType.DISPUTE_RESOLVED,
            ride_id=ride_id,
            db=db,
            phone=phone,
            email=email,
            outcome=outcome,
        )
    except Exception:
        logger.exception(
            "Failed to send dispute_resolved notification to user %d for ride %d",
            filer_id,
            ride_id,
        )


async def notify_dispute_response_received(
    db: AsyncSession,
    filer_id: int,
    ride_id: int,
) -> None:
    """Notify the dispute filer that the other party has submitted a response."""
    try:
        phone, email = await _get_user_contact(db, filer_id)
        await send_ride_notification(
            user_id=filer_id,
            type=NotificationType.DISPUTE_RESPONSE_RECEIVED,
            ride_id=ride_id,
            db=db,
            phone=phone,
            email=email,
        )
    except Exception:
        logger.exception(
            "Failed to send dispute_response_received notification to user %d for ride %d",
            filer_id,
            ride_id,
        )


async def notify_trip_receipt(
    db: AsyncSession,
    rider_id: int,
    ride_id: int,
) -> None:
    """Email the rider a detailed trip receipt after ride completion."""
    try:
        from app.services.notifications import Notification, NotificationType, NotificationChannel, send_notification
        from app.services.notification_templates import render
        from app.services.receipts import generate_receipt

        _, email = await _get_user_contact(db, rider_id)
        if not email:
            return

        receipt = await generate_receipt(ride_id=ride_id, user_id=rider_id, db=db)
        if not receipt:
            return

        fare = receipt.get("fare_breakdown", {})
        driver = receipt.get("driver") or {}

        title, body, channels = render(
            NotificationType.TRIP_RECEIPT,
            receipt_number=receipt.get("receipt_number", ""),
            pickup_address=receipt.get("pickup_address", "") or "",
            dropoff_address=receipt.get("dropoff_address", "") or "",
            distance_km=receipt.get("distance_km", ""),
            duration_min=receipt.get("duration_min", ""),
            fare_base=fare.get("base", ""),
            fare_distance_comp=fare.get("distance", ""),
            fare_time_comp=fare.get("time", ""),
            promo_discount=receipt.get("promo_discount", 0),
            tip=receipt.get("tip", 0),
            total_charged=receipt.get("total_charged", ""),
            driver_name=driver.get("name", ""),
            driver_rating=driver.get("rating", ""),
            driver_vehicle=driver.get("vehicle", ""),
        )
        notification = Notification(
            user_id=rider_id,
            type=NotificationType.TRIP_RECEIPT,
            title=title,
            body=body,
            channels=channels,
            data={"ride_id": ride_id},
            ride_id=ride_id,
        )
        await send_notification(notification, db=db, email=email)
    except Exception:
        logger.exception("Failed to send trip receipt email for ride %d", ride_id)


async def notify_driver_earnings(
    db: AsyncSession,
    driver_id: int,
    ride_id: int,
) -> None:
    """Email the driver a detailed earnings summary after ride completion."""
    try:
        from app.services.notifications import Notification, NotificationType, NotificationChannel, send_notification
        from app.services.notification_templates import render
        from app.services.receipts import generate_receipt

        _, email = await _get_user_contact(db, driver_id)
        if not email:
            return

        receipt = await generate_receipt(ride_id=ride_id, user_id=driver_id, db=db)
        if not receipt:
            return

        fare = receipt.get("fare_breakdown", {})
        rider = receipt.get("rider") or {}
        payment = receipt.get("payment") or {}

        # Derive platform commission and net payout from payment data when available
        platform_commission = payment.get("platform_fee", fare.get("platform_fee", ""))
        net_payout = payment.get("driver_payout", "")

        # Trip date from completed_at
        trip_date = ""
        if receipt.get("completed_at"):
            try:
                trip_date = receipt["completed_at"].strftime("%Y-%m-%d")
            except Exception:
                pass

        title, body, channels = render(
            NotificationType.DRIVER_EARNINGS,
            ride_id=ride_id,
            trip_date=trip_date,
            pickup_address=receipt.get("pickup_address", "") or "",
            dropoff_address=receipt.get("dropoff_address", "") or "",
            fare_base=fare.get("base", ""),
            fare_distance_comp=fare.get("distance", ""),
            fare_time_comp=fare.get("time", ""),
            surge_bonus=0,
            tip=receipt.get("tip", 0),
            platform_commission=platform_commission,
            net_payout=net_payout,
            rider_name=rider.get("name", ""),
            rider_rating_given=receipt.get("rider_rating_given", ""),
        )
        notification = Notification(
            user_id=driver_id,
            type=NotificationType.DRIVER_EARNINGS,
            title=title,
            body=body,
            channels=channels,
            data={"ride_id": ride_id},
            ride_id=ride_id,
        )
        await send_notification(notification, db=db, email=email)
    except Exception:
        logger.exception("Failed to send driver earnings email for ride %d", ride_id)


async def notify_streak_completed(
    db: AsyncSession,
    driver_id: int,
    program_name: str = "streak",
    bonus_amount: float = 0.0,
    program_id: int | None = None,
) -> None:
    """Notify driver that they earned a streak bonus."""
    from app.services.notifications import Notification, send_notification
    from app.services.notification_templates import render

    try:
        phone, email = await _get_user_contact(db, driver_id)
        title, body, channels = render(
            NotificationType.STREAK_COMPLETED,
            program_name=program_name,
            bonus_amount=bonus_amount,
        )
        notification = Notification(
            user_id=driver_id,
            type=NotificationType.STREAK_COMPLETED,
            title=title,
            body=body,
            channels=channels,
            data={"program_name": program_name, "bonus_amount": bonus_amount, "program_id": program_id},
        )
        await send_notification(notification, db=db, phone=phone, email=email)
    except Exception:
        logger.exception(
            "Failed to send streak_completed notification to driver %d", driver_id
        )


async def notify_streak_lost(
    db: AsyncSession,
    driver_id: int,
    program_name: str = "streak",
    program_id: int | None = None,
) -> None:
    """Notify driver that their streak was reset due to a cancellation."""
    from app.services.notifications import Notification, send_notification
    from app.services.notification_templates import render

    try:
        phone, email = await _get_user_contact(db, driver_id)
        title, body, channels = render(
            NotificationType.STREAK_LOST,
            program_name=program_name,
        )
        notification = Notification(
            user_id=driver_id,
            type=NotificationType.STREAK_LOST,
            title=title,
            body=body,
            channels=channels,
            data={"program_name": program_name, "program_id": program_id},
        )
        await send_notification(notification, db=db, phone=phone, email=email)
    except Exception:
        logger.exception(
            "Failed to send streak_lost notification to driver %d", driver_id
        )


async def notify_driver_activated(db: AsyncSession, driver_user_id: int) -> None:
    """Notify a driver that their account has been approved."""
    try:
        from app.services.notifications import Notification, NotificationType, send_notification
        from app.services.notification_templates import render
        from app.models.user import User
        from sqlalchemy import select

        result = await db.execute(select(User).where(User.id == driver_user_id))
        user = result.scalar_one_or_none()
        if not user:
            return
        phone, email = user.phone, user.email
        driver_name = getattr(user, 'first_name', '') or user.name or ''
        title, body, channels = render(NotificationType.DRIVER_ACTIVATED, driver_name=driver_name)
        notification = Notification(
            user_id=driver_user_id,
            type=NotificationType.DRIVER_ACTIVATED,
            title=title,
            body=body,
            channels=channels,
        )
        await send_notification(notification, db=db, phone=phone, email=email)
    except Exception:
        logger.exception("Failed to send driver activation notification for user %d", driver_user_id)


async def notify_driver_suspended(db: AsyncSession, driver_user_id: int, reason: str = "") -> None:
    """Notify a driver that their account has been suspended."""
    try:
        from app.services.notifications import Notification, NotificationType, send_notification
        from app.services.notification_templates import render
        from app.models.user import User
        from sqlalchemy import select

        result = await db.execute(select(User).where(User.id == driver_user_id))
        user = result.scalar_one_or_none()
        if not user:
            return
        phone, email = user.phone, user.email
        driver_name = getattr(user, 'first_name', '') or user.name or ''
        title, body, channels = render(NotificationType.DRIVER_SUSPENDED, driver_name=driver_name, reason=reason)
        notification = Notification(
            user_id=driver_user_id,
            type=NotificationType.DRIVER_SUSPENDED,
            title=title,
            body=body,
            channels=channels,
        )
        await send_notification(notification, db=db, phone=phone, email=email)
    except Exception:
        logger.exception("Failed to send driver suspension notification for user %d", driver_user_id)


async def _feedback_already_submitted(db: AsyncSession, ride_id: int, user_id: int) -> bool:
    """Return True if the user has already submitted feedback for this ride."""
    try:
        from sqlalchemy import select
        from app.models.feedback import RideFeedback

        result = await db.execute(
            select(RideFeedback).where(
                RideFeedback.ride_id == ride_id,
                RideFeedback.user_id == user_id,
            )
        )
        return result.scalar_one_or_none() is not None
    except Exception:
        logger.exception(
            "Failed to check feedback status for ride %d user %d", ride_id, user_id
        )
        return False


async def notify_feedback_prompt_rider(
    db: AsyncSession,
    rider_id: int,
    ride_id: int,
    driver_name: str = "",
) -> None:
    """Prompt rider to rate their driver after ride completion.

    Skips silently if the rider has already submitted feedback for this ride,
    making the dispatcher safe to call from retry or scheduled-reminder flows.
    """
    try:
        if await _feedback_already_submitted(db, ride_id, rider_id):
            logger.debug(
                "Skipping feedback_prompt_rider for ride %d — rider %d already rated",
                ride_id,
                rider_id,
            )
            return
        phone, email = await _get_user_contact(db, rider_id)
        await send_ride_notification(
            user_id=rider_id,
            type=NotificationType.FEEDBACK_PROMPT_RIDER,
            ride_id=ride_id,
            db=db,
            phone=phone,
            email=email,
            driver_name=driver_name,
        )
    except Exception:
        logger.exception("Failed to send feedback_prompt_rider notification for ride %d", ride_id)


async def notify_feedback_prompt_driver(
    db: AsyncSession,
    driver_id: int,
    ride_id: int,
    rider_name: str = "",
) -> None:
    """Prompt driver to rate their rider after ride completion.

    Skips silently if the driver has already submitted feedback for this ride,
    making the dispatcher safe to call from retry or scheduled-reminder flows.
    """
    try:
        if await _feedback_already_submitted(db, ride_id, driver_id):
            logger.debug(
                "Skipping feedback_prompt_driver for ride %d — driver %d already rated",
                ride_id,
                driver_id,
            )
            return
        phone, email = await _get_user_contact(db, driver_id)
        await send_ride_notification(
            user_id=driver_id,
            type=NotificationType.FEEDBACK_PROMPT_DRIVER,
            ride_id=ride_id,
            db=db,
            phone=phone,
            email=email,
            rider_name=rider_name,
        )
    except Exception:
        logger.exception("Failed to send feedback_prompt_driver notification for ride %d", ride_id)


async def notify_document_expiry_warning(
    db: AsyncSession,
    driver_id: int,
    document_type: str,
    expiry_date: str = "",
    days_remaining: int | None = None,
) -> None:
    """Warn a driver that one of their compliance documents is expiring soon.

    Args:
        db: Database session.
        driver_id: The user_id of the driver to notify.
        document_type: Human-readable document type slug, e.g. "license",
            "vehicle_registration", or "vehicle_insurance".
        expiry_date: ISO-formatted expiry date string for the notification body.
        days_remaining: Days until expiry (30, 14, 7, or 1).
    """
    try:
        phone, email = await _get_user_contact(db, driver_id)
        from app.services.notifications import Notification, send_notification
        from app.services.notification_templates import render

        title, body, channels = render(
            NotificationType.DOCUMENT_EXPIRY_WARNING,
            document_type=document_type,
            expiry_date=expiry_date,
            days_remaining=days_remaining,
        )
        notification = Notification(
            user_id=driver_id,
            type=NotificationType.DOCUMENT_EXPIRY_WARNING,
            title=title,
            body=body,
            channels=channels,
            data={
                "document_type": document_type,
                "expiry_date": expiry_date,
                "days_remaining": days_remaining,
            },
        )
        await send_notification(notification, db=db, phone=phone, email=email)
    except Exception:
        logger.exception(
            "Failed to send document_expiry_warning notification to driver %d", driver_id
        )


async def notify_document_expired(
    db: AsyncSession,
    driver_id: int,
    document_type: str,
    expiry_date: str = "",
    days_overdue: int | None = None,
) -> None:
    """Notify a driver that one of their compliance documents has already expired.

    Args:
        db: Database session.
        driver_id: The user_id of the driver to notify.
        document_type: Human-readable document type slug, e.g. "license",
            "vehicle_registration", or "vehicle_insurance".
        expiry_date: ISO-formatted expiry date string for the notification body.
        days_overdue: Number of days since expiry (0 means expired today).
    """
    try:
        phone, email = await _get_user_contact(db, driver_id)
        from app.services.notifications import Notification, send_notification
        from app.services.notification_templates import render

        title, body, channels = render(
            NotificationType.DOCUMENT_EXPIRED,
            document_type=document_type,
            expiry_date=expiry_date,
            days_overdue=days_overdue,
        )
        notification = Notification(
            user_id=driver_id,
            type=NotificationType.DOCUMENT_EXPIRED,
            title=title,
            body=body,
            channels=channels,
            data={
                "document_type": document_type,
                "expiry_date": expiry_date,
                "days_overdue": days_overdue,
            },
        )
        await send_notification(notification, db=db, phone=phone, email=email)
    except Exception:
        logger.exception(
            "Failed to send document_expired notification to driver %d", driver_id
        )
