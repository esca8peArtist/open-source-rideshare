"""Service functions for corporate pre-paid credits.

Enterprise accounts can maintain a pre-loaded credit balance that is drawn down
as rides are completed.  All movements are recorded in an append-only ledger.

Public API
----------
get_or_create_credit_account   — idempotent setup; returns (account, created)
get_credit_balance             — return CorporateCreditAccount or 404
deposit_credits                — admin adds funds
deduct_credits                 — system deducts for a completed ride
refund_credits                 — return funds (cancellation / dispute)
adjust_credits                 — platform-admin manual correction (signed amount)
list_credit_transactions       — paginated ledger view
list_low_balance_accounts      — platform-admin: all accounts below their threshold
set_low_balance_threshold      — admin sets alert threshold
"""

from __future__ import annotations

from decimal import Decimal
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.corporate_credit_account import (
    CorporateCreditAccount,
    CorporateCreditTransaction,
    CreditTransactionType,
)


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


async def _get_credit_account(
    db: AsyncSession, account_id: int
) -> CorporateCreditAccount:
    """Return the credit account for *account_id*; raise 404 if none exists."""
    result = await db.execute(
        select(CorporateCreditAccount).where(
            CorporateCreditAccount.account_id == account_id
        )
    )
    credit_account = result.scalar_one_or_none()
    if credit_account is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No credit account found for this corporate account.",
        )
    return credit_account


def _record_transaction(
    credit_account: CorporateCreditAccount,
    transaction_type: CreditTransactionType,
    amount_usd: Decimal,
    new_balance: Decimal,
    description: str,
    reference_id: Optional[str],
    reference_type: Optional[str],
    created_by_id: Optional[int],
) -> CorporateCreditTransaction:
    """Construct and return (unsaved) a ledger entry."""
    return CorporateCreditTransaction(
        account_id=credit_account.account_id,
        credit_account_id=credit_account.id,
        transaction_type=transaction_type,
        amount_usd=amount_usd,
        balance_after_usd=new_balance,
        reference_id=reference_id,
        reference_type=reference_type,
        description=description,
        created_by_id=created_by_id,
    )


# ---------------------------------------------------------------------------
# Public service API
# ---------------------------------------------------------------------------


async def get_or_create_credit_account(
    db: AsyncSession, account_id: int
) -> tuple[CorporateCreditAccount, bool]:
    """Return the credit account for *account_id*, creating it if necessary.

    Returns:
        (CorporateCreditAccount, created: bool)
    """
    result = await db.execute(
        select(CorporateCreditAccount).where(
            CorporateCreditAccount.account_id == account_id
        )
    )
    existing = result.scalar_one_or_none()
    if existing is not None:
        return existing, False

    credit_account = CorporateCreditAccount(
        account_id=account_id,
        balance_usd=Decimal("0.00"),
        total_deposited_usd=Decimal("0.00"),
        total_spent_usd=Decimal("0.00"),
        total_refunded_usd=Decimal("0.00"),
    )
    db.add(credit_account)
    await db.flush()
    return credit_account, True


async def get_credit_balance(
    db: AsyncSession, account_id: int
) -> CorporateCreditAccount:
    """Return the credit account summary; raises 404 if not yet initialised."""
    return await _get_credit_account(db, account_id)


async def deposit_credits(
    db: AsyncSession,
    account_id: int,
    amount_usd: Decimal,
    description: str = "",
    created_by_id: Optional[int] = None,
    reference_id: Optional[str] = None,
    reference_type: Optional[str] = None,
) -> CorporateCreditTransaction:
    """Add *amount_usd* to the corporate credit balance.

    Raises 422 if amount is not positive.
    Raises 404 if the credit account does not exist.
    """
    if amount_usd <= Decimal("0"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Deposit amount must be greater than zero.",
        )

    credit_account = await _get_credit_account(db, account_id)
    new_balance = credit_account.balance_usd + amount_usd

    credit_account.balance_usd = new_balance
    credit_account.total_deposited_usd += amount_usd

    txn = _record_transaction(
        credit_account,
        CreditTransactionType.deposit,
        amount_usd,
        new_balance,
        description or f"Deposit of ${amount_usd:.2f}",
        reference_id,
        reference_type,
        created_by_id,
    )
    db.add(txn)
    await db.flush()
    return txn


async def deduct_credits(
    db: AsyncSession,
    account_id: int,
    amount_usd: Decimal,
    description: str = "",
    reference_id: Optional[str] = None,
    reference_type: Optional[str] = None,
    created_by_id: Optional[int] = None,
) -> CorporateCreditTransaction:
    """Deduct *amount_usd* from the credit balance for a completed ride.

    Raises 422 if amount is not positive.
    Raises 409 if the account has insufficient balance.
    Raises 404 if the credit account does not exist.
    """
    if amount_usd <= Decimal("0"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Deduction amount must be greater than zero.",
        )

    credit_account = await _get_credit_account(db, account_id)
    if credit_account.balance_usd < amount_usd:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Insufficient credit balance.  Available: "
                f"${credit_account.balance_usd:.2f}, requested: ${amount_usd:.2f}."
            ),
        )

    new_balance = credit_account.balance_usd - amount_usd
    credit_account.balance_usd = new_balance
    credit_account.total_spent_usd += amount_usd

    txn = _record_transaction(
        credit_account,
        CreditTransactionType.deduction,
        amount_usd,
        new_balance,
        description or f"Deduction of ${amount_usd:.2f}",
        reference_id,
        reference_type,
        created_by_id,
    )
    db.add(txn)
    await db.flush()
    return txn


