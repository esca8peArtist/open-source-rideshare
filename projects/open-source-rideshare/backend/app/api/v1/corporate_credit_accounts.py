"""Corporate Pre-paid Credit endpoints.

Enterprise admins manage a pre-loaded credit balance.  Rides are deducted from
available credits; all movements are recorded in an append-only ledger.

Member endpoints (require corporate account membership):
  GET    /corporate/accounts/me/credits                           — balance summary
  GET    /corporate/accounts/me/credits/transactions             — transaction history

Admin endpoints (require account membership):
  POST   /corporate/accounts/me/credits/deposit                  — add funds
  POST   /corporate/accounts/me/credits/refund                   — refund ride
  PUT    /corporate/accounts/me/credits/threshold                — set low-balance alert

Platform-admin endpoints:
  GET    /admin/corporate/accounts/{account_id}/credits                   — any account balance
  GET    /admin/corporate/accounts/{account_id}/credits/transactions      — any account history
  POST   /admin/corporate/accounts/{account_id}/credits/adjust            — manual adjustment
  GET    /admin/corporate/credits/low-balance                             — all low-balance accounts
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, Query, status
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, require_admin
from app.models.corporate_credit_account import CreditTransactionType
from app.models.user import User
from app.schemas.corporate_credit_account import (
    CreditAccountResponse,
    CreditAdjustRequest,
    CreditDepositRequest,
    CreditRefundRequest,
    CreditThresholdRequest,
    CreditTransactionListResponse,
    CreditTransactionResponse,
    LowBalanceListResponse,
)
from app.services.corporate_account_mgmt import get_user_account
from app.services.corporate_credit_account import (
    adjust_credits,
    deposit_credits,
    get_or_create_credit_account,
    list_credit_transactions,
    list_low_balance_accounts,
    refund_credits,
    set_low_balance_threshold,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["corporate-credits"])


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _resolve_account_id(db: AsyncSession, user_id: int) -> int:
    account = await get_user_account(db, user_id)
    if account is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="You are not a member of any corporate account.",
        )
    return account.id


def _to_credit_response(obj) -> CreditAccountResponse:
    return CreditAccountResponse.from_orm_with_flag(obj)


def _to_txn_response(txn) -> CreditTransactionResponse:
    return CreditTransactionResponse.model_validate(txn)


# ---------------------------------------------------------------------------
# Member: balance summary
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/accounts/me/credits",
    response_model=CreditAccountResponse,
    summary="Member: get corporate credit balance",
)
async def get_my_credit_balance(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return the current credit balance and running totals for the caller's
    corporate account.  Initialises the credit account if it does not yet exist."""
    account_id = await _resolve_account_id(db, user.id)
    credit_account, created = await get_or_create_credit_account(db, account_id)
    if created:
        await db.commit()
    return _to_credit_response(credit_account)


