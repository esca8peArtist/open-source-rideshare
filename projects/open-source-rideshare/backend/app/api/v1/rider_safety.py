"""Rider emergency safety endpoints.

POST   /riders/me/panic                                     — trigger panic alert
GET    /riders/me/panic/{alert_id}                          — get alert status
DELETE /riders/me/panic/{alert_id}                          — cancel alert
GET    /admin/panic-alerts                                  — admin: list all ACTIVE alerts
POST   /admin/panic-alerts/{alert_id}/resolve               — admin: resolve alert

POST   /riders/me/trusted-contacts                          — add trusted contact (max 3)
GET    /riders/me/trusted-contacts                          — list all contacts
PUT    /riders/me/trusted-contacts/{contact_id}             — update contact
DELETE /riders/me/trusted-contacts/{contact_id}             — deactivate contact
GET    /riders/me/trusted-contacts/{contact_id}/notification-log  — recent notifications

All business rules are enforced in the service layer.  This module handles
HTTP mapping only: 404 on ownership mismatches (do not leak existence),
400 on invalid state transitions, 422 on constraint violations.
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_admin
from app.db.database import get_db
from app.models.user import User
from app.schemas.rider_safety import (
    AdminResolvePanicRequest,
    PanicAlertListResponse,
    PanicAlertResponse,
    TriggerPanicRequest,
    TrustedContactCreate,
    TrustedContactNotificationLogResponse,
    TrustedContactNotificationType,
    TrustedContactResponse,
    TrustedContactUpdate,
)
from app.services.rider_safety import (
    add_trusted_contact,
    admin_list_active_panic_alerts,
    admin_resolve_panic_alert,
    cancel_panic_alert,
    deactivate_trusted_contact,
    get_notification_log,
    get_panic_alert,
    get_trusted_contact,
    list_trusted_contacts,
    send_trusted_contact_notifications,
    trigger_panic,
    update_trusted_contact,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["rider-safety"])


# ---------------------------------------------------------------------------
# Panic alert — rider endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/riders/me/panic",
    response_model=PanicAlertResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Trigger panic alert",
    description=(
        "Trigger a panic alert during an active ride.  The alert is immediately "
        "visible to platform admins, sorted by oldest trigger time (most urgent "
        "first).  Only one ACTIVE alert per ride is permitted.\n\n"
        "The rider's current location may optionally be included to assist "
        "responders."
    ),
)
async def post_trigger_panic(
    body: TriggerPanicRequest,
    rider: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PanicAlertResponse:
    """Trigger a panic alert for the rider's current active ride."""
    # Resolve current active ride for this rider from the DB
    from sqlalchemy import select
    from app.models.ride import Ride, RideStatus

    result = await db.execute(
        select(Ride).where(
            Ride.rider_id == rider.id,
            Ride.status == RideStatus.IN_PROGRESS,
        )
    )
    ride = result.scalar_one_or_none()
    if ride is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No active ride found. A panic alert requires an active ride.",
        )

    try:
        alert = await trigger_panic(
            db=db,
            rider_id=rider.id,
            ride_id=ride.id,
            driver_id=ride.driver_id,
            location_lat=body.location_lat,
            location_lng=body.location_lng,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    # Notify trusted contacts with notify_on_panic=True — fire-and-forget.
    try:
        await send_trusted_contact_notifications(
            db, ride_id=ride.id, rider_id=rider.id,
            notification_type=TrustedContactNotificationType.PANIC_ALERT,
        )
    except Exception:
        logger.exception("Failed to notify trusted contacts for panic alert on ride %d", ride.id)

    return PanicAlertResponse(**alert)


@router.get(
    "/riders/me/panic/{alert_id}",
    response_model=PanicAlertResponse,
    summary="Get panic alert status",
    description="Retrieve the current status of a panic alert triggered by the authenticated rider.",
)
async def get_panic_alert_endpoint(
    alert_id: str,
    rider: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PanicAlertResponse:
    """Get a panic alert owned by the authenticated rider."""
    alert = await get_panic_alert(db=db, rider_id=rider.id, alert_id=alert_id)
    if alert is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Panic alert not found.",
        )
    return PanicAlertResponse(**alert)


@router.delete(
    "/riders/me/panic/{alert_id}",
    response_model=PanicAlertResponse,
    summary="Cancel panic alert",
    description=(
        "Cancel an ACTIVE panic alert.  If cancelled within 30 seconds of "
        "triggering, the status is set to FALSE_ALARM.  After 30 seconds "
        "it is set to RESOLVED."
    ),
)
async def delete_cancel_panic_alert(
    alert_id: str,
    rider: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PanicAlertResponse:
    """Cancel a panic alert triggered by the authenticated rider."""
    try:
        alert = await cancel_panic_alert(db=db, rider_id=rider.id, alert_id=alert_id)
    except PermissionError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Panic alert not found.",
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    return PanicAlertResponse(**alert)


# ---------------------------------------------------------------------------
# Panic alert — admin endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/admin/panic-alerts",
    response_model=PanicAlertListResponse,
    summary="Admin: list all active panic alerts",
    description=(
        "List all ACTIVE panic alerts across the platform, sorted oldest-first "
        "(most urgent first).  Admin access required."
    ),
)
async def admin_get_active_panic_alerts(
    skip: int = Query(0, ge=0, description="Pagination offset."),
    limit: int = Query(50, ge=1, le=200, description="Maximum results per page."),
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> PanicAlertListResponse:
    """Return all ACTIVE panic alerts (admin view)."""
    total, items = await admin_list_active_panic_alerts(db=db, skip=skip, limit=limit)
    return PanicAlertListResponse(
        total=total,
        items=[PanicAlertResponse(**a) for a in items],
    )


@router.post(
    "/admin/panic-alerts/{alert_id}/resolve",
    response_model=PanicAlertResponse,
    summary="Admin: resolve a panic alert",
    description=(
        "Mark an ACTIVE panic alert as RESOLVED with optional resolution notes.  "
        "Admin access required."
    ),
)
async def admin_post_resolve_panic_alert(
    alert_id: str,
    body: AdminResolvePanicRequest,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> PanicAlertResponse:
    """Resolve a panic alert (admin operation)."""
    try:
        alert = await admin_resolve_panic_alert(
            db=db,
            alert_id=alert_id,
            admin_id=admin.id,
            resolution_notes=body.resolution_notes,
        )
    except KeyError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Panic alert not found.",
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    return PanicAlertResponse(**alert)


# ---------------------------------------------------------------------------
# Trusted contacts — rider endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/riders/me/trusted-contacts",
    response_model=TrustedContactResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add trusted contact",
    description=(
        "Add a trusted contact who will receive notifications on trip start, "
        "trip end, and/or panic events.  A rider may have at most 3 active "
        "trusted contacts."
    ),
)
async def post_add_trusted_contact(
    body: TrustedContactCreate,
    rider: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TrustedContactResponse:
    """Add a trusted contact for the authenticated rider."""
    try:
        contact = await add_trusted_contact(
            db=db,
            rider_id=rider.id,
            name=body.name,
            phone=body.phone,
            email=body.email,
            notify_on_trip_start=body.notify_on_trip_start,
            notify_on_trip_end=body.notify_on_trip_end,
            notify_on_panic=body.notify_on_panic,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    return TrustedContactResponse(**contact)


@router.get(
    "/riders/me/trusted-contacts",
    response_model=list[TrustedContactResponse],
    summary="List trusted contacts",
    description="Return all trusted contacts for the authenticated rider.",
)
async def get_list_trusted_contacts(
    rider: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[TrustedContactResponse]:
    """List trusted contacts for the authenticated rider."""
    contacts = await list_trusted_contacts(db=db, rider_id=rider.id)
    return [TrustedContactResponse(**c) for c in contacts]


@router.put(
    "/riders/me/trusted-contacts/{contact_id}",
    response_model=TrustedContactResponse,
    summary="Update trusted contact",
    description="Update one or more fields on a trusted contact.  Only provided fields are changed.",
)
async def put_update_trusted_contact(
    contact_id: str,
    body: TrustedContactUpdate,
    rider: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TrustedContactResponse:
    """Update a trusted contact owned by the authenticated rider."""
    try:
        contact = await update_trusted_contact(
            db=db,
            rider_id=rider.id,
            contact_id=contact_id,
            name=body.name,
            phone=body.phone,
            email=body.email,
            notify_on_trip_start=body.notify_on_trip_start,
            notify_on_trip_end=body.notify_on_trip_end,
            notify_on_panic=body.notify_on_panic,
        )
    except PermissionError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Trusted contact not found.",
        )

    return TrustedContactResponse(**contact)


@router.delete(
    "/riders/me/trusted-contacts/{contact_id}",
    response_model=TrustedContactResponse,
    summary="Deactivate trusted contact",
    description=(
        "Soft-delete a trusted contact by setting is_active=False.  "
        "The contact record is retained but will no longer receive notifications."
    ),
)
async def delete_deactivate_trusted_contact(
    contact_id: str,
    rider: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TrustedContactResponse:
    """Deactivate a trusted contact (soft delete)."""
    try:
        contact = await deactivate_trusted_contact(
            db=db,
            rider_id=rider.id,
            contact_id=contact_id,
        )
    except PermissionError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Trusted contact not found.",
        )

    return TrustedContactResponse(**contact)


@router.get(
    "/riders/me/trusted-contacts/{contact_id}/notification-log",
    response_model=TrustedContactNotificationLogResponse,
    summary="Get notification log",
    description="Return the last 30 notifications sent to a trusted contact.",
)
async def get_contact_notification_log(
    contact_id: str,
    rider: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TrustedContactNotificationLogResponse:
    """Return recent notification history for a trusted contact."""
    try:
        notifications = await get_notification_log(
            db=db,
            rider_id=rider.id,
            contact_id=contact_id,
        )
    except PermissionError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Trusted contact not found.",
        )

    from app.schemas.rider_safety import TrustedContactNotificationResponse

    return TrustedContactNotificationLogResponse(
        contact_id=contact_id,
        items=[TrustedContactNotificationResponse(**n) for n in notifications],
    )
