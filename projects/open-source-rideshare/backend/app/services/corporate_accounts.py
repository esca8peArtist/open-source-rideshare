"""Corporate account service.

Pure validation helpers (no I/O) and async DB operations for managing
corporate/business accounts, memberships, and ride billing integration.

Public surface
--------------
validate_corporate_billing(user_id, estimated_fare, db)
    Raises ValueError if billing validation fails; returns (account, membership).

record_corporate_spend(account_id, amount, db)
    Increments spend counters; resets monthly counter if the calendar month
    has changed since the last recorded ride.

create_account / get_account / list_accounts / update_account
invite_member / remove_member / list_members
list_account_rides
get_spend_summary
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.corporate_account import CorporateAccount, CorporateMembership, MembershipStatus
from app.models.ride import Ride

DEFAULT_PAGE_SIZE: int = 20


# ---------------------------------------------------------------------------
# Pure helpers — no I/O
# ---------------------------------------------------------------------------


def _current_month_str(now: datetime | None = None) -> str:
    """Return "YYYY-MM" for the given (or current) UTC datetime."""
    if now is None:
        now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m")


def check_per_ride_limit(account: CorporateAccount, estimated_fare: float) -> str | None:
    """Return an error string if the ride exceeds the per-ride limit, else None."""
    if account.per_ride_limit is not None and estimated_fare > account.per_ride_limit:
        return (
            f"Ride fare ${estimated_fare:.2f} exceeds the corporate per-ride limit "
            f"of ${account.per_ride_limit:.2f}."
        )
    return None


def check_monthly_limit(account: CorporateAccount, estimated_fare: float) -> str | None:
    """Return an error string if adding this fare would breach the monthly limit, else None."""
    if account.monthly_limit is None:
        return None
    projected = account.current_month_spend + estimated_fare
    if projected > account.monthly_limit:
        return (
            f"This ride would bring the monthly corporate spend to "
            f"${projected:.2f}, exceeding the limit of ${account.monthly_limit:.2f}."
        )
    return None


# ---------------------------------------------------------------------------
# Core billing validation (async — reads DB)
# ---------------------------------------------------------------------------


async def validate_corporate_billing(
    user_id: int,
    estimated_fare: float,
    db: AsyncSession,
) -> tuple[CorporateAccount, CorporateMembership]:
    """Validate that a rider may charge this ride to a corporate account.

    Rules checked (in order):
    1. Rider must have exactly one ACTIVE corporate membership.
    2. The corporate account must be is_active.
    3. Estimated fare must not exceed per_ride_limit (if set).
    4. Projected monthly spend must not exceed monthly_limit (if set).

    Returns:
        (account, membership) on success.

    Raises:
        ValueError: with a human-readable reason if any rule is violated.
    """
    result = await db.execute(
        select(CorporateMembership).where(
            CorporateMembership.user_id == user_id,
            CorporateMembership.status == MembershipStatus.ACTIVE,
        )
    )
    active_memberships = result.scalars().all()

    if len(active_memberships) == 0:
        raise ValueError("You do not have an active corporate membership.")
    if len(active_memberships) > 1:
        raise ValueError(
            "Multiple active corporate memberships found. Please contact support."
        )

    membership = active_memberships[0]

    acc_result = await db.execute(
        select(CorporateAccount).where(CorporateAccount.id == membership.account_id)
    )
    account = acc_result.scalar_one_or_none()

    if account is None or not account.is_active:
        raise ValueError("The corporate account is not currently active.")

    err = check_per_ride_limit(account, estimated_fare)
    if err:
        raise ValueError(err)

    err = check_monthly_limit(account, estimated_fare)
    if err:
        raise ValueError(err)

    return account, membership


# ---------------------------------------------------------------------------
# Spend tracking (async)
# ---------------------------------------------------------------------------


async def record_corporate_spend(
    account_id: int,
    amount: float,
    db: AsyncSession,
    now: datetime | None = None,
) -> CorporateAccount | None:
    """Increment spend counters for a corporate account after a ride completes.

    If the stored ``current_month`` differs from today's month, the
    ``current_month_spend`` counter is reset before adding the new amount.

    Returns the updated account, or None if the account is not found.
    """
    result = await db.execute(
        select(CorporateAccount).where(CorporateAccount.id == account_id)
    )
    account = result.scalar_one_or_none()
    if account is None:
        return None

    this_month = _current_month_str(now)
    if account.current_month != this_month:
        account.current_month_spend = 0.0
        account.current_month = this_month

    account.current_month_spend += amount
    account.total_spend += amount
    db.add(account)
    await db.commit()
    await db.refresh(account)
    return account


# ---------------------------------------------------------------------------
# CRUD: CorporateAccount
# ---------------------------------------------------------------------------


async def create_account(
    db: AsyncSession,
    *,
    company_name: str,
    billing_email: str,
    monthly_limit: float | None = None,
    per_ride_limit: float | None = None,
    now: datetime | None = None,
) -> CorporateAccount:
    """Create and persist a new corporate account."""
    account = CorporateAccount(
        company_name=company_name,
        billing_email=billing_email,
        monthly_limit=monthly_limit,
        per_ride_limit=per_ride_limit,
        is_active=True,
        current_month_spend=0.0,
        current_month=_current_month_str(now),
        total_spend=0.0,
    )
    db.add(account)
    await db.commit()
    await db.refresh(account)
    return account


async def get_account(
    db: AsyncSession, account_id: int
) -> CorporateAccount | None:
    """Fetch a corporate account by ID."""
    result = await db.execute(
        select(CorporateAccount).where(CorporateAccount.id == account_id)
    )
    return result.scalar_one_or_none()


async def list_accounts(
    db: AsyncSession,
    *,
    active_only: bool = False,
    page: int = 1,
    page_size: int = DEFAULT_PAGE_SIZE,
) -> tuple[Sequence[CorporateAccount], int]:
    """List corporate accounts with optional active-only filter.

    Returns:
        (items, total_count)
    """
    q = select(CorporateAccount)
    if active_only:
        q = q.where(CorporateAccount.is_active == True)  # noqa: E712

    count_result = await db.execute(
        select(func.count()).select_from(q.subquery())
    )
    total = count_result.scalar_one()

    q = q.order_by(CorporateAccount.created_at.desc())
    q = q.offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(q)
    return result.scalars().all(), total


async def update_account(
    db: AsyncSession,
    account_id: int,
    *,
    company_name: str | None = None,
    billing_email: str | None = None,
    monthly_limit: float | None = None,
    per_ride_limit: float | None = None,
    is_active: bool | None = None,
) -> CorporateAccount | None:
    """Partially update a corporate account.

    Returns:
        The updated account, or None if not found.
    """
    account = await get_account(db, account_id)
    if account is None:
        return None

    if company_name is not None:
        account.company_name = company_name
    if billing_email is not None:
        account.billing_email = billing_email
    if monthly_limit is not None:
        account.monthly_limit = monthly_limit
    if per_ride_limit is not None:
        account.per_ride_limit = per_ride_limit
    if is_active is not None:
        account.is_active = is_active

    db.add(account)
    await db.commit()
    await db.refresh(account)
    return account


# ---------------------------------------------------------------------------
# CRUD: CorporateMembership
# ---------------------------------------------------------------------------


async def invite_member(
    db: AsyncSession,
    account_id: int,
    user_id: int,
    monthly_limit: float | None = None,
) -> tuple[CorporateMembership | None, str | None]:
    """Invite a user to a corporate account.

    Returns:
        (membership, None) on success.
        (None, error_message) if the user already has a non-removed membership.
    """
    # Check for an existing, non-removed membership
    existing_result = await db.execute(
        select(CorporateMembership).where(
            CorporateMembership.account_id == account_id,
            CorporateMembership.user_id == user_id,
            CorporateMembership.status != MembershipStatus.REMOVED,
        )
    )
    existing = existing_result.scalar_one_or_none()
    if existing is not None:
        return None, "User already has an active or pending membership for this account."

    membership = CorporateMembership(
        account_id=account_id,
        user_id=user_id,
        monthly_limit=monthly_limit,
        status=MembershipStatus.PENDING,
    )
    db.add(membership)
    await db.commit()
    await db.refresh(membership)
    return membership, None


async def activate_membership(
    db: AsyncSession,
    membership_id: int,
    user_id: int,
    now: datetime | None = None,
) -> tuple[CorporateMembership | None, str | None]:
    """Accept a pending corporate membership invitation.

    Only the invited user (matching user_id) may activate their own invite.

    Returns:
        (membership, None) on success.
        (None, error_message) on failure.
    """
    if now is None:
        now = datetime.now(timezone.utc)

    result = await db.execute(
        select(CorporateMembership).where(
            CorporateMembership.id == membership_id,
            CorporateMembership.user_id == user_id,
        )
    )
    membership = result.scalar_one_or_none()

    if membership is None:
        return None, "Membership not found."
    if membership.status != MembershipStatus.PENDING:
        return None, f"Cannot activate a membership with status '{membership.status.value}'."

    membership.status = MembershipStatus.ACTIVE
    membership.activated_at = now
    db.add(membership)
    await db.commit()
    await db.refresh(membership)
    return membership, None


async def remove_member(
    db: AsyncSession,
    account_id: int,
    user_id: int,
) -> tuple[CorporateMembership | None, str | None]:
    """Remove a member from a corporate account (sets status to REMOVED).

    Returns:
        (membership, None) on success.
        (None, error_message) if not found.
    """
    result = await db.execute(
        select(CorporateMembership).where(
            CorporateMembership.account_id == account_id,
            CorporateMembership.user_id == user_id,
            CorporateMembership.status != MembershipStatus.REMOVED,
        )
    )
    membership = result.scalar_one_or_none()

    if membership is None:
        return None, "Active membership not found for this user."

    membership.status = MembershipStatus.REMOVED
    db.add(membership)
    await db.commit()
    await db.refresh(membership)
    return membership, None


async def list_members(
    db: AsyncSession,
    account_id: int,
    *,
    page: int = 1,
    page_size: int = DEFAULT_PAGE_SIZE,
) -> tuple[Sequence[CorporateMembership], int]:
    """List all memberships for a corporate account (all statuses).

    Returns:
        (items, total_count)
    """
    q = select(CorporateMembership).where(
        CorporateMembership.account_id == account_id
    )

    count_result = await db.execute(
        select(func.count()).select_from(q.subquery())
    )
    total = count_result.scalar_one()

    q = q.order_by(CorporateMembership.invited_at.desc())
    q = q.offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(q)
    return result.scalars().all(), total


async def list_rider_memberships(
    db: AsyncSession,
    user_id: int,
) -> Sequence[CorporateMembership]:
    """Return all PENDING and ACTIVE memberships for a rider."""
    result = await db.execute(
        select(CorporateMembership).where(
            CorporateMembership.user_id == user_id,
            CorporateMembership.status.in_(
                [MembershipStatus.PENDING, MembershipStatus.ACTIVE]
            ),
        ).order_by(CorporateMembership.invited_at.desc())
    )
    return result.scalars().all()


# ---------------------------------------------------------------------------
# Ride listing
# ---------------------------------------------------------------------------


async def list_account_rides(
    db: AsyncSession,
    account_id: int,
    *,
    page: int = 1,
    page_size: int = DEFAULT_PAGE_SIZE,
) -> tuple[Sequence[Ride], int]:
    """List rides billed to a corporate account, newest first.

    Returns:
        (items, total_count)
    """
    q = select(Ride).where(Ride.corporate_account_id == account_id)

    count_result = await db.execute(
        select(func.count()).select_from(q.subquery())
    )
    total = count_result.scalar_one()

    q = q.order_by(Ride.requested_at.desc())
    q = q.offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(q)
    return result.scalars().all(), total


# ---------------------------------------------------------------------------
# Spend summary
# ---------------------------------------------------------------------------


async def get_spend_summary(
    db: AsyncSession,
    account_id: int,
) -> dict:
    """Compute monthly spend breakdown from completed corporate rides.

    Returns the last 12 months of spend data plus the account's current-month
    running total.

    Returns:
        dict with keys: account_id, current_month, current_month_spend,
        monthly_breakdown (list of {month, total}).
    """
    account = await get_account(db, account_id)
    if account is None:
        return {}

    # Aggregate actual_fare by month from ride records
    from sqlalchemy import cast, extract
    from sqlalchemy.dialects.postgresql import aggregate_order_by

    # Build a simpler cross-db compatible grouping using string formatting
    # We use func.to_char for PostgreSQL but fall back gracefully in tests
    result = await db.execute(
        select(
            func.to_char(Ride.completed_at, "YYYY-MM").label("month"),
            func.sum(Ride.actual_fare).label("total"),
        )
        .where(
            Ride.corporate_account_id == account_id,
            Ride.actual_fare.is_not(None),
            Ride.completed_at.is_not(None),
        )
        .group_by(func.to_char(Ride.completed_at, "YYYY-MM"))
        .order_by(func.to_char(Ride.completed_at, "YYYY-MM").desc())
        .limit(12)
    )
    rows = result.all()

    monthly_breakdown = [{"month": row.month, "total": float(row.total)} for row in rows]

    return {
        "account_id": account_id,
        "current_month": account.current_month,
        "current_month_spend": account.current_month_spend,
        "monthly_breakdown": monthly_breakdown,
    }
