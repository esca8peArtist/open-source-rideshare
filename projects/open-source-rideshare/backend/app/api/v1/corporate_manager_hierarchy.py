"""Corporate Manager Hierarchy endpoints.

Admin endpoints (require_admin):
  POST   /corporate/accounts/{account_id}/manager-relationships
         — create a manager relationship (direct or dotted-line)
  GET    /corporate/accounts/{account_id}/manager-relationships
         — list all relationships for the account
  GET    /corporate/accounts/{account_id}/manager-relationships/{rel_id}
         — get a single relationship
  PUT    /corporate/accounts/{account_id}/manager-relationships/{rel_id}
         — update notes / is_active
  DELETE /corporate/accounts/{account_id}/manager-relationships/{rel_id}
         — hard-delete a relationship
  GET    /corporate/accounts/{account_id}/members/{member_id}/managers
         — list all managers for a specific member
  GET    /corporate/accounts/{account_id}/members/{member_id}/direct-reports
         — list direct reports for a specific member
  GET    /corporate/accounts/{account_id}/org-summary
         — account-level org chart statistics

Member endpoints (authenticated):
  GET /corporate/accounts/me/managers
      — view own manager relationships
  GET /corporate/accounts/me/direct-reports
      — view own direct reports (if this member manages others)
  GET /corporate/accounts/me/reporting-chain
      — view own reporting chain up to root

Platform-admin:
  GET /admin/corporate/manager-relationships
      — list all relationships across all accounts
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, require_admin
from app.models.user import User
from app.schemas.corporate_manager_hierarchy import (
    ManagerRelationshipCreate,
    ManagerRelationshipListResponse,
    ManagerRelationshipResponse,
    ManagerRelationshipUpdate,
    OrgSummaryResponse,
    RelationshipType,
    ReportingChainResponse,
)
from app.services.corporate_account_mgmt import get_user_account
from app.services.corporate_manager_hierarchy import (
    create_relationship,
    get_all_reports,
    get_direct_reports,
    get_managers,
    get_org_summary,
    get_relationship,
    get_reporting_chain,
    list_all_relationships_platform,
    list_relationships,
    remove_relationship,
    update_relationship,
)
from fastapi import HTTPException

logger = logging.getLogger(__name__)

router = APIRouter(tags=["corporate-manager-hierarchy"])


# ---------------------------------------------------------------------------
# Internal helper
# ---------------------------------------------------------------------------


async def _resolve_member_account(db: AsyncSession, user_id: int) -> int:
    """Return the corporate account ID for the authenticated member.

    Raises HTTP 404 when the user is not a member of any corporate account.
    """
    account = await get_user_account(db, user_id)
    if account is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="You are not a member of any corporate account.",
        )
    return account.id


async def _get_member_id_for_user(db: AsyncSession, user_id: int, account_id: int) -> int:
    """Return the corporate_account_members.id for the authenticated user.

    Raises HTTP 404 when the user is not a member of the given account.
    """
    from sqlalchemy import select
    from app.models.corporate_account import BusinessAccountMember

    result = await db.execute(
        select(BusinessAccountMember.id).where(
            BusinessAccountMember.account_id == account_id,
            BusinessAccountMember.user_id == user_id,
        )
    )
    member_id = result.scalar_one_or_none()
    if member_id is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="You are not a member of any corporate account.",
        )
    return member_id


# ===========================================================================
# Admin endpoints
# ===========================================================================


@router.post(
    "/corporate/accounts/{account_id}/manager-relationships",
    response_model=ManagerRelationshipResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Admin: create a manager relationship",
)
async def admin_create_relationship(
    account_id: int,
    payload: ManagerRelationshipCreate,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Create a direct or dotted-line manager relationship.

    For **direct** relationships, any existing active direct manager for
    the employee is automatically deactivated first.  Only one direct
    manager is allowed per employee per account.

    For **dotted_line** relationships, multiple managers are allowed but
    an exact duplicate (same employee + manager pair, if already active)
    returns HTTP 409.

    Returns HTTP 400 if an employee is set as their own manager.
    Returns HTTP 409 if the relationship would create a reporting cycle.

    Corporate admin only.
    """
    return await create_relationship(
        db, account_id=account_id, data=payload, created_by_id=admin.id
    )


