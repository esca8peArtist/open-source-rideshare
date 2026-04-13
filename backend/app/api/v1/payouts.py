from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_admin, require_driver
from app.db.database import get_db
from app.models.user import User
from app.schemas.payout import (
    AdminBulkPayoutRequest,
    AdminCreatePayoutRequest,
    AdminPayoutOverview,
    AdminProcessPayoutRequest,
    BankAccountResponse,
    ConnectAccountSetupRequest,
    ConnectAccountSetupResponse,
    PayoutDetailResponse,
    PayoutListResponse,
    PayoutSummary,
    UpdatePayoutFrequencyRequest,
)
from app.services.payouts import (
    PayoutError,
    bulk_create_payouts,
    create_connect_account,
    create_payout,
    deactivate_bank_account,
    get_admin_payout_overview,
    get_bank_account,
    get_driver_payouts,
    get_payout_by_id,
    get_payout_totals,
    process_payout,
    retry_failed_payout,
    update_payout_frequency,
)

router = APIRouter(prefix="/payouts", tags=["payouts"])


# ---- Driver: Bank Account ----


@router.post("/bank-account/setup", response_model=ConnectAccountSetupResponse, status_code=201)
async def setup_bank_account(
    req: ConnectAccountSetupRequest,
    user: User = Depends(require_driver),
    db: AsyncSession = Depends(get_db),
):
    """Start Stripe Connect onboarding for the driver."""
    try:
        result = await create_connect_account(
            driver_id=user.id,
            return_url=req.return_url,
            refresh_url=req.refresh_url,
            db=db,
        )
        return ConnectAccountSetupResponse(**result)
    except PayoutError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.get("/bank-account", response_model=BankAccountResponse)
async def get_my_bank_account(
    user: User = Depends(require_driver),
    db: AsyncSession = Depends(get_db),
):
    """Get the driver's linked bank account info."""
    account = await get_bank_account(user.id, db)
    if not account:
        raise HTTPException(status_code=404, detail="No bank account linked")
    return account


@router.put("/bank-account/frequency", response_model=BankAccountResponse)
async def update_my_payout_frequency(
    req: UpdatePayoutFrequencyRequest,
    user: User = Depends(require_driver),
    db: AsyncSession = Depends(get_db),
):
    """Update the driver's payout frequency preference."""
    try:
        account = await update_payout_frequency(user.id, req.frequency, db)
        return account
    except PayoutError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/bank-account", status_code=204)
async def deactivate_my_bank_account(
    user: User = Depends(require_driver),
    db: AsyncSession = Depends(get_db),
):
    """Deactivate the driver's bank account (does not delete Stripe account)."""
    try:
        await deactivate_bank_account(user.id, db)
    except PayoutError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ---- Driver: Payouts ----


@router.get("/my-payouts", response_model=PayoutListResponse)
async def get_my_payouts(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    user: User = Depends(require_driver),
    db: AsyncSession = Depends(get_db),
):
    """List the driver's payout history."""
    payouts = await get_driver_payouts(user.id, db, limit=limit, offset=offset)
    totals = await get_payout_totals(user.id, db)
    return PayoutListResponse(
        payouts=[PayoutSummary.model_validate(p) for p in payouts],
        total_paid=totals["total_paid"],
        total_pending=totals["total_pending"],
    )


@router.get("/my-payouts/{payout_id}", response_model=PayoutDetailResponse)
async def get_my_payout_detail(
    payout_id: int,
    user: User = Depends(require_driver),
    db: AsyncSession = Depends(get_db),
):
    """Get details of a specific payout."""
    payout = await get_payout_by_id(payout_id, db)
    if not payout or payout.driver_id != user.id:
        raise HTTPException(status_code=404, detail="Payout not found")
    return payout


# ---- Admin: Payouts ----


@router.get("/admin/overview", response_model=AdminPayoutOverview)
async def admin_payout_overview(
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Admin dashboard for payout state."""
    overview = await get_admin_payout_overview(db)
    return AdminPayoutOverview(**overview)


@router.post("/admin/create", response_model=PayoutDetailResponse, status_code=201)
async def admin_create_payout(
    req: AdminCreatePayoutRequest,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Admin creates a payout for a specific driver."""
    try:
        payout = await create_payout(
            driver_id=req.driver_id,
            period_start=req.period_start,
            period_end=req.period_end,
            db=db,
            bonus_amount=req.bonus_amount,
            deductions=req.deductions,
            notes=req.notes,
        )
        return payout
    except PayoutError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/admin/process", response_model=PayoutDetailResponse)
async def admin_process_payout(
    req: AdminProcessPayoutRequest,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Admin triggers Stripe transfer for a pending payout."""
    try:
        payout = await process_payout(req.payout_id, db)
        return payout
    except PayoutError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/admin/retry/{payout_id}", response_model=PayoutDetailResponse)
async def admin_retry_payout(
    payout_id: int,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Admin retries a failed payout."""
    try:
        payout = await retry_failed_payout(payout_id, db)
        return payout
    except PayoutError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/admin/bulk", response_model=list[PayoutDetailResponse], status_code=201)
async def admin_bulk_create_payouts(
    req: AdminBulkPayoutRequest,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Admin triggers settlements for all eligible drivers."""
    payouts = await bulk_create_payouts(
        period_start=req.period_start,
        period_end=req.period_end,
        db=db,
        bonus_amount=req.bonus_amount,
        deductions=req.deductions,
        notes=req.notes,
    )
    return payouts


@router.get("/admin/driver/{driver_id}", response_model=PayoutListResponse)
async def admin_get_driver_payouts(
    driver_id: int,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Admin views a specific driver's payout history."""
    payouts = await get_driver_payouts(driver_id, db, limit=limit, offset=offset)
    totals = await get_payout_totals(driver_id, db)
    return PayoutListResponse(
        payouts=[PayoutSummary.model_validate(p) for p in payouts],
        total_paid=totals["total_paid"],
        total_pending=totals["total_pending"],
    )
