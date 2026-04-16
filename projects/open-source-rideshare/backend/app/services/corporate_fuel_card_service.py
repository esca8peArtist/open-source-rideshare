"""Service functions for corporate fuel card management.

Fleet managers register company fuel cards, assign them to vehicles and/or
drivers, and record fuel transactions.  Admins can set per-card monthly
spending limits and view aggregate statistics.

Public API
----------
issue_card              — register a new fuel card; 409 on duplicate nickname
get_card                — fetch one card by id; 404 if not in account
list_cards              — list cards for account; vehicle/driver/is_active filters
update_card             — partial update; 409 on nickname collision
assign_to_vehicle       — attach card to a fleet vehicle; 409 if already assigned
assign_to_driver        — associate card with a driver; 409 if already assigned
unassign                — remove vehicle and/or driver assignment
deactivate_card         — 409 if already inactive
reactivate_card         — 409 if already active
record_transaction      — append a fuel transaction; 409 if card inactive
list_card_transactions  — list transactions for a card; optional date filters
get_card_summary        — per-card aggregate stats + monthly utilization
get_account_fuel_summary — account-level aggregate stats
list_all_platform       — platform-admin cross-account listing
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import extract, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.corporate_fuel_card import (
    CardNetwork,
    CorporateFuelCard,
    CorporateFuelCardTransaction,
    FuelType,
)


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _now_utc() -> datetime:
    return datetime.now(tz=timezone.utc)


def _current_year_month() -> tuple[int, int]:
    now = _now_utc()
    return now.year, now.month


async def _get_card_or_404(
    db: AsyncSession,
    account_id: int,
    card_id: int,
) -> CorporateFuelCard:
    result = await db.execute(
        select(CorporateFuelCard).where(
            CorporateFuelCard.id == card_id,
            CorporateFuelCard.account_id == account_id,
        )
    )
    card = result.scalar_one_or_none()
    if card is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Fuel card not found.",
        )
    return card


async def _nickname_exists(
    db: AsyncSession,
    account_id: int,
    nickname: str,
    exclude_id: Optional[int] = None,
) -> bool:
    query = select(CorporateFuelCard.id).where(
        CorporateFuelCard.account_id == account_id,
        CorporateFuelCard.nickname == nickname,
    )
    if exclude_id is not None:
        query = query.where(CorporateFuelCard.id != exclude_id)
    result = await db.execute(query)
    return result.scalar_one_or_none() is not None


# ---------------------------------------------------------------------------
# Card management
# ---------------------------------------------------------------------------


async def issue_card(
    db: AsyncSession,
    account_id: int,
    card_last_four: str,
    card_network: CardNetwork,
    nickname: str,
    issued_by_id: int,
    assigned_vehicle_id: Optional[uuid.UUID] = None,
    assigned_driver_id: Optional[int] = None,
    monthly_limit_usd: Optional[Decimal] = None,
    notes: Optional[str] = None,
) -> CorporateFuelCard:
    """Register a new company fuel card.

    Raises 409 if a card with the same *nickname* already exists for the account.
    """
    if await _nickname_exists(db, account_id, nickname):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A fuel card with nickname '{nickname}' already exists for this account.",
        )

    card = CorporateFuelCard(
        account_id=account_id,
        card_last_four=card_last_four,
        card_network=card_network,
        nickname=nickname,
        assigned_vehicle_id=assigned_vehicle_id,
        assigned_driver_id=assigned_driver_id,
        monthly_limit_usd=monthly_limit_usd,
        issued_by_id=issued_by_id,
        notes=notes,
    )
    db.add(card)
    await db.flush()
    return card


async def get_card(
    db: AsyncSession,
    account_id: int,
    card_id: int,
) -> CorporateFuelCard:
    """Return a fuel card by id.  Raises 404 if not found."""
    return await _get_card_or_404(db, account_id, card_id)


async def list_cards(
    db: AsyncSession,
    account_id: int,
    is_active: Optional[bool] = None,
    assigned_vehicle_id: Optional[uuid.UUID] = None,
    assigned_driver_id: Optional[int] = None,
    limit: int = 100,
    offset: int = 0,
) -> list[CorporateFuelCard]:
    """Return fuel cards for *account_id*, with optional filters.

    Results are ordered by nickname ascending.
    """
    query = (
        select(CorporateFuelCard)
        .where(CorporateFuelCard.account_id == account_id)
        .order_by(CorporateFuelCard.nickname)
        .limit(limit)
        .offset(offset)
    )
    if is_active is not None:
        query = query.where(CorporateFuelCard.is_active == is_active)
    if assigned_vehicle_id is not None:
        query = query.where(
            CorporateFuelCard.assigned_vehicle_id == assigned_vehicle_id
        )
    if assigned_driver_id is not None:
        query = query.where(
            CorporateFuelCard.assigned_driver_id == assigned_driver_id
        )
    result = await db.execute(query)
    return list(result.scalars().all())


async def update_card(
    db: AsyncSession,
    account_id: int,
    card_id: int,
    **kwargs,
) -> CorporateFuelCard:
    """Partially update a fuel card.

    Raises 409 if the new *nickname* collides with another card in the account.
    """
    card = await _get_card_or_404(db, account_id, card_id)

    if "nickname" in kwargs and kwargs["nickname"] is not None:
        if await _nickname_exists(db, account_id, kwargs["nickname"], exclude_id=card_id):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"A fuel card with nickname '{kwargs['nickname']}' already exists for this account.",
            )

    for key, value in kwargs.items():
        setattr(card, key, value)

    await db.flush()
    return card


async def assign_to_vehicle(
    db: AsyncSession,
    account_id: int,
    card_id: int,
    vehicle_id: uuid.UUID,
) -> CorporateFuelCard:
    """Assign (or re-assign) a fuel card to a fleet vehicle.

    Raises 409 if the card is already assigned to the same vehicle.
    Silently replaces a prior different-vehicle assignment.
    """
    card = await _get_card_or_404(db, account_id, card_id)

    if card.assigned_vehicle_id == vehicle_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Card is already assigned to this vehicle.",
        )

    card.assigned_vehicle_id = vehicle_id
    await db.flush()
    return card


async def assign_to_driver(
    db: AsyncSession,
    account_id: int,
    card_id: int,
    driver_id: int,
) -> CorporateFuelCard:
    """Associate (or re-associate) a fuel card with a driver.

    Raises 409 if the card is already assigned to the same driver.
    Silently replaces a prior different-driver assignment.
    """
    card = await _get_card_or_404(db, account_id, card_id)

    if card.assigned_driver_id == driver_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Card is already assigned to this driver.",
        )

    card.assigned_driver_id = driver_id
    await db.flush()
    return card


async def unassign(
    db: AsyncSession,
    account_id: int,
    card_id: int,
    unassign_vehicle: bool = True,
    unassign_driver: bool = True,
) -> CorporateFuelCard:
    """Remove vehicle and/or driver assignment from a fuel card."""
    card = await _get_card_or_404(db, account_id, card_id)

    if unassign_vehicle:
        card.assigned_vehicle_id = None
    if unassign_driver:
        card.assigned_driver_id = None

    await db.flush()
    return card


async def deactivate_card(
    db: AsyncSession,
    account_id: int,
    card_id: int,
) -> CorporateFuelCard:
    """Mark a fuel card inactive.  Raises 409 if already inactive."""
    card = await _get_card_or_404(db, account_id, card_id)
    if not card.is_active:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Fuel card is already inactive.",
        )
    card.is_active = False
    await db.flush()
    return card


async def reactivate_card(
    db: AsyncSession,
    account_id: int,
    card_id: int,
) -> CorporateFuelCard:
    """Mark a fuel card active.  Raises 409 if already active."""
    card = await _get_card_or_404(db, account_id, card_id)
    if card.is_active:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Fuel card is already active.",
        )
    card.is_active = True
    await db.flush()
    return card


# ---------------------------------------------------------------------------
# Transactions
# ---------------------------------------------------------------------------


async def record_transaction(
    db: AsyncSession,
    account_id: int,
    card_id: int,
    recorded_by_id: int,
    transaction_date: date,
    merchant_name: str,
    fuel_type: FuelType,
    amount_usd: Decimal,
    gallons: Optional[Decimal] = None,
    odometer_miles: Optional[int] = None,
    notes: Optional[str] = None,
) -> CorporateFuelCardTransaction:
    """Record a fuel transaction against a card.

    Raises 404 if the card is not found.
    Raises 409 if the card is inactive.
    """
    card = await _get_card_or_404(db, account_id, card_id)
    if not card.is_active:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot record a transaction against an inactive fuel card.",
        )

    txn = CorporateFuelCardTransaction(
        fuel_card_id=card_id,
        account_id=account_id,
        transaction_date=transaction_date,
        merchant_name=merchant_name,
        fuel_type=fuel_type,
        gallons=gallons,
        amount_usd=amount_usd,
        odometer_miles=odometer_miles,
        notes=notes,
        recorded_by_id=recorded_by_id,
    )
    db.add(txn)
    await db.flush()
    return txn


async def list_card_transactions(
    db: AsyncSession,
    account_id: int,
    card_id: int,
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
    limit: int = 100,
    offset: int = 0,
) -> list[CorporateFuelCardTransaction]:
    """Return transactions for a specific fuel card.

    Ordered by transaction_date descending.  Raises 404 if card not found.
    """
    # Verify the card belongs to this account.
    await _get_card_or_404(db, account_id, card_id)

    query = (
        select(CorporateFuelCardTransaction)
        .where(CorporateFuelCardTransaction.fuel_card_id == card_id)
        .order_by(CorporateFuelCardTransaction.transaction_date.desc())
        .limit(limit)
        .offset(offset)
    )
    if from_date is not None:
        query = query.where(
            CorporateFuelCardTransaction.transaction_date >= from_date
        )
    if to_date is not None:
        query = query.where(
            CorporateFuelCardTransaction.transaction_date <= to_date
        )
    result = await db.execute(query)
    return list(result.scalars().all())


# ---------------------------------------------------------------------------
# Summaries
# ---------------------------------------------------------------------------


async def get_card_summary(
    db: AsyncSession,
    account_id: int,
    card_id: int,
) -> dict:
    """Return aggregate statistics for a single fuel card.

    Includes total transactions, total spend, current-month spend, monthly
    utilization percentage (when a limit is configured), and a per-fuel-type
    breakdown.
    """
    card = await _get_card_or_404(db, account_id, card_id)

    # Per-fuel-type breakdown (all time)
    rows = await db.execute(
        select(
            CorporateFuelCardTransaction.fuel_type,
            func.count(CorporateFuelCardTransaction.id).label("cnt"),
            func.coalesce(
                func.sum(CorporateFuelCardTransaction.gallons), 0
            ).label("total_gallons"),
            func.coalesce(
                func.sum(CorporateFuelCardTransaction.amount_usd), 0
            ).label("total_amount"),
        )
        .where(CorporateFuelCardTransaction.fuel_card_id == card_id)
        .group_by(CorporateFuelCardTransaction.fuel_type)
    )

    by_fuel_type = []
    total_transactions = 0
    total_amount = Decimal("0")

    for row in rows:
        ft, cnt, gal_sum, amt_sum = row
        gallons_val = Decimal(str(gal_sum)) if gal_sum else None
        amount_val = Decimal(str(amt_sum))
        by_fuel_type.append(
            {
                "fuel_type": ft,
                "transaction_count": cnt,
                "total_gallons": gallons_val,
                "total_amount_usd": amount_val,
            }
        )
        total_transactions += cnt
        total_amount += amount_val

    # Current-month spend
    year, month = _current_year_month()
    month_result = await db.execute(
        select(
            func.coalesce(
                func.sum(CorporateFuelCardTransaction.amount_usd), 0
            ).label("month_amount")
        ).where(
            CorporateFuelCardTransaction.fuel_card_id == card_id,
            extract("year", CorporateFuelCardTransaction.transaction_date) == year,
            extract("month", CorporateFuelCardTransaction.transaction_date) == month,
        )
    )
    current_month_amount = Decimal(str(month_result.scalar_one()))

    # Utilization percentage
    utilization_pct = None
    if card.monthly_limit_usd is not None:
        limit = Decimal(str(card.monthly_limit_usd))
        if limit > 0:
            utilization_pct = (current_month_amount / limit * 100).quantize(
                Decimal("0.01")
            )

    return {
        "card_id": card.id,
        "nickname": card.nickname,
        "is_active": card.is_active,
        "monthly_limit_usd": (
            Decimal(str(card.monthly_limit_usd))
            if card.monthly_limit_usd is not None
            else None
        ),
        "total_transactions": total_transactions,
        "total_amount_usd": total_amount,
        "current_month_amount_usd": current_month_amount,
        "monthly_limit_utilization_pct": utilization_pct,
        "by_fuel_type": by_fuel_type,
    }


async def get_account_fuel_summary(
    db: AsyncSession,
    account_id: int,
) -> dict:
    """Return account-level aggregate fuel card statistics.

    Includes card counts, total and current-month spend, and a per-fuel-type
    breakdown across all account cards.
    """
    # Card counts
    total_cards_r = await db.execute(
        select(func.count(CorporateFuelCard.id)).where(
            CorporateFuelCard.account_id == account_id
        )
    )
    active_cards_r = await db.execute(
        select(func.count(CorporateFuelCard.id)).where(
            CorporateFuelCard.account_id == account_id,
            CorporateFuelCard.is_active.is_(True),
        )
    )
    total_cards = total_cards_r.scalar_one()
    active_cards = active_cards_r.scalar_one()

    # Per-fuel-type breakdown
    rows = await db.execute(
        select(
            CorporateFuelCardTransaction.fuel_type,
            func.count(CorporateFuelCardTransaction.id).label("cnt"),
            func.coalesce(
                func.sum(CorporateFuelCardTransaction.gallons), 0
            ).label("total_gallons"),
            func.coalesce(
                func.sum(CorporateFuelCardTransaction.amount_usd), 0
            ).label("total_amount"),
        )
        .where(CorporateFuelCardTransaction.account_id == account_id)
        .group_by(CorporateFuelCardTransaction.fuel_type)
    )

    by_fuel_type = []
    total_transactions = 0
    total_amount = Decimal("0")

    for row in rows:
        ft, cnt, gal_sum, amt_sum = row
        gallons_val = Decimal(str(gal_sum)) if gal_sum else None
        amount_val = Decimal(str(amt_sum))
        by_fuel_type.append(
            {
                "fuel_type": ft,
                "transaction_count": cnt,
                "total_gallons": gallons_val,
                "total_amount_usd": amount_val,
            }
        )
        total_transactions += cnt
        total_amount += amount_val

    # Current-month spend
    year, month = _current_year_month()
    month_result = await db.execute(
        select(
            func.coalesce(
                func.sum(CorporateFuelCardTransaction.amount_usd), 0
            ).label("month_amount")
        ).where(
            CorporateFuelCardTransaction.account_id == account_id,
            extract("year", CorporateFuelCardTransaction.transaction_date) == year,
            extract("month", CorporateFuelCardTransaction.transaction_date) == month,
        )
    )
    current_month_amount = Decimal(str(month_result.scalar_one()))

    return {
        "account_id": account_id,
        "total_cards": total_cards,
        "active_cards": active_cards,
        "total_transactions": total_transactions,
        "total_amount_usd": total_amount,
        "current_month_amount_usd": current_month_amount,
        "by_fuel_type": by_fuel_type,
    }


async def list_all_platform(
    db: AsyncSession,
    account_id: Optional[int] = None,
    is_active: Optional[bool] = None,
    limit: int = 100,
    offset: int = 0,
) -> list[CorporateFuelCard]:
    """Platform-admin: list fuel cards across all accounts.

    Optionally filtered by *account_id* or *is_active*.
    """
    query = (
        select(CorporateFuelCard)
        .order_by(
            CorporateFuelCard.account_id,
            CorporateFuelCard.nickname,
        )
        .limit(limit)
        .offset(offset)
    )
    if account_id is not None:
        query = query.where(CorporateFuelCard.account_id == account_id)
    if is_active is not None:
        query = query.where(CorporateFuelCard.is_active == is_active)
    result = await db.execute(query)
    return list(result.scalars().all())
