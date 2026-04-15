"""Community Partner Organization API endpoints.

Endpoint groups
---------------
Admin — full CRUD on org accounts, grant issuance, revocation, reporting.
Partner admin — read-only view of their own org's data.
Rider — view active credits and usage history.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_admin
from app.db.database import get_db
from app.models.partner_org import PartnerCreditStatus, PartnerOrgStatus, PartnerOrgType
from app.models.user import User
from app.schemas.partner_org import (
    PartnerCreditGrantRequest,
    PartnerCreditGrantResponse,
    PartnerCreditUsageResponse,
    PartnerOrgCreateRequest,
    PartnerOrgResponse,
    PartnerOrgSummaryResponse,
    PartnerOrgUpdateRequest,
    PlatformPartnerSummaryResponse,
    RevokeGrantRequest,
    RiderPartnerCreditHistoryItem,
    RiderPartnerCreditSummary,
)
from app.services.partner_orgs import (
    activate_partner_org,
    apply_credit_to_ride,
    create_partner_org,
    expire_stale_grants,
    get_credit_grant,
    get_grant_usages,
    get_org_summary,
    get_partner_org,
    get_platform_partner_summary,
    get_rider_active_grants,
    get_rider_credit_history,
    issue_credit_grant,
    list_org_grants,
    list_partner_orgs,
    revoke_credit_grant,
    suspend_partner_org,
    terminate_partner_org,
    update_partner_org,
)

router = APIRouter(tags=["partner-orgs"])


# ===========================================================================
# Admin — Organization management
# ===========================================================================


@router.post(
    "/admin/partner-orgs",
    response_model=PartnerOrgResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_admin)],
)
async def admin_create_partner_org(
    req: PartnerOrgCreateRequest,
    db: AsyncSession = Depends(get_db),
):
    """Create a new community partner org account (starts as pending)."""
    return await create_partner_org(req, db)


@router.get(
    "/admin/partner-orgs",
    response_model=list[PartnerOrgResponse],
    dependencies=[Depends(require_admin)],
)
async def admin_list_partner_orgs(
    status_filter: PartnerOrgStatus | None = Query(None, alias="status"),
    org_type: PartnerOrgType | None = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    """List all partner organizations with optional filters."""
    return await list_partner_orgs(db, status=status_filter, org_type=org_type, skip=skip, limit=limit)


@router.get(
    "/admin/partner-orgs/summary",
    response_model=PlatformPartnerSummaryResponse,
    dependencies=[Depends(require_admin)],
)
async def admin_platform_partner_summary(db: AsyncSession = Depends(get_db)):
    """Platform-wide aggregate stats across all partner organizations."""
    data = await get_platform_partner_summary(db)
    return PlatformPartnerSummaryResponse(**data)


@router.post(
    "/admin/partner-orgs/expire-grants",
    dependencies=[Depends(require_admin)],
)
async def admin_expire_stale_grants(db: AsyncSession = Depends(get_db)):
    """Expire all active grants whose expiry_date has passed. Returns count expired."""
    count = await expire_stale_grants(db)
    return {"expired_count": count}


@router.get(
    "/admin/partner-orgs/{org_id}",
    response_model=PartnerOrgResponse,
    dependencies=[Depends(require_admin)],
)
async def admin_get_partner_org(org_id: int, db: AsyncSession = Depends(get_db)):
    """Get a single partner org by ID."""
    org = await get_partner_org(org_id, db)
    if not org:
        raise HTTPException(status_code=404, detail="Partner organization not found")
    return org


@router.put(
    "/admin/partner-orgs/{org_id}",
    response_model=PartnerOrgResponse,
    dependencies=[Depends(require_admin)],
)
async def admin_update_partner_org(
    org_id: int,
    req: PartnerOrgUpdateRequest,
    db: AsyncSession = Depends(get_db),
):
    """Update partner org contact info and settings."""
    org = await get_partner_org(org_id, db)
    if not org:
        raise HTTPException(status_code=404, detail="Partner organization not found")
    return await update_partner_org(org, req, db)


@router.put(
    "/admin/partner-orgs/{org_id}/activate",
    response_model=PartnerOrgResponse,
    dependencies=[Depends(require_admin)],
)
async def admin_activate_partner_org(org_id: int, db: AsyncSession = Depends(get_db)):
    """Activate a pending or suspended partner org."""
    org = await get_partner_org(org_id, db)
    if not org:
        raise HTTPException(status_code=404, detail="Partner organization not found")
    try:
        return await activate_partner_org(org, db)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.put(
    "/admin/partner-orgs/{org_id}/suspend",
    response_model=PartnerOrgResponse,
    dependencies=[Depends(require_admin)],
)
async def admin_suspend_partner_org(org_id: int, db: AsyncSession = Depends(get_db)):
    """Suspend an active partner org (prevents new credit issuance)."""
    org = await get_partner_org(org_id, db)
    if not org:
        raise HTTPException(status_code=404, detail="Partner organization not found")
    try:
        return await suspend_partner_org(org, db)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.put(
    "/admin/partner-orgs/{org_id}/terminate",
    response_model=PartnerOrgResponse,
    dependencies=[Depends(require_admin)],
)
async def admin_terminate_partner_org(org_id: int, db: AsyncSession = Depends(get_db)):
    """Permanently terminate a partner org and revoke all active grants."""
    org = await get_partner_org(org_id, db)
    if not org:
        raise HTTPException(status_code=404, detail="Partner organization not found")
    try:
        return await terminate_partner_org(org, db)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.get(
    "/admin/partner-orgs/{org_id}/summary",
    response_model=PartnerOrgSummaryResponse,
    dependencies=[Depends(require_admin)],
)
async def admin_get_org_summary(org_id: int, db: AsyncSession = Depends(get_db)):
    """Aggregate credit and usage stats for one org."""
    org = await get_partner_org(org_id, db)
    if not org:
        raise HTTPException(status_code=404, detail="Partner organization not found")
    data = await get_org_summary(org, db)
    return PartnerOrgSummaryResponse(**data)


# ===========================================================================
# Admin — Credit Grant management
# ===========================================================================


@router.post(
    "/admin/partner-orgs/{org_id}/credits",
    response_model=PartnerCreditGrantResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_admin)],
)
async def admin_issue_credit_grant(
    org_id: int,
    req: PartnerCreditGrantRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Issue a credit grant to a specific rider on behalf of the partner org."""
    org = await get_partner_org(org_id, db)
    if not org:
        raise HTTPException(status_code=404, detail="Partner organization not found")
    try:
        grant = await issue_credit_grant(org, req, current_user, db)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return _grant_response(grant)


