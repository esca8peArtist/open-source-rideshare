from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_admin
from app.db.database import get_db
from app.models.promo import PromoCode, PromoRedemption, PromoType
from app.models.user import User
from app.schemas.promo import (
    ApplyPromoRequest,
    ApplyPromoResponse,
    CreatePromoCodeRequest,
    PromoCodeResponse,
    PromoRedemptionResponse,
    PromoStats,
    PromoTopEntry,
    UpdatePromoCodeRequest,
)
from app.services.promos import validate_promo

router = APIRouter(prefix="/promos", tags=["promos"])


# --- Admin endpoints ---

@router.post(
    "/admin",
    response_model=PromoCodeResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_admin)],
)
async def create_promo_code(
    req: CreatePromoCodeRequest,
    db: AsyncSession = Depends(get_db),
):
    """Create a new promo code (admin only)."""
    # Check for duplicate code
    existing = await db.execute(
        select(PromoCode).where(PromoCode.code == req.code)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="A promo code with this code already exists")

    promo = PromoCode(
        code=req.code,
        description=req.description,
        promo_type=PromoType(req.promo_type),
        value=req.value,
        max_discount=req.max_discount,
        minimum_fare=req.minimum_fare,
        max_uses=req.max_uses,
        max_uses_per_user=req.max_uses_per_user,
        first_ride_only=req.first_ride_only,
        expires_at=req.expires_at,
        is_active=True,
        is_referral=False,
    )
    db.add(promo)
    await db.commit()
    await db.refresh(promo)

    return _promo_to_response(promo)


