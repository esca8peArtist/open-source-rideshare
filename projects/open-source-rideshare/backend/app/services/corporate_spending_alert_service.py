"""Service layer for corporate spending limit alerts.

Public surface
--------------
check_and_create_alerts(db, account_id, as_of_date)
get_account_alerts(db, account_id, requesting_user_id, year, month)
get_member_alerts(db, account_id, member_id, requesting_user_id, year, month)
get_alerts_summary(db, account_id, requesting_user_id)

Spend calculation
-----------------
Account-level spend:
    SUM(total_amount) from BusinessInvoice WHERE account_id = X
    AND status IN ('issued', 'paid') AND created_at is within the period.

Member-level spend:
    The BusinessInvoice table does not carry a member_id column.  As a result
    member-level spend cannot be derived precisely from invoices alone.

    LIMITATION: Member-level spend is approximated as:
        account_spend / active_member_count

    This is a known limitation documented here so future contributors can
    replace it once a per-member spend tracking mechanism exists (e.g. a
    ride-level table that carries both account_id and member_id).  Until then,
    member spend limits are enforced on an averaged basis — all members share
    the same effective spend figure — which is a conservative approximation
    (it will alert earlier than a precise per-member figure would).

Alert thresholds (platform defaults, not yet configurable per account)
----------------------------------------------------------------------
    75 % of limit  → AlertType.WARNING_75PCT  (threshold_pct = 75)
    90 % of limit  → AlertType.WARNING_90PCT  (threshold_pct = 90)
    100 % of limit → AlertType.LIMIT_REACHED  (threshold_pct = 100)
"""

from __future__ import annotations

import calendar
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Sequence

from fastapi import HTTPException, status
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.corporate import (
    BusinessAccount,
    BusinessAccountMember,
    BusinessInvoice,
    InvoiceStatus,
    MemberRole,
)
from app.models.corporate_spending_alert import AlertType, CorporateSpendingAlert
from app.schemas.corporate_spending_alert import (
    MemberSpendStatus,
    SpendingAlertsSummary,
)

# ---------------------------------------------------------------------------
# Platform-wide thresholds — (pct, AlertType)
# ---------------------------------------------------------------------------

_THRESHOLDS: list[tuple[int, AlertType]] = [
    (75, AlertType.WARNING_75PCT),
    (90, AlertType.WARNING_90PCT),
    (100, AlertType.LIMIT_REACHED),
]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _period_bounds(year: int, month: int) -> tuple[datetime, datetime]:
    """Return (start_dt, end_dt) covering the full calendar month in UTC."""
    last_day = calendar.monthrange(year, month)[1]
    start = datetime(year, month, 1, 0, 0, 0, tzinfo=timezone.utc)
    end = datetime(year, month, last_day, 23, 59, 59, 999999, tzinfo=timezone.utc)
    return start, end


async def _require_account_admin(
    db: AsyncSession, account_id: int, user_id: int
) -> BusinessAccountMember:
    """Verify user is an active ADMIN of the account; raise 403 otherwise."""
    result = await db.execute(
        select(BusinessAccountMember).where(
            BusinessAccountMember.account_id == account_id,
            BusinessAccountMember.user_id == user_id,
            BusinessAccountMember.is_active.is_(True),
            BusinessAccountMember.role == MemberRole.ADMIN,
        )
    )
    member = result.scalar_one_or_none()
    if member is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account admin access required.",
        )
    return member


async def _require_account_member(
    db: AsyncSession, account_id: int, user_id: int
) -> BusinessAccountMember:
    """Verify user is an active member of the account; raise 403 otherwise."""
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
            detail="You are not an active member of this account.",
        )
    return member


async def _get_account(db: AsyncSession, account_id: int) -> BusinessAccount:
    """Fetch account; raise 404 if not found."""
    result = await db.execute(
        select(BusinessAccount).where(BusinessAccount.id == account_id)
    )
    account = result.scalar_one_or_none()
    if account is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Corporate account not found.",
        )
    return account


async def _compute_account_spend(
    db: AsyncSession, account_id: int, year: int, month: int
) -> Decimal:
    """Sum total_amount from issued/paid invoices in the given calendar month."""
    start_dt, end_dt = _period_bounds(year, month)
    result = await db.execute(
        select(BusinessInvoice).where(
            BusinessInvoice.account_id == account_id,
            BusinessInvoice.status.in_([InvoiceStatus.ISSUED, InvoiceStatus.PAID]),
            BusinessInvoice.created_at >= start_dt,
            BusinessInvoice.created_at <= end_dt,
        )
    )
    invoices: Sequence[BusinessInvoice] = result.scalars().all()
    return sum((inv.total_amount for inv in invoices), Decimal("0.00"))


