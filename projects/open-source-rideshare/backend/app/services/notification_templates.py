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


_CANCELLATION_CATEGORY_LABELS: dict[str, str] = {
    "wrong_pickup": "Wrong pickup location",
    "wait_too_long": "Wait time too long",
    "found_other_ride": "Found another ride",
    "plans_changed": "Plans changed",
    "driver_not_acceptable": "Driver not acceptable",
    "price_too_high": "Price too high",
    "safety_concern": "Safety concern",
    "other": "Other",
    "vehicle_issue": "Vehicle issue",
    "rider_no_show": "Rider no-show",
    "unable_to_locate": "Unable to locate rider",
    "emergency": "Emergency",
    "driver_other": "Other",
    "driver_no_show": "Driver no-show",
}


def ride_cancelled(
    cancelled_by: str = "The ride",
    reason: str = "",
    cancellation_category: str = "",
    **kw,
) -> TemplateResult:
    category_label = _CANCELLATION_CATEGORY_LABELS.get(cancellation_category, "") if cancellation_category else ""
    reason_part = f" Reason: {category_label}" if category_label else (f" Reason: {reason}" if reason else "")
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


def trip_receipt(
    receipt_number: str = "",
    pickup_address: str = "",
    dropoff_address: str = "",
    distance_km: float | str = "",
    duration_min: float | str = "",
    fare_base: float | str = "",
    fare_distance_comp: float | str = "",
    fare_time_comp: float | str = "",
    promo_discount: float | str = 0,
    tip: float | str = 0,
    total_charged: float | str = "",
    driver_name: str = "",
    driver_rating: float | str = "",
    driver_vehicle: str = "",
    **kw,
) -> TemplateResult:
    lines = ["Thanks for riding with OpenRide!\n"]
    if pickup_address and dropoff_address:
        lines.append(f"Route: {pickup_address} → {dropoff_address}")
    if distance_km:
        dist_line = f"Distance: {distance_km} km"
        if duration_min:
            dist_line += f"  |  Duration: {duration_min} min"
        lines.append(dist_line)
    lines.append("")
    lines.append("Fare breakdown:")
    if fare_base:
        lines.append(f"  Base fare:  ${fare_base}")
    if fare_distance_comp:
        lines.append(f"  Distance:   ${fare_distance_comp}")
    if fare_time_comp:
        lines.append(f"  Time:       ${fare_time_comp}")
    if promo_discount and float(promo_discount) > 0:
        lines.append(f"  Promo:     -${promo_discount}")
    if tip and float(tip) > 0:
        lines.append(f"  Tip:        ${tip}")
    if total_charged:
        lines.append(f"  Total:      ${total_charged}")
    if driver_name:
        lines.append("")
        driver_line = f"Driver: {driver_name}"
        if driver_rating:
            driver_line += f"  ★ {driver_rating}"
        lines.append(driver_line)
        if driver_vehicle:
            lines.append(f"Vehicle: {driver_vehicle}")
    if receipt_number:
        lines.append(f"\nReceipt #{receipt_number}")
    return (
        f"Your trip receipt{' — ' + receipt_number if receipt_number else ''}",
        "\n".join(lines),
        [NotificationChannel.EMAIL],
    )


