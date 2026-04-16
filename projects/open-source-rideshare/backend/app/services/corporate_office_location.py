"""Service layer for Corporate Office Locations & Memberships.

Enterprise accounts define named office locations and assign employees to
them.  At most one location per account may be the headquarters.  Each
member may have at most one primary office per account.

Public surface
--------------
create_office(db, account_id, data, created_by_id) -> OfficeLocationResponse
get_office(db, office_id, account_id) -> OfficeLocationResponse
list_offices(db, account_id, is_active, is_headquarters) -> OfficeLocationListResponse
update_office(db, office_id, account_id, data) -> OfficeLocationResponse
deactivate_office(db, office_id, account_id) -> OfficeLocationResponse
reactivate_office(db, office_id, account_id) -> OfficeLocationResponse
delete_office(db, office_id, account_id) -> None
assign_member(db, office_id, account_id, member_id, is_primary,
              assigned_by_id, notes) -> OfficeMembershipResponse
remove_member(db, office_id, account_id, member_id) -> None
list_office_members(db, office_id, account_id, is_active) -> OfficeMembershipListResponse
get_member_offices(db, member_id, account_id, is_primary) -> OfficeMembershipListResponse
get_office_summary(db, office_id, account_id) -> OfficeSummaryResponse
list_all_platform(db, account_id) -> OfficeLocationListResponse
"""

from __future__ import annotations

import uuid
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.corporate_office_location import (
    CorporateOfficeLocation,
    CorporateOfficeMembership,
)
from app.schemas.corporate_office_location import (
    AssignMemberRequest,
    OfficeLocationCreate,
    OfficeLocationListResponse,
    OfficeLocationResponse,
    OfficeLocationUpdate,
    OfficeMembershipListResponse,
    OfficeMembershipResponse,
    OfficeSummaryResponse,
)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _office_to_response(office: CorporateOfficeLocation) -> OfficeLocationResponse:
    """Convert a CorporateOfficeLocation ORM instance to a response schema."""
    return OfficeLocationResponse(
        id=office.id,
        account_id=office.account_id,
        name=office.name,
        description=office.description,
        address_line1=office.address_line1,
        address_line2=office.address_line2,
        city=office.city,
        state=office.state,
        postal_code=office.postal_code,
        country=office.country,
        latitude=float(office.latitude) if office.latitude is not None else None,
        longitude=float(office.longitude) if office.longitude is not None else None,
        default_cost_center_id=office.default_cost_center_id,
        is_headquarters=office.is_headquarters,
        is_active=office.is_active,
        created_by_id=office.created_by_id,
        created_at=office.created_at,
        updated_at=office.updated_at,
    )


def _membership_to_response(
    membership: CorporateOfficeMembership,
) -> OfficeMembershipResponse:
    """Convert a CorporateOfficeMembership ORM instance to a response schema."""
    return OfficeMembershipResponse(
        id=membership.id,
        office_id=membership.office_id,
        member_id=membership.member_id,
        account_id=membership.account_id,
        is_primary=membership.is_primary,
        assigned_by_id=membership.assigned_by_id,
        notes=membership.notes,
        is_active=membership.is_active,
        created_at=membership.created_at,
    )


async def _get_office_row(
    db: AsyncSession,
    office_id: uuid.UUID,
    account_id: int,
) -> CorporateOfficeLocation | None:
    """Return the office for this (account, id) pair or None."""
    result = await db.execute(
        select(CorporateOfficeLocation).where(
            CorporateOfficeLocation.id == office_id,
            CorporateOfficeLocation.account_id == account_id,
        )
    )
    return result.scalar_one_or_none()


async def _get_office_or_404(
    db: AsyncSession,
    office_id: uuid.UUID,
    account_id: int,
) -> CorporateOfficeLocation:
    """Return the office or raise HTTP 404."""
    office = await _get_office_row(db, office_id, account_id)
    if office is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Office location not found.",
        )
    return office


