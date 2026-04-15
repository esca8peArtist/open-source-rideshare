"""Corporate business account endpoints.

Account-admin endpoints (account-level admins):
  POST   /corporate/accounts                         — create account (any auth user)
  GET    /corporate/accounts/me                      — get own account
  PUT    /corporate/accounts/me                      — update own account
  GET    /corporate/accounts/me/members              — list members
  POST   /corporate/accounts/me/members              — add member
  PUT    /corporate/accounts/me/members/{user_id}   — update member
  DELETE /corporate/accounts/me/members/{user_id}   — remove member
  GET    /corporate/accounts/me/invoices             — list invoices
  GET    /corporate/accounts/me/spend                — spend summary

Platform admin endpoints:
  GET    /admin/corporate/accounts                               — list all accounts
  GET    /admin/corporate/accounts/{account_id}                  — get account
  PUT    /admin/corporate/accounts/{account_id}/suspend          — suspend
  PUT    /admin/corporate/accounts/{account_id}/activate         — activate
  POST   /admin/corporate/accounts/{account_id}/invoices         — generate invoice
  PUT    /admin/corporate/invoices/{invoice_id}/issue            — issue invoice
  PUT    /admin/corporate/invoices/{invoice_id}/paid             — mark paid
  GET    /admin/corporate/summary                                — platform summary
"""
from __future__ import annotations

import logging
from decimal import Decimal

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, require_admin
from app.models.corporate import (
    BusinessAccount,
    BusinessAccountMember,
    BusinessInvoice,
    CorporateAccountStatus,
    InvoiceStatus,
)

# Aliases for readability in route handlers
CorporateAccount = BusinessAccount
CorporateAccountMember = BusinessAccountMember
CorporateInvoice = BusinessInvoice
from app.models.user import User
from app.schemas.corporate import (
    CorporateAccountCreate,
    CorporateAccountMemberAdd,
    CorporateAccountMemberResponse,
    CorporateAccountMemberUpdate,
    CorporateAccountResponse,
    CorporateAccountUpdate,
    CorporateInvoiceResponse,
    CorporatePlatformSummary,
    CorporateSpendSummary,
    InvoiceGenerateRequest,
)
from app.services.corporate_account_mgmt import (
    activate_account,
    add_member,
    create_account,
    generate_invoice,
    get_account,
    get_spend_summary,
    get_user_account,
    issue_invoice,
    list_invoices,
    list_members,
    mark_invoice_paid,
    remove_member,
    suspend_account,
    update_account,
    update_member,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["corporate-business-accounts"])


# ---------------------------------------------------------------------------
# Helper: build CorporateAccountResponse with member count
# ---------------------------------------------------------------------------


async def _account_response(
    db: AsyncSession, account: CorporateAccount
) -> CorporateAccountResponse:
    """Build a CorporateAccountResponse, injecting the live member count."""
    count_result = await db.execute(
        select(func.count(CorporateAccountMember.id)).where(
            CorporateAccountMember.account_id == account.id,
            CorporateAccountMember.is_active.is_(True),
        )
    )
    member_count = count_result.scalar() or 0
    data = CorporateAccountResponse.model_validate(account)
    data.member_count = member_count
    return data


async def _member_response(
    member: CorporateAccountMember,
) -> CorporateAccountMemberResponse:
    """Build a CorporateAccountMemberResponse, injecting user info when available."""
    resp = CorporateAccountMemberResponse.model_validate(member)
    if hasattr(member, "user") and member.user is not None:
        resp.user_email = getattr(member.user, "email", None)
        full_name = getattr(member.user, "full_name", None)
        if full_name is None:
            first = getattr(member.user, "first_name", "") or ""
            last = getattr(member.user, "last_name", "") or ""
            full_name = f"{first} {last}".strip() or None
        resp.user_name = full_name
    return resp


# ---------------------------------------------------------------------------
# Account-admin: account management
# ---------------------------------------------------------------------------


@router.post(
    "/corporate/accounts",
    response_model=CorporateAccountResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a corporate account",
)
async def create_corporate_account(
    req: CorporateAccountCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new corporate account.

    The authenticated user automatically becomes the account admin.  A user
    may only belong to one active corporate account at a time.
    """
    account = await create_account(db, user.id, req)
    return await _account_response(db, account)


@router.get(
    "/corporate/accounts/me",
    response_model=CorporateAccountResponse,
    summary="Get own corporate account",
)
async def get_my_account(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return the corporate account the authenticated user belongs to.

    Returns 404 if the user is not a member of any corporate account.
    """
    from fastapi import HTTPException

    account = await get_user_account(db, user.id)
    if account is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="You are not a member of any corporate account.",
        )
    return await _account_response(db, account)


