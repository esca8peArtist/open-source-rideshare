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
_SMS = [NotificationChannel.SMS]


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


def promo_expiring(code: str = "", hours_left: int | None = None, **kw) -> TemplateResult:
    time_part = f" in {hours_left} hour{'s' if hours_left != 1 else ''}" if hours_left else " soon"
    body = (
        f"Your promo code '{code}' expires{time_part}! Use it on your next ride before it's gone."
        if code
        else f"A promo code on your account expires{time_part}. Use it before it's gone."
    )
    return ("Promo code expiring", body, _PUSH_SMS)


def promo_applied(code: str = "", discount: str = "", **kw) -> TemplateResult:
    return (
        "Promo code applied",
        f"Code '{code}' applied! {discount} discount on your next ride." if code else "A promo code has been applied to your account.",
        _PUSH,
    )


def ride_in_progress(dropoff_address: str = "", **kw) -> TemplateResult:
    dest_part = f" Destination: {dropoff_address}" if dropoff_address else ""
    return (
        "Your ride has started",
        f"You're on your way!{dest_part} Sit back and relax.",
        _PUSH,
    )


def ride_assigned(rider_name: str = "A rider", pickup_address: str = "", **kw) -> TemplateResult:
    pickup_part = f" Pickup: {pickup_address}" if pickup_address else ""
    return (
        "New ride assigned",
        f"{rider_name} is waiting for you.{pickup_part} Head to the pickup location.",
        _PUSH_SMS,
    )


def ride_completed_driver(fare: float | str = "", **kw) -> TemplateResult:
    fare_part = f" Earnings: ${fare}" if fare else ""
    return (
        "Ride complete",
        f"You've completed a ride.{fare_part} Great work!",
        _PUSH,
    )


def route_deviation(dropoff_address: str = "", **kw) -> TemplateResult:
    dest_part = f" to {dropoff_address}" if dropoff_address else ""
    return (
        "Route alert",
        f"Your driver appears to have deviated from the expected route{dest_part}. Tap to check your trip or contact support.",
        _PUSH_SMS,
    )


def driver_no_show(
    wait_minutes: int | str = "", new_ride_id: int | None = None, **kw
) -> TemplateResult:
    wait_part = f" after {wait_minutes} minutes" if wait_minutes else ""
    if new_ride_id:
        body = (
            f"Your driver did not arrive{wait_part}. Any payment will be refunded. "
            f"We've automatically requested a new driver for you (ride #{new_ride_id})."
        )
    else:
        body = (
            f"Your driver did not arrive{wait_part}. Your ride has been cancelled "
            "and any payment will be refunded. Please request a new ride."
        )
    return ("Driver no-show — ride cancelled", body, _PUSH_SMS)


_ALERT_LABELS: dict[str, str] = {
    "high_no_show": "high no-show rate",
    "low_score": "low performance score",
    "high_cancellation": "high cancellation rate",
}


def driver_performance_warning(
    alert_type: str = "", warning_count: int = 1, **kw
) -> TemplateResult:
    label = _ALERT_LABELS.get(alert_type, "performance issue")
    return (
        "Performance warning",
        (
            f"Your account has been flagged for {label}. "
            "This is your first warning. Continued issues may result in account suspension. "
            "Open the app to view your performance dashboard."
        ),
        _PUSH_SMS,
    )


def driver_performance_final_warning(
    alert_type: str = "", warning_count: int = 2, **kw
) -> TemplateResult:
    label = _ALERT_LABELS.get(alert_type, "performance issue")
    return (
        "Final performance warning",
        (
            f"Your account has received a second flag for {label}. "
            "This is your final warning — one more escalation will result in automatic suspension. "
            "Please review your performance dashboard and contact support if you need help."
        ),
        _PUSH_SMS,
    )


def scheduled_dispatched(pickup_address: str = "", scheduled_for: str = "", **kw) -> TemplateResult:
    pickup_part = f" from {pickup_address}" if pickup_address else ""
    time_part = f" (originally scheduled for {scheduled_for})" if scheduled_for else ""
    return (
        "Your ride is being dispatched",
        f"We're finding a driver for your scheduled ride{pickup_part}{time_part}.",
        _PUSH_SMS,
    )


def driver_auto_suspended(
    alert_type: str = "", warning_count: int = 3, **kw
) -> TemplateResult:
    label = _ALERT_LABELS.get(alert_type, "performance issue")
    return (
        "Account suspended",
        (
            f"Your driver account has been automatically suspended due to repeated {label}. "
            "You will not be able to accept new rides until this is resolved. "
            "Please contact support to appeal or request a review."
        ),
        _PUSH_SMS,
    )


def geofence_exit(**kw) -> TemplateResult:
    return (
        "Driver has left the service area",
        "Your driver has moved outside our service area. We're monitoring your trip. Tap to view your ride or contact support.",
        _PUSH_SMS,
    )


def driver_geofence_exit(**kw) -> TemplateResult:
    return (
        "You have left the service area",
        "You have moved outside the service area for your current trip. Please return to complete the ride.",
        _PUSH,
    )