async def _get_membership_row(
    db: AsyncSession,
    office_id: uuid.UUID,
    member_id: int,
) -> CorporateOfficeMembership | None:
    """Return the membership for this (office, member) pair or None."""
    result = await db.execute(
        select(CorporateOfficeMembership).where(
            CorporateOfficeMembership.office_id == office_id,
            CorporateOfficeMembership.member_id == member_id,
        )
    )
    return result.scalar_one_or_none()


async def _clear_hq_flag(db: AsyncSession, account_id: int) -> None:
    """Clear is_headquarters on any currently flagged HQ office for the account."""
    result = await db.execute(
        select(CorporateOfficeLocation).where(
            CorporateOfficeLocation.account_id == account_id,
            CorporateOfficeLocation.is_headquarters == True,  # noqa: E712
        )
    )
    current_hq = result.scalar_one_or_none()
    if current_hq is not None:
        current_hq.is_headquarters = False


async def _clear_primary_membership(
    db: AsyncSession, member_id: int, account_id: int
) -> None:
    """Clear is_primary on the current primary membership for a member in an account."""
    result = await db.execute(
        select(CorporateOfficeMembership).where(
            CorporateOfficeMembership.member_id == member_id,
            CorporateOfficeMembership.account_id == account_id,
            CorporateOfficeMembership.is_primary == True,  # noqa: E712
        )
    )
    current_primary = result.scalar_one_or_none()
    if current_primary is not None:
        current_primary.is_primary = False


# ---------------------------------------------------------------------------
# Public service functions — offices
# ---------------------------------------------------------------------------


async def create_office(
    db: AsyncSession,
    account_id: int,
    data: OfficeLocationCreate,
    created_by_id: Optional[int] = None,
) -> OfficeLocationResponse:
    """Create a new office location for the account.

    Raises HTTP 409 if an office with the same name already exists in the
    account.  If ``is_headquarters=True``, clears the existing HQ flag first.
    """
    # Check for duplicate name within the account.
    existing = await db.execute(
        select(CorporateOfficeLocation).where(
            CorporateOfficeLocation.account_id == account_id,
            CorporateOfficeLocation.name == data.name,
        )
    )
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An office with this name already exists for the account.",
        )

    if data.is_headquarters:
        await _clear_hq_flag(db, account_id)

    office = CorporateOfficeLocation(
        account_id=account_id,
        name=data.name,
        description=data.description,
        address_line1=data.address_line1,
        address_line2=data.address_line2,
        city=data.city,
        state=data.state,
        postal_code=data.postal_code,
        country=data.country,
        latitude=data.latitude,
        longitude=data.longitude,
        default_cost_center_id=data.default_cost_center_id,
        is_headquarters=data.is_headquarters,
        is_active=True,
        created_by_id=created_by_id,
    )
    db.add(office)
    await db.commit()
    await db.refresh(office)
    return _office_to_response(office)


async def get_office(
    db: AsyncSession,
    office_id: uuid.UUID,
    account_id: int,
) -> OfficeLocationResponse:
    """Return a specific office by ID.

    Raises HTTP 404 if not found or belongs to a different account.
    """
    office = await _get_office_or_404(db, office_id, account_id)
    return _office_to_response(office)


async def list_offices(
    db: AsyncSession,
    account_id: int,
    is_active: Optional[bool] = None,
    is_headquarters: Optional[bool] = None,
) -> OfficeLocationListResponse:
    """List all office locations for the account, sorted by name.

    Optional filters:
      - ``is_active``: True → active only; False → inactive only.
      - ``is_headquarters``: True → HQ only; False → non-HQ only.
    """
    stmt = select(CorporateOfficeLocation).where(
        CorporateOfficeLocation.account_id == account_id
    )
    if is_active is not None:
        stmt = stmt.where(CorporateOfficeLocation.is_active == is_active)
    if is_headquarters is not None:
        stmt = stmt.where(
            CorporateOfficeLocation.is_headquarters == is_headquarters
        )
    stmt = stmt.order_by(CorporateOfficeLocation.name)

    result = await db.execute(stmt)
    offices = result.scalars().all()
    return OfficeLocationListResponse(
        items=[_office_to_response(o) for o in offices],
        total=len(offices),
    )


