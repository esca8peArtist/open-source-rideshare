"""Service layer for the corporate business accounts system.

Manages CorporateAccount, CorporateAccountMember, and CorporateInvoice
entities. All business rules are enforced here; the router delegates to
these functions.

Account management:
    create_account, get_account, get_user_account, update_account,
    suspend_account, activate_account

Member management:
    add_member, list_members, get_member, update_member, remove_member

Invoice management:
    generate_invoice, issue_invoice, mark_invoice_paid, list_invoices

Spend tracking:
    get_spend_summary
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Sequence

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.corporate import (
    BusinessAccount,
    BusinessAccountMember,
    BusinessInvoice,
    CorporateAccountStatus,
    InvoiceStatus,
    MemberRole,
)

# Type aliases for readability in this module
CorporateAccount = BusinessAccount
CorporateAccountMember = BusinessAccountMember
CorporateInvoice = BusinessInvoice

MAX_MEMBERS_PER_ACCOUNT = 500


# ---------------------------------------------------------------------------
# Account management
# ---------------------------------------------------------------------------


async def create_account(
    db: AsyncSession,
    user_id: int,
    data,
) -> CorporateAccount:
    """Create a new corporate account and make the requesting user its admin.

    The requesting user must not already belong to an active corporate account.

    Args:
        db: Database session.
        user_id: ID of the user creating the account (becomes account admin).
        data: CorporateAccountCreate schema instance.

    Returns:
        The newly created CorporateAccount.

    Raises:
        HTTPException 400: If the user already belongs to an active account.
    """
    existing = await get_user_account(db, user_id)
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You already belong to a corporate account.",
        )

    account = CorporateAccount(
        name=data.name,
        billing_email=data.billing_email,
        tax_id=getattr(data, "tax_id", None),
        billing_address=getattr(data, "billing_address", None),
        status=CorporateAccountStatus.ACTIVE,
        monthly_budget_limit=getattr(data, "monthly_budget_limit", None),
    )
    db.add(account)
    await db.flush()  # Get the account ID without committing

    # Add the creating user as admin
    member = CorporateAccountMember(
        account_id=account.id,
        user_id=user_id,
        role=MemberRole.ADMIN,
        is_active=True,
    )
    db.add(member)
    await db.commit()
    await db.refresh(account)
    return account


async def get_account(db: AsyncSession, account_id: int) -> CorporateAccount:
    """Fetch a corporate account by ID.

    Raises:
        HTTPException 404: If the account is not found.
    """
    result = await db.execute(
        select(CorporateAccount).where(CorporateAccount.id == account_id)
    )
    account = result.scalar_one_or_none()
    if account is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Corporate account not found.",
        )
    return account


async def get_user_account(
    db: AsyncSession, user_id: int
) -> CorporateAccount | None:
    """Return the active corporate account a user belongs to, or None.

    A user may only belong to one active account at a time.
    """
    result = await db.execute(
        select(CorporateAccountMember).where(
            CorporateAccountMember.user_id == user_id,
            CorporateAccountMember.is_active.is_(True),
        )
    )
    membership = result.scalar_one_or_none()
    if membership is None:
        return None

    acc_result = await db.execute(
        select(CorporateAccount).where(
            CorporateAccount.id == membership.account_id,
            CorporateAccount.status != CorporateAccountStatus.CANCELLED,
        )
    )
    return acc_result.scalar_one_or_none()


async def update_account(
    db: AsyncSession,
    account_id: int,
    data,
    requesting_user_id: int,
) -> CorporateAccount:
    """Partially update a corporate account.

    Only the account admin (or a platform admin via the admin API) may call
    this. Pass ``requesting_user_id=-1`` from admin endpoints to bypass the
    membership check.

    Raises:
        HTTPException 403: If the requesting user is not an account admin.
        HTTPException 404: If the account does not exist.
    """
    account = await get_account(db, account_id)

    if requesting_user_id != -1:
        await _require_account_admin(db, account_id, requesting_user_id)

    if data.name is not None:
        account.name = data.name
    if data.billing_email is not None:
        account.billing_email = data.billing_email
    if hasattr(data, "tax_id") and data.tax_id is not None:
        account.tax_id = data.tax_id
    if hasattr(data, "billing_address") and data.billing_address is not None:
        account.billing_address = data.billing_address
    if hasattr(data, "monthly_budget_limit") and data.monthly_budget_limit is not None:
        account.monthly_budget_limit = data.monthly_budget_limit

    db.add(account)
    await db.commit()
    await db.refresh(account)
    return account


async def suspend_account(db: AsyncSession, account_id: int) -> CorporateAccount:
    """Suspend a corporate account (platform admin only).

    Raises:
        HTTPException 404: If the account does not exist.
    """
    account = await get_account(db, account_id)
    account.status = CorporateAccountStatus.SUSPENDED
    db.add(account)
    await db.commit()
    await db.refresh(account)
    return account


async def activate_account(db: AsyncSession, account_id: int) -> CorporateAccount:
    """Activate a corporate account (platform admin only).

    Raises:
        HTTPException 404: If the account does not exist.
    """
    account = await get_account(db, account_id)
    account.status = CorporateAccountStatus.ACTIVE
    db.add(account)
    await db.commit()
    await db.refresh(account)
    return account


# ---------------------------------------------------------------------------
# Member management
# ---------------------------------------------------------------------------


async def add_member(
    db: AsyncSession,
    account_id: int,
    data,
    requesting_user_id: int,
) -> CorporateAccountMember:
    """Add a user to a corporate account.

    Business rules:
    - Requesting user must be an account admin.
    - Target user must not already be in another active account.
    - Target user must not already be a member of this account.
    - Account may not exceed MAX_MEMBERS_PER_ACCOUNT (500).

    Raises:
        HTTPException 400: Duplicate member, user in another account, or max members.
        HTTPException 403: Requesting user is not an account admin.
        HTTPException 404: Account not found.
    """
    await get_account(db, account_id)
    await _require_account_admin(db, account_id, requesting_user_id)

    # Check max members
    count_result = await db.execute(
        select(func.count(CorporateAccountMember.id)).where(
            CorporateAccountMember.account_id == account_id,
            CorporateAccountMember.is_active.is_(True),
        )
    )
    current_count = count_result.scalar() or 0
    if current_count >= MAX_MEMBERS_PER_ACCOUNT:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Account has reached the maximum of {MAX_MEMBERS_PER_ACCOUNT} members.",
        )

    # Check user not already in this account
    existing_result = await db.execute(
        select(CorporateAccountMember).where(
            CorporateAccountMember.account_id == account_id,
            CorporateAccountMember.user_id == data.user_id,
        )
    )
    if existing_result.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User is already a member of this account.",
        )

    # Check user not already in another active account
    other_membership_result = await db.execute(
        select(CorporateAccountMember).where(
            CorporateAccountMember.user_id == data.user_id,
            CorporateAccountMember.is_active.is_(True),
            CorporateAccountMember.account_id != account_id,
        )
    )
    if other_membership_result.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User already belongs to another active corporate account.",
        )

    member = CorporateAccountMember(
        account_id=account_id,
        user_id=data.user_id,
        role=getattr(data, "role", MemberRole.MEMBER),
        monthly_spend_limit=getattr(data, "monthly_spend_limit", None),
        is_active=True,
    )
    db.add(member)
    await db.commit()
    await db.refresh(member)
    return member


async def list_members(
    db: AsyncSession, account_id: int
) -> Sequence[CorporateAccountMember]:
    """Return active members of an account, sorted by joined_at ascending."""
    result = await db.execute(
        select(CorporateAccountMember)
        .where(
            CorporateAccountMember.account_id == account_id,
            CorporateAccountMember.is_active.is_(True),
        )
        .order_by(CorporateAccountMember.joined_at.asc())
    )
    return result.scalars().all()


async def get_member(
    db: AsyncSession, account_id: int, user_id: int
) -> CorporateAccountMember:
    """Fetch a specific member of an account.

    Raises:
        HTTPException 404: If the member is not found.
    """
    result = await db.execute(
        select(CorporateAccountMember).where(
            CorporateAccountMember.account_id == account_id,
            CorporateAccountMember.user_id == user_id,
        )
    )
    member = result.scalar_one_or_none()
    if member is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Member not found.",
        )
    return member


async def update_member(
    db: AsyncSession,
    account_id: int,
    user_id: int,
    data,
    requesting_user_id: int,
) -> CorporateAccountMember:
    """Update a member's role or spend limit.

    Raises:
        HTTPException 403: Requesting user is not an account admin.
        HTTPException 404: Member not found.
    """
    await _require_account_admin(db, account_id, requesting_user_id)
    member = await get_member(db, account_id, user_id)

    if data.role is not None:
        member.role = data.role
    if data.monthly_spend_limit is not None:
        member.monthly_spend_limit = data.monthly_spend_limit
    if data.is_active is not None:
        member.is_active = data.is_active

    db.add(member)
    await db.commit()
    await db.refresh(member)
    return member


async def remove_member(
    db: AsyncSession,
    account_id: int,
    user_id: int,
    requesting_user_id: int,
) -> CorporateAccountMember:
    """Soft-delete a member (sets is_active=False).

    An account admin cannot remove themselves if they are the only remaining
    admin.

    Raises:
        HTTPException 400: Removing the last admin of an account.
        HTTPException 403: Requesting user is not an account admin.
        HTTPException 404: Member not found.
    """
    await _require_account_admin(db, account_id, requesting_user_id)
    member = await get_member(db, account_id, user_id)

    # Guard: cannot remove last admin
    if member.role == MemberRole.ADMIN:
        admin_count_result = await db.execute(
            select(func.count(CorporateAccountMember.id)).where(
                CorporateAccountMember.account_id == account_id,
                CorporateAccountMember.role == MemberRole.ADMIN,
                CorporateAccountMember.is_active.is_(True),
            )
        )
        admin_count = admin_count_result.scalar() or 0
        if admin_count <= 1:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot remove the last admin of a corporate account.",
            )

    member.is_active = False
    db.add(member)
    await db.commit()
    await db.refresh(member)
    return member


# ---------------------------------------------------------------------------
# Invoice management
# ---------------------------------------------------------------------------


async def generate_invoice(
    db: AsyncSession,
    account_id: int,
    period_start: date,
    period_end: date,
) -> CorporateInvoice:
    """Generate a draft invoice for the given billing period.

    Counts rides and sums amounts from corporate ride data. In the current
    implementation, the invoice is seeded with zero totals (ride data
    aggregation would be added when the ride model is linked).

    Raises:
        HTTPException 404: If the account does not exist.
    """
    await get_account(db, account_id)

    invoice = CorporateInvoice(
        account_id=account_id,
        billing_period_start=period_start,
        billing_period_end=period_end,
        total_rides=0,
        total_amount=Decimal("0.00"),
        status=InvoiceStatus.DRAFT,
    )
    db.add(invoice)
    await db.commit()
    await db.refresh(invoice)
    return invoice


async def issue_invoice(
    db: AsyncSession, invoice_id: int
) -> CorporateInvoice:
    """Transition an invoice from draft to issued.

    Raises:
        HTTPException 404: If the invoice does not exist.
    """
    invoice = await _get_invoice(db, invoice_id)
    invoice.status = InvoiceStatus.ISSUED
    invoice.issued_at = datetime.now(timezone.utc)
    db.add(invoice)
    await db.commit()
    await db.refresh(invoice)
    return invoice


async def mark_invoice_paid(
    db: AsyncSession, invoice_id: int
) -> CorporateInvoice:
    """Transition an invoice to paid.

    Raises:
        HTTPException 404: If the invoice does not exist.
    """
    invoice = await _get_invoice(db, invoice_id)
    invoice.status = InvoiceStatus.PAID
    invoice.paid_at = datetime.now(timezone.utc)
    db.add(invoice)
    await db.commit()
    await db.refresh(invoice)
    return invoice


async def list_invoices(
    db: AsyncSession, account_id: int
) -> Sequence[CorporateInvoice]:
    """Return all invoices for an account, newest first."""
    result = await db.execute(
        select(CorporateInvoice)
        .where(CorporateInvoice.account_id == account_id)
        .order_by(CorporateInvoice.created_at.desc())
    )
    return result.scalars().all()


# ---------------------------------------------------------------------------
# Spend tracking
# ---------------------------------------------------------------------------


async def get_spend_summary(
    db: AsyncSession, account_id: int
) -> dict:
    """Compute current-month spend summary for a corporate account.

    Returns a dict with keys:
        account_id, account_name, current_month_spend, member_count,
        monthly_budget_limit, budget_utilization_pct.
    """
    account = await get_account(db, account_id)

    member_count_result = await db.execute(
        select(func.count(CorporateAccountMember.id)).where(
            CorporateAccountMember.account_id == account_id,
            CorporateAccountMember.is_active.is_(True),
        )
    )
    member_count = member_count_result.scalar() or 0

    # Current month spend is derived from issued/paid invoices created this month.
    # For now we sum total_amount from invoices in the current month.
    now = datetime.now(timezone.utc)
    month_start = date(now.year, now.month, 1)

    spend_result = await db.execute(
        select(func.coalesce(func.sum(CorporateInvoice.total_amount), 0)).where(
            CorporateInvoice.account_id == account_id,
            CorporateInvoice.billing_period_start >= month_start,
            CorporateInvoice.status.in_([InvoiceStatus.ISSUED, InvoiceStatus.PAID]),
        )
    )
    current_month_spend = Decimal(str(spend_result.scalar() or 0))

    budget_utilization_pct: float | None = None
    if account.monthly_budget_limit and account.monthly_budget_limit > 0:
        budget_utilization_pct = float(
            (current_month_spend / account.monthly_budget_limit) * 100
        )

    return {
        "account_id": account_id,
        "account_name": account.name,
        "current_month_spend": current_month_spend,
        "member_count": member_count,
        "monthly_budget_limit": account.monthly_budget_limit,
        "budget_utilization_pct": budget_utilization_pct,
    }


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


async def _require_account_admin(
    db: AsyncSession, account_id: int, user_id: int
) -> CorporateAccountMember:
    """Raise 403 if the user is not an active admin of the account."""
    result = await db.execute(
        select(CorporateAccountMember).where(
            CorporateAccountMember.account_id == account_id,
            CorporateAccountMember.user_id == user_id,
            CorporateAccountMember.role == MemberRole.ADMIN,
            CorporateAccountMember.is_active.is_(True),
        )
    )
    membership = result.scalar_one_or_none()
    if membership is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have admin access to this corporate account.",
        )
    return membership


async def _get_invoice(
    db: AsyncSession, invoice_id: int
) -> CorporateInvoice:
    """Fetch an invoice by ID, raising 404 if not found."""
    result = await db.execute(
        select(CorporateInvoice).where(CorporateInvoice.id == invoice_id)
    )
    invoice = result.scalar_one_or_none()
    if invoice is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Invoice not found.",
        )
    return invoice
