"""Service layer for Corporate Manager Hierarchy.

Admins define employee→manager reporting relationships within a corporate
account.  Two relationship types are supported:

  direct      — canonical "reports to".  At most one active direct manager
                per employee per account.  Setting a new direct manager
                deactivates any existing one first.
  dotted_line — informal / matrix-org relationships.  Multiple allowed per
                employee.  Returns 409 on exact duplicate.

Cycle prevention: before creating any relationship A→B the service walks
B's direct-manager chain; if it reaches A a 409 is raised.

All functions are async and require a SQLAlchemy ``AsyncSession``.

Public surface
--------------
create_relationship(db, account_id, data, created_by_id)
    -> ManagerRelationshipResponse
get_relationship(db, account_id, relationship_id)
    -> ManagerRelationshipResponse
update_relationship(db, account_id, relationship_id, data)
    -> ManagerRelationshipResponse
remove_relationship(db, account_id, relationship_id)
    -> None
list_relationships(db, account_id, *, relationship_type, is_active)
    -> list[ManagerRelationshipResponse]
get_managers(db, account_id, employee_member_id, *, is_active)
    -> list[ManagerRelationshipResponse]
get_direct_reports(db, account_id, manager_member_id, *, is_active)
    -> list[ManagerRelationshipResponse]
get_all_reports(db, account_id, manager_member_id, *, is_active)
    -> list[ManagerRelationshipResponse]
get_reporting_chain(db, account_id, employee_member_id, *, max_depth)
    -> ReportingChainResponse
get_org_summary(db, account_id)
    -> OrgSummaryResponse
list_all_relationships_platform(db, *, skip, limit)
    -> list[ManagerRelationshipResponse]
"""

from __future__ import annotations

from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.corporate_manager_hierarchy import CorporateManagerRelationship
from app.schemas.corporate_manager_hierarchy import (
    ManagerRelationshipCreate,
    ManagerRelationshipListResponse,
    ManagerRelationshipResponse,
    ManagerRelationshipUpdate,
    OrgSummaryResponse,
    RelationshipType,
    ReportingChainEntry,
    ReportingChainResponse,
)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _to_response(row: CorporateManagerRelationship) -> ManagerRelationshipResponse:
    """Convert an ORM row to ManagerRelationshipResponse."""
    return ManagerRelationshipResponse.model_validate(row)


async def _get_row(
    db: AsyncSession,
    account_id: int,
    relationship_id: int,
) -> CorporateManagerRelationship:
    """Fetch a relationship row by ID, scoped to the given account.

    Raises HTTP 404 if the row does not exist or belongs to another account.
    """
    result = await db.execute(
        select(CorporateManagerRelationship).where(
            CorporateManagerRelationship.id == relationship_id,
            CorporateManagerRelationship.account_id == account_id,
        )
    )
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Manager relationship {relationship_id} not found.",
        )
    return row


async def _would_create_cycle(
    db: AsyncSession,
    account_id: int,
    employee_member_id: int,
    manager_member_id: int,
    max_depth: int = 20,
) -> bool:
    """Return True if setting employee→manager would create a cycle.

    Walks B's direct-manager chain (B = manager_member_id).  If it reaches
    A (= employee_member_id) the relationship would create a cycle.

    Only follows *direct* relationships because dotted-line links do not
    participate in the canonical hierarchy traversal.
    """
    current = manager_member_id
    for _ in range(max_depth):
        result = await db.execute(
            select(CorporateManagerRelationship.manager_member_id).where(
                CorporateManagerRelationship.account_id == account_id,
                CorporateManagerRelationship.employee_member_id == current,
                CorporateManagerRelationship.relationship_type == RelationshipType.direct,
                CorporateManagerRelationship.is_active.is_(True),
            )
        )
        next_manager = result.scalar_one_or_none()
        if next_manager is None:
            break
        if next_manager == employee_member_id:
            return True
        current = next_manager
    return False


# ---------------------------------------------------------------------------
# Public service functions
# ---------------------------------------------------------------------------