async def update_office(
    db: AsyncSession,
    office_id: uuid.UUID,
    account_id: int,
    data: OfficeLocationUpdate,
) -> OfficeLocationResponse:
    """Partially update an office location.

    Raises HTTP 404 if not found.
    Raises HTTP 409 on name collision with another office in the same account.
    If ``is_headquarters=True``, clears the existing HQ flag for the account.
    """
    office = await _get_office_or_404(db, office_id, account_id)

    update_data = data.model_dump(exclude_unset=True)

    if "name" in update_data and update_data["name"] != office.name:
        collision = await db.execute(
            select(CorporateOfficeLocation).where(
                CorporateOfficeLocation.account_id == account_id,
                CorporateOfficeLocation.name == update_data["name"],
                CorporateOfficeLocation.id != office_id,
            )
        )
        if collision.scalar_one_or_none() is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="An office with this name already exists for the account.",
            )

    if update_data.get("is_headquarters") is True and not office.is_headquarters:
        await _clear_hq_flag(db, account_id)

    for field, value in update_data.items():
        setattr(office, field, value)

    await db.commit()
    await db.refresh(office)
    return _office_to_response(office)


async def deactivate_office(
    db: AsyncSession,
    office_id: uuid.UUID,
    account_id: int,
) -> OfficeLocationResponse:
    """Deactivate an active office location.

    Raises HTTP 404 if not found.
    Raises HTTP 409 if already inactive.
    """
    office = await _get_office_or_404(db, office_id, account_id)
    if not office.is_active:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Office is already inactive.",
        )
    office.is_active = False
    await db.commit()
    await db.refresh(office)
    return _office_to_response(office)


async def reactivate_office(
    db: AsyncSession,
    office_id: uuid.UUID,
    account_id: int,
) -> OfficeLocationResponse:
    """Reactivate an inactive office location.

    Raises HTTP 404 if not found.
    Raises HTTP 409 if already active.
    """
    office = await _get_office_or_404(db, office_id, account_id)
    if office.is_active:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Office is already active.",
        )
    office.is_active = True
    await db.commit()
    await db.refresh(office)
    return _office_to_response(office)


async def delete_office(
    db: AsyncSession,
    office_id: uuid.UUID,
    account_id: int,
) -> None:
    """Hard-delete an office location.

    Raises HTTP 404 if not found.
    Raises HTTP 409 if the office is still active — deactivate it first.
    """
    office = await _get_office_or_404(db, office_id, account_id)
    if office.is_active:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot delete an active office. Deactivate it first.",
        )
    await db.delete(office)
    await db.commit()


# ---------------------------------------------------------------------------
# Public service functions — memberships
# ---------------------------------------------------------------------------


async def assign_member(
    db: AsyncSession,
    office_id: uuid.UUID,
    account_id: int,
    member_id: int,
    is_primary: bool = False,
    assigned_by_id: Optional[int] = None,
    notes: Optional[str] = None,
) -> OfficeMembershipResponse:
    """Assign an account member to an office location.

    Raises HTTP 404 if the office is not found.
    Raises HTTP 409 if the member is already assigned to this office.
    If ``is_primary=True``, clears the member's existing primary office first.
    """
    # Ensure the office exists for this account.
    await _get_office_or_404(db, office_id, account_id)

    # Check for duplicate assignment.
    if await _get_membership_row(db, office_id, member_id) is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Member is already assigned to this office.",
        )

    if is_primary:
        await _clear_primary_membership(db, member_id, account_id)

    membership = CorporateOfficeMembership(
        office_id=office_id,
        member_id=member_id,
        account_id=account_id,
        is_primary=is_primary,
        assigned_by_id=assigned_by_id,
        notes=notes,
        is_active=True,
    )
    db.add(membership)
    await db.commit()
    await db.refresh(membership)
    return _membership_to_response(membership)