@router.get(
    "/admin/partner-orgs/{org_id}/credits",
    response_model=list[PartnerCreditGrantResponse],
    dependencies=[Depends(require_admin)],
)
async def admin_list_org_credits(
    org_id: int,
    status_filter: PartnerCreditStatus | None = Query(None, alias="status"),
    rider_id: int | None = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    """List credit grants for a specific org."""
    org = await get_partner_org(org_id, db)
    if not org:
        raise HTTPException(status_code=404, detail="Partner organization not found")
    grants = await list_org_grants(org_id, db, status=status_filter, rider_id=rider_id, skip=skip, limit=limit)
    return [_grant_response(g) for g in grants]


@router.get(
    "/admin/partner-credits/{grant_id}",
    response_model=PartnerCreditGrantResponse,
    dependencies=[Depends(require_admin)],
)
async def admin_get_credit_grant(grant_id: int, db: AsyncSession = Depends(get_db)):
    """Get a single credit grant by ID."""
    grant = await get_credit_grant(grant_id, db)
    if not grant:
        raise HTTPException(status_code=404, detail="Credit grant not found")
    return _grant_response(grant)


@router.put(
    "/admin/partner-credits/{grant_id}/revoke",
    response_model=PartnerCreditGrantResponse,
    dependencies=[Depends(require_admin)],
)
async def admin_revoke_credit_grant(
    grant_id: int,
    req: RevokeGrantRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Revoke an active credit grant."""
    grant = await get_credit_grant(grant_id, db)
    if not grant:
        raise HTTPException(status_code=404, detail="Credit grant not found")
    try:
        grant = await revoke_credit_grant(grant, req, current_user, db)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return _grant_response(grant)


@router.get(
    "/admin/partner-credits/{grant_id}/usages",
    response_model=list[PartnerCreditUsageResponse],
    dependencies=[Depends(require_admin)],
)
async def admin_get_grant_usages(grant_id: int, db: AsyncSession = Depends(get_db)):
    """List all ride usages for a specific credit grant."""
    grant = await get_credit_grant(grant_id, db)
    if not grant:
        raise HTTPException(status_code=404, detail="Credit grant not found")
    usages = await get_grant_usages(grant_id, db)
    return usages


# ===========================================================================
# Partner Admin — view their own org's data
# ===========================================================================


async def _get_partner_org_for_user(
    current_user: User,
    db: AsyncSession,
) -> "PartnerOrganization":
    """Return the org for which current_user is the designated partner admin."""
    from sqlalchemy import select
    from app.models.partner_org import PartnerOrganization

    result = await db.execute(
        select(PartnerOrganization).where(
            PartnerOrganization.partner_admin_user_id == current_user.id
        )
    )
    org = result.scalar_one_or_none()
    if not org:
        raise HTTPException(
            status_code=403,
            detail="You are not designated as a partner admin for any organization.",
        )
    return org


@router.get("/partner/me/org", response_model=PartnerOrgResponse)
async def partner_get_my_org(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Partner admin views their own org's profile."""
    org = await _get_partner_org_for_user(current_user, db)
    return org


@router.get("/partner/me/summary", response_model=PartnerOrgSummaryResponse)
async def partner_get_my_summary(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Partner admin views their org's aggregate credit and usage stats."""
    org = await _get_partner_org_for_user(current_user, db)
    data = await get_org_summary(org, db)
    return PartnerOrgSummaryResponse(**data)


@router.get("/partner/me/credits", response_model=list[PartnerCreditGrantResponse])
async def partner_list_my_credits(
    status_filter: PartnerCreditStatus | None = Query(None, alias="status"),
    rider_id: int | None = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Partner admin lists credits issued by their org."""
    org = await _get_partner_org_for_user(current_user, db)
    grants = await list_org_grants(
        org.id, db, status=status_filter, rider_id=rider_id, skip=skip, limit=limit
    )
    return [_grant_response(g) for g in grants]


# ===========================================================================
# Rider — view and use partner credits
# ===========================================================================


@router.get("/riders/me/partner-credits", response_model=RiderPartnerCreditSummary)
async def rider_get_partner_credits(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Rider views their active partner credit grants and total available balance."""
    grants = await get_rider_active_grants(current_user.id, db)
    total_available = sum(float(g.amount_usd - g.amount_used_usd) for g in grants)
    return RiderPartnerCreditSummary(
        total_active_grants=len(grants),
        total_available_usd=round(total_available, 2),
        grants=[_grant_response(g) for g in grants],
    )


@router.get(
    "/riders/me/partner-credits/history",
    response_model=list[RiderPartnerCreditHistoryItem],
)
async def rider_get_partner_credit_history(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Rider views their history of partner credit usages."""
    rows = await get_rider_credit_history(current_user.id, db, skip=skip, limit=limit)
    return [RiderPartnerCreditHistoryItem(**r) for r in rows]


# ===========================================================================
# Internal helper
# ===========================================================================


def _grant_response(grant: "PartnerCreditGrant") -> PartnerCreditGrantResponse:
    """Build a PartnerCreditGrantResponse, computing the derived remaining field."""
    from decimal import Decimal

    return PartnerCreditGrantResponse(
        id=grant.id,
        organization_id=grant.organization_id,
        rider_id=grant.rider_id,
        issued_by_admin_id=grant.issued_by_admin_id,
        status=grant.status,
        amount_usd=grant.amount_usd,
        amount_used_usd=grant.amount_used_usd,
        amount_remaining_usd=grant.amount_usd - grant.amount_used_usd,
        per_ride_cap_usd=grant.per_ride_cap_usd,
        purpose=grant.purpose,
        expiry_date=grant.expiry_date,
        revoked_by_admin_id=grant.revoked_by_admin_id,
        revoke_reason=grant.revoke_reason,
        revoked_at=grant.revoked_at,
        created_at=grant.created_at,
        updated_at=grant.updated_at,
    )
