"""Driver dispute resolution API endpoints.

POST   /drivers/me/disputes               — file a new dispute
GET    /drivers/me/disputes               — list own disputes (filterable)
GET    /drivers/me/disputes/{dispute_id}  — retrieve one dispute
POST   /drivers/me/disputes/{dispute_id}/appeal   — appeal a decision
DELETE /drivers/me/disputes/{dispute_id}  — withdraw an open dispute
GET    /admin/disputes                    — admin: list all disputes
POST   /admin/disputes/{dispute_id}/resolve — admin: resolve a dispute

Rationale:
    On Uber and Lyft, drivers have no meaningful dispute resolution.  Fares
    get silently adjusted, accounts deactivated without recourse, false rider
    complaints accepted without review.  A cooperative rideshare platform is
    legally and ethically obligated to provide its member-owners with due
    process: a formal mechanism to file a grievance, have it reviewed, appeal
    an unfavorable ruling, and receive a timely resolution.

    This endpoint set surfaces that process via the API.  The is_overdue flag
    on each dispute holds the platform accountable to its own 14-day resolution
    commitment — cooperative member-owners can see exactly which disputes are
    past due.
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_admin, require_driver
from app.db.database import get_db
from app.models.user import User
from app.schemas.driver_dispute import (
    AppealDecisionRequest,
    DisputeListResponse,
    DisputeResponse,
    DisputeStatus,
    DisputeType,
    FileDisputeRequest,
    ResolveDisputeRequest,
)
from app.services.driver_dispute import (
    admin_list_disputes,
    admin_resolve_dispute,
    appeal_decision,
    file_dispute,
    get_dispute,
    list_driver_disputes,
    withdraw_dispute,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["driver-disputes"])

# Admin-allowed resolution statuses (used in validation error message)
_ALLOWED_RESOLUTIONS = {
    DisputeStatus.RESOLVED_IN_DRIVER_FAVOR,
    DisputeStatus.RESOLVED_AGAINST_DRIVER,
    DisputeStatus.DISMISSED,
}


# ---------------------------------------------------------------------------
# Driver endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/drivers/me/disputes",
    response_model=DisputeResponse,
    status_code=status.HTTP_201_CREATED,
    summary="File a dispute",
    description=(
        "File a new dispute as the authenticated driver.  The cooperative "
        "commits to reviewing all disputes within 14 days — disputes older "
        "than that are flagged as `is_overdue` in the response.\n\n"
        "Dispute types:\n"
        "- **FARE_ADJUSTMENT** — a fare was changed without driver consent\n"
        "- **DEACTIVATION_APPEAL** — account was deactivated or suspended\n"
        "- **FALSE_COMPLAINT** — a rider complaint the driver believes is fabricated\n"
        "- **PAYMENT_MISSING** — a payment was not received\n"
        "- **OTHER** — anything not covered by the above categories\n\n"
        "No equivalent endpoint exists on Uber or Lyft."
    ),
)
async def post_file_dispute(
    body: FileDisputeRequest,
    driver: User = Depends(require_driver),
    db: AsyncSession = Depends(get_db),
) -> DisputeResponse:
    """File a new dispute on behalf of the authenticated driver."""
    dispute = await file_dispute(
        db=db,
        driver_id=driver.id,
        dispute_type=body.dispute_type,
        description=body.description,
        ride_id=body.ride_id,
        amount_disputed_usd=body.amount_disputed_usd,
    )
    return DisputeResponse(**dispute)


@router.get(
    "/drivers/me/disputes",
    response_model=DisputeListResponse,
    summary="List own disputes",
    description=(
        "Return a paginated list of disputes filed by the authenticated driver.  "
        "Optionally filter by `status`.  Results are sorted newest-first."
    ),
)
async def get_list_driver_disputes(
    status: Optional[DisputeStatus] = Query(None, description="Filter by dispute status."),
    skip: int = Query(0, ge=0, description="Pagination offset."),
    limit: int = Query(20, ge=1, le=100, description="Maximum results per page."),
    driver: User = Depends(require_driver),
    db: AsyncSession = Depends(get_db),
) -> DisputeListResponse:
    """Return disputes belonging to the authenticated driver."""
    total, items = await list_driver_disputes(
        db=db,
        driver_id=driver.id,
        status_filter=status,
        skip=skip,
        limit=limit,
    )
    return DisputeListResponse(
        total=total,
        items=[DisputeResponse(**d) for d in items],
    )


@router.get(
    "/drivers/me/disputes/{dispute_id}",
    response_model=DisputeResponse,
    summary="Get one dispute",
    description=(
        "Retrieve a single dispute by ID.  The dispute must belong to the "
        "authenticated driver — attempting to access another driver's dispute "
        "returns 404 (ownership is not leaked)."
    ),
)
async def get_one_dispute(
    dispute_id: int,
    driver: User = Depends(require_driver),
    db: AsyncSession = Depends(get_db),
) -> DisputeResponse:
    """Return a single dispute owned by the authenticated driver."""
    dispute = await get_dispute(db=db, driver_id=driver.id, dispute_id=dispute_id)
    if dispute is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dispute not found.",
        )
    return DisputeResponse(**dispute)


@router.post(
    "/drivers/me/disputes/{dispute_id}/appeal",
    response_model=DisputeResponse,
    summary="Appeal a dispute resolution",
    description=(
        "Appeal a dispute that was resolved against the driver.  The dispute "
        "must be in `RESOLVED_AGAINST_DRIVER` status.  After a successful "
        "appeal request the status transitions to `PENDING_APPEAL` and the "
        "case is queued for senior review."
    ),
)
async def post_appeal_dispute(
    dispute_id: int,
    body: AppealDecisionRequest,
    driver: User = Depends(require_driver),
    db: AsyncSession = Depends(get_db),
) -> DisputeResponse:
    """File an appeal on a dispute that was resolved against the driver."""
    try:
        dispute = await appeal_decision(
            db=db,
            driver_id=driver.id,
            dispute_id=dispute_id,
            appeal_reason=body.appeal_reason,
        )
    except PermissionError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dispute not found.",
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )
    return DisputeResponse(**dispute)


@router.delete(
    "/drivers/me/disputes/{dispute_id}",
    response_model=DisputeResponse,
    summary="Withdraw a dispute",
    description=(
        "Withdraw an OPEN or UNDER_REVIEW dispute.  Once withdrawn, the "
        "dispute cannot be reopened.  Disputes in any other status cannot "
        "be withdrawn."
    ),
)
async def delete_withdraw_dispute(
    dispute_id: int,
    driver: User = Depends(require_driver),
    db: AsyncSession = Depends(get_db),
) -> DisputeResponse:
    """Withdraw an open dispute filed by the authenticated driver."""
    try:
        dispute = await withdraw_dispute(
            db=db,
            driver_id=driver.id,
            dispute_id=dispute_id,
        )
    except PermissionError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dispute not found.",
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )
    return DisputeResponse(**dispute)


# ---------------------------------------------------------------------------
# Admin endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/admin/disputes",
    response_model=DisputeListResponse,
    summary="Admin: list all disputes",
    description=(
        "Return a paginated list of all driver disputes across the platform.  "
        "Optionally filter by `status` or `dispute_type`.  Results sorted "
        "newest-first.  Admin access required."
    ),
)
async def admin_get_disputes(
    status: Optional[DisputeStatus] = Query(None, description="Filter by dispute status."),
    dispute_type: Optional[DisputeType] = Query(None, description="Filter by dispute type."),
    skip: int = Query(0, ge=0, description="Pagination offset."),
    limit: int = Query(20, ge=1, le=100, description="Maximum results per page."),
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> DisputeListResponse:
    """List all disputes on the platform (admin view)."""
    total, items = await admin_list_disputes(
        db=db,
        status_filter=status,
        dispute_type_filter=dispute_type,
        skip=skip,
        limit=limit,
    )
    return DisputeListResponse(
        total=total,
        items=[DisputeResponse(**d) for d in items],
    )


@router.post(
    "/admin/disputes/{dispute_id}/resolve",
    response_model=DisputeResponse,
    summary="Admin: resolve a dispute",
    description=(
        "Resolve a dispute.  Allowed resolution statuses:\n\n"
        "- **RESOLVED_IN_DRIVER_FAVOR** — dispute upheld, driver wins\n"
        "- **RESOLVED_AGAINST_DRIVER** — dispute denied (not allowed when resolving a PENDING_APPEAL)\n"
        "- **DISMISSED** — dispute closed without a finding\n\n"
        "Admin access required."
    ),
)
async def admin_post_resolve_dispute(
    dispute_id: int,
    body: ResolveDisputeRequest,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> DisputeResponse:
    """Resolve a dispute (admin operation)."""
    if body.resolution not in _ALLOWED_RESOLUTIONS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"'{body.resolution.value}' is not a valid resolution.  "
                f"Allowed: {[r.value for r in _ALLOWED_RESOLUTIONS]}"
            ),
        )
    try:
        dispute = await admin_resolve_dispute(
            db=db,
            dispute_id=dispute_id,
            resolution=body.resolution,
            admin_notes=body.admin_notes,
            admin_id=admin.id,
        )
    except KeyError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dispute not found.",
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )
    return DisputeResponse(**dispute)
