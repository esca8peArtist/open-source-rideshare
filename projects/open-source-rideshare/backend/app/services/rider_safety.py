"""Rider emergency safety service.

Implements panic button and trusted contact alert features for the
cooperative rideshare platform.

Panic Button:
    Riders can trigger a panic alert during an active ride.  Alerts are
    visible to admins immediately, sorted oldest-first (most urgent).
    Only one ACTIVE alert is permitted per ride.  Cancelling within 30
    seconds marks the alert FALSE_ALARM; after 30 seconds it becomes
    RESOLVED.

Trusted Contacts:
    Riders can designate up to 3 contacts to receive notifications on
    trip start, trip end, and panic events.  Actual SMS/email delivery is
    stubbed — notification records are written to the in-memory store with
    delivery_status=SENT.  A production implementation would replace the
    stub with a real delivery provider.

All storage uses the same in-memory dict pattern as the rest of this
codebase.  A production implementation would replace stores with async
SQLAlchemy queries.

Public API:
    trigger_panic(db, rider_id, ride_id, driver_id, location_lat, location_lng) -> dict
    get_panic_alert(db, rider_id, alert_id) -> dict | None
    cancel_panic_alert(db, rider_id, alert_id) -> dict
    admin_list_active_panic_alerts(db, skip, limit) -> tuple[int, list[dict]]
    admin_resolve_panic_alert(db, alert_id, admin_id, resolution_notes) -> dict

    add_trusted_contact(db, rider_id, name, phone, email, notify_on_trip_start,
                        notify_on_trip_end, notify_on_panic) -> dict
    list_trusted_contacts(db, rider_id) -> list[dict]
    get_trusted_contact(db, rider_id, contact_id) -> dict | None
    update_trusted_contact(db, rider_id, contact_id, **fields) -> dict
    deactivate_trusted_contact(db, rider_id, contact_id) -> dict
    get_notification_log(db, rider_id, contact_id, limit) -> list[dict]
    send_trusted_contact_notifications(db, ride_id, rider_id, notification_type) -> list[dict]
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.rider_safety import (
    PanicAlertStatus,
    TrustedContactDeliveryStatus,
    TrustedContactNotificationType,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# In-memory stores (same pattern as other services in this codebase)
# ---------------------------------------------------------------------------

_panic_alerts: dict[str, dict] = {}
_trusted_contacts: dict[str, dict] = {}
_trusted_contact_notifications: dict[str, dict] = {}

# Maximum active trusted contacts per rider
MAX_TRUSTED_CONTACTS = 3

# Seconds within which a cancel is considered FALSE_ALARM
FALSE_ALARM_WINDOW_SECONDS = 30


def _utc_now() -> datetime:
    return datetime.now(tz=timezone.utc)


def _new_id() -> str:
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


def _reset_store() -> None:
    """Clear all in-memory state.  For use in tests only."""
    _panic_alerts.clear()
    _trusted_contacts.clear()
    _trusted_contact_notifications.clear()


# ---------------------------------------------------------------------------
# Panic alert operations
# ---------------------------------------------------------------------------


async def trigger_panic(
    db: AsyncSession,
    rider_id: int,
    ride_id: int,
    driver_id: int,
    location_lat: Optional[float] = None,
    location_lng: Optional[float] = None,
) -> dict:
    """Trigger a panic alert for the given active ride.

    Only one ACTIVE panic alert is permitted per ride.  If an alert already
    exists for this ride, raises ValueError.

    Args:
        db:          Async database session (unused in this implementation).
        rider_id:    ID of the rider triggering the alert.
        ride_id:     ID of the active ride.
        driver_id:   ID of the driver on the ride.
        location_lat: Rider's latitude at trigger time (optional).
        location_lng: Rider's longitude at trigger time (optional).

    Returns:
        The newly created panic alert as a dict.

    Raises:
        ValueError: If there is already an ACTIVE panic alert for this ride.
    """
    # One active alert per ride
    existing = [
        a for a in _panic_alerts.values()
        if a["ride_id"] == ride_id and a["status"] == PanicAlertStatus.ACTIVE
    ]
    if existing:
        raise ValueError(f"An active panic alert already exists for ride {ride_id}.")

    alert_id = _new_id()
    now = _utc_now()
    alert = {
        "id": alert_id,
        "ride_id": ride_id,
        "rider_id": rider_id,
        "driver_id": driver_id,
        "triggered_at": now,
        "location_lat": location_lat,
        "location_lng": location_lng,
        "status": PanicAlertStatus.ACTIVE,
        "resolved_at": None,
        "resolved_by": None,
        "resolution_notes": None,
    }
    _panic_alerts[alert_id] = alert
    logger.warning(
        "PANIC ALERT triggered — rider=%s ride=%s alert=%s",
        rider_id, ride_id, alert_id,
    )
    return dict(alert)


async def get_panic_alert(
    db: AsyncSession,
    rider_id: int,
    alert_id: str,
) -> Optional[dict]:
    """Retrieve a panic alert owned by the given rider.

    Returns None if the alert does not exist or belongs to a different rider.
    Callers should raise HTTP 404 in either case — do not leak existence.

    Args:
        db:       Async database session (unused in this implementation).
        rider_id: ID of the authenticated rider.
        alert_id: UUID of the panic alert.

    Returns:
        Alert dict if found and owned by rider_id, else None.
    """
    alert = _panic_alerts.get(alert_id)
    if alert is None or alert["rider_id"] != rider_id:
        return None
    return dict(alert)


async def cancel_panic_alert(
    db: AsyncSession,
    rider_id: int,
    alert_id: str,
) -> dict:
    """Cancel a panic alert.

    If cancelled within FALSE_ALARM_WINDOW_SECONDS of trigger, the status
    is set to FALSE_ALARM; otherwise it is set to RESOLVED.

    Args:
        db:       Async database session (unused in this implementation).
        rider_id: ID of the authenticated rider.
        alert_id: UUID of the panic alert to cancel.

    Returns:
        Updated alert dict.

    Raises:
        PermissionError: If alert does not exist or belongs to another rider.
        ValueError:      If alert is not ACTIVE.
    """
    alert = _panic_alerts.get(alert_id)
    if alert is None or alert["rider_id"] != rider_id:
        raise PermissionError(f"Panic alert {alert_id} not found.")

    if alert["status"] != PanicAlertStatus.ACTIVE:
        raise ValueError(
            f"Cannot cancel alert in status '{alert['status'].value}'. "
            "Only ACTIVE alerts can be cancelled."
        )

    now = _utc_now()
    elapsed = (now - alert["triggered_at"]).total_seconds()
    new_status = (
        PanicAlertStatus.FALSE_ALARM
        if elapsed <= FALSE_ALARM_WINDOW_SECONDS
        else PanicAlertStatus.RESOLVED
    )
    alert["status"] = new_status
    alert["resolved_at"] = now
    logger.info(
        "Panic alert %s cancelled as %s by rider %s (%.1fs after trigger)",
        alert_id, new_status.value, rider_id, elapsed,
    )
    return dict(alert)


async def admin_list_active_panic_alerts(
    db: AsyncSession,
    skip: int = 0,
    limit: int = 50,
) -> tuple[int, list[dict]]:
    """List all ACTIVE panic alerts, sorted oldest-first (most urgent).

    Args:
        db:    Async database session (unused in this implementation).
        skip:  Pagination offset.
        limit: Maximum number of results.

    Returns:
        (total, items) — total ACTIVE count and the requested page.
    """
    active = [
        a for a in _panic_alerts.values()
        if a["status"] == PanicAlertStatus.ACTIVE
    ]
    active.sort(key=lambda a: a["triggered_at"])  # oldest first = most urgent
    total = len(active)
    page = active[skip: skip + limit]
    return total, [dict(a) for a in page]


async def admin_resolve_panic_alert(
    db: AsyncSession,
    alert_id: str,
    admin_id: int,
    resolution_notes: Optional[str] = None,
) -> dict:
    """Admin resolves a panic alert with optional notes.

    Args:
        db:               Async database session (unused in this implementation).
        alert_id:         UUID of the panic alert to resolve.
        admin_id:         ID of the admin performing the resolution.
        resolution_notes: Optional notes on the resolution.

    Returns:
        Updated alert dict.

    Raises:
        KeyError:   If the alert does not exist.
        ValueError: If the alert is not ACTIVE.
    """
    alert = _panic_alerts.get(alert_id)
    if alert is None:
        raise KeyError(f"Panic alert {alert_id} not found.")

    if alert["status"] != PanicAlertStatus.ACTIVE:
        raise ValueError(
            f"Alert is already in status '{alert['status'].value}'. "
            "Only ACTIVE alerts can be resolved."
        )

    now = _utc_now()
    alert["status"] = PanicAlertStatus.RESOLVED
    alert["resolved_at"] = now
    alert["resolved_by"] = admin_id
    alert["resolution_notes"] = resolution_notes
    logger.info(
        "Admin %s resolved panic alert %s",
        admin_id, alert_id,
    )
    return dict(alert)


# ---------------------------------------------------------------------------
# Trusted contact operations
# ---------------------------------------------------------------------------


async def add_trusted_contact(
    db: AsyncSession,
    rider_id: int,
    name: str,
    phone: str,
    email: Optional[str] = None,
    notify_on_trip_start: bool = True,
    notify_on_trip_end: bool = True,
    notify_on_panic: bool = True,
) -> dict:
    """Add a trusted contact for the rider.

    A rider may have at most MAX_TRUSTED_CONTACTS (3) active contacts.

    Args:
        db:                   Async database session (unused in this implementation).
        rider_id:             ID of the authenticated rider.
        name:                 Contact's full name.
        phone:                Contact's phone number.
        email:                Contact's email address (optional).
        notify_on_trip_start: Whether to notify on trip start.
        notify_on_trip_end:   Whether to notify on trip end.
        notify_on_panic:      Whether to notify on panic alert.

    Returns:
        Newly created trusted contact dict.

    Raises:
        ValueError: If the rider already has MAX_TRUSTED_CONTACTS active contacts.
    """
    active_count = sum(
        1 for c in _trusted_contacts.values()
        if c["rider_id"] == rider_id and c["is_active"]
    )
    if active_count >= MAX_TRUSTED_CONTACTS:
        raise ValueError(
            f"Riders may have at most {MAX_TRUSTED_CONTACTS} active trusted contacts. "
            "Please deactivate an existing contact before adding a new one."
        )

    contact_id = _new_id()
    contact = {
        "id": contact_id,
        "rider_id": rider_id,
        "name": name,
        "phone": phone,
        "email": email,
        "notify_on_trip_start": notify_on_trip_start,
        "notify_on_trip_end": notify_on_trip_end,
        "notify_on_panic": notify_on_panic,
        "is_active": True,
        "created_at": _utc_now(),
    }
    _trusted_contacts[contact_id] = contact
    logger.info("Rider %s added trusted contact %s", rider_id, contact_id)
    return dict(contact)


async def list_trusted_contacts(
    db: AsyncSession,
    rider_id: int,
) -> list[dict]:
    """Return all trusted contacts (active and inactive) for a rider.

    Args:
        db:       Async database session (unused in this implementation).
        rider_id: ID of the authenticated rider.

    Returns:
        List of trusted contact dicts, ordered by creation time.
    """
    contacts = [
        c for c in _trusted_contacts.values()
        if c["rider_id"] == rider_id
    ]
    contacts.sort(key=lambda c: c["created_at"])
    return [dict(c) for c in contacts]


async def get_trusted_contact(
    db: AsyncSession,
    rider_id: int,
    contact_id: str,
) -> Optional[dict]:
    """Retrieve a single trusted contact owned by the given rider.

    Returns None if contact does not exist or belongs to a different rider.

    Args:
        db:         Async database session (unused in this implementation).
        rider_id:   ID of the authenticated rider.
        contact_id: UUID of the trusted contact.

    Returns:
        Contact dict if found and owned by rider_id, else None.
    """
    contact = _trusted_contacts.get(contact_id)
    if contact is None or contact["rider_id"] != rider_id:
        return None
    return dict(contact)


async def update_trusted_contact(
    db: AsyncSession,
    rider_id: int,
    contact_id: str,
    name: Optional[str] = None,
    phone: Optional[str] = None,
    email: Optional[str] = None,
    notify_on_trip_start: Optional[bool] = None,
    notify_on_trip_end: Optional[bool] = None,
    notify_on_panic: Optional[bool] = None,
) -> dict:
    """Update fields on a trusted contact.

    Only fields provided (not None) are updated.

    Args:
        db:         Async database session (unused in this implementation).
        rider_id:   ID of the authenticated rider.
        contact_id: UUID of the trusted contact.

    Returns:
        Updated trusted contact dict.

    Raises:
        PermissionError: If contact does not exist or belongs to another rider.
    """
    contact = _trusted_contacts.get(contact_id)
    if contact is None or contact["rider_id"] != rider_id:
        raise PermissionError(f"Trusted contact {contact_id} not found.")

    if name is not None:
        contact["name"] = name
    if phone is not None:
        contact["phone"] = phone
    if email is not None:
        contact["email"] = email
    if notify_on_trip_start is not None:
        contact["notify_on_trip_start"] = notify_on_trip_start
    if notify_on_trip_end is not None:
        contact["notify_on_trip_end"] = notify_on_trip_end
    if notify_on_panic is not None:
        contact["notify_on_panic"] = notify_on_panic

    logger.info("Rider %s updated trusted contact %s", rider_id, contact_id)
    return dict(contact)


async def deactivate_trusted_contact(
    db: AsyncSession,
    rider_id: int,
    contact_id: str,
) -> dict:
    """Soft-delete a trusted contact by setting is_active=False.

    Args:
        db:         Async database session (unused in this implementation).
        rider_id:   ID of the authenticated rider.
        contact_id: UUID of the trusted contact.

    Returns:
        Updated trusted contact dict with is_active=False.

    Raises:
        PermissionError: If contact does not exist or belongs to another rider.
    """
    contact = _trusted_contacts.get(contact_id)
    if contact is None or contact["rider_id"] != rider_id:
        raise PermissionError(f"Trusted contact {contact_id} not found.")

    contact["is_active"] = False
    logger.info("Rider %s deactivated trusted contact %s", rider_id, contact_id)
    return dict(contact)


async def get_notification_log(
    db: AsyncSession,
    rider_id: int,
    contact_id: str,
    limit: int = 30,
) -> list[dict]:
    """Return recent notifications sent to a trusted contact.

    Args:
        db:         Async database session (unused in this implementation).
        rider_id:   ID of the authenticated rider (ownership check).
        contact_id: UUID of the trusted contact.
        limit:      Maximum notifications to return (default 30).

    Returns:
        List of notification dicts, most recent first.

    Raises:
        PermissionError: If contact does not exist or belongs to another rider.
    """
    contact = _trusted_contacts.get(contact_id)
    if contact is None or contact["rider_id"] != rider_id:
        raise PermissionError(f"Trusted contact {contact_id} not found.")

    notifications = [
        n for n in _trusted_contact_notifications.values()
        if n["contact_id"] == contact_id
    ]
    notifications.sort(key=lambda n: n["sent_at"], reverse=True)
    return [dict(n) for n in notifications[:limit]]


async def send_trusted_contact_notifications(
    db: AsyncSession,
    ride_id: int,
    rider_id: int,
    notification_type: TrustedContactNotificationType,
) -> list[dict]:
    """Stub: log notification records for all eligible trusted contacts.

    No actual SMS or email is sent.  Records are written to the in-memory
    store with delivery_status=SENT.  A production implementation would
    call a real delivery provider here and update delivery_status accordingly.

    Contacts that do not have the relevant notify_on_* flag set are skipped.

    Args:
        db:                Async database session (unused in this implementation).
        ride_id:           ID of the ride this notification relates to.
        rider_id:          ID of the rider whose contacts to notify.
        notification_type: Type of event (TRIP_START, TRIP_END, PANIC_ALERT).

    Returns:
        List of created notification dicts.
    """
    _type_to_flag = {
        TrustedContactNotificationType.TRIP_START: "notify_on_trip_start",
        TrustedContactNotificationType.TRIP_END: "notify_on_trip_end",
        TrustedContactNotificationType.PANIC_ALERT: "notify_on_panic",
    }
    flag = _type_to_flag[notification_type]

    eligible_contacts = [
        c for c in _trusted_contacts.values()
        if c["rider_id"] == rider_id and c["is_active"] and c[flag]
    ]

    _type_messages = {
        TrustedContactNotificationType.TRIP_START: "Your contact has started a ride.",
        TrustedContactNotificationType.TRIP_END: "Your contact has completed their ride.",
        TrustedContactNotificationType.PANIC_ALERT: "URGENT: Your contact has triggered a panic alert.",
    }
    message_preview = _type_messages[notification_type]

    created: list[dict] = []
    now = _utc_now()
    for contact in eligible_contacts:
        notif_id = _new_id()
        notification = {
            "id": notif_id,
            "contact_id": contact["id"],
            "ride_id": ride_id,
            "notification_type": notification_type,
            "sent_at": now,
            "delivery_status": TrustedContactDeliveryStatus.SENT,
            "message_preview": message_preview,
        }
        _trusted_contact_notifications[notif_id] = notification
        created.append(dict(notification))
        logger.info(
            "Stub notification sent to contact %s for rider %s — type=%s ride=%s",
            contact["id"], rider_id, notification_type.value, ride_id,
        )

    return created