async def refund_credits(
    db: AsyncSession,
    account_id: int,
    amount_usd: Decimal,
    description: str = "",
    reference_id: Optional[str] = None,
    reference_type: Optional[str] = None,
    created_by_id: Optional[int] = None,
) -> CorporateCreditTransaction:
    """Return *amount_usd* to the balance (ride cancellation / dispute resolution).

    Raises 422 if amount is not positive.
    Raises 404 if the credit account does not exist.
    """
    if amount_usd <= Decimal("0"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Refund amount must be greater than zero.",
        )

    credit_account = await _get_credit_account(db, account_id)
    new_balance = credit_account.balance_usd + amount_usd

    credit_account.balance_usd = new_balance
    credit_account.total_refunded_usd += amount_usd

    txn = _record_transaction(
        credit_account,
        CreditTransactionType.refund,
        amount_usd,
        new_balance,
        description or f"Refund of ${amount_usd:.2f}",
        reference_id,
        reference_type,
        created_by_id,
    )
    db.add(txn)
    await db.flush()
    return txn


async def adjust_credits(
    db: AsyncSession,
    account_id: int,
    signed_amount_usd: Decimal,
    description: str = "",
    reference_id: Optional[str] = None,
    reference_type: Optional[str] = None,
    created_by_id: Optional[int] = None,
) -> CorporateCreditTransaction:
    """Platform-admin manual correction.  *signed_amount_usd* may be negative.

    Raises 422 if the amount is zero or if a negative adjustment would produce
    a negative balance.
    Raises 404 if the credit account does not exist.
    """
    if signed_amount_usd == Decimal("0"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Adjustment amount must not be zero.",
        )

    credit_account = await _get_credit_account(db, account_id)
    new_balance = credit_account.balance_usd + signed_amount_usd

    if new_balance < Decimal("0"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"Adjustment would produce a negative balance "
                f"(current: ${credit_account.balance_usd:.2f}, "
                f"adjustment: ${signed_amount_usd:.2f})."
            ),
        )

    credit_account.balance_usd = new_balance
    if signed_amount_usd > 0:
        credit_account.total_deposited_usd += signed_amount_usd

    txn = _record_transaction(
        credit_account,
        CreditTransactionType.adjustment,
        abs(signed_amount_usd),
        new_balance,
        description or f"Manual adjustment of ${signed_amount_usd:.2f}",
        reference_id,
        reference_type,
        created_by_id,
    )
    db.add(txn)
    await db.flush()
    return txn


async def list_credit_transactions(
    db: AsyncSession,
    account_id: int,
    transaction_type: Optional[CreditTransactionType] = None,
    limit: int = 50,
    offset: int = 0,
) -> list[CorporateCreditTransaction]:
    """Return paginated ledger entries for *account_id*, newest first.

    Optionally filter by *transaction_type*.
    """
    query = (
        select(CorporateCreditTransaction)
        .where(CorporateCreditTransaction.account_id == account_id)
        .order_by(CorporateCreditTransaction.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    if transaction_type is not None:
        query = query.where(
            CorporateCreditTransaction.transaction_type == transaction_type
        )
    result = await db.execute(query)
    return list(result.scalars().all())


async def list_low_balance_accounts(
    db: AsyncSession,
) -> list[CorporateCreditAccount]:
    """Return all credit accounts where balance_usd < low_balance_threshold_usd.

    Only accounts that have a threshold configured are included.
    """
    result = await db.execute(
        select(CorporateCreditAccount).where(
            CorporateCreditAccount.low_balance_threshold_usd.is_not(None),
            CorporateCreditAccount.balance_usd
            < CorporateCreditAccount.low_balance_threshold_usd,
        )
    )
    return list(result.scalars().all())


async def set_low_balance_threshold(
    db: AsyncSession,
    account_id: int,
    threshold_usd: Optional[Decimal],
) -> CorporateCreditAccount:
    """Set or clear the low-balance alert threshold for an account.

    Pass ``None`` to disable the alert.
    Raises 422 if a non-None threshold is not positive.
    Raises 404 if the credit account does not exist.
    """
    if threshold_usd is not None and threshold_usd < Decimal("0"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Threshold must be zero or positive (pass null to disable).",
        )

    credit_account = await _get_credit_account(db, account_id)
    credit_account.low_balance_threshold_usd = threshold_usd
    await db.flush()
    return credit_account