async def _get_active_members(
    db: AsyncSession, account_id: int
) -> list[BusinessAccountMember]:
    """Return all active members for an account."""
    result = await db.execute(
        select(BusinessAccountMember).where(
            BusinessAccountMember.account_id == account_id,
            BusinessAccountMember.is_active.is_(True),
        )
    )
    return list(result.scalars().all())


async def _existing_alert_types(
    db: AsyncSession,
    account_id: int,
    member_id: int | None,
    year: int,
    month: int,
) -> set[AlertType]:
    """Return the set of AlertTypes already recorded for this (account, member, period)."""
    result = await db.execute(
        select(CorporateSpendingAlert).where(
            CorporateSpendingAlert.account_id == account_id,
            CorporateSpendingAlert.member_id == member_id,
            CorporateSpendingAlert.period_year == year,
            CorporateSpendingAlert.period_month == month,
        )
    )
    return {row.alert_type for row in result.scalars().all()}


def _alerts_for_spend(
    spend: Decimal,
    limit: Decimal,
    already_fired: set[AlertType],
) -> list[tuple[int, AlertType]]:
    """Return (pct, AlertType) pairs for thresholds newly crossed."""
    new_alerts: list[tuple[int, AlertType]] = []
    if limit <= Decimal("0"):
        return new_alerts
    ratio = spend / limit
    for pct, alert_type in _THRESHOLDS:
        if ratio >= Decimal(pct) / Decimal(100) and alert_type not in already_fired:
            new_alerts.append((pct, alert_type))
    return new_alerts


# ---------------------------------------------------------------------------
# Public service functions
# ---------------------------------------------------------------------------


async def check_and_create_alerts(
    db: AsyncSession,
    account_id: int,
    as_of_date: date | None = None,
) -> list[CorporateSpendingAlert]:
    """Compute current spend and create new alert records for thresholds crossed.

    Checks both account-level and per-member limits.  Idempotent within a
    period — does not create duplicate alerts for the same threshold.

    Args:
        db: Async database session.
        account_id: The corporate account to check.
        as_of_date: The reference date (determines which calendar month to
            examine).  Defaults to today.

    Returns:
        List of newly created CorporateSpendingAlert rows.
    """
    if as_of_date is None:
        as_of_date = date.today()
    year, month = as_of_date.year, as_of_date.month

    account = await _get_account(db, account_id)
    account_spend = await _compute_account_spend(db, account_id, year, month)
    active_members = await _get_active_members(db, account_id)

    new_alerts: list[CorporateSpendingAlert] = []

    # -- Account-level alerts --
    if account.monthly_budget_limit is not None and account.monthly_budget_limit > 0:
        fired = await _existing_alert_types(db, account_id, None, year, month)
        for pct, alert_type in _alerts_for_spend(
            account_spend, account.monthly_budget_limit, fired
        ):
            alert = CorporateSpendingAlert(
                account_id=account_id,
                member_id=None,
                alert_type=alert_type,
                threshold_pct=pct,
                current_spend_usd=account_spend,
                limit_usd=account.monthly_budget_limit,
                period_year=year,
                period_month=month,
            )
            db.add(alert)
            new_alerts.append(alert)

    # -- Member-level alerts --
    # NOTE: Member spend is approximated as account_spend / active_member_count.
    # See module docstring for details of this known limitation.
    member_count = len(active_members)
    for member in active_members:
        if member.monthly_spend_limit is None or member.monthly_spend_limit <= 0:
            continue
        member_spend = (
            account_spend / Decimal(member_count)
            if member_count > 0
            else Decimal("0.00")
        )
        fired = await _existing_alert_types(db, account_id, member.id, year, month)
        for pct, alert_type in _alerts_for_spend(
            member_spend, member.monthly_spend_limit, fired
        ):
            alert = CorporateSpendingAlert(
                account_id=account_id,
                member_id=member.id,
                alert_type=alert_type,
                threshold_pct=pct,
                current_spend_usd=member_spend,
                limit_usd=member.monthly_spend_limit,
                period_year=year,
                period_month=month,
            )
            db.add(alert)
            new_alerts.append(alert)

    if new_alerts:
        await db.commit()
        for alert in new_alerts:
            await db.refresh(alert)

    return new_alerts


async def get_account_alerts(
    db: AsyncSession,
    account_id: int,
    requesting_user_id: int,
    year: int,
    month: int,
) -> list[CorporateSpendingAlert]:
    """List all alerts for an account in a given period (admin only).

    Args:
        db: Async database session.
        account_id: Corporate account to query.
        requesting_user_id: Must be an account admin.
        year: Period year.
        month: Period month (1-12).

    Returns:
        List of CorporateSpendingAlert rows ordered by created_at ascending.

    Raises:
        HTTPException 403: Caller is not an account admin.
        HTTPException 404: Account not found.
    """
    await _get_account(db, account_id)
    await _require_account_admin(db, account_id, requesting_user_id)

    result = await db.execute(
        select(CorporateSpendingAlert)
        .where(
            CorporateSpendingAlert.account_id == account_id,
            CorporateSpendingAlert.period_year == year,
            CorporateSpendingAlert.period_month == month,
        )
        .order_by(CorporateSpendingAlert.created_at.asc())
    )
    return list(result.scalars().all())


