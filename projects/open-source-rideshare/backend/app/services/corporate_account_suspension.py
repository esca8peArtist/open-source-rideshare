"""Service layer for Corporate Account Suspension & Reinstatement.

Platform admins can suspend corporate accounts for billing, compliance, or
policy reasons.  Reinstatement restores normal account operation.  Every
suspension and reinstatement event is persisted for audit purposes.

Public surface
--------------
suspend_account(db, account_id, suspended_by_id, reason, note) -> SuspensionResponse
reinstate_account(db, account_id, reinstated_by_id, reinstatement_note) -> SuspensionResponse
get_active_suspension(db, account_id) -> CorporateAccountSuspension | None
is_account_suspended(db, account_id) -> bool
list_suspension_history(db, account_id, skip, limit) -> list[CorporateAccountSuspension]
list_all_suspended_accounts(db, skip, limit) -> list[CorporateAccountSuspension]
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional, Sequence

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.corporate_account_suspension import (
    CorporateAccountSuspension,
    SuspensionReason,
)
from app.schemas.corporate_account_suspension import SuspensionResponse


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _to_response(suspension: CorporateAccountSuspension) -> SuspensionResponse:
    """Convert a model instance to a SuspensionResponse schema object."""
    return SuspensionResponse(
        id=suspension.id,
        account_id=suspension.account_id,
        suspended_by_id=suspension.suspended_by_id,
        reason=suspension.reason,
        suspension_note=suspension.suspension_note,
        suspended_at=suspension.suspended_at,
        reinstated_at=suspension.reinstated_at,
        reinstated_by_id=suspension.reinstated_by_id,
        reinstatement_note=suspension.reinstatement_note,
        is_active=suspension.is_active,
    )


# ---------------------------------------------------------------------------
# Core operations
# ---------------------------------------------------------------------------


async def suspend_account(
    db: AsyncSession,
    account_id: int,
    suspended_by_id: Optional[int],
    reason: SuspensionReason,
    note: Optional[str],
) -> SuspensionResponse:
    """Suspend a corporate account.

    Creates a new suspension record with is_active=True.  Only one active
    suspension is permitted per account; raises HTTP 409 when one already
    exists.

    Args:
        db:               Async database session.
        account_id:       Corporate account to suspend.
        suspended_by_id:  ID of the admin performing the suspension, or None for
                          system-initiated suspensions.
        reason:           Structured reason category.
        note:             Optional free-text admin note.

    Returns:
        SuspensionResponse for the newly created suspension.

    Raises:
        HTTP 409: When the account already has an active suspension.
    """
    existing = await get_active_suspension(db, account_id)
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This account already has an active suspension.",
        )

    suspension = CorporateAccountSuspension(
        account_id=account_id,
        suspended_by_id=suspended_by_id,
        reason=reason,
        suspension_note=note,
        is_active=True,
    )
    db.add(suspension)
    await db.commit()
    await db.refresh(suspension)
    return _to_response(suspension)


async def reinstate_account(
    db: AsyncSession,
    account_id: int,
    reinstated_by_id: Optional[int],
    reinstatement_note: Optional[str],
) -> SuspensionResponse:
    """Reinstate a suspended corporate account.

    Marks the active suspension as resolved by setting is_active=False and
    recording the reinstatement timestamp and actor.

    Args:
        db:                  Async database session.
        account_id:          Corporate account to reinstate.
        reinstated_by_id:    ID of the admin performing the reinstatement.
        reinstatement_note:  Optional free-text note recorded on reinstatement.

    Returns:
        Updated SuspensionResponse reflecting the reinstatement.

    Raises:
        HTTP 404: When no active suspension exists for the account.
    """
    suspension = await get_active_suspension(db, account_id)
    if suspension is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No active suspension found for this account.",
        )

    suspension.is_active = False
    suspension.reinstated_at = datetime.now(timezone.utc)
    suspension.reinstated_by_id = reinstated_by_id
    suspension.reinstatement_note = reinstatement_note

    await db.commit()
    await db.refresh(suspension)
    return _to_response(suspension)


# ---------------------------------------------------------------------------
# Query helpers
# ---------------------------------------------------------------------------


async def get_active_suspension(
    db: AsyncSession,
    account_id: int,
) -> CorporateAccountSuspension | None:
    """Return the active suspension for an account, or None if not suspended.

    Args:
        db:         Async database session.
        account_id: Corporate account identifier.

    Returns:
        The active CorporateAccountSuspension model instance, or None.
    """
    result = await db.execute(
        select(CorporateAccountSuspension).where(
            CorporateAccountSuspension.account_id == account_id,
            CorporateAccountSuspension.is_active.is_(True),
        )
    )
    return result.scalar_one_or_none()


async def is_account_suspended(
    db: AsyncSession,
    account_id: int,
) -> bool:
    """Return True when the account has an active suspension.

    Args:
        db:         Async database session.
        account_id: Corporate account identifier.

    Returns:
        Boolean indicating whether the account is currently suspended.
    """
    suspension = await get_active_suspension(db, account_id)
    return suspension is not None


async def list_suspension_history(
    db: AsyncSession,
    account_id: int,
    skip: int = 0,
    limit: int = 50,
) -> Sequence[CorporateAccountSuspension]:
    """Return all suspension records for an account, most recent first.

    Args:
        db:         Async database session.
        account_id: Corporate account identifier.
        skip:       Number of records to skip (pagination offset).
        limit:      Maximum number of records to return.

    Returns:
        List of CorporateAccountSuspension model instances ordered by
        suspended_at descending.
    """
    result = await db.execute(
        select(CorporateAccountSuspension)
        .where(CorporateAccountSuspension.account_id == account_id)
        .order_by(CorporateAccountSuspension.suspended_at.desc())
        .offset(skip)
        .limit(limit)
    )
    return result.scalars().all()


async def list_all_suspended_accounts(
    db: AsyncSession,
    skip: int = 0,
    limit: int = 50,
) -> Sequence[CorporateAccountSuspension]:
    """Return all currently active suspensions across all accounts.

    Intended for platform-admin dashboards.  Ordered by suspended_at
    descending so the most recently suspended accounts appear first.

    Args:
        db:    Async database session.
        skip:  Number of records to skip (pagination offset).
        limit: Maximum number of records to return.

    Returns:
        List of active CorporateAccountSuspension model instances.
    """
    result = await db.execute(
        select(CorporateAccountSuspension)
        .where(CorporateAccountSuspension.is_active.is_(True))
        .order_by(CorporateAccountSuspension.suspended_at.desc())
        .offset(skip)
        .limit(limit)
    )
    return result.scalars().all()
