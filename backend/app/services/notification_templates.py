"""Notification templates for ride lifecycle events.

Each template returns (title, body, channels) for a given event. Templates
support variable interpolation via keyword arguments. The channel list
determines which providers are attempted for each notification type.
"""

from __future__ import annotations

from app.services.notifications import NotificationChannel, NotificationType

# Type alias for a template result
TemplateResult = tuple[str, str, list[NotificationChannel]]

# Default channels: push for everything, SMS/email for critical events
_PUSH = [NotificationChannel.PUSH]
_PUSH_SMS = [NotificationChannel.PUSH, NotificationChannel.SMS]
_PUSH_EMAIL = [NotificationChannel.PUSH, NotificationChannel.EMAIL]
_ALL = [NotificationChannel.PUSH, NotificationChannel.SMS, NotificationChannel.EMAIL]


def ride_matched(driver_name: str = "your driver", eta_minutes: int | None = None, **kw) -> TemplateResult:
    eta_part = f" ETA: {eta_minutes} min." if eta_minutes else ""
    return (
        "Driver matched!",
        f"{driver_name} has been matched to your ride.{eta_part}",
        _PUSH_SMS,
    )


def ride_cancelled(cancelled_by: str = "The ride", reason: str = "", **kw) -> TemplateResult:
    reason_part = f" Reason: {reason}" if reason else ""
    return (
        "Ride cancelled",
        f"{cancelled_by} has been cancelled.{reason_part}",
        _PUSH_SMS,
    )


def ride_completed(fare: float | str = "", distance_km: float | str = "", **kw) -> TemplateResult:
    details = []
    if fare:
        details.append(f"Fare: ${fare}")
    if distance_km:
        details.append(f"Distance: {distance_km} km")
    detail_str = " " + " | ".join(details) if details else ""
    return (
        "Ride completed",
        f"Your ride is complete. Rate your experience!{detail_str}",
        _PUSH_EMAIL,
    )


def driver_en_route(driver_name: str = "Your driver", eta_minutes: int | None = None, **kw) -> TemplateResult:
    eta_part = f" Arriving in ~{eta_minutes} min." if eta_minutes else ""
    return (
        "Driver is on the way",
        f"{driver_name} is heading to your pickup location.{eta_part}",
        _PUSH,
    )


def driver_arrived(driver_name: str = "Your driver", **kw) -> TemplateResult:
    return (
        "Driver has arrived",
        f"{driver_name} is at the pickup location. Please come out!",
        _PUSH_SMS,
    )


def payment_received(amount: float | str = "", **kw) -> TemplateResult:
    amount_part = f" Amount: ${amount}" if amount else ""
    return (
        "Payment received",
        f"Your payment has been processed successfully.{amount_part}",
        _PUSH_EMAIL,
    )


def sos_alert(ride_id: int | str = "", user_name: str = "", **kw) -> TemplateResult:
    return (
        "SOS Alert",
        f"Emergency alert triggered{' by ' + user_name if user_name else ''}{' for ride #' + str(ride_id) if ride_id else ''}. Help is being dispatched.",
        _ALL,
    )


def rating_received(rating: float | int | str = "", **kw) -> TemplateResult:
    rating_part = f" Rating: {rating}/5" if rating else ""
    return (
        "New rating received",
        f"You received a new rating.{rating_part}",
        _PUSH,
    )


def account_verification(status: str = "update", **kw) -> TemplateResult:
    return (
        "Account verification",
        f"Your account verification status: {status}. Check the app for details.",
        _PUSH_EMAIL,
    )


def payout_completed(amount: float | str = "", period: str = "", **kw) -> TemplateResult:
    parts = []
    if amount:
        parts.append(f"Amount: ${amount}")
    if period:
        parts.append(f"Period: {period}")
    detail_str = " " + " | ".join(parts) if parts else ""
    return (
        "Payout sent",
        f"Your earnings payout has been deposited to your bank account.{detail_str}",
        _PUSH_EMAIL,
    )


def ride_reminder(pickup_time: str = "", pickup_address: str = "", **kw) -> TemplateResult:
    parts = []
    if pickup_time:
        parts.append(f"at {pickup_time}")
    if pickup_address:
        parts.append(f"from {pickup_address}")
    detail_str = " ".join(parts)
    return (
        "Upcoming ride",
        f"Reminder: you have a scheduled ride {detail_str}.",
        _PUSH_SMS,
    )


def fare_split_request(initiator_name: str = "Someone", amount: float | str = "", **kw) -> TemplateResult:
    amount_part = f" Your share: ${amount}" if amount else ""
    return (
        "Fare split request",
        f"{initiator_name} has requested to split a ride fare with you.{amount_part}",
        _PUSH,
    )


def promo_applied(code: str = "", discount: str = "", **kw) -> TemplateResult:
    return (
        "Promo code applied",
        f"Code '{code}' applied! {discount} discount on your next ride." if code else "A promo code has been applied to your account.",
        _PUSH,
    )


# Registry mapping NotificationType to template functions
TEMPLATES: dict[str, callable] = {
    NotificationType.RIDE_MATCHED: ride_matched,
    NotificationType.RIDE_CANCELLED: ride_cancelled,
    NotificationType.RIDE_COMPLETED: ride_completed,
    NotificationType.DRIVER_EN_ROUTE: driver_en_route,
    NotificationType.DRIVER_ARRIVED: driver_arrived,
    NotificationType.PAYMENT_RECEIVED: payment_received,
    NotificationType.SOS_ALERT: sos_alert,
    NotificationType.RATING_RECEIVED: rating_received,
    NotificationType.ACCOUNT_VERIFICATION: account_verification,
    "payout_completed": payout_completed,
    "ride_reminder": ride_reminder,
    "fare_split_request": fare_split_request,
    "promo_applied": promo_applied,
}


def render(notification_type: str | NotificationType, **kwargs) -> TemplateResult:
    """Look up and render a notification template. Falls back to defaults."""
    template_fn = TEMPLATES.get(notification_type)
    if template_fn:
        return template_fn(**kwargs)
    # Fallback
    return ("OpenRide Update", "You have a new update.", _PUSH)