async def create_relationship(
    db: AsyncSession,
    account_id: int,
    data: ManagerRelationshipCreate,
    created_by_id: int,
) -> ManagerRelationshipResponse:
    """Create a manager relationship.

    For ``direct`` relationships: if the employee already has an active direct
    manager, that relationship is deactivated before creating the new one.

    For ``dotted_line`` relationships: returns HTTP 409 if the exact
    (employee, manager) pair already exists and is active.

    Raises:
        HTTP 400 if employee_member_id == manager_member_id.
        HTTP 409 if a cycle would be created.
        HTTP 409 if a duplicate dotted-line relationship exists.
    """
    if data.employee_member_id == data.manager_member_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="An employee cannot be their own manager.",
        )

    # Cycle check
    if await _would_create_cycle(
        db, account_id, data.employee_member_id, data.manager_member_id
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "This relationship would create a reporting cycle. "
                "The proposed manager already reports (directly or indirectly) "
                "to this employee."
            ),
        )

    if data.relationship_type == RelationshipType.direct:
        # Deactivate any existing active direct manager for this employee
        existing_result = await db.execute(
            select(CorporateManagerRelationship).where(
                CorporateManagerRelationship.account_id == account_id,
                CorporateManagerRelationship.employee_member_id == data.employee_member_id,
                CorporateManagerRelationship.relationship_type == RelationshipType.direct,
                CorporateManagerRelationship.is_active.is_(True),
            )
        )
        existing = existing_result.scalar_one_or_none()
        if existing is not None:
            existing.is_active = False
            await db.flush()

    else:
        # dotted_line: check for duplicate
        dup_result = await db.execute(
            select(CorporateManagerRelationship).where(
                CorporateManagerRelationship.account_id == account_id,
                CorporateManagerRelationship.employee_member_id == data.employee_member_id,
                CorporateManagerRelationship.manager_member_id == data.manager_member_id,
                CorporateManagerRelationship.is_active.is_(True),
            )
        )
        if dup_result.scalar_one_or_none() is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="An active relationship between this employee and manager already exists.",
            )

    row = CorporateManagerRelationship(
        account_id=account_id,
        employee_member_id=data.employee_member_id,
        manager_member_id=data.manager_member_id,
        relationship_type=data.relationship_type.value,
        notes=data.notes,
        is_active=True,
        created_by_id=created_by_id,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return _to_response(row)


async def get_relationship(
    db: AsyncSession,
    account_id: int,
    relationship_id: int,
) -> ManagerRelationshipResponse:
    """Fetch a single relationship by ID.

    Raises HTTP 404 if not found or belonging to another account.
    """
    row = await _get_row(db, account_id, relationship_id)
    return _to_response(row)


async def update_relationship(
    db: AsyncSession,
    account_id: int,
    relationship_id: int,
    data: ManagerRelationshipUpdate,
) -> ManagerRelationshipResponse:
    """Update notes and/or is_active on a relationship.

    Only supplied fields are written.

    Raises HTTP 404 if not found or belonging to another account.
    """
    row = await _get_row(db, account_id, relationship_id)
    if data.notes is not None:
        row.notes = data.notes
    if data.is_active is not None:
        row.is_active = data.is_active
    await db.commit()
    await db.refresh(row)
    return _to_response(row)


async def remove_relationship(
    db: AsyncSession,
    account_id: int,
    relationship_id: int,
) -> None:
    """Hard-delete a manager relationship.

    Raises HTTP 404 if not found or belonging to another account.
    """
    row = await _get_row(db, account_id, relationship_id)
    await db.delete(row)
    await db.commit()


async def list_relationships(
    db: AsyncSession,
    account_id: int,
    *,
    relationship_type: Optional[RelationshipType] = None,
    is_active: Optional[bool] = None,
    skip: int = 0,
    limit: int = 100,
) -> list[ManagerRelationshipResponse]:
    """List all manager relationships for an account with optional filters.

    Args:
        account_id:        Corporate account to scope results to.
        relationship_type: Filter to "direct" or "dotted_line".
        is_active:         Filter by active/inactive status.
        skip:              Pagination offset.
        limit:             Maximum rows to return.

    Returns:
        List of ManagerRelationshipResponse, ordered by created_at desc.
    """
    q = select(CorporateManagerRelationship).where(
        CorporateManagerRelationship.account_id == account_id
    )
    if relationship_type is not None:
        q = q.where(
            CorporateManagerRelationship.relationship_type == relationship_type.value
        )
    if is_active is not None:
        q = q.where(CorporateManagerRelationship.is_active.is_(is_active))
    q = q.order_by(CorporateManagerRelationship.created_at.desc()).offset(skip).limit(limit)
    result = await db.execute(q)
    return [_to_response(r) for r in result.scalars().all()]


async def get_managers(
    db: AsyncSession,
    account_id: int,
    employee_member_id: int,
    *,
    is_active: Optional[bool] = True,
) -> list[ManagerRelationshipResponse]:
    """Return all manager relationships for a given employee.

    Args:
        account_id:          Corporate account to scope.
        employee_member_id:  The subordinate member.
        is_active:           Default True (active only).  Pass None for all.

    Returns:
        Direct manager listed first, then dotted-line managers.
    """
    q = select(CorporateManagerRelationship).where(
        CorporateManagerRelationship.account_id == account_id,
        CorporateManagerRelationship.employee_member_id == employee_member_id,
    )
    if is_active is not None:
        q = q.where(CorporateManagerRelationship.is_active.is_(is_active))
    # Sort: direct first, then dotted_line; within each type, newest last
    q = q.order_by(
        CorporateManagerRelationship.relationship_type,
        CorporateManagerRelationship.created_at,
    )
    result = await db.execute(q)
    return [_to_response(r) for r in result.scalars().all()]


async def get_direct_reports(
    db: AsyncSession,
    account_id: int,
    manager_member_id: int,
    *,
    relationship_type: Optional[RelationshipType] = RelationshipType.direct,
    is_active: Optional[bool] = True,
) -> list[ManagerRelationshipResponse]:
    """Return relationships where the given member is listed as manager.

    Args:
        account_id:         Corporate account to scope.
        manager_member_id:  The manager member.
        relationship_type:  Default "direct" only.  Pass None for all types.
        is_active:          Default True.  Pass None for all.
    """
    q = select(CorporateManagerRelationship).where(
        CorporateManagerRelationship.account_id == account_id,
        CorporateManagerRelationship.manager_member_id == manager_member_id,
    )
    if relationship_type is not None:
        q = q.where(
            CorporateManagerRelationship.relationship_type == relationship_type.value
        )
    if is_active is not None:
        q = q.where(CorporateManagerRelationship.is_active.is_(is_active))
    q = q.order_by(CorporateManagerRelationship.created_at)
    result = await db.execute(q)
    return [_to_response(r) for r in result.scalars().all()]


async def get_all_reports(
    db: AsyncSession,
    account_id: int,
    manager_member_id: int,
    *,
    is_active: Optional[bool] = True,
) -> list[ManagerRelationshipResponse]:
    """Return all relationships (direct + dotted-line) where member is manager."""
    return await get_direct_reports(
        db,
        account_id,
        manager_member_id,
        relationship_type=None,
        is_active=is_active,
    )


async def get_reporting_chain(
    db: AsyncSession,
    account_id: int,
    employee_member_id: int,
    *,
    max_depth: int = 10,
) -> ReportingChainResponse:
    """Walk the direct-manager chain from the employee upward to the root.

    Only follows ``direct`` relationships.  Stops when a member has no
    direct manager or when ``max_depth`` steps have been taken (safety valve
    against unexpected cycles in the data).

    Returns:
        ReportingChainResponse with an ordered list of managers from
        closest (depth=0) to root.  Empty chain if no direct manager is set.
    """
    chain: list[ReportingChainEntry] = []
    current = employee_member_id
    for depth in range(max_depth):
        result = await db.execute(
            select(CorporateManagerRelationship).where(
                CorporateManagerRelationship.account_id == account_id,
                CorporateManagerRelationship.employee_member_id == current,
                CorporateManagerRelationship.relationship_type == RelationshipType.direct,
                CorporateManagerRelationship.is_active.is_(True),
            )
        )
        row = result.scalar_one_or_none()
        if row is None:
            break
        chain.append(
            ReportingChainEntry(
                member_id=row.manager_member_id,
                relationship_type=RelationshipType.direct,
                depth=depth,
            )
        )
        current = row.manager_member_id

    return ReportingChainResponse(
        employee_member_id=employee_member_id,
        chain=chain,
    )


async def get_org_summary(
    db: AsyncSession,
    account_id: int,
) -> OrgSummaryResponse:
    """Return account-level org chart statistics.

    Queries are intentionally simple (in-Python set operations over a
    reasonable number of rows) to avoid complex SQL while keeping accuracy.

    Returns:
        OrgSummaryResponse with counts and list of top-level manager IDs.
    """
    result = await db.execute(
        select(CorporateManagerRelationship).where(
            CorporateManagerRelationship.account_id == account_id,
            CorporateManagerRelationship.is_active.is_(True),
        )
    )
    rows = list(result.scalars().all())

    total = len(rows)
    direct_rows = [r for r in rows if r.relationship_type == RelationshipType.direct]
    dotted_rows = [r for r in rows if r.relationship_type == RelationshipType.dotted_line]

    employees_with_direct = {r.employee_member_id for r in direct_rows}
    all_managers = {r.manager_member_id for r in rows}
    # Top-level = managers who are not themselves subordinates in a direct link
    top_level = all_managers - {r.employee_member_id for r in direct_rows}

    return OrgSummaryResponse(
        account_id=account_id,
        total_active_relationships=total,
        direct_relationships=len(direct_rows),
        dotted_line_relationships=len(dotted_rows),
        members_with_direct_manager=len(employees_with_direct),
        members_who_are_managers=len(all_managers),
        top_level_managers=sorted(top_level),
    )


async def list_all_relationships_platform(
    db: AsyncSession,
    *,
    skip: int = 0,
    limit: int = 100,
) -> list[ManagerRelationshipResponse]:
    """Platform-admin: list all manager relationships across all accounts.

    Ordered newest-first.
    """
    result = await db.execute(
        select(CorporateManagerRelationship)
        .order_by(CorporateManagerRelationship.created_at.desc())
        .offset(skip)
        .limit(limit)
    )
    return [_to_response(r) for r in result.scalars().all()]
