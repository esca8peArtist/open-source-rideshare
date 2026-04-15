"""Service layer for Corporate Delegate Access.

Enterprise assistants (executive assistants, office managers) can be granted
the ability to book rides on behalf of other employees (principals/executives).
Admins manage delegations; delegates and principals can inspect their own records.

Public surface
--------------
grant_delegate_access(db, account_id, user_id, data)
revoke_delegate_access(db, account_id, delegation_id, user_id)
get_delegate(db, account_id, delegation_id)
list_my_principals(db, account_id, user_id, active_only, skip, limit)
list_my_delegates(db, account_id, user_id, active_only, skip, limit)
check_delegate_permission(db, account_id, delegate_user_id, principal_user_id, estimated_cost)
update_delegate_access(db, account_id, delegation_id, user_id, data)
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.corporate import BusinessAccountMember, MemberRole
from app.models.corporate_delegate import CorporateDelegate
from app.schemas.corporate_delegate import (
    DelegateCreate,
    DelegateListResponse,
    DelegatePermissionResult,
    DelegateResponse,
    DelegateUpdate,
)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _require_admin(
    db: AsyncSession,
    account_id: int,
    user_id: int,
) -> BusinessAccountMember:
    """Return the member row or raise HTTP 403 if the user is not an admin."""
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


async def _require_member(
    db: AsyncSession,
    account_id: int,
    user_id: int,
) -> BusinessAccountMember:
    """Return the member row or raise HTTP 403 if the user is not an active member."""
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


async def _get_delegation(
    db: AsyncSession,
    account_id: int,
    delegation_id: int,
) -> CorporateDelegate:
    """Return the delegation or raise HTTP 404 if not found in this account."""
    result = await db.execute(
        select(CorporateDelegate).where(
            CorporateDelegate.id == delegation_id,
            CorporateDelegate.account_id == account_id,
        )
    )
    delegation = result.scalar_one_or_none()
    if delegation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Delegation not found in this account.",
        )
    return delegation


def _delegation_to_response(d: CorporateDelegate) -> DelegateResponse:
    now = datetime.now(timezone.utc)
    return DelegateResponse(
        id=d.id,
        account_id=d.account_id,
        principal_id=d.principal_id,
        delegate_id=d.delegate_id,
        can_book_rides=d.can_book_rides,
        can_view_history=d.can_view_history,
        max_per_ride_usd=Decimal(str(d.max_per_ride_usd)) if d.max_per_ride_usd is not None else None,
        valid_until=d.valid_until,
        is_active=d.is_active,
        created_by_id=d.created_by_id,
        created_at=d.created_at or now,
        updated_at=d.updated_at or now,
    )


# ---------------------------------------------------------------------------
# Service functions
# ---------------------------------------------------------------------------


async def grant_delegate_access(
    db: AsyncSession,
    account_id: int,
    user_id: int,
    data: DelegateCreate,
) -> DelegateResponse:
    """Grant delegate access (admin only).

    Args:
        db: Database session.
        account_id: Corporate account identifier.
        user_id: ID of the requesting admin.
        data: DelegateCreate payload.

    Returns:
        DelegateResponse for the newly created delegation.

    Raises:
        HTTP 403: When the user is not an account admin.
        HTTP 409: When the same (account, principal, delegate) combination already exists.
    """
    await _require_admin(db, account_id, user_id)

    dup = await db.execute(
        select(CorporateDelegate).where(
            CorporateDelegate.account_id == account_id,
            CorporateDelegate.principal_id == data.principal_user_id,
            CorporateDelegate.delegate_id == data.delegate_user_id,
        )
    )
    if dup.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A delegation for this principal/delegate combination already exists in the account.",
        )

    delegation = CorporateDelegate(
        account_id=account_id,
        principal_id=data.principal_user_id,
        delegate_id=data.delegate_user_id,
        can_book_rides=data.can_book_rides,
        can_view_history=data.can_view_history,
        max_per_ride_usd=float(data.max_per_ride_usd) if data.max_per_ride_usd is not None else None,
        valid_until=data.valid_until,
        is_active=True,
        created_by_id=user_id,
    )
    db.add(delegation)
    await db.flush()

    return _delegation_to_response(delegation)


async def revoke_delegate_access(
    db: AsyncSession,
    account_id: int,
    delegation_id: int,
    user_id: int,
) -> DelegateResponse:
    """Revoke (soft-delete) a delegation (admin only).

    Args:
        db: Database session.
        account_id: Corporate account identifier.
        delegation_id: Delegation identifier.
        user_id: ID of the requesting admin.

    Raises:
        HTTP 403: When the user is not an account admin.
        HTTP 404: When the delegation is not found in this account.
        HTTP 409: When the delegation is already inactive.
    """
    await _require_admin(db, account_id, user_id)
    delegation = await _get_delegation(db, account_id, delegation_id)

    if not delegation.is_active:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Delegation is already inactive.",
        )

    delegation.is_active = False
    await db.flush()
    return _delegation_to_response(delegation)


async def get_delegate(
    db: AsyncSession,
    account_id: int,
    delegation_id: int,
) -> DelegateResponse:
    """Return a single delegation.

    Args:
        db: Database session.
        account_id: Corporate account identifier.
        delegation_id: Delegation identifier.

    Raises:
        HTTP 404: When the delegation is not found in this account.
    """
    delegation = await _get_delegation(db, account_id, delegation_id)
    return _delegation_to_response(delegation)


async def list_my_principals(
    db: AsyncSession,
    account_id: int,
    user_id: int,
    active_only: bool = True,
    skip: int = 0,
    limit: int = 50,
) -> DelegateListResponse:
    """Return delegations where I (user_id) am the delegate — who I can book for.

    Args:
        db: Database session.
        account_id: Corporate account identifier.
        user_id: The delegate's user ID.
        active_only: When True, only return active, non-expired delegations.
        skip: Pagination offset.
        limit: Maximum rows to return.
    """
    now = datetime.now(timezone.utc)
    q = select(CorporateDelegate).where(
        CorporateDelegate.account_id == account_id,
        CorporateDelegate.delegate_id == user_id,
    )
    if active_only:
        q = q.where(
            CorporateDelegate.is_active.is_(True),
            (CorporateDelegate.valid_until.is_(None) | (CorporateDelegate.valid_until > now)),
        )

    total_result = await db.execute(select(func.count()).select_from(q.subquery()))
    total = total_result.scalar_one() or 0

    page_result = await db.execute(q.offset(skip).limit(limit))
    delegations = page_result.scalars().all()

    return DelegateListResponse(
        account_id=account_id,
        total=total,
        delegates=[_delegation_to_response(d) for d in delegations],
    )


async def list_my_delegates(
    db: AsyncSession,
    account_id: int,
    user_id: int,
    active_only: bool = True,
    skip: int = 0,
    limit: int = 50,
) -> DelegateListResponse:
    """Return delegations where I (user_id) am the principal — who can book for me.

    Args:
        db: Database session.
        account_id: Corporate account identifier.
        user_id: The principal's user ID.
        active_only: When True, only return active, non-expired delegations.
        skip: Pagination offset.
        limit: Maximum rows to return.
    """
    now = datetime.now(timezone.utc)
    q = select(CorporateDelegate).where(
        CorporateDelegate.account_id == account_id,
        CorporateDelegate.principal_id == user_id,
    )
    if active_only:
        q = q.where(
            CorporateDelegate.is_active.is_(True),
            (CorporateDelegate.valid_until.is_(None) | (CorporateDelegate.valid_until > now)),
        )

    total_result = await db.execute(select(func.count()).select_from(q.subquery()))
    total = total_result.scalar_one() or 0

    page_result = await db.execute(q.offset(skip).limit(limit))
    delegations = page_result.scalars().all()

    return DelegateListResponse(
        account_id=account_id,
        total=total,
        delegates=[_delegation_to_response(d) for d in delegations],
    )


async def check_delegate_permission(
    db: AsyncSession,
    account_id: int,
    delegate_user_id: int,
    principal_user_id: int,
    estimated_cost: Optional[Decimal] = None,
) -> DelegatePermissionResult:
    """Check whether a delegate may book a ride for a principal.

    This function never raises HTTP errors — it always returns a
    DelegatePermissionResult with allowed=True or allowed=False and a reason.

    Args:
        db: Database session.
        account_id: Corporate account identifier.
        delegate_user_id: The delegate's user ID.
        principal_user_id: The principal's user ID.
        estimated_cost: Optional estimated ride cost in USD.

    Returns:
        DelegatePermissionResult indicating whether the booking is allowed.
    """
    now = datetime.now(timezone.utc)

    result = await db.execute(
        select(CorporateDelegate).where(
            CorporateDelegate.account_id == account_id,
            CorporateDelegate.delegate_id == delegate_user_id,
            CorporateDelegate.principal_id == principal_user_id,
            CorporateDelegate.is_active.is_(True),
        )
    )
    delegation = result.scalar_one_or_none()

    if delegation is None:
        return DelegatePermissionResult(allowed=False, reason="No active delegation found.")

    # Check expiry
    if delegation.valid_until is not None and delegation.valid_until <= now:
        return DelegatePermissionResult(allowed=False, reason="Delegation has expired.")

    if not delegation.can_book_rides:
        return DelegatePermissionResult(
            allowed=False, reason="Delegation does not permit booking rides."
        )

    if (
        delegation.max_per_ride_usd is not None
        and estimated_cost is not None
        and estimated_cost > Decimal(str(delegation.max_per_ride_usd))
    ):
        return DelegatePermissionResult(
            allowed=False,
            reason=(
                f"Estimated ride cost ${estimated_cost} exceeds the per-ride cap of "
                f"${delegation.max_per_ride_usd}."
            ),
        )

    return DelegatePermissionResult(allowed=True, reason="Delegation is valid.")


async def list_all_delegates(
    db: AsyncSession,
    account_id: int,
    active_only: bool = False,
    skip: int = 0,
    limit: int = 50,
) -> DelegateListResponse:
    """Return all delegations for a given account (platform-admin use).

    Args:
        db: Database session.
        account_id: Corporate account identifier.
        active_only: When True, only return active, non-expired delegations.
        skip: Pagination offset.
        limit: Maximum rows to return.
    """
    now = datetime.now(timezone.utc)
    q = select(CorporateDelegate).where(CorporateDelegate.account_id == account_id)
    if active_only:
        q = q.where(
            CorporateDelegate.is_active.is_(True),
            (CorporateDelegate.valid_until.is_(None) | (CorporateDelegate.valid_until > now)),
        )

    total_result = await db.execute(select(func.count()).select_from(q.subquery()))
    total = total_result.scalar_one() or 0

    page_result = await db.execute(q.offset(skip).limit(limit))
    delegations = page_result.scalars().all()

    return DelegateListResponse(
        account_id=account_id,
        total=total,
        delegates=[_delegation_to_response(d) for d in delegations],
    )


async def update_delegate_access(
    db: AsyncSession,
    account_id: int,
    delegation_id: int,
    user_id: int,
    data: DelegateUpdate,
) -> DelegateResponse:
    """Update a delegation (admin only).

    Args:
        db: Database session.
        account_id: Corporate account identifier.
        delegation_id: Delegation identifier.
        user_id: ID of the requesting admin.
        data: DelegateUpdate payload.

    Raises:
        HTTP 403: When the user is not an account admin.
        HTTP 404: When the delegation is not found in this account.
    """
    await _require_admin(db, account_id, user_id)
    delegation = await _get_delegation(db, account_id, delegation_id)

    if data.can_book_rides is not None:
        delegation.can_book_rides = data.can_book_rides
    if data.can_view_history is not None:
        delegation.can_view_history = data.can_view_history
    if data.max_per_ride_usd is not None:
        delegation.max_per_ride_usd = float(data.max_per_ride_usd)
    if data.valid_until is not None:
        delegation.valid_until = data.valid_until
    if data.is_active is not None:
        delegation.is_active = data.is_active

    await db.flush()
    return _delegation_to_response(delegation)
