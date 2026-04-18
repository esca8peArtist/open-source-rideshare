"""Driver emergency safety endpoints.

POST   /drivers/me/panic                              — trigger panic alert
GET    /drivers/me/panic/{alert_id}                   — get alert status
DELETE /drivers/me/panic/{alert_id}                   — cancel alert
GET    /admin/driver-panic-alerts                     — admin: list all ACTIVE driver alerts
POST   /admin/driver-panic-alerts/{alert_id}/resolve  — admin: resolve alert

All business rules are enforced in the service layer.  This module handles
HTTP mapping only: 404 on ownership mismatches (do not leak existence),
400 on invalid state transitions.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_admin
from app.db.database import get_db
from app.models.user import User
from app.schemas.driver_safety import (
    AdminResolveDriverPanicRequest,
    DriverPanicAlertListResponse,
    DriverPanicAlertResponse,
    TriggerDriverPanicRequest,
)
from app.services.driver_safety import (
    admin_list_active_driver_panic_alerts,
    admin_resolve_driver_panic_alert,
    cancel_driver_panic_alert,
    get_driver_panic_alert,
    trigger_driver_panic,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["driver-safety"])


# ---------------------------------------------------------------------------
# Panic alert — driver endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/drivers/me/panic",
    response_model=DriverPanicAlertResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Trigger driver panic alert",
    description=(
        "Trigger a panic alert during an active ride.  The alert is immediately "
        "visible to platform admins, sorted oldest-first (most urgent first).  "
        "Only one ACTIVE alert per ride is permitted.\n\n"
        "The driver's current location may optionally be included to assist "
        "responders."
    ),
)
async def post_trigger_driver_panic(
    body: TriggerDriverPanicRequest,
    driver: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DriverPanicAlertResponse:
    """Trigger a panic alert for the driver's current active ride."""
    from sqlalchemy import select
    from app.models.ride import Ride, RideStatus

    result = await db.execute(
        select(Ride).where(
            Ride.driver_id == driver.id,
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
        alert = await trigger_driver_panic(
            db=db,
            driver_id=driver.id,
            ride_id=ride.id,
            rider_id=ride.rider_id,
            location_lat=body.location_lat,
            location_lng=body.location_lng,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    return DriverPanicAlertResponse(**alert)


@router.get(
    "/drivers/me/panic/{alert_id}",
    response_model=DriverPanicAlertResponse,
    summary="Get driver panic alert status",
    description="Retrieve the current status of a panic alert triggered by the authenticated driver.",
)
async def get_driver_panic_alert_endpoint(
    alert_id: str,
    driver: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DriverPanicAlertResponse:
    """Get a panic alert owned by the authenticated driver."""
    alert = await get_driver_panic_alert(db=db, driver_id=driver.id, alert_id=alert_id)
    if alert is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Driver panic alert not found.",
        )
    return DriverPanicAlertResponse(**alert)


@router.delete(
    "/drivers/me/panic/{alert_id}",
    response_model=DriverPanicAlertResponse,
    summary="Cancel driver panic alert",
    description=(
        "Cancel an ACTIVE panic alert.  If cancelled within 30 seconds of "
        "triggering, the status is set to FALSE_ALARM.  After 30 seconds "
        "it is set to RESOLVED."
    ),
)
async def delete_cancel_driver_panic_alert(
    alert_id: str,
    driver: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DriverPanicAlertResponse:
    """Cancel a panic alert triggered by the authenticated driver."""
    try:
        alert = await cancel_driver_panic_alert(db=db, driver_id=driver.id, alert_id=alert_id)
    except PermissionError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Driver panic alert not found.",
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    return DriverPanicAlertResponse(**alert)


# ---------------------------------------------------------------------------
# Panic alert — admin endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/admin/driver-panic-alerts",
    response_model=DriverPanicAlertListResponse,
    summary="Admin: list all active driver panic alerts",
    description=(
        "List all ACTIVE driver panic alerts across the platform, sorted "
        "oldest-first (most urgent first).  Admin access required."
    ),
)
async def admin_get_active_driver_panic_alerts(
    skip: int = Query(0, ge=0, description="Pagination offset."),
    limit: int = Query(50, ge=1, le=200, description="Maximum results per page."),
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> DriverPanicAlertListResponse:
    """Return all ACTIVE driver panic alerts (admin view)."""
    total, items = await admin_list_active_driver_panic_alerts(db=db, skip=skip, limit=limit)
    return DriverPanicAlertListResponse(
        total=total,
        items=[DriverPanicAlertResponse(**a) for a in items],
    )


@router.post(
    "/admin/driver-panic-alerts/{alert_id}/resolve",
    response_model=DriverPanicAlertResponse,
    summary="Admin: resolve a driver panic alert",
    description=(
        "Mark an ACTIVE driver panic alert as RESOLVED with optional resolution notes.  "
        "Admin access required."
    ),
)
async def admin_post_resolve_driver_panic_alert(
    alert_id: str,
    body: AdminResolveDriverPanicRequest,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> DriverPanicAlertResponse:
    """Resolve a driver panic alert (admin operation)."""
    try:
        alert = await admin_resolve_driver_panic_alert(
            db=db,
            alert_id=alert_id,
            admin_id=admin.id,
            resolution_notes=body.resolution_notes,
        )
    except KeyError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Driver panic alert not found.",
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    return DriverPanicAlertResponse(**alert)
