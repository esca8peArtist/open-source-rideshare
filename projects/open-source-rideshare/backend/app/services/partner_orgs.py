"""Service layer for the Community Partner Organization system.

All database access lives here; the router is thin and delegates to these
functions.  Each function receives an open AsyncSession and a calling user
object so the router can pass them in after auth.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.partner_org import (
    PartnerCreditGrant,
    PartnerCreditStatus,
    PartnerCreditUsage,
    PartnerOrganization,
    PartnerOrgStatus,
    PartnerOrgType,
)
from app.models.user import User
from app.schemas.partner_org import (
    PartnerCreditGrantRequest,
    PartnerOrgCreateRequest,
    PartnerOrgUpdateRequest,
    RevokeGrantRequest,
)


# ---------------------------------------------------------------------------
# Partner Organization management (admin)
# ---------------------------------------------------------------------------


async def create_partner_org(
    req: PartnerOrgCreateRequest,
    db: AsyncSession,
) -> PartnerOrganization:
    """Create a new partner org in pending status."""
    org = PartnerOrganization(
        name=req.name,
        org_type=req.org_type,
        status=PartnerOrgStatus.pending,
        contact_name=req.contact_name,
        contact_email=req.contact_email,
        contact_phone=req.contact_phone,
        partner_admin_user_id=req.partner_admin_user_id,
        monthly_credit_limit_usd=req.monthly_credit_limit_usd,
        description=req.description,
        admin_note=req.admin_note,
    )
    db.add(org)
    await db.commit()
    await db.refresh(org)
    return org


async def get_partner_org(org_id: int, db: AsyncSession) -> PartnerOrganization | None:
    result = await db.execute(
        select(PartnerOrganization).where(PartnerOrganization.id == org_id)
    )
    return result.scalar_one_or_none()


async def list_partner_orgs(
    db: AsyncSession,
    status: PartnerOrgStatus | None = None,
    org_type: PartnerOrgType | None = None,
    skip: int = 0,
    limit: int = 50,
) -> list[PartnerOrganization]:
    q = select(PartnerOrganization)
    if status:
        q = q.where(PartnerOrganization.status == status)
    if org_type:
        q = q.where(PartnerOrganization.org_type == org_type)
    q = q.order_by(PartnerOrganization.created_at.desc()).offset(skip).limit(limit)
    result = await db.execute(q)
    return list(result.scalars().all())


async def update_partner_org(
    org: PartnerOrganization,
    req: PartnerOrgUpdateRequest,
    db: AsyncSession,
) -> PartnerOrganization:
    """Apply non-None fields from the request to the org."""
    if req.name is not None:
        org.name = req.name
    if req.contact_name is not None:
        org.contact_name = req.contact_name
    if req.contact_email is not None:
        org.contact_email = req.contact_email
    if req.contact_phone is not None:
        org.contact_phone = req.contact_phone
    if req.partner_admin_user_id is not None:
        org.partner_admin_user_id = req.partner_admin_user_id
    if req.monthly_credit_limit_usd is not None:
        org.monthly_credit_limit_usd = req.monthly_credit_limit_usd
    if req.description is not None:
        org.description = req.description
    if req.admin_note is not None:
        org.admin_note = req.admin_note
    await db.commit()
    await db.refresh(org)
    return org


async def activate_partner_org(
    org: PartnerOrganization,
    db: AsyncSession,
) -> PartnerOrganization:
    if org.status not in (PartnerOrgStatus.pending, PartnerOrgStatus.suspended):
        raise ValueError(f"Cannot activate an org with status '{org.status.value}'")
    org.status = PartnerOrgStatus.active
    org.activated_at = datetime.now(timezone.utc)
    org.suspended_at = None
    await db.commit()
    await db.refresh(org)
    return org


async def suspend_partner_org(
    org: PartnerOrganization,
    db: AsyncSession,
) -> PartnerOrganization:
    if org.status != PartnerOrgStatus.active:
        raise ValueError(f"Cannot suspend an org with status '{org.status.value}'")
    org.status = PartnerOrgStatus.suspended
    org.suspended_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(org)
    return org


async def terminate_partner_org(
    org: PartnerOrganization,
    db: AsyncSession,
) -> PartnerOrganization:
    if org.status == PartnerOrgStatus.terminated:
        raise ValueError("Org is already terminated")
    org.status = PartnerOrgStatus.terminated
    # Revoke all active grants
    grants_q = await db.execute(
        select(PartnerCreditGrant).where(
            PartnerCreditGrant.organization_id == org.id,
            PartnerCreditGrant.status == PartnerCreditStatus.active,
        )
    )
    for grant in grants_q.scalars().all():
        grant.status = PartnerCreditStatus.revoked
        grant.revoke_reason = "Partner organization terminated"
        grant.revoked_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(org)
    return org


# ---------------------------------------------------------------------------
# Credit Grant management
# ---------------------------------------------------------------------------


async def issue_credit_grant(
    org: PartnerOrganization,
    req: PartnerCreditGrantRequest,
    issuing_admin: User,
    db: AsyncSession,
) -> PartnerCreditGrant:
    """Issue a credit grant to a rider on behalf of an org.

    Validates:
    - Org must be active
    - amount_usd must be positive (enforced by schema, double-checked here)
    - Monthly limit: if org.monthly_credit_limit_usd is set, check current
      calendar-month issuance does not exceed it after this grant.
    """
    if org.status != PartnerOrgStatus.active:
        raise ValueError("Cannot issue credits from a non-active organization")

    if req.amount_usd <= Decimal("0"):
        raise ValueError("amount_usd must be positive")

    # Monthly cap check
    if org.monthly_credit_limit_usd is not None:
        now = datetime.now(timezone.utc)
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        month_total_result = await db.execute(
            select(func.coalesce(func.sum(PartnerCreditGrant.amount_usd), 0)).where(
                PartnerCreditGrant.organization_id == org.id,
                PartnerCreditGrant.created_at >= month_start,
                PartnerCreditGrant.status != PartnerCreditStatus.revoked,
            )
        )
        month_total = Decimal(str(month_total_result.scalar()))
        if month_total + req.amount_usd > org.monthly_credit_limit_usd:
            raise ValueError(
                f"Issuing this grant would exceed the org's monthly credit limit of "
                f"${org.monthly_credit_limit_usd:.2f}. "
                f"Already issued this month: ${month_total:.2f}."
            )

    grant = PartnerCreditGrant(
        organization_id=org.id,
        rider_id=req.rider_id,
        issued_by_admin_id=issuing_admin.id,
        status=PartnerCreditStatus.active,
        amount_usd=req.amount_usd,
        amount_used_usd=Decimal("0.00"),
        per_ride_cap_usd=req.per_ride_cap_usd,
        purpose=req.purpose,
        expiry_date=req.expiry_date,
    )
    db.add(grant)
    await db.commit()
    await db.refresh(grant)
    return grant


async def get_credit_grant(grant_id: int, db: AsyncSession) -> PartnerCreditGrant | None:
    result = await db.execute(
        select(PartnerCreditGrant).where(PartnerCreditGrant.id == grant_id)
    )
    return result.scalar_one_or_none()


async def list_org_grants(
    org_id: int,
    db: AsyncSession,
    status: PartnerCreditStatus | None = None,
    rider_id: int | None = None,
    skip: int = 0,
    limit: int = 50,
) -> list[PartnerCreditGrant]:
    q = select(PartnerCreditGrant).where(PartnerCreditGrant.organization_id == org_id)
    if status:
        q = q.where(PartnerCreditGrant.status == status)
    if rider_id:
        q = q.where(PartnerCreditGrant.rider_id == rider_id)
    q = q.order_by(PartnerCreditGrant.created_at.desc()).offset(skip).limit(limit)
    result = await db.execute(q)
    return list(result.scalars().all())


async def revoke_credit_grant(
    grant: PartnerCreditGrant,
    req: RevokeGrantRequest,
    admin: User,
    db: AsyncSession,
) -> PartnerCreditGrant:
    if grant.status != PartnerCreditStatus.active:
        raise ValueError(f"Cannot revoke a grant with status '{grant.status.value}'")
    grant.status = PartnerCreditStatus.revoked
    grant.revoked_by_admin_id = admin.id
    grant.revoke_reason = req.reason
    grant.revoked_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(grant)
    return grant


async def expire_stale_grants(db: AsyncSession) -> int:
    """Mark all active grants whose expiry_date < today as expired.

    Returns the count of grants expired.  Intended to be called from a
    scheduled task or admin endpoint, not on every request.
    """
    today = date.today()
    q = await db.execute(
        select(PartnerCreditGrant).where(
            PartnerCreditGrant.status == PartnerCreditStatus.active,
            PartnerCreditGrant.expiry_date < today,
            PartnerCreditGrant.expiry_date.isnot(None),
        )
    )
    grants = q.scalars().all()
    count = 0
    for grant in grants:
        grant.status = PartnerCreditStatus.expired
        count += 1
    if count:
        await db.commit()
    return count


# ---------------------------------------------------------------------------
# Credit application (called from rides service or admin)
# ---------------------------------------------------------------------------


async def apply_credit_to_ride(
    rider_id: int,
    ride_id: int,
    ride_fare_usd: Decimal,
    db: AsyncSession,
) -> Decimal:
    """Apply the best available active credit grant to a completed ride.

    Selects the oldest active grant for the rider (FIFO), applies up to
    the per-ride cap or the remaining grant balance, whichever is smaller,
    and records a PartnerCreditUsage row.

    Returns the amount applied (may be $0.00 if no grant available).
    """
    today = date.today()
    q = await db.execute(
        select(PartnerCreditGrant).where(
            PartnerCreditGrant.rider_id == rider_id,
            PartnerCreditGrant.status == PartnerCreditStatus.active,
            (PartnerCreditGrant.expiry_date.is_(None))
            | (PartnerCreditGrant.expiry_date >= today),
        ).order_by(PartnerCreditGrant.created_at.asc())
    )
    grant: PartnerCreditGrant | None = q.scalars().first()
    if grant is None:
        return Decimal("0.00")

    # Determine how much to apply
    remaining = grant.amount_usd - grant.amount_used_usd
    if remaining <= Decimal("0"):
        grant.status = PartnerCreditStatus.exhausted
        await db.commit()
        return Decimal("0.00")

    cap = grant.per_ride_cap_usd if grant.per_ride_cap_usd is not None else ride_fare_usd
    apply_amount = min(remaining, cap, ride_fare_usd)
    apply_amount = apply_amount.quantize(Decimal("0.01"))

    # Check for duplicate usage (idempotency)
    existing = await db.execute(
        select(PartnerCreditUsage).where(
            PartnerCreditUsage.grant_id == grant.id,
            PartnerCreditUsage.ride_id == ride_id,
        )
    )
    if existing.scalar_one_or_none():
        return apply_amount  # already recorded

    usage = PartnerCreditUsage(
        grant_id=grant.id,
        ride_id=ride_id,
        amount_applied_usd=apply_amount,
    )
    db.add(usage)

    grant.amount_used_usd += apply_amount
    if grant.amount_used_usd >= grant.amount_usd:
        grant.status = PartnerCreditStatus.exhausted

    await db.commit()
    return apply_amount


# ---------------------------------------------------------------------------
# Summary / reporting
# ---------------------------------------------------------------------------


async def get_org_summary(org: PartnerOrganization, db: AsyncSession) -> dict:
    grants_result = await db.execute(
        select(
            func.count(PartnerCreditGrant.id),
            func.coalesce(func.sum(PartnerCreditGrant.amount_usd), 0),
            func.coalesce(func.sum(PartnerCreditGrant.amount_used_usd), 0),
        ).where(PartnerCreditGrant.organization_id == org.id)
    )
    row = grants_result.one()
    total_grants, total_issued, total_used = int(row[0]), float(row[1]), float(row[2])

    active_grants_result = await db.execute(
        select(func.count(PartnerCreditGrant.id)).where(
            PartnerCreditGrant.organization_id == org.id,
            PartnerCreditGrant.status == PartnerCreditStatus.active,
        )
    )
    active_grants = int(active_grants_result.scalar())

    riders_result = await db.execute(
        select(func.count(func.distinct(PartnerCreditGrant.rider_id))).where(
            PartnerCreditGrant.organization_id == org.id
        )
    )
    riders_served = int(riders_result.scalar())

    # Count rides funded via usages for this org's grants
    rides_result = await db.execute(
        select(func.count(PartnerCreditUsage.id)).where(
            PartnerCreditUsage.grant_id.in_(
                select(PartnerCreditGrant.id).where(
                    PartnerCreditGrant.organization_id == org.id
                )
            )
        )
    )
    rides_funded = int(rides_result.scalar())

    return {
        "organization_id": org.id,
        "organization_name": org.name,
        "org_type": org.org_type,
        "status": org.status,
        "total_grants_issued": total_grants,
        "total_credits_issued_usd": total_issued,
        "total_credits_used_usd": total_used,
        "total_credits_remaining_usd": round(total_issued - total_used, 2),
        "active_grants": active_grants,
        "riders_served": riders_served,
        "rides_funded": rides_funded,
    }


async def get_platform_partner_summary(db: AsyncSession) -> dict:
    orgs_result = await db.execute(
        select(
            func.count(PartnerOrganization.id),
            func.count(
                PartnerOrganization.id
            ).filter(PartnerOrganization.status == PartnerOrgStatus.active),
            func.count(
                PartnerOrganization.id
            ).filter(PartnerOrganization.status == PartnerOrgStatus.pending),
        )
    )
    row = orgs_result.one()
    total_orgs, active_orgs, pending_orgs = int(row[0]), int(row[1]), int(row[2])

    credits_result = await db.execute(
        select(
            func.coalesce(func.sum(PartnerCreditGrant.amount_usd), 0),
            func.coalesce(func.sum(PartnerCreditGrant.amount_used_usd), 0),
        )
    )
    credits_row = credits_result.one()
    total_issued, total_used = float(credits_row[0]), float(credits_row[1])

    rides_result = await db.execute(select(func.count(PartnerCreditUsage.id)))
    total_rides = int(rides_result.scalar())

    riders_result = await db.execute(
        select(func.count(func.distinct(PartnerCreditGrant.rider_id)))
    )
    total_riders = int(riders_result.scalar())

    return {
        "total_organizations": total_orgs,
        "active_organizations": active_orgs,
        "pending_organizations": pending_orgs,
        "total_credits_issued_usd": total_issued,
        "total_credits_used_usd": total_used,
        "total_rides_funded": total_rides,
        "total_riders_served": total_riders,
    }


# ---------------------------------------------------------------------------
# Rider-facing helpers
# ---------------------------------------------------------------------------


async def get_rider_active_grants(
    rider_id: int,
    db: AsyncSession,
) -> list[PartnerCreditGrant]:
    today = date.today()
    result = await db.execute(
        select(PartnerCreditGrant).where(
            PartnerCreditGrant.rider_id == rider_id,
            PartnerCreditGrant.status == PartnerCreditStatus.active,
            (PartnerCreditGrant.expiry_date.is_(None))
            | (PartnerCreditGrant.expiry_date >= today),
        ).order_by(PartnerCreditGrant.created_at.asc())
    )
    return list(result.scalars().all())


async def get_rider_credit_history(
    rider_id: int,
    db: AsyncSession,
    skip: int = 0,
    limit: int = 50,
) -> list[dict]:
    """Return usage records for the rider, enriched with org name and purpose."""
    result = await db.execute(
        select(
            PartnerCreditUsage.ride_id,
            PartnerCreditUsage.amount_applied_usd,
            PartnerCreditUsage.created_at,
            PartnerOrganization.name,
            PartnerCreditGrant.purpose,
        )
        .join(PartnerCreditGrant, PartnerCreditUsage.grant_id == PartnerCreditGrant.id)
        .join(PartnerOrganization, PartnerCreditGrant.organization_id == PartnerOrganization.id)
        .where(PartnerCreditGrant.rider_id == rider_id)
        .order_by(PartnerCreditUsage.created_at.desc())
        .offset(skip)
        .limit(limit)
    )
    rows = result.all()
    return [
        {
            "ride_id": row.ride_id,
            "amount_applied_usd": row.amount_applied_usd,
            "organization_name": row.name,
            "purpose": row.purpose,
            "used_at": row.created_at,
        }
        for row in rows
    ]


async def get_grant_usages(grant_id: int, db: AsyncSession) -> list[PartnerCreditUsage]:
    result = await db.execute(
        select(PartnerCreditUsage)
        .where(PartnerCreditUsage.grant_id == grant_id)
        .order_by(PartnerCreditUsage.created_at.desc())
    )
    return list(result.scalars().all())