def driver_earnings(
    ride_id: int | str = "",
    trip_date: str = "",
    pickup_address: str = "",
    dropoff_address: str = "",
    fare_base: float | str = "",
    fare_distance_comp: float | str = "",
    fare_time_comp: float | str = "",
    surge_bonus: float | str = 0,
    tip: float | str = 0,
    platform_commission: float | str = "",
    net_payout: float | str = "",
    rider_name: str = "",
    rider_rating_given: float | str = "",
    total_rides_today: int | str = "",
    total_earnings_today: float | str = "",
    **kw,
) -> TemplateResult:
    lines = ["Here's your earnings summary for this trip.\n"]
    if trip_date:
        date_line = f"Date: {trip_date}"
        if ride_id:
            date_line += f"  |  Ride #{ride_id}"
        lines.append(date_line)
    elif ride_id:
        lines.append(f"Ride #{ride_id}")
    if pickup_address and dropoff_address:
        lines.append(f"Route: {pickup_address} → {dropoff_address}")
    lines.append("")
    lines.append("Earnings breakdown:")
    if fare_base:
        lines.append(f"  Base fare:           ${fare_base}")
    if fare_distance_comp:
        lines.append(f"  Distance earnings:   ${fare_distance_comp}")
    if fare_time_comp:
        lines.append(f"  Time earnings:       ${fare_time_comp}")
    if surge_bonus and float(surge_bonus) > 0:
        lines.append(f"  Surge/Bonus:         ${surge_bonus}")
    if tip and float(tip) > 0:
        lines.append(f"  Tip:                 ${tip}")
    if platform_commission:
        lines.append(f"  Platform commission: -${platform_commission}")
    if net_payout:
        lines.append(f"  Net payout:          ${net_payout}")
    if rider_name:
        lines.append("")
        rider_line = f"Rider: {rider_name}"
        if rider_rating_given:
            rider_line += f"  ★ {rider_rating_given} (rating you received)"
        lines.append(rider_line)
    if total_rides_today or total_earnings_today:
        lines.append("")
        today_parts = []
        if total_rides_today:
            today_parts.append(f"Rides today: {total_rides_today}")
        if total_earnings_today:
            today_parts.append(f"Total earned today: ${total_earnings_today}")
        lines.append("  |  ".join(today_parts))
    return (
        f"Your earnings summary — Ride #{ride_id}" if ride_id else "Your trip earnings summary",
        "\n".join(lines),
        [NotificationChannel.EMAIL],
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


def background_check_approved(driver_name: str = "", **kw) -> TemplateResult:
    name = driver_name or "Your"
    return (
        "Background check approved",
        f"Great news, {name}! Your background check passed. Complete your remaining requirements to start accepting rides.",
        _PUSH_SMS,
    )


def background_check_action_required(driver_name: str = "", **kw) -> TemplateResult:
    greeting = f"Hi {driver_name}," if driver_name else "Hi there,"
    return (
        "Background check requires attention",
        f"{greeting} your background check needs review before you can drive. Log in for details or contact support with questions.",
        _PUSH_SMS,
    )


def driver_activated(driver_name: str = "", **kw) -> TemplateResult:
    name = driver_name or "there"
    return (
        "You're approved to drive!",
        f"Congratulations {name}! Your account has been approved. You're ready to go online and start accepting rides.",
        _PUSH_SMS,
    )


def driver_suspended(driver_name: str = "", reason: str = "", **kw) -> TemplateResult:
    greeting = f"Hi {driver_name}," if driver_name else "Hi there,"
    reason_part = f" Reason: {reason}." if reason else ""
    return (
        "Your account has been suspended",
        f"{greeting} your driver account has been suspended.{reason_part} Please contact support for assistance.",
        _PUSH_SMS,
    )


def feedback_prompt_rider(driver_name: str = "your driver", ride_id: int | str = "", **kw) -> TemplateResult:
    ride_part = f" (Ride #{ride_id})" if ride_id else ""
    return (
        "Rate your ride",
        f"How was your ride with {driver_name}?{ride_part} Your rating helps us maintain quality service.",
        _PUSH_SMS,
    )


def document_expiry_warning(
    document_type: str = "document",
    expiry_date: str = "",
    days_remaining: int | None = None,
    **kw,
) -> TemplateResult:
    """Advance warning that a driver document is expiring soon."""
    doc_label = document_type.replace("_", " ").title()
    if days_remaining == 1:
        when = "tomorrow"
    elif days_remaining is not None:
        when = f"in {days_remaining} day{'s' if days_remaining != 1 else ''}"
    else:
        when = "soon"
    expiry_part = f" (expires {expiry_date})" if expiry_date else ""
    return (
        f"{doc_label} expiring {when}",
        (
            f"Your {doc_label.lower()} expires {when}{expiry_part}. "
            "Please upload an updated document in the app to keep your account active."
        ),
        _PUSH_SMS,
    )


def document_expired(
    document_type: str = "document",
    expiry_date: str = "",
    days_overdue: int | None = None,
    **kw,
) -> TemplateResult:
    """Alert that a driver document has already expired."""
    doc_label = document_type.replace("_", " ").title()
    if days_overdue == 0:
        when = "today"
    elif days_overdue is not None and days_overdue > 0:
        when = f"{days_overdue} day{'s' if days_overdue != 1 else ''} ago"
    else:
        when = "recently"
    expiry_part = f" on {expiry_date}" if expiry_date else ""
    return (
        f"{doc_label} expired",
        (
            f"Your {doc_label.lower()} expired {when}{expiry_part}. "
            "You cannot accept new rides until you upload a valid document. "
            "Please update it in the app immediately."
        ),
        _PUSH_SMS,
    )


def feedback_prompt_driver(rider_name: str = "your rider", ride_id: int | str = "", **kw) -> TemplateResult:
    ride_part = f" (Ride #{ride_id})" if ride_id else ""
    return (
        "Rate your rider",
        f"How was {rider_name}?{ride_part} Your feedback helps keep the platform safe for everyone.",
        _PUSH_SMS,
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
    NotificationType.TRIP_RECEIPT: trip_receipt,
    NotificationType.DRIVER_EARNINGS: driver_earnings,
    NotificationType.BACKGROUND_CHECK_APPROVED: background_check_approved,
    NotificationType.BACKGROUND_CHECK_ACTION_REQUIRED: background_check_action_required,
    NotificationType.DRIVER_ACTIVATED: driver_activated,
    NotificationType.DRIVER_SUSPENDED: driver_suspended,
    NotificationType.FEEDBACK_PROMPT_RIDER: feedback_prompt_rider,
    NotificationType.FEEDBACK_PROMPT_DRIVER: feedback_prompt_driver,
    NotificationType.DOCUMENT_EXPIRY_WARNING: document_expiry_warning,
    NotificationType.DOCUMENT_EXPIRED: document_expired,
}


def render(notification_type: str | NotificationType, **kwargs) -> TemplateResult:
    """Look up and render a notification template. Falls back to defaults."""
    template_fn = TEMPLATES.get(notification_type)
    if template_fn:
        return template_fn(**kwargs)
    # Fallback
    return ("OpenRide Update", "You have a new update.", _PUSH)
