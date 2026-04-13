"""Driver onboarding status and activation workflow endpoints.

Driver endpoints (own profile only):
  GET  /drivers/me/onboarding        — view own checklist + status

Admin endpoints:
  GET  /admin/drivers/{driver_profile_id}/onboarding            — view any driver's checklist
  POST /admin/drivers/{driver_profile_id}/onboarding/activate   — activate driver (all checks must pass)
  POST /admin/drivers/{driver_profile_id}/onboarding/suspend    — suspend driver with reason
  GET  /admin/drivers/onboarding/pending                        — list drivers pending review
  GET  /admin/drivers/onboarding/incomplete                     — list drivers with incomplete requirements

Note: activate/suspend are scoped under /onboarding/ to avoid path conflicts with the
existing /admin/drivers/{driver_id}/approve and /admin/drivers/{driver_id}/suspend
routes in admin.py which use a different schema and purpose.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_admin, require_driver
from app.db.database import get_db
from app.models.driver import DriverProfile
from app.models.driver_onboarding import DriverOnboarding, OnboardingStatus
from app.models.user import User
from app.schemas.driver_onboarding import (
    ActivateDriverRequest,
    DriverOnboardingResponse,
    IncompleteDriverItem,
    OnboardingChecklist,
    PendingDriverItem,
    SuspendDriverRequest,
)
from app.services.driver_onboarding import (
    OnboardingError,
    activate_driver,
    get_onboarding_checklist,
    get_or_create_onboarding,
    list_incomplete,
    list_pending_review,
    suspend_driver,
)

router = APIRouter(tags=["driver-onboarding"])


# ---------------------------------------------------------------------------
# Driver — own checklist
# ---------------------------------------------------------------------------


@router.get(
    "/drivers/me/onboarding",
    response_model=OnboardingChecklist,
    summary="Get my onboarding checklist and current status",
)
async def get_my_onboarding(
    user: User = Depends(require_driver),
    db: AsyncSession = Depends(get_db),
):
    """Return the authenticated driver's onboarding checklist."""
    result = await db.execute(
        select(DriverProfile).where(DriverProfile.user_id == user.id)
    )
    profile = result.scalar_one_or_none()
    if not profile:
        raise HTTPException(status_code=404, detail="Driver profile not found")

    try:
        return await get_onboarding_checklist(profile.id, db)
    except OnboardingError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


# ---------------------------------------------------------------------------
# Admin — NOTE: static-prefix routes must come before parameterised ones
# ---------------------------------------------------------------------------


@router.get(
    "/admin/drivers/onboarding/pending",
    response_model=list[PendingDriverItem],
    summary="List drivers with status pending_review",
)
async def admin_list_pending(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return drivers who have submitted all documents but are not yet activated."""
    rows = await list_pending_review(db, page=page, page_size=page_size)
    return await _build_pending_items(rows, db)


@router.get(
    "/admin/drivers/onboarding/incomplete",
    response_model=list[IncompleteDriverItem],
    summary="List drivers with status incomplete",
)
async def admin_list_incomplete(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return drivers who are missing one or more onboarding requirements."""
    rows = await list_incomplete(db, page=page, page_size=page_size)
    return await _build_incomplete_items(rows, db)


@router.get(
    "/admin/drivers/{driver_profile_id}/onboarding",
    response_model=OnboardingChecklist,
    summary="Get a specific driver's onboarding checklist",
)
async def admin_get_driver_onboarding(
    driver_profile_id: int,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Admin view of any driver's onboarding checklist."""
    try:
        return await get_onboarding_checklist(driver_profile_id, db)
    except OnboardingError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post(
    "/admin/drivers/{driver_profile_id}/onboarding/activate",
    response_model=DriverOnboardingResponse,
    summary="Activate a driver once all requirements are met",
)
async def admin_activate_driver(
    driver_profile_id: int,
    _req: ActivateDriverRequest,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Activate the driver. Returns 409 if any requirement is not satisfied."""
    try:
        onboarding = await activate_driver(driver_profile_id, admin.id, db)
        await db.commit()
        await db.refresh(onboarding)
        return onboarding
    except OnboardingError as exc:
        msg = str(exc)
        if "not found" in msg.lower():
            raise HTTPException(status_code=404, detail=msg)
        raise HTTPException(status_code=409, detail=msg)


@router.post(
    "/admin/drivers/{driver_profile_id}/onboarding/suspend",
    response_model=DriverOnboardingResponse,
    summary="Suspend a driver with a mandatory reason",
)
async def admin_suspend_driver(
    driver_profile_id: int,
    req: SuspendDriverRequest,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Suspend the driver and record the reason."""
    try:
        onboarding = await suspend_driver(driver_profile_id, req.reason, admin.id, db)
        await db.commit()
        await db.refresh(onboarding)
        return onboarding
    except OnboardingError as exc:
        msg = str(exc)
        if "not found" in msg.lower():
            raise HTTPException(status_code=404, detail=msg)
        raise HTTPException(status_code=422, detail=msg)


# ---------------------------------------------------------------------------
# Private helpers for building list response items
# ---------------------------------------------------------------------------


async def _build_pending_items(
    rows: list[DriverOnboarding], db: AsyncSession
) -> list[PendingDriverItem]:
    items: list[PendingDriverItem] = []
    for row in rows:
        profile_result = await db.execute(
            select(DriverProfile).where(DriverProfile.id == row.driver_profile_id)
        )
        profile = profile_result.scalar_one_or_none()
        if not profile:
            continue
        user_result = await db.execute(
            select(User).where(User.id == profile.user_id)
        )
        user = user_result.scalar_one_or_none()
        if not user:
            continue
        items.append(
            PendingDriverItem(
                driver_profile_id=row.driver_profile_id,
                driver_user_id=profile.user_id,
                driver_name=user.name,
                onboarding_id=row.id,
                status=row.status,
                updated_at=row.updated_at,
            )
        )
    return items


async def _build_incomplete_items(
    rows: list[DriverOnboarding], db: AsyncSession
) -> list[IncompleteDriverItem]:
    items: list[IncompleteDriverItem] = []
    for row in rows:
        profile_result = await db.execute(
            select(DriverProfile).where(DriverProfile.id == row.driver_profile_id)
        )
        profile = profile_result.scalar_one_or_none()
        if not profile:
            continue
        user_result = await db.execute(
            select(User).where(User.id == profile.user_id)
        )
        user = user_result.scalar_one_or_none()
        if not user:
            continue

        # Build checklist to identify missing steps
        try:
            checklist = await get_onboarding_checklist(row.driver_profile_id, db)
        except OnboardingError:
            continue

        missing: list[str] = []
        for field in [
            "background_check",
            "driver_license",
            "vehicle_registration",
            "vehicle_inspection",
            "insurance_document",
            "profile_complete",
        ]:
            item = getattr(checklist, field)
            if item.required and not item.met:
                missing.append(field)

        items.append(
            IncompleteDriverItem(
                driver_profile_id=row.driver_profile_id,
                driver_user_id=profile.user_id,
                driver_name=user.name,
                onboarding_id=row.id,
                status=row.status,
                missing_steps=missing,
                updated_at=row.updated_at,
            )
        )
    return items
