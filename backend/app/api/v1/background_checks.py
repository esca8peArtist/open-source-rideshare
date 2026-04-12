"""Background check API endpoints.

Endpoints:
  POST /driver/background-check/order  — driver orders their check
  GET  /driver/background-check        — driver views their check status
  POST /background-checks/webhook      — Checkr webhook (signature-verified)
  GET  /admin/background-checks        — admin list with optional status filter
  GET  /admin/background-checks/{driver_profile_id} — admin view single driver
  POST /admin/background-checks/{check_id}/override — admin override
"""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_admin, require_driver
from app.config import settings
from app.db.database import get_db
from app.models.background_check import BackgroundCheck, BackgroundCheckStatus
from app.models.driver import DriverProfile
from app.models.user import User
from app.schemas.background_check import (
    AdminBackgroundCheckListResponse,
    AdminBackgroundCheckResponse,
    AdminOverrideRequest,
    BackgroundCheckResponse,
    OrderBackgroundCheckRequest,
)
from app.services.background_checks import (
    VALID_PACKAGES,
    admin_override_check,
    create_candidate,
    handle_webhook,
    order_check,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["background-checks"])


# ---------------------------------------------------------------------------
# Driver endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/driver/background-check/order",
    response_model=BackgroundCheckResponse,
    status_code=status.HTTP_201_CREATED,
)
async def order_background_check(
    req: OrderBackgroundCheckRequest,
    user: User = Depends(require_driver),
    db: AsyncSession = Depends(get_db),
):
    """Driver initiates a Checkr background check.

    Requires an existing driver profile.  Will reject if a pending or
    completed non-cancelled check already exists for this driver.
    """
    if req.package not in VALID_PACKAGES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid package. Choose from: {', '.join(sorted(VALID_PACKAGES))}",
        )

    # Fetch driver profile
    result = await db.execute(
        select(DriverProfile).where(DriverProfile.user_id == user.id)
    )
    profile = result.scalar_one_or_none()
    if not profile:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Driver profile not found. Create a profile before ordering a background check.",
        )

    # Reject if an active check already exists
    result = await db.execute(
        select(BackgroundCheck).where(
            BackgroundCheck.driver_profile_id == profile.id,
            BackgroundCheck.status.notin_(
                [BackgroundCheckStatus.CANCELLED]
            ),
        )
    )
    existing = result.scalar_one_or_none()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A background check already exists with status '{existing.status.value}'.",
        )

    # Default package from config if driver doesn't specify
    package = req.package or getattr(settings, "checkr_default_package", "driver_pro")

    try:
        # Create candidate on Checkr
        candidate_data = await create_candidate(
            first_name=user.name.split()[0] if user.name else "",
            last_name=" ".join(user.name.split()[1:]) if user.name and " " in user.name else user.name or "",
            email=user.email or "",
            phone=user.phone,
        )
        candidate_id = candidate_data["id"]

        # Order the check
        check_data = await order_check(candidate_id=candidate_id, package=package)
        check_id = check_data["id"]

    except Exception:
        logger.exception("Failed to initiate Checkr background check for user %d", user.id)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to initiate background check. Please try again later.",
        )

    from datetime import datetime, timezone

    bg_check = BackgroundCheck(
        driver_profile_id=profile.id,
        checkr_candidate_id=candidate_id,
        checkr_check_id=check_id,
        package=package,
        status=BackgroundCheckStatus.PENDING,
        ordered_at=datetime.now(timezone.utc),
    )
    db.add(bg_check)
    await db.flush()

    return bg_check


@router.get("/driver/background-check", response_model=BackgroundCheckResponse)
async def get_my_background_check(
    user: User = Depends(require_driver),
    db: AsyncSession = Depends(get_db),
):
    """Driver views their most recent background check status."""
    result = await db.execute(
        select(DriverProfile).where(DriverProfile.user_id == user.id)
    )
    profile = result.scalar_one_or_none()
    if not profile:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Driver profile not found.",
        )

    result = await db.execute(
        select(BackgroundCheck)
        .where(BackgroundCheck.driver_profile_id == profile.id)
        .order_by(BackgroundCheck.created_at.desc())
        .limit(1)
    )
    check = result.scalar_one_or_none()
    if not check:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No background check found.",
        )

    return check


# ---------------------------------------------------------------------------
# Webhook endpoint (no auth — signature-verified)
# ---------------------------------------------------------------------------


@router.post("/background-checks/webhook")
async def checkr_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Checkr webhook receiver.

    Validates HMAC-SHA256 signature from ``X-Checkr-Signature`` header then
    processes the event to update check status and driver profile.
    """
    signature = request.headers.get("X-Checkr-Signature", "")
    body = await request.body()

    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid JSON payload",
        )

    result = await handle_webhook(
        payload=payload,
        signature=signature,
        payload_body=body,
        db=db,
    )

    if result.get("status") == "invalid_signature":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid webhook signature",
        )

    return result


# ---------------------------------------------------------------------------
# Admin endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/admin/background-checks",
    response_model=AdminBackgroundCheckListResponse,
)
async def admin_list_background_checks(
    status_filter: str | None = Query(None, alias="status"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Admin: list all background checks with optional status filter."""
    from sqlalchemy import func

    query = select(BackgroundCheck)

    if status_filter:
        try:
            status_enum = BackgroundCheckStatus(status_filter)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Invalid status filter. Valid: {[s.value for s in BackgroundCheckStatus]}",
            )
        query = query.where(BackgroundCheck.status == status_enum)

    count_result = await db.execute(
        select(func.count()).select_from(query.subquery())
    )
    total = count_result.scalar() or 0

    query = query.order_by(BackgroundCheck.created_at.desc()).offset(offset).limit(limit)
    result = await db.execute(query)
    checks = result.scalars().all()

    return AdminBackgroundCheckListResponse(
        checks=[AdminBackgroundCheckResponse.model_validate(c) for c in checks],
        total=total,
    )


@router.get(
    "/admin/background-checks/{driver_profile_id}",
    response_model=AdminBackgroundCheckResponse,
)
async def admin_get_driver_background_check(
    driver_profile_id: int,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Admin: view the most recent background check for a driver profile."""
    result = await db.execute(
        select(BackgroundCheck)
        .where(BackgroundCheck.driver_profile_id == driver_profile_id)
        .order_by(BackgroundCheck.created_at.desc())
        .limit(1)
    )
    check = result.scalar_one_or_none()
    if not check:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No background check found for driver profile {driver_profile_id}.",
        )

    return check


@router.post(
    "/admin/background-checks/{check_id}/override",
    response_model=AdminBackgroundCheckResponse,
)
async def admin_override_background_check(
    check_id: int,
    req: AdminOverrideRequest,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Admin: override a background check result (clear / consider / cancelled)."""
    try:
        new_status = BackgroundCheckStatus(req.status)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid status '{req.status}'.",
        )

    try:
        check = await admin_override_check(
            db=db,
            check_id=check_id,
            new_status=new_status,
            reason=req.reason,
            admin_user_id=user.id,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        )

    return check