@router.get(
    "/corporate/accounts/{account_id}/manager-relationships",
    response_model=ManagerRelationshipListResponse,
    summary="Admin: list manager relationships for an account",
)
async def admin_list_relationships(
    account_id: int,
    relationship_type: RelationshipType | None = Query(
        None, description="Filter by direct or dotted_line"
    ),
    is_active: bool | None = Query(None, description="Filter by active status"),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """List all manager relationships for a corporate account.

    Optionally filter by relationship_type and/or is_active status.
    Results are ordered newest-first.

    Corporate admin only.
    """
    rows = await list_relationships(
        db,
        account_id,
        relationship_type=relationship_type,
        is_active=is_active,
        skip=skip,
        limit=limit,
    )
    return ManagerRelationshipListResponse(relationships=rows, total=len(rows))


@router.get(
    "/corporate/accounts/{account_id}/manager-relationships/{rel_id}",
    response_model=ManagerRelationshipResponse,
    summary="Admin: get a single manager relationship",
)
async def admin_get_relationship(
    account_id: int,
    rel_id: int,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Fetch a single manager relationship by ID.

    Returns HTTP 404 if not found or belonging to another account.

    Corporate admin only.
    """
    return await get_relationship(db, account_id=account_id, relationship_id=rel_id)


@router.put(
    "/corporate/accounts/{account_id}/manager-relationships/{rel_id}",
    response_model=ManagerRelationshipResponse,
    summary="Admin: update a manager relationship",
)
async def admin_update_relationship(
    account_id: int,
    rel_id: int,
    payload: ManagerRelationshipUpdate,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Update the notes and/or is_active flag on a relationship.

    All request body fields are optional.  Only supplied fields are written.

    Returns HTTP 404 if not found or belonging to another account.

    Corporate admin only.
    """
    return await update_relationship(
        db, account_id=account_id, relationship_id=rel_id, data=payload
    )


@router.delete(
    "/corporate/accounts/{account_id}/manager-relationships/{rel_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Admin: delete a manager relationship",
)
async def admin_delete_relationship(
    account_id: int,
    rel_id: int,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Permanently remove a manager relationship.

    Returns HTTP 404 if not found or belonging to another account.

    Corporate admin only.
    """
    await remove_relationship(db, account_id=account_id, relationship_id=rel_id)


@router.get(
    "/corporate/accounts/{account_id}/members/{member_id}/managers",
    response_model=ManagerRelationshipListResponse,
    summary="Admin: list managers for a specific member",
)
async def admin_get_member_managers(
    account_id: int,
    member_id: int,
    is_active: bool | None = Query(True, description="Filter by active status"),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """List all manager relationships for a given member (as subordinate).

    Returns direct manager first, then dotted-line managers.

    Corporate admin only.
    """
    rows = await get_managers(
        db, account_id, employee_member_id=member_id, is_active=is_active
    )
    return ManagerRelationshipListResponse(relationships=rows, total=len(rows))


@router.get(
    "/corporate/accounts/{account_id}/members/{member_id}/direct-reports",
    response_model=ManagerRelationshipListResponse,
    summary="Admin: list direct reports for a specific member",
)
async def admin_get_member_direct_reports(
    account_id: int,
    member_id: int,
    include_dotted_line: bool = Query(
        False, description="Include dotted-line reports in addition to direct"
    ),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """List all members who report directly (or via dotted-line) to the given member.

    By default only direct relationships are returned.  Set
    ``include_dotted_line=true`` to also include dotted-line reports.

    Corporate admin only.
    """
    if include_dotted_line:
        rows = await get_all_reports(db, account_id, manager_member_id=member_id)
    else:
        rows = await get_direct_reports(db, account_id, manager_member_id=member_id)
    return ManagerRelationshipListResponse(relationships=rows, total=len(rows))


@router.get(
    "/corporate/accounts/{account_id}/members/{member_id}/reporting-chain",
    response_model=ReportingChainResponse,
    summary="Admin: get reporting chain for a member",
)
async def admin_get_reporting_chain(
    account_id: int,
    member_id: int,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Walk the direct-manager chain from the member up to the org root.

    Returns an ordered list of managers from closest (depth=0) to root.
    Returns an empty chain if the member has no direct manager.

    Corporate admin only.
    """
    return await get_reporting_chain(
        db, account_id=account_id, employee_member_id=member_id
    )


@router.get(
    "/corporate/accounts/{account_id}/org-summary",
    response_model=OrgSummaryResponse,
    summary="Admin: get org chart summary for an account",
)
async def admin_get_org_summary(
    account_id: int,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return account-level org chart statistics.

    Includes total relationship counts, number of members with a direct
    manager, number of distinct managers, and a list of top-level manager
    member IDs (managers who are not themselves subordinates).

    Corporate admin only.
    """
    return await get_org_summary(db, account_id=account_id)


# ===========================================================================
# Member endpoints
# ===========================================================================


@router.get(
    "/corporate/accounts/me/managers",
    response_model=ManagerRelationshipListResponse,
    summary="View your own manager relationships",
)
async def member_get_own_managers(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return all active manager relationships for the authenticated member.

    Direct manager is listed first, then dotted-line managers.
    Returns an empty list if no manager is set.
    """
    account_id = await _resolve_member_account(db, user.id)
    member_id = await _get_member_id_for_user(db, user.id, account_id)
    rows = await get_managers(db, account_id, employee_member_id=member_id, is_active=True)
    return ManagerRelationshipListResponse(relationships=rows, total=len(rows))


@router.get(
    "/corporate/accounts/me/reporting-chain",
    response_model=ReportingChainResponse,
    summary="View your own reporting chain",
)
async def member_get_own_reporting_chain(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Walk the direct-manager chain from the authenticated member upward.

    Returns an ordered list from direct manager (depth=0) to the org root.
    Returns an empty chain if no direct manager is set.
    """
    account_id = await _resolve_member_account(db, user.id)
    member_id = await _get_member_id_for_user(db, user.id, account_id)
    return await get_reporting_chain(
        db, account_id=account_id, employee_member_id=member_id
    )


@router.get(
    "/corporate/accounts/me/direct-reports",
    response_model=ManagerRelationshipListResponse,
    summary="View your own direct reports",
)
async def member_get_own_direct_reports(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return all members who directly report to the authenticated member.

    Returns an empty list if this member does not manage anyone.
    """
    account_id = await _resolve_member_account(db, user.id)
    member_id = await _get_member_id_for_user(db, user.id, account_id)
    rows = await get_direct_reports(
        db, account_id, manager_member_id=member_id, is_active=True
    )
    return ManagerRelationshipListResponse(relationships=rows, total=len(rows))


# ===========================================================================
# Platform-admin endpoints
# ===========================================================================


@router.get(
    "/admin/corporate/manager-relationships",
    response_model=ManagerRelationshipListResponse,
    summary="Platform-admin: list all manager relationships",
)
async def platform_admin_list_all(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """List all manager relationships across all corporate accounts.

    Ordered newest-first.  Platform admin only.
    """
    rows = await list_all_relationships_platform(db, skip=skip, limit=limit)
    return ManagerRelationshipListResponse(relationships=rows, total=len(rows))