@router.put(
    "/corporate/accounts/me",
    response_model=CorporateAccountResponse,
    summary="Update own corporate account (account admin only)",
)
async def update_my_account(
    req: CorporateAccountUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update the corporate account the authenticated user administers.

    Only account admins may call this endpoint.
    """
    from fastapi import HTTPException

    account = await get_user_account(db, user.id)
    if account is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="You are not a member of any corporate account.",
        )
    updated = await update_account(db, account.id, req, requesting_user_id=user.id)
    return await _account_response(db, updated)


# ---------------------------------------------------------------------------
# Account-admin: member management
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/accounts/me/members",
    response_model=list[CorporateAccountMemberResponse],
    summary="List members of own corporate account",
)
async def list_my_account_members(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return active members of the user's corporate account."""
    from fastapi import HTTPException

    account = await get_user_account(db, user.id)
    if account is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="You are not a member of any corporate account.",
        )
    members = await list_members(db, account.id)
    return [await _member_response(m) for m in members]


@router.post(
    "/corporate/accounts/me/members",
    response_model=CorporateAccountMemberResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add a member to own corporate account (account admin only)",
)
async def add_my_account_member(
    req: CorporateAccountMemberAdd,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Add a user to the corporate account.

    The authenticated user must be an account admin.
    """
    from fastapi import HTTPException

    account = await get_user_account(db, user.id)
    if account is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="You are not a member of any corporate account.",
        )
    member = await add_member(db, account.id, req, requesting_user_id=user.id)
    return await _member_response(member)


@router.put(
    "/corporate/accounts/me/members/{target_user_id}",
    response_model=CorporateAccountMemberResponse,
    summary="Update a member in own corporate account (account admin only)",
)
async def update_my_account_member(
    target_user_id: int,
    req: CorporateAccountMemberUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update a member's role or spend limit."""
    from fastapi import HTTPException

    account = await get_user_account(db, user.id)
    if account is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="You are not a member of any corporate account.",
        )
    member = await update_member(
        db, account.id, target_user_id, req, requesting_user_id=user.id
    )
    return await _member_response(member)


@router.delete(
    "/corporate/accounts/me/members/{target_user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove a member from own corporate account (account admin only)",
)
async def remove_my_account_member(
    target_user_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Soft-delete a member (sets is_active=False).

    An account admin cannot remove themselves if they are the only admin.
    """
    from fastapi import HTTPException

    account = await get_user_account(db, user.id)
    if account is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="You are not a member of any corporate account.",
        )
    await remove_member(db, account.id, target_user_id, requesting_user_id=user.id)


# ---------------------------------------------------------------------------
# Account-admin: invoices and spend
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/accounts/me/invoices",
    response_model=list[CorporateInvoiceResponse],
    summary="List invoices for own corporate account",
)
async def list_my_invoices(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return all invoices for the user's corporate account, newest first."""
    from fastapi import HTTPException

    account = await get_user_account(db, user.id)
    if account is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="You are not a member of any corporate account.",
        )
    invoices = await list_invoices(db, account.id)
    return [CorporateInvoiceResponse.model_validate(inv) for inv in invoices]


@router.get(
    "/corporate/accounts/me/spend",
    response_model=CorporateSpendSummary,
    summary="Get spend summary for own corporate account",
)
async def get_my_spend_summary(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return current-month spend summary for the user's corporate account."""
    from fastapi import HTTPException

    account = await get_user_account(db, user.id)
    if account is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="You are not a member of any corporate account.",
        )
    summary = await get_spend_summary(db, account.id)
    return CorporateSpendSummary(**summary)


# ---------------------------------------------------------------------------
# Platform admin: account management
# ---------------------------------------------------------------------------