def speeding_alert(**kw) -> TemplateResult:
    return (
        "Speed alert",
        "Your driver appears to be travelling at an unsafe speed. Tap to check your trip or contact support.",
        _PUSH_SMS,
    )


def pool_rider_joined(new_rider_name: str = "A new rider", **kw) -> TemplateResult:
    return (
        "New rider joined your pool",
        f"{new_rider_name} has joined your pool ride. Your fare discount has been updated.",
        _PUSH,
    )


def trip_share_viewed(**kw) -> TemplateResult:
    return (
        "Someone viewed your trip",
        "Someone is following your live trip using your shared link.",
        _PUSH,
    )


def dispute_filed(dispute_type: str = "a", **kw) -> TemplateResult:
    return (
        "Dispute filed on your ride",
        f"A dispute ({dispute_type}) has been filed on a recent ride you completed. You can submit your response via the app.",
        _PUSH_EMAIL,
    )


def dispute_resolved(outcome: str = "resolved", **kw) -> TemplateResult:
    return (
        "Your dispute has been resolved",
        f"Your dispute has been {outcome}. Check the app for details and any refund information.",
        _PUSH_EMAIL,
    )


def dispute_response_received(**kw) -> TemplateResult:
    return (
        "Response received on your dispute",
        "The other party has submitted a response to your dispute. An admin will review both sides.",
        _PUSH,
    )


def streak_completed(program_name: str = "streak", bonus_amount: float | str = "", **kw) -> TemplateResult:
    bonus_part = f" Bonus: ${bonus_amount}" if bonus_amount else ""
    return (
        "Streak bonus earned!",
        f"You completed your {program_name}!{bonus_part} It will be included in your next payout.",
        _PUSH_EMAIL,
    )


def streak_lost(program_name: str = "streak", **kw) -> TemplateResult:
    return (
        "Streak reset",
        f"Your {program_name} was reset due to a cancellation. Start fresh — complete your next rides without cancelling to earn the bonus.",
        _PUSH,
    )


def safe_arrival_contact(
    user_name: str = "Someone",
    ride_id: int | str = "",
    **kw,
) -> TemplateResult:
    ride_part = f" (Ride #{ride_id})" if ride_id else ""
    return (
        "Safe Arrival Confirmed",
        f"{user_name} has confirmed they arrived safely.{ride_part} No action needed.",
        _SMS,
    )


def emergency_contact_sos(
    user_name: str = "Someone",
    ride_id: int | str = "",
    latitude: float | str = "",
    longitude: float | str = "",
    **kw,
) -> TemplateResult:
    location_part = f" Location: {latitude}, {longitude}" if latitude and longitude else ""
    ride_part = f" Ride #{ride_id}" if ride_id else ""
    return (
        "Emergency SOS Alert",
        f"{user_name} has triggered an emergency SOS alert.{ride_part}{location_part} Please check on them immediately.",
        _SMS,
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
    "promo_expiring": promo_expiring,
    NotificationType.RIDE_IN_PROGRESS: ride_in_progress,
    NotificationType.RIDE_ASSIGNED: ride_assigned,
    NotificationType.RIDE_COMPLETED_DRIVER: ride_completed_driver,
    NotificationType.ROUTE_DEVIATION: route_deviation,
    NotificationType.DRIVER_NO_SHOW: driver_no_show,
    NotificationType.DRIVER_PERFORMANCE_WARNING: driver_performance_warning,
    NotificationType.DRIVER_PERFORMANCE_FINAL_WARNING: driver_performance_final_warning,
    NotificationType.DRIVER_AUTO_SUSPENDED: driver_auto_suspended,
    NotificationType.RIDE_SCHEDULED_DISPATCHED: scheduled_dispatched,
    NotificationType.GEOFENCE_EXIT: geofence_exit,
    NotificationType.DRIVER_GEOFENCE_EXIT: driver_geofence_exit,
    NotificationType.SPEEDING_ALERT: speeding_alert,
    NotificationType.POOL_RIDER_JOINED: pool_rider_joined,
    NotificationType.TRIP_SHARE_VIEWED: trip_share_viewed,
    NotificationType.DISPUTE_FILED: dispute_filed,
    NotificationType.DISPUTE_RESOLVED: dispute_resolved,
    NotificationType.DISPUTE_RESPONSE_RECEIVED: dispute_response_received,
    NotificationType.STREAK_COMPLETED: streak_completed,
    NotificationType.STREAK_LOST: streak_lost,
    NotificationType.EMERGENCY_CONTACT_SOS: emergency_contact_sos,
    NotificationType.SAFE_ARRIVAL_CONTACT: safe_arrival_contact,
}


def render(notification_type: str | NotificationType, **kwargs) -> TemplateResult:
    """Look up and render a notification template. Falls back to defaults."""
    template_fn = TEMPLATES.get(notification_type)
    if template_fn:
        return template_fn(**kwargs)
    # Fallback
    return ("OpenRide Update", "You have a new update.", _PUSH)
