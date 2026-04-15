"""Driver Emergency Assistance Fund endpoints.

Public endpoint:
  GET  /cooperative/hardship-fund             — public fund balance (transparency)

Driver endpoints (authenticated):
  POST   /drivers/me/hardship-applications    — submit an emergency application
  GET    /drivers/me/hardship-applications    — list my applications
  GET    /drivers/me/hardship-applications/{id} — get a specific application
  DELETE /drivers/me/hardship-applications/{id} — withdraw a pending application

Admin endpoints (ADMIN role):
  GET  /admin/hardship-fund/balance           — detailed fund balance
  POST /admin/hardship-fund/contributions     — add a contribution
  GET  /admin/hardship-applications           — list all applications
  GET  /admin/hardship-applications/{id}      — get application details
  PUT  /admin/hardship-applications/{id}/review   — start review (pending → under_review)
  PUT  /admin/hardship-applications/{id}/approve  — approve with amount
  PUT  /admin/hardship-applications/{id}/deny     — deny with reason
  PUT  /admin/hardship-applications/{id}/disburse — mark disbursed
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_admin, require_driver
from app.db.database import get_db
from app.models.hardship_fund import ApplicationStatus
from app.models.user import User
from app.schemas.hardship_fund import (
    ApproveApplicationRequest,
    ApplicationCreateRequest,
    ApplicationResponse,
    ContributionRequest,
    ContributionResponse,
    DenyApplicationRequest,
    FundSummaryResponse,
    HardshipFundBalanceResponse,
    PublicFundBalanceResponse,
    ReviewStartRequest,
)
from app.services import hardship_fund as svc
from app.services.hardship_fund import HardshipFundError

router = APIRouter(tags=["hardship_fund"])


# ---------------------------------------------------------------------------
# Internal helper
# ---------------------------------------------------------------------------


def _http(exc: HardshipFundError) -> HTTPException:
    """Convert a HardshipFundError to an HTTPException."""
    return HTTPException(status_code=exc.status_code, detail=exc.message)


# ---------------------------------------------------------------------------
# Public
# ---------------------------------------------------------------------------


@router.get(
    "/cooperative/hardship-fund",
    response_model=PublicFundBalanceResponse,
    summary="Public fund balance",
)
async def get_public_fund_balance(db: AsyncSession = Depends(get_db)):
    """Return the current fund balance for public transparency.

    Only exposes the total available balance — contribution and disbursement
    details are reserved for admin views.
    """
    fund = await svc.get_or_create_fund(db)
    return PublicFundBalanceResponse(total_balance_usd=fund.total_balance_usd)


# ---------------------------------------------------------------------------
# Driver endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/drivers/me/hardship-applications",
    response_model=ApplicationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Submit an emergency assistance application",
)
async def create_application(
    req: ApplicationCreateRequest,
    user: User = Depends(require_driver),
    db: AsyncSession = Depends(get_db),
):
    """Submit an emergency assistance application.

    A driver may have only one active (pending or under_review) application
    at a time.  Returns 409 if an active application already exists.
    """
    try:
        application = await svc.create_application(
            db=db,
            driver_id=user.id,
            application_type=req.application_type,
            description=req.description,
            amount_requested_usd=req.amount_requested_usd,
        )
    except HardshipFundError as e:
        raise _http(e)
    return application


@router.get(
    "/drivers/me/hardship-applications",
    response_model=list[ApplicationResponse],
    summary="List my emergency applications",
)
async def list_my_applications(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return all applications submitted by the authenticated driver."""
    return await svc.get_driver_applications(db=db, driver_id=user.id, skip=skip, limit=limit)