async def remove_member(
    db: AsyncSession,
    office_id: uuid.UUID,
    account_id: int,
    member_id: int,
) -> None:
    """Remove a member's assignment from an office location.

    Raises HTTP 404 if the office or assignment is not found.
    """
    await _get_office_or_404(db, office_id, account_id)
    membership = await _get_membership_row(db, office_id, member_id)
    if membership is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Member is not assigned to this office.",
        )
    await db.delete(membership)
    await db.commit()


async def list_office_members(
    db: AsyncSession,
    office_id: uuid.UUID,
    account_id: int,
    is_active: Optional[bool] = None,
) -> OfficeMembershipListResponse:
    """Return all memberships for an office location.

    Raises HTTP 404 if the office is not found.
    """
    await _get_office_or_404(db, office_id, account_id)

    stmt = select(CorporateOfficeMembership).where(
        CorporateOfficeMembership.office_id == office_id
    )
    if is_active is not None:
        stmt = stmt.where(CorporateOfficeMembership.is_active == is_active)
    stmt = stmt.order_by(CorporateOfficeMembership.created_at)

    result = await db.execute(stmt)
    memberships = result.scalars().all()
    return OfficeMembershipListResponse(
        items=[_membership_to_response(m) for m in memberships],
        total=len(memberships),
    )


async def get_member_offices(
    db: AsyncSession,
    member_id: int,
    account_id: int,
    is_primary: Optional[bool] = None,
) -> OfficeMembershipListResponse:
    """Return all office memberships for a member within an account.

    Optional filter:
      - ``is_primary``: True → return only the primary office membership.
    """
    stmt = select(CorporateOfficeMembership).where(
        CorporateOfficeMembership.member_id == member_id,
        CorporateOfficeMembership.account_id == account_id,
    )
    if is_primary is not None:
        stmt = stmt.where(CorporateOfficeMembership.is_primary == is_primary)
    stmt = stmt.order_by(CorporateOfficeMembership.created_at)

    result = await db.execute(stmt)
    memberships = result.scalars().all()
    return OfficeMembershipListResponse(
        items=[_membership_to_response(m) for m in memberships],
        total=len(memberships),
    )


async def get_office_summary(
    db: AsyncSession,
    office_id: uuid.UUID,
    account_id: int,
) -> OfficeSummaryResponse:
    """Return office details with total and active member counts.

    Raises HTTP 404 if the office is not found.
    """
    office = await _get_office_or_404(db, office_id, account_id)

    total_result = await db.execute(
        select(func.count(CorporateOfficeMembership.id)).where(
            CorporateOfficeMembership.office_id == office_id
        )
    )
    total_members = total_result.scalar() or 0

    active_result = await db.execute(
        select(func.count(CorporateOfficeMembership.id)).where(
            CorporateOfficeMembership.office_id == office_id,
            CorporateOfficeMembership.is_active == True,  # noqa: E712
        )
    )
    active_members = active_result.scalar() or 0

    return OfficeSummaryResponse(
        office=_office_to_response(office),
        total_members=total_members,
        active_members=active_members,
    )


async def list_all_platform(
    db: AsyncSession,
    account_id: Optional[int] = None,
) -> OfficeLocationListResponse:
    """Platform-admin: list all office locations, optionally filtered by account."""
    stmt = select(CorporateOfficeLocation)
    if account_id is not None:
        stmt = stmt.where(CorporateOfficeLocation.account_id == account_id)
    stmt = stmt.order_by(
        CorporateOfficeLocation.account_id,
        CorporateOfficeLocation.name,
    )
    result = await db.execute(stmt)
    offices = result.scalars().all()
    return OfficeLocationListResponse(
        items=[_office_to_response(o) for o in offices],
        total=len(offices),
    )