@router.get(
    "/admin",
    response_model=list[PromoCodeResponse],
    dependencies=[Depends(require_admin)],
)
async def list_promo_codes(
    active_only: bool = Query(False),
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    """List all promo codes (admin only)."""
    query = select(PromoCode)
    if active_only:
        query = query.where(PromoCode.is_active == True)  # noqa: E712
    query = query.order_by(PromoCode.created_at.desc()).offset(offset).limit(limit)

    result = await db.execute(query)
    promos = result.scalars().all()
    return [_promo_to_response(p) for p in promos]


@router.get(
    "/admin/{promo_id}",
    response_model=PromoCodeResponse,
    dependencies=[Depends(require_admin)],
)
async def get_promo_code(
    promo_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Get a single promo code by ID (admin only)."""
    result = await db.execute(select(PromoCode).where(PromoCode.id == promo_id))
    promo = result.scalar_one_or_none()
    if not promo:
        raise HTTPException(status_code=404, detail="Promo code not found")
    return _promo_to_response(promo)


@router.patch(
    "/admin/{promo_id}",
    response_model=PromoCodeResponse,
    dependencies=[Depends(require_admin)],
)
async def update_promo_code(
    promo_id: int,
    req: UpdatePromoCodeRequest,
    db: AsyncSession = Depends(get_db),
):
    """Update a promo code (admin only)."""
    result = await db.execute(select(PromoCode).where(PromoCode.id == promo_id))
    promo = result.scalar_one_or_none()
    if not promo:
        raise HTTPException(status_code=404, detail="Promo code not found")

    if req.description is not None:
        promo.description = req.description
    if req.is_active is not None:
        promo.is_active = req.is_active
    if req.max_uses is not None:
        promo.max_uses = req.max_uses
    if req.max_uses_per_user is not None:
        promo.max_uses_per_user = req.max_uses_per_user
    if req.expires_at is not None:
        promo.expires_at = req.expires_at

    await db.commit()
    await db.refresh(promo)
    return _promo_to_response(promo)


@router.delete(
    "/admin/{promo_id}",
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(require_admin)],
)
async def deactivate_promo_code(
    promo_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Deactivate a promo code (admin only). Does not delete — preserves redemption history."""
    result = await db.execute(select(PromoCode).where(PromoCode.id == promo_id))
    promo = result.scalar_one_or_none()
    if not promo:
        raise HTTPException(status_code=404, detail="Promo code not found")

    promo.is_active = False
    await db.commit()
    return {"status": "deactivated", "code": promo.code}


@router.get(
    "/admin/{promo_id}/redemptions",
    response_model=list[PromoRedemptionResponse],
    dependencies=[Depends(require_admin)],
)
async def list_redemptions(
    promo_id: int,
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    """List redemptions for a promo code (admin only)."""
    result = await db.execute(
        select(PromoRedemption)
        .where(PromoRedemption.promo_code_id == promo_id)
        .order_by(PromoRedemption.redeemed_at.desc())
        .offset(offset)
        .limit(limit)
    )
    redemptions = result.scalars().all()

    # Fetch codes for response
    promo_result = await db.execute(select(PromoCode).where(PromoCode.id == promo_id))
    promo = promo_result.scalar_one_or_none()
    code_str = promo.code if promo else ""

    return [
        PromoRedemptionResponse(
            id=r.id,
            promo_code_id=r.promo_code_id,
            code=code_str,
            user_id=r.user_id,
            ride_id=r.ride_id,
            discount_amount=r.discount_amount,
            redeemed_at=r.redeemed_at,
        )
        for r in redemptions
    ]


# --- Rider-facing endpoints ---

@router.post("/validate", response_model=ApplyPromoResponse)
async def validate_promo_code(
    req: ApplyPromoRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Validate a promo code for the current user. Does not redeem it.

    Use this before requesting a ride to show the rider the discount they'll get.
    Pass a fare of 0 to just check validity without calculating a discount.
    """
    # Use a representative fare for validation (the actual discount is computed at ride time)
    validation = await validate_promo(req.code, user.id, fare=10.0, db=db)

    # Fetch promo details for the response
    promo_result = await db.execute(
        select(PromoCode).where(PromoCode.code == req.code.upper().strip())
    )
    promo = promo_result.scalar_one_or_none()

    return ApplyPromoResponse(
        valid=validation.valid,
        reason=validation.reason,
        discount=validation.discount,
        code=promo.code if promo else req.code,
        promo_type=promo.promo_type.value if promo else "",
        value=promo.value if promo else 0.0,
    )


@router.get("/my-referral")
async def get_my_referral_code(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get the current user's referral code and stats."""
    from app.services.promos import get_referral_promo_for_user

    promo = await get_referral_promo_for_user(user.id, db)
    if not promo:
        return {"has_referral_code": False, "referral_code": None, "total_referrals": 0}

    return {
        "has_referral_code": True,
        "referral_code": promo.code,
        "total_referrals": promo.total_uses,
        "is_active": promo.is_active,
    }


@router.get(
    "/admin/stats",
    response_model=PromoStats,
    dependencies=[Depends(require_admin)],
)
async def promo_stats(
    period: str = Query("month", pattern="^(week|month|year|all)$"),
    db: AsyncSession = Depends(get_db),
) -> PromoStats:
    """Promo code usage analytics. Admin only.

    Returns redemption counts, total discount value, top codes by usage
    and by discount given, and referral vs non-referral breakdown.
    """
    now = datetime.now(timezone.utc)
    if period == "week":
        start: datetime | None = now - timedelta(days=7)
    elif period == "month":
        start = now - timedelta(days=30)
    elif period == "year":
        start = now - timedelta(days=365)
    else:
        start = None  # "all" — no date filter

    redemption_q = select(PromoRedemption)
    if start:
        redemption_q = redemption_q.where(PromoRedemption.redeemed_at >= start)

    # Summary stats
    total_q = select(
        func.count(PromoRedemption.id).label("total"),
        func.coalesce(func.sum(PromoRedemption.discount_amount), 0.0).label("discount_total"),
        func.count(func.distinct(PromoRedemption.user_id)).label("unique_users"),
    )
    if start:
        total_q = total_q.where(PromoRedemption.redeemed_at >= start)
    summary = (await db.execute(total_q)).one()

    # Active promo count (point-in-time, not period-filtered)
    active_count = (
        await db.execute(
            select(func.count(PromoCode.id)).where(PromoCode.is_active.is_(True))
        )
    ).scalar() or 0

    # Referral vs non-referral breakdown
    ref_q = (
        select(
            PromoCode.is_referral,
            func.count(PromoRedemption.id).label("cnt"),
        )
        .join(PromoCode, PromoRedemption.promo_code_id == PromoCode.id)
        .group_by(PromoCode.is_referral)
    )
    if start:
        ref_q = ref_q.where(PromoRedemption.redeemed_at >= start)
    ref_rows = (await db.execute(ref_q)).all()
    referral_redemptions = sum(r.cnt for r in ref_rows if r.is_referral)
    non_referral_redemptions = sum(r.cnt for r in ref_rows if not r.is_referral)

    # Top 10 by usage count
    top_usage_q = (
        select(
            PromoCode.id.label("promo_code_id"),
            PromoCode.code,
            PromoCode.description,
            PromoCode.promo_type,
            PromoCode.is_referral,
            func.count(PromoRedemption.id).label("redemptions"),
            func.coalesce(func.sum(PromoRedemption.discount_amount), 0.0).label("total_discount_given"),
        )
        .join(PromoCode, PromoRedemption.promo_code_id == PromoCode.id)
        .group_by(PromoCode.id, PromoCode.code, PromoCode.description, PromoCode.promo_type, PromoCode.is_referral)
        .order_by(func.count(PromoRedemption.id).desc())
        .limit(10)
    )
    if start:
        top_usage_q = top_usage_q.where(PromoRedemption.redeemed_at >= start)
    top_usage_rows = (await db.execute(top_usage_q)).all()

    # Top 10 by total discount given
    top_discount_q = (
        select(
            PromoCode.id.label("promo_code_id"),
            PromoCode.code,
            PromoCode.description,
            PromoCode.promo_type,
            PromoCode.is_referral,
            func.count(PromoRedemption.id).label("redemptions"),
            func.coalesce(func.sum(PromoRedemption.discount_amount), 0.0).label("total_discount_given"),
        )
        .join(PromoCode, PromoRedemption.promo_code_id == PromoCode.id)
        .group_by(PromoCode.id, PromoCode.code, PromoCode.description, PromoCode.promo_type, PromoCode.is_referral)
        .order_by(func.sum(PromoRedemption.discount_amount).desc())
        .limit(10)
    )
    if start:
        top_discount_q = top_discount_q.where(PromoRedemption.redeemed_at >= start)
    top_discount_rows = (await db.execute(top_discount_q)).all()

    def _row_to_top_entry(row) -> PromoTopEntry:
        return PromoTopEntry(
            promo_code_id=row.promo_code_id,
            code=row.code,
            description=row.description,
            promo_type=row.promo_type.value if hasattr(row.promo_type, "value") else str(row.promo_type),
            is_referral=row.is_referral,
            redemptions=int(row.redemptions),
            total_discount_given=round(float(row.total_discount_given), 2),
        )

    return PromoStats(
        period=period,
        total_redemptions=int(summary.total),
        total_discount_given=round(float(summary.discount_total), 2),
        unique_riders_used=int(summary.unique_users),
        active_promo_count=int(active_count),
        referral_redemptions=int(referral_redemptions),
        non_referral_redemptions=int(non_referral_redemptions),
        top_promos_by_usage=[_row_to_top_entry(r) for r in top_usage_rows],
        top_promos_by_discount=[_row_to_top_entry(r) for r in top_discount_rows],
    )


def _promo_to_response(promo: PromoCode) -> PromoCodeResponse:
    return PromoCodeResponse(
        id=promo.id,
        code=promo.code,
        description=promo.description,
        promo_type=promo.promo_type.value,
        value=promo.value,
        max_discount=promo.max_discount,
        minimum_fare=promo.minimum_fare,
        max_uses=promo.max_uses,
        max_uses_per_user=promo.max_uses_per_user,
        total_uses=promo.total_uses,
        is_active=promo.is_active,
        first_ride_only=promo.first_ride_only,
        is_referral=promo.is_referral,
        expires_at=promo.expires_at,
        created_at=promo.created_at,
    )