@router.get(
    "/admin/corporate/accounts",
    response_model=list[CorporateAccountResponse],
    summary="Admin: list all corporate accounts",
)
async def admin_list_corporate_accounts(
    status_filter: CorporateAccountStatus | None = Query(None, alias="status"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """List all corporate accounts, optionally filtered by status."""
    q = select(CorporateAccount)
    if status_filter is not None:
        q = q.where(CorporateAccount.status == status_filter)
    q = q.order_by(CorporateAccount.created_at.desc())
    q = q.offset((page - 1) * page_size).limit(page_size)

    result = await db.execute(q)
    accounts = result.scalars().all()
    return [await _account_response(db, a) for a in accounts]


@router.get(
    "/admin/corporate/accounts/{account_id}",
    response_model=CorporateAccountResponse,
    summary="Admin: get a corporate account",
)
async def admin_get_corporate_account(
    account_id: int,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return full detail for a single corporate account."""
    account = await get_account(db, account_id)
    return await _account_response(db, account)


@router.put(
    "/admin/corporate/accounts/{account_id}/suspend",
    response_model=CorporateAccountResponse,
    summary="Admin: suspend a corporate account",
)
async def admin_suspend_corporate_account(
    account_id: int,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Suspend a corporate account, preventing new ride charges."""
    account = await suspend_account(db, account_id)
    return await _account_response(db, account)


@router.put(
    "/admin/corporate/accounts/{account_id}/activate",
    response_model=CorporateAccountResponse,
    summary="Admin: activate a corporate account",
)
async def admin_activate_corporate_account(
    account_id: int,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Activate (or re-activate) a corporate account."""
    account = await activate_account(db, account_id)
    return await _account_response(db, account)


# ---------------------------------------------------------------------------
# Platform admin: invoice management
# ---------------------------------------------------------------------------


@router.post(
    "/admin/corporate/accounts/{account_id}/invoices",
    response_model=CorporateInvoiceResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Admin: generate a draft invoice for a corporate account",
)
async def admin_generate_invoice(
    account_id: int,
    req: InvoiceGenerateRequest,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Generate a draft invoice covering the specified billing period."""
    invoice = await generate_invoice(
        db, account_id, req.period_start, req.period_end
    )
    return CorporateInvoiceResponse.model_validate(invoice)


@router.put(
    "/admin/corporate/invoices/{invoice_id}/issue",
    response_model=CorporateInvoiceResponse,
    summary="Admin: issue (send) a draft invoice",
)
async def admin_issue_invoice(
    invoice_id: int,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Transition an invoice from draft to issued and stamp issued_at."""
    invoice = await issue_invoice(db, invoice_id)
    return CorporateInvoiceResponse.model_validate(invoice)


@router.put(
    "/admin/corporate/invoices/{invoice_id}/paid",
    response_model=CorporateInvoiceResponse,
    summary="Admin: mark an invoice as paid",
)
async def admin_mark_invoice_paid(
    invoice_id: int,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Mark an invoice as paid and stamp paid_at."""
    invoice = await mark_invoice_paid(db, invoice_id)
    return CorporateInvoiceResponse.model_validate(invoice)


# ---------------------------------------------------------------------------
# Platform admin: summary
# ---------------------------------------------------------------------------


@router.get(
    "/admin/corporate/summary",
    response_model=CorporatePlatformSummary,
    summary="Admin: platform-wide corporate accounts summary",
)
async def admin_corporate_summary(
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return a platform-wide summary of corporate accounts.

    Includes total accounts by status, total active members, and
    revenue (total invoice amount) generated this month.
    """
    from datetime import date as date_type, datetime as dt_type, timezone as tz

    # Accounts by status
    status_rows = await db.execute(
        select(
            CorporateAccount.status,
            func.count(CorporateAccount.id).label("cnt"),
        ).group_by(CorporateAccount.status)
    )
    accounts_by_status: dict[str, int] = {}
    total_accounts = 0
    for row in status_rows:
        accounts_by_status[row.status.value] = row.cnt
        total_accounts += row.cnt

    # Total active members
    members_result = await db.execute(
        select(func.count(CorporateAccountMember.id)).where(
            CorporateAccountMember.is_active.is_(True)
        )
    )
    total_members = members_result.scalar() or 0

    # Revenue this month (issued + paid invoices)
    now = dt_type.now(tz.utc)
    month_start = date_type(now.year, now.month, 1)
    revenue_result = await db.execute(
        select(
            func.coalesce(func.sum(CorporateInvoice.total_amount), 0)
        ).where(
            CorporateInvoice.billing_period_start >= month_start,
            CorporateInvoice.status.in_(
                [InvoiceStatus.ISSUED, InvoiceStatus.PAID]
            ),
        )
    )
    revenue_this_month = Decimal(str(revenue_result.scalar() or 0))

    return CorporatePlatformSummary(
        total_accounts=total_accounts,
        accounts_by_status=accounts_by_status,
        total_members=total_members,
        revenue_this_month=revenue_this_month,
    )