# ---------------------------------------------------------------------------
# Member: transaction history
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/accounts/me/credits/transactions",
    response_model=CreditTransactionListResponse,
    summary="Member: list credit transaction history",
)
async def list_my_credit_transactions(
    transaction_type: Optional[CreditTransactionType] = Query(
        None, description="Filter by transaction type."
    ),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return paginated credit ledger entries for the caller's corporate account,
    newest first.  Optionally filter by transaction type."""
    account_id = await _resolve_account_id(db, user.id)
    txns = await list_credit_transactions(
        db, account_id, transaction_type=transaction_type, limit=limit, offset=offset
    )
    return CreditTransactionListResponse(
        account_id=account_id,
        total_returned=len(txns),
        items=[_to_txn_response(t) for t in txns],
    )


# ---------------------------------------------------------------------------
# Admin: deposit credits
# ---------------------------------------------------------------------------


@router.post(
    "/corporate/accounts/me/credits/deposit",
    response_model=CreditTransactionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Admin: deposit credits into corporate account",
)
async def deposit_my_credits(
    data: CreditDepositRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Add funds to the corporate credit balance.  Requires account admin role.

    The credit account is initialised automatically if it does not yet exist.
    """
    account_id = await _resolve_account_id(db, user.id)
    # Ensure credit account exists
    await get_or_create_credit_account(db, account_id)
    txn = await deposit_credits(
        db,
        account_id=account_id,
        amount_usd=data.amount_usd,
        description=data.description,
        created_by_id=user.id,
        reference_id=data.reference_id,
        reference_type=data.reference_type,
    )
    await db.commit()
    return _to_txn_response(txn)


# ---------------------------------------------------------------------------
# Admin: refund credits
# ---------------------------------------------------------------------------


@router.post(
    "/corporate/accounts/me/credits/refund",
    response_model=CreditTransactionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Admin: refund credits to corporate account",
)
async def refund_my_credits(
    data: CreditRefundRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return funds to the credit balance (ride cancellation or dispute resolution)."""
    account_id = await _resolve_account_id(db, user.id)
    await get_or_create_credit_account(db, account_id)
    txn = await refund_credits(
        db,
        account_id=account_id,
        amount_usd=data.amount_usd,
        description=data.description,
        reference_id=data.reference_id,
        reference_type=data.reference_type,
        created_by_id=user.id,
    )
    await db.commit()
    return _to_txn_response(txn)


# ---------------------------------------------------------------------------
# Admin: set low-balance threshold
# ---------------------------------------------------------------------------


@router.put(
    "/corporate/accounts/me/credits/threshold",
    response_model=CreditAccountResponse,
    summary="Admin: set low-balance alert threshold",
)
async def set_my_credit_threshold(
    data: CreditThresholdRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Set or clear the low-balance notification threshold.

    When balance drops below this value the account appears in the platform-admin
    low-balance list.  Pass ``threshold_usd: null`` to disable the alert.

    The credit account is initialised automatically if it does not yet exist.
    """
    account_id = await _resolve_account_id(db, user.id)
    await get_or_create_credit_account(db, account_id)
    credit_account = await set_low_balance_threshold(db, account_id, data.threshold_usd)
    await db.commit()
    return _to_credit_response(credit_account)


# ---------------------------------------------------------------------------
# Platform-admin: view any account balance
# ---------------------------------------------------------------------------


@router.get(
    "/admin/corporate/accounts/{account_id}/credits",
    response_model=CreditAccountResponse,
    summary="Platform admin: get credit balance for any corporate account",
)
async def platform_admin_get_credits(
    account_id: int,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return the credit balance for any corporate account."""
    credit_account, created = await get_or_create_credit_account(db, account_id)
    if created:
        await db.commit()
    return _to_credit_response(credit_account)


# ---------------------------------------------------------------------------
# Platform-admin: view any account transactions
# ---------------------------------------------------------------------------


@router.get(
    "/admin/corporate/accounts/{account_id}/credits/transactions",
    response_model=CreditTransactionListResponse,
    summary="Platform admin: list credit transactions for any corporate account",
)
async def platform_admin_list_credit_transactions(
    account_id: int,
    transaction_type: Optional[CreditTransactionType] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return paginated ledger entries for any corporate account."""
    txns = await list_credit_transactions(
        db, account_id, transaction_type=transaction_type, limit=limit, offset=offset
    )
    return CreditTransactionListResponse(
        account_id=account_id,
        total_returned=len(txns),
        items=[_to_txn_response(t) for t in txns],
    )


# ---------------------------------------------------------------------------
# Platform-admin: manual adjustment
# ---------------------------------------------------------------------------


@router.post(
    "/admin/corporate/accounts/{account_id}/credits/adjust",
    response_model=CreditTransactionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Platform admin: manual credit adjustment",
)
async def platform_admin_adjust_credits(
    account_id: int,
    data: CreditAdjustRequest,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Apply a signed adjustment to any corporate account's credit balance.

    Use positive values to add funds and negative values to remove funds.
    A negative adjustment that would produce a balance below zero is rejected.
    """
    await get_or_create_credit_account(db, account_id)
    txn = await adjust_credits(
        db,
        account_id=account_id,
        signed_amount_usd=data.signed_amount_usd,
        description=data.description,
        reference_id=data.reference_id,
        reference_type=data.reference_type,
        created_by_id=admin.id,
    )
    await db.commit()
    return _to_txn_response(txn)


# ---------------------------------------------------------------------------
# Platform-admin: low-balance accounts
# ---------------------------------------------------------------------------


@router.get(
    "/admin/corporate/credits/low-balance",
    response_model=LowBalanceListResponse,
    summary="Platform admin: list all corporate accounts currently below their low-balance threshold",
)
async def platform_admin_low_balance_accounts(
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return all corporate credit accounts whose balance is below the configured
    low-balance threshold.  Accounts without a threshold set are excluded."""
    accounts = await list_low_balance_accounts(db)
    return LowBalanceListResponse(
        total=len(accounts),
        items=[_to_credit_response(a) for a in accounts],
    )