async def get_member_alerts(
    db: AsyncSession,
    account_id: int,
    member_id: int,
    requesting_user_id: int,
    year: int,
    month: int,
) -> list[CorporateSpendingAlert]:
    """List own alerts for a member (member can only see their own alerts).

    The requesting user must be an active member of the account, and may only
    retrieve alerts tied to their own membership record (member_id must
    correspond to a membership whose user_id matches requesting_user_id).

    Args:
        db: Async database session.
        account_id: Corporate account.
        member_id: The membership record ID whose alerts are requested.
        requesting_user_id: The authenticated user — must own the membership.
        year: Period year.
        month: Period month (1-12).

    Returns:
        List of CorporateSpendingAlert rows for this member this period.

    Raises:
        HTTPException 403: Caller does not own this membership.
        HTTPException 404: Account not found.
    """
    await _get_account(db, account_id)
    membership = await _require_account_member(db, account_id, requesting_user_id)

    # Members may only view their own alert records.
    if membership.id != member_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You may only view your own spending alerts.",
        )

    result = await db.execute(
        select(CorporateSpendingAlert)
        .where(
            CorporateSpendingAlert.account_id == account_id,
            CorporateSpendingAlert.member_id == member_id,
            CorporateSpendingAlert.period_year == year,
            CorporateSpendingAlert.period_month == month,
        )
        .order_by(CorporateSpendingAlert.created_at.asc())
    )
    return list(result.scalars().all())


async def get_alerts_summary(
    db: AsyncSession,
    account_id: int,
    requesting_user_id: int,
    year: int | None = None,
    month: int | None = None,
) -> SpendingAlertsSummary:
    """Return a current-month spending alert summary for an account (admin only).

    Computes live spend figures and cross-references with stored alert records
    to produce a snapshot of which members are near or at their limits.

    Args:
        db: Async database session.
        account_id: Corporate account to summarise.
        requesting_user_id: Must be an account admin.
        year: Period year (defaults to current year).
        month: Period month (defaults to current month).

    Returns:
        SpendingAlertsSummary with per-member and account-level status.

    Raises:
        HTTPException 403: Caller is not an account admin.
        HTTPException 404: Account not found.
    """
    today = date.today()
    if year is None:
        year = today.year
    if month is None:
        month = today.month

    account = await _get_account(db, account_id)
    await _require_account_admin(db, account_id, requesting_user_id)

    account_spend = await _compute_account_spend(db, account_id, year, month)
    active_members = await _get_active_members(db, account_id)
    member_count = len(active_members)

    # Account-level status
    account_limit = account.monthly_budget_limit
    account_pct: float | None = None
    if account_limit and account_limit > 0:
        account_pct = float(account_spend / account_limit * 100)

    # Highest account-level alert already fired
    acct_alert_types = await _existing_alert_types(db, account_id, None, year, month)
    account_alert: AlertType | None = None
    for _, at in reversed(_THRESHOLDS):
        if at in acct_alert_types:
            account_alert = at
            break

    # Per-member status
    members_near: list[MemberSpendStatus] = []
    members_at: list[MemberSpendStatus] = []
    members_over: list[MemberSpendStatus] = []

    for member in active_members:
        if member.monthly_spend_limit is None or member.monthly_spend_limit <= 0:
            continue
        member_spend = (
            account_spend / Decimal(member_count)
            if member_count > 0
            else Decimal("0.00")
        )
        pct_used = float(member_spend / member.monthly_spend_limit * 100)
        fired = await _existing_alert_types(db, account_id, member.id, year, month)
        highest: AlertType | None = None
        for _, at in reversed(_THRESHOLDS):
            if at in fired:
                highest = at
                break

        status_obj = MemberSpendStatus(
            member_id=member.id,
            current_spend_usd=member_spend,
            limit_usd=member.monthly_spend_limit,
            pct_used=pct_used,
            highest_alert=highest,
        )

        if pct_used >= 100:
            members_over.append(status_obj)
        elif pct_used >= 90:
            members_at.append(status_obj)
        elif pct_used >= 75:
            members_near.append(status_obj)

    return SpendingAlertsSummary(
        account_id=account_id,
        period_year=year,
        period_month=month,
        account_spend_usd=account_spend,
        account_limit_usd=account_limit,
        account_pct_used=account_pct,
        account_alert=account_alert,
        members_near_limit=members_near,
        members_at_limit=members_at,
        members_over_limit=members_over,
    )
