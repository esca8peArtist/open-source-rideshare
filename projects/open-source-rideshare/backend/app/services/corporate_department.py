"""Service layer for Corporate Department Management.

Corporate admins can organise account members into named departments.
Each department may carry an optional monthly budget and link to a cost center.
Spend analytics aggregate ride charges for all members in the department.

Public surface
--------------
create_department(db, account_id, user_id, data)
get_department(db, account_id, department_id)
list_departments(db, account_id, active_only=True, skip=0, limit=50)
update_department(db, account_id, department_id, user_id, data)
deactivate_department(db, account_id, department_id, user_id)
add_department_member(db, account_id, department_id, user_id, target_user_id, is_head)
remove_department_member(db, account_id, department_id, user_id, target_user_id)
list_department_members(db, account_id, department_id)
get_department_spend(db, account_id, department_id)
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Sequence

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.corporate import BusinessAccountMember, MemberRole
from app.models.corporate_cost_center import CorporateCostCenter
from app.models.corporate_department import CorporateDepartment, CorporateDepartmentMember
from app.models.ride import Ride
from app.schemas.corporate_department import (
    AddMemberRequest,
    DepartmentCreate,
    DepartmentListResponse,
    DepartmentMemberResponse,
    DepartmentMembersResponse,
    DepartmentMemberSpend,
    DepartmentResponse,
    DepartmentSpendResponse,
    DepartmentUpdate,
)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _month_str(dt: datetime) -> str:
    return dt.strftime("%Y-%m")


def _utilization_pct(spend: Decimal, budget: Decimal | None) -> float | None:
    if budget is None or budget == 0:
        return None
    return float(
        (spend / budget * 100).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    )


async def _require_admin(
    db: AsyncSession,
    account_id: int,
    user_id: int,
) -> BusinessAccountMember:
    """Return the member row or raise HTTP 403 if not an account admin."""
    result = await db.execute(
        select(BusinessAccountMember).where(
            BusinessAccountMember.account_id == account_id,
            BusinessAccountMember.user_id == user_id,
            BusinessAccountMember.role == MemberRole.ADMIN,
            BusinessAccountMember.is_active.is_(True),
        )
    )
    member = result.scalar_one_or_none()
    if member is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have admin access to this corporate account.",
        )
    return member


async def _require_active_member(
    db: AsyncSession,
    account_id: int,
    user_id: int,
) -> BusinessAccountMember:
    """Return the member row or raise HTTP 403 if not an active member."""
    result = await db.execute(
        select(BusinessAccountMember).where(
            BusinessAccountMember.account_id == account_id,
            BusinessAccountMember.user_id == user_id,
            BusinessAccountMember.is_active.is_(True),
        )
    )
    member = result.scalar_one_or_none()
    if member is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not an active member of this corporate account.",
        )
    return member


async def _get_dept(
    db: AsyncSession,
    account_id: int,
    department_id: int,
) -> CorporateDepartment:
    """Return the department or raise HTTP 404 if not found in this account."""
    result = await db.execute(
        select(CorporateDepartment).where(
            CorporateDepartment.id == department_id,
            CorporateDepartment.account_id == account_id,
        )
    )
    dept = result.scalar_one_or_none()
    if dept is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Department not found in this account.",
        )
    return dept


async def _member_count(db: AsyncSession, department_id: int) -> int:
    """Return the number of members in a department."""
    result = await db.execute(
        select(func.count(CorporateDepartmentMember.id)).where(
            CorporateDepartmentMember.department_id == department_id,
        )
    )
    return result.scalar_one() or 0


def _dept_to_response(dept: CorporateDepartment, member_count: int) -> DepartmentResponse:
    now = _now_utc()
    return DepartmentResponse(
        id=dept.id,
        account_id=dept.account_id,
        name=dept.name,
        code=dept.code,
        description=dept.description,
        cost_center_id=dept.cost_center_id,
        monthly_budget=dept.monthly_budget,
        is_active=dept.is_active,
        created_by_id=dept.created_by_id,
        member_count=member_count,
        created_at=dept.created_at or now,
        updated_at=dept.updated_at or now,
    )


# ---------------------------------------------------------------------------
# Department CRUD
# ---------------------------------------------------------------------------


async def create_department(
    db: AsyncSession,
    account_id: int,
    user_id: int,
    data: DepartmentCreate,
) -> DepartmentResponse:
    """Create a new department for the account.

    Args:
        db: Database session.
        account_id: Corporate account identifier.
        user_id: ID of the requesting admin.
        data: Department creation payload.

    Returns:
        DepartmentResponse for the newly created department.

    Raises:
        HTTP 403: When the user is not an account admin.
        HTTP 404: When cost_center_id is provided but not found in this account.
        HTTP 409: When a department with the same code already exists.
    """
    await _require_admin(db, account_id, user_id)

    # Validate cost_center_id belongs to this account
    if data.cost_center_id is not None:
        cc_result = await db.execute(
            select(CorporateCostCenter).where(
                CorporateCostCenter.id == data.cost_center_id,
                CorporateCostCenter.account_id == account_id,
                CorporateCostCenter.is_active.is_(True),
            )
        )
        if cc_result.scalar_one_or_none() is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Cost center not found or inactive in this account.",
            )

    # Duplicate code check
    existing = await db.execute(
        select(CorporateDepartment).where(
            CorporateDepartment.account_id == account_id,
            CorporateDepartment.code == data.code.upper(),
        )
    )
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A department with code '{data.code.upper()}' already exists in this account.",
        )

    dept = CorporateDepartment(
        account_id=account_id,
        name=data.name,
        code=data.code.upper(),
        description=data.description,
        cost_center_id=data.cost_center_id,
        monthly_budget=data.monthly_budget,
        created_by_id=user_id,
        is_active=True,
    )
    db.add(dept)
    await db.flush()

    return _dept_to_response(dept, 0)


async def get_department(
    db: AsyncSession,
    account_id: int,
    department_id: int,
) -> DepartmentResponse:
    """Return a single department.

    Args:
        db: Database session.
        account_id: Corporate account identifier.
        department_id: Department identifier.

    Returns:
        DepartmentResponse.

    Raises:
        HTTP 404: When the department is not found in this account.
    """
    dept = await _get_dept(db, account_id, department_id)
    count = await _member_count(db, dept.id)
    return _dept_to_response(dept, count)


async def list_departments(
    db: AsyncSession,
    account_id: int,
    active_only: bool = True,
    skip: int = 0,
    limit: int = 50,
) -> DepartmentListResponse:
    """Return a paginated list of departments for the account.

    Args:
        db: Database session.
        account_id: Corporate account identifier.
        active_only: When True, only return is_active=True departments.
        skip: Pagination offset.
        limit: Maximum rows to return (1–200).

    Returns:
        DepartmentListResponse with total count and page of results.
    """
    q = select(CorporateDepartment).where(
        CorporateDepartment.account_id == account_id
    )
    if active_only:
        q = q.where(CorporateDepartment.is_active.is_(True))

    total_result = await db.execute(
        select(func.count()).select_from(q.subquery())
    )
    total = total_result.scalar_one() or 0

    page_result = await db.execute(
        q.order_by(CorporateDepartment.name).offset(skip).limit(limit)
    )
    depts: Sequence[CorporateDepartment] = page_result.scalars().all()

    # Bulk fetch member counts
    dept_ids = [d.id for d in depts]
    count_map: dict[int, int] = {}
    if dept_ids:
        count_result = await db.execute(
            select(
                CorporateDepartmentMember.department_id,
                func.count(CorporateDepartmentMember.id).label("cnt"),
            )
            .where(CorporateDepartmentMember.department_id.in_(dept_ids))
            .group_by(CorporateDepartmentMember.department_id)
        )
        for row in count_result.all():
            count_map[row.department_id] = row.cnt or 0

    return DepartmentListResponse(
        account_id=account_id,
        total=total,
        departments=[_dept_to_response(d, count_map.get(d.id, 0)) for d in depts],
    )


async def update_department(
    db: AsyncSession,
    account_id: int,
    department_id: int,
    user_id: int,
    data: DepartmentUpdate,
) -> DepartmentResponse:
    """Update a department's metadata (admin only).

    Args:
        db: Database session.
        account_id: Corporate account identifier.
        department_id: Department to update.
        user_id: ID of the requesting admin.
        data: Fields to update (all optional).

    Returns:
        Updated DepartmentResponse.

    Raises:
        HTTP 403: When the user is not an account admin.
        HTTP 404: When the department or cost center is not found.
        HTTP 409: When the new code conflicts with an existing department.
    """
    await _require_admin(db, account_id, user_id)
    dept = await _get_dept(db, account_id, department_id)

    if data.cost_center_id is not None:
        cc_result = await db.execute(
            select(CorporateCostCenter).where(
                CorporateCostCenter.id == data.cost_center_id,
                CorporateCostCenter.account_id == account_id,
                CorporateCostCenter.is_active.is_(True),
            )
        )
        if cc_result.scalar_one_or_none() is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Cost center not found or inactive in this account.",
            )

    if data.code is not None and data.code.upper() != dept.code:
        dup = await db.execute(
            select(CorporateDepartment).where(
                CorporateDepartment.account_id == account_id,
                CorporateDepartment.code == data.code.upper(),
                CorporateDepartment.id != department_id,
            )
        )
        if dup.scalar_one_or_none() is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"A department with code '{data.code.upper()}' already exists.",
            )
        dept.code = data.code.upper()

    if data.name is not None:
        dept.name = data.name
    if data.description is not None:
        dept.description = data.description
    if data.cost_center_id is not None:
        dept.cost_center_id = data.cost_center_id
    if data.monthly_budget is not None:
        dept.monthly_budget = data.monthly_budget

    await db.flush()
    count = await _member_count(db, dept.id)
    return _dept_to_response(dept, count)


async def deactivate_department(
    db: AsyncSession,
    account_id: int,
    department_id: int,
    user_id: int,
) -> DepartmentResponse:
    """Soft-delete a department (admin only).

    Members are not removed — the membership records remain for history.

    Args:
        db: Database session.
        account_id: Corporate account identifier.
        department_id: Department to deactivate.
        user_id: ID of the requesting admin.

    Returns:
        Updated DepartmentResponse with is_active=False.

    Raises:
        HTTP 403: When the user is not an account admin.
        HTTP 404: When the department is not found.
        HTTP 409: When the department is already inactive.
    """
    await _require_admin(db, account_id, user_id)
    dept = await _get_dept(db, account_id, department_id)

    if not dept.is_active:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Department is already inactive.",
        )

    dept.is_active = False
    await db.flush()
    count = await _member_count(db, dept.id)
    return _dept_to_response(dept, count)


# ---------------------------------------------------------------------------
# Department member management
# ---------------------------------------------------------------------------


async def add_department_member(
    db: AsyncSession,
    account_id: int,
    department_id: int,
    user_id: int,
    data: AddMemberRequest,
) -> DepartmentMemberResponse:
    """Add an account member to a department (admin only).

    The target user must already be an active member of the corporate account.

    Args:
        db: Database session.
        account_id: Corporate account identifier.
        department_id: Department to add the member to.
        user_id: ID of the requesting admin.
        data: AddMemberRequest with target user_id and head flag.

    Returns:
        DepartmentMemberResponse for the new membership.

    Raises:
        HTTP 403: When the requester is not an account admin.
        HTTP 404: When the department or target member is not found.
        HTTP 409: When the target user is already in the department.
    """
    await _require_admin(db, account_id, user_id)
    dept = await _get_dept(db, account_id, department_id)

    if not dept.is_active:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot add members to an inactive department.",
        )

    # Target must be an active account member
    target_result = await db.execute(
        select(BusinessAccountMember).where(
            BusinessAccountMember.account_id == account_id,
            BusinessAccountMember.user_id == data.user_id,
            BusinessAccountMember.is_active.is_(True),
        )
    )
    if target_result.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Target user is not an active member of this corporate account.",
        )

    # Duplicate check
    dup = await db.execute(
        select(CorporateDepartmentMember).where(
            CorporateDepartmentMember.department_id == department_id,
            CorporateDepartmentMember.user_id == data.user_id,
        )
    )
    if dup.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="User is already a member of this department.",
        )

    dm = CorporateDepartmentMember(
        department_id=department_id,
        user_id=data.user_id,
        is_department_head=data.is_department_head,
        added_by_id=user_id,
    )
    db.add(dm)
    await db.flush()

    return DepartmentMemberResponse(
        department_id=dm.department_id,
        user_id=dm.user_id,
        is_department_head=dm.is_department_head,
        added_by_id=dm.added_by_id,
        added_at=dm.added_at or _now_utc(),
    )


async def remove_department_member(
    db: AsyncSession,
    account_id: int,
    department_id: int,
    user_id: int,
    target_user_id: int,
) -> dict:
    """Remove a user from a department (admin only).

    Args:
        db: Database session.
        account_id: Corporate account identifier.
        department_id: Department from which to remove the member.
        user_id: ID of the requesting admin.
        target_user_id: ID of the user to remove.

    Returns:
        Dict with 'removed': True and 'user_id'.

    Raises:
        HTTP 403: When the requester is not an account admin.
        HTTP 404: When the department or membership is not found.
    """
    await _require_admin(db, account_id, user_id)
    await _get_dept(db, account_id, department_id)

    result = await db.execute(
        select(CorporateDepartmentMember).where(
            CorporateDepartmentMember.department_id == department_id,
            CorporateDepartmentMember.user_id == target_user_id,
        )
    )
    dm = result.scalar_one_or_none()
    if dm is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User is not a member of this department.",
        )

    await db.delete(dm)
    await db.flush()
    return {"removed": True, "user_id": target_user_id}


async def list_department_members(
    db: AsyncSession,
    account_id: int,
    department_id: int,
) -> DepartmentMembersResponse:
    """Return all members of a department.

    Any active account member may call this.

    Args:
        db: Database session.
        account_id: Corporate account identifier.
        department_id: Department identifier.

    Returns:
        DepartmentMembersResponse with a list of members.

    Raises:
        HTTP 404: When the department is not found in this account.
    """
    dept = await _get_dept(db, account_id, department_id)

    result = await db.execute(
        select(CorporateDepartmentMember)
        .where(CorporateDepartmentMember.department_id == department_id)
        .order_by(
            CorporateDepartmentMember.is_department_head.desc(),
            CorporateDepartmentMember.added_at,
        )
    )
    members: Sequence[CorporateDepartmentMember] = result.scalars().all()

    return DepartmentMembersResponse(
        department_id=department_id,
        account_id=account_id,
        total=len(members),
        members=[
            DepartmentMemberResponse(
                department_id=dm.department_id,
                user_id=dm.user_id,
                is_department_head=dm.is_department_head,
                added_by_id=dm.added_by_id,
                added_at=dm.added_at,
            )
            for dm in members
        ],
    )


# ---------------------------------------------------------------------------
# Department spend analytics
# ---------------------------------------------------------------------------


async def get_department_spend(
    db: AsyncSession,
    account_id: int,
    department_id: int,
) -> DepartmentSpendResponse:
    """Return current-month spend analytics for a department.

    Aggregates completed rides for all members of the department.

    Args:
        db: Database session.
        account_id: Corporate account identifier.
        department_id: Department identifier.

    Returns:
        DepartmentSpendResponse with per-member breakdown.

    Raises:
        HTTP 404: When the department is not found in this account.
    """
    dept = await _get_dept(db, account_id, department_id)

    now = _now_utc()
    month_start = date(now.year, now.month, 1)
    month = _month_str(now)

    # Fetch department members
    members_result = await db.execute(
        select(CorporateDepartmentMember).where(
            CorporateDepartmentMember.department_id == department_id
        )
    )
    members: Sequence[CorporateDepartmentMember] = members_result.scalars().all()
    user_ids = [m.user_id for m in members]

    member_spend: list[DepartmentMemberSpend] = []
    total_rides = 0
    total_spend = Decimal("0")

    if user_ids:
        spend_result = await db.execute(
            select(
                Ride.rider_id.label("user_id"),
                func.count(Ride.id).label("rides"),
                func.coalesce(func.sum(Ride.actual_fare), 0).label("spend"),
            )
            .where(
                Ride.corporate_account_id == account_id,
                Ride.rider_id.in_(user_ids),
                Ride.actual_fare.is_not(None),
                Ride.completed_at.is_not(None),
                func.date(Ride.completed_at) >= month_start,
            )
            .group_by(Ride.rider_id)
        )
        spend_map: dict[int, tuple[int, Decimal]] = {}
        for row in spend_result.all():
            spend_map[row.user_id] = (row.rides or 0, Decimal(str(row.spend or 0)))

        # Build per-member list preserving head ordering
        head_map = {m.user_id: m.is_department_head for m in members}
        for uid in user_ids:
            rides, spend = spend_map.get(uid, (0, Decimal("0")))
            total_rides += rides
            total_spend += spend
            member_spend.append(
                DepartmentMemberSpend(
                    user_id=uid,
                    is_department_head=head_map.get(uid, False),
                    current_month_rides=rides,
                    current_month_spend=spend,
                )
            )

    return DepartmentSpendResponse(
        department_id=department_id,
        account_id=account_id,
        department_name=dept.name,
        current_month=month,
        total_rides=total_rides,
        total_spend=total_spend,
        monthly_budget=dept.monthly_budget,
        budget_utilization_pct=_utilization_pct(total_spend, dept.monthly_budget),
        member_count=len(members),
        members=member_spend,
    )