@router.get(
    "/drivers/me/hardship-applications/{application_id}",
    response_model=ApplicationResponse,
    summary="Get a specific application",
)
async def get_my_application(
    application_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return a single application.  Returns 403 if it belongs to another driver."""
    try:
        # Re-use _get_application via the service; ownership check here
        from sqlalchemy import select
        from app.models.hardship_fund import HardshipApplication

        result = await db.execute(
            select(HardshipApplication).where(HardshipApplication.id == application_id)
        )
        application = result.scalar_one_or_none()
        if application is None:
            raise HTTPException(status_code=404, detail="Application not found.")
        if application.driver_id != user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to view this application.",
            )
        return application
    except HTTPException:
        raise
    except HardshipFundError as e:
        raise _http(e)


@router.delete(
    "/drivers/me/hardship-applications/{application_id}",
    response_model=ApplicationResponse,
    summary="Withdraw a pending application",
)
async def withdraw_application(
    application_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Withdraw a pending application.

    Only the owning driver may withdraw, and only while status is 'pending'.
    Returns 403 for wrong owner, 409 if not pending.
    """
    try:
        return await svc.withdraw_application(
            db=db, application_id=application_id, driver_id=user.id
        )
    except HardshipFundError as e:
        raise _http(e)


# ---------------------------------------------------------------------------
# Admin — fund balance & contributions
# ---------------------------------------------------------------------------


@router.get(
    "/admin/hardship-fund/balance",
    response_model=HardshipFundBalanceResponse,
    summary="Detailed fund balance (admin)",
)
async def admin_get_fund_balance(
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return the detailed fund balance including contribution and disbursement totals."""
    fund = await svc.get_or_create_fund(db)
    return fund


@router.post(
    "/admin/hardship-fund/contributions",
    response_model=ContributionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add a contribution to the fund (admin)",
)
async def add_contribution(
    req: ContributionRequest,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Record a deposit from any source (driver, platform, donation, other)."""
    try:
        return await svc.add_contribution(
            db=db,
            source=req.source,
            amount_usd=req.amount_usd,
            driver_id=req.driver_id,
            note=req.note,
        )
    except HardshipFundError as e:
        raise _http(e)


# ---------------------------------------------------------------------------
# Admin — application management
# ---------------------------------------------------------------------------


@router.get(
    "/admin/hardship-applications",
    response_model=list[ApplicationResponse],
    summary="List all applications (admin)",
)
async def admin_list_applications(
    status: ApplicationStatus | None = Query(default=None, alias="status"),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return all applications, optionally filtered by status."""
    return await svc.admin_list_applications(
        db=db, status_filter=status, skip=skip, limit=limit
    )


@router.get(
    "/admin/hardship-applications/{application_id}",
    response_model=ApplicationResponse,
    summary="Get application details (admin)",
)
async def admin_get_application(
    application_id: int,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return full details for any application."""
    try:
        from sqlalchemy import select
        from app.models.hardship_fund import HardshipApplication

        result = await db.execute(
            select(HardshipApplication).where(HardshipApplication.id == application_id)
        )
        application = result.scalar_one_or_none()
        if application is None:
            raise HTTPException(status_code=404, detail="Application not found.")
        return application
    except HTTPException:
        raise


@router.put(
    "/admin/hardship-applications/{application_id}/review",
    response_model=ApplicationResponse,
    summary="Start reviewing an application (admin)",
)
async def start_review(
    application_id: int,
    req: ReviewStartRequest = None,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Transition a pending application to under_review."""
    try:
        return await svc.start_review(
            db=db, application_id=application_id, admin_id=user.id
        )
    except HardshipFundError as e:
        raise _http(e)


@router.put(
    "/admin/hardship-applications/{application_id}/approve",
    response_model=ApplicationResponse,
    summary="Approve an application with disbursement amount (admin)",
)
async def approve_application(
    application_id: int,
    req: ApproveApplicationRequest,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Approve an under_review application.

    The approved_amount_usd may differ from the requested amount.
    Returns 400 if the fund has insufficient balance.
    """
    try:
        return await svc.approve_application(
            db=db,
            application_id=application_id,
            admin_id=user.id,
            approved_amount_usd=req.approved_amount_usd,
            admin_note=req.admin_note,
        )
    except HardshipFundError as e:
        raise _http(e)


@router.put(
    "/admin/hardship-applications/{application_id}/deny",
    response_model=ApplicationResponse,
    summary="Deny an application (admin)",
)
async def deny_application(
    application_id: int,
    req: DenyApplicationRequest,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Deny a pending or under_review application with a mandatory reason."""
    try:
        return await svc.deny_application(
            db=db,
            application_id=application_id,
            admin_id=user.id,
            admin_note=req.admin_note,
        )
    except HardshipFundError as e:
        raise _http(e)


@router.put(
    "/admin/hardship-applications/{application_id}/disburse",
    response_model=ApplicationResponse,
    summary="Mark an approved application as disbursed (admin)",
)
async def disburse_application(
    application_id: int,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Mark an approved application as disbursed and deduct from the fund balance."""
    try:
        return await svc.disburse_application(
            db=db, application_id=application_id, admin_id=user.id
        )
    except HardshipFundError as e:
        raise _http(e)


@router.get(
    "/admin/hardship-fund/summary",
    response_model=FundSummaryResponse,
    summary="Fund summary with aggregate stats (admin)",
)
async def admin_fund_summary(
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return aggregate fund stats including application counts and monetary totals."""
    summary = await svc.get_fund_summary(db)
    return FundSummaryResponse(**summary)
