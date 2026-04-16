"""Corporate Fuel Card Management endpoints.

Fleet managers register company fuel cards, assign them to vehicles and/or
drivers, set spending limits, and record fuel transactions.

Member endpoints (any corporate member):
  GET  /corporate/accounts/me/fuel-cards                              — list cards (200)
  GET  /corporate/accounts/me/fuel-cards/summary                      — account summary (200)
  GET  /corporate/accounts/me/fuel-cards/{card_id}                    — get card (200)
  GET  /corporate/accounts/me/fuel-cards/{card_id}/transactions        — list transactions (200)

Admin endpoints (account admin):
  POST /corporate/accounts/me/fuel-cards                              — issue card (201)
  PUT  /corporate/accounts/me/fuel-cards/{card_id}                    — update card (200)
  POST /corporate/accounts/me/fuel-cards/{card_id}/assign-vehicle     — assign to vehicle (200)
  POST /corporate/accounts/me/fuel-cards/{card_id}/assign-driver      — assign to driver (200)
  POST /corporate/accounts/me/fuel-cards/{card_id}/unassign           — unassign (200)
  POST /corporate/accounts/me/fuel-cards/{card_id}/deactivate         — deactivate (200)
  POST /corporate/accounts/me/fuel-cards/{card_id}/reactivate         — reactivate (200)
  POST /corporate/accounts/me/fuel-cards/{card_id}/transactions        — record transaction (201)
  GET  /corporate/accounts/me/fuel-cards/{card_id}/summary             — card summary (200)

Platform-admin endpoint:
  GET  /admin/corporate/accounts/{account_id}/fuel-cards              — list cards (200)
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, require_admin
from app.models.user import User
from app.schemas.corporate_fuel_card import (
    AccountFuelSummaryResponse,
    FuelCardAssignDriverRequest,
    FuelCardAssignVehicleRequest,
    FuelCardCreateRequest,
    FuelCardListResponse,
    FuelCardResponse,
    FuelCardSummaryResponse,
    FuelCardUpdateRequest,
    FuelTransactionCreateRequest,
    FuelTransactionListResponse,
    FuelTransactionResponse,
    FuelTypeBreakdown,
)
from app.services.corporate_account_mgmt import get_user_account
from app.services.corporate_fuel_card_service import (
    assign_to_driver,
    assign_to_vehicle,
    deactivate_card,
    get_account_fuel_summary,
    get_card,
    get_card_summary,
    issue_card,
    list_all_platform,
    list_card_transactions,
    list_cards,
    reactivate_card,
    record_transaction,
    unassign,
    update_card,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["corporate-fuel-cards"])


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


def _to_card_response(card) -> FuelCardResponse:
    return FuelCardResponse.model_validate(card)


def _to_txn_response(txn) -> FuelTransactionResponse:
    return FuelTransactionResponse.model_validate(txn)


def _to_card_summary(raw: dict) -> FuelCardSummaryResponse:
    return FuelCardSummaryResponse(
        card_id=raw["card_id"],
        nickname=raw["nickname"],
        is_active=raw["is_active"],
        monthly_limit_usd=raw["monthly_limit_usd"],
        total_transactions=raw["total_transactions"],
        total_amount_usd=raw["total_amount_usd"],
        current_month_amount_usd=raw["current_month_amount_usd"],
        monthly_limit_utilization_pct=raw["monthly_limit_utilization_pct"],
        by_fuel_type=[FuelTypeBreakdown(**b) for b in raw["by_fuel_type"]],
    )


def _to_account_summary(raw: dict) -> AccountFuelSummaryResponse:
    return AccountFuelSummaryResponse(
        account_id=raw["account_id"],
        total_cards=raw["total_cards"],
        active_cards=raw["active_cards"],
        total_transactions=raw["total_transactions"],
        total_amount_usd=raw["total_amount_usd"],
        current_month_amount_usd=raw["current_month_amount_usd"],
        by_fuel_type=[FuelTypeBreakdown(**b) for b in raw["by_fuel_type"]],
    )


# ---------------------------------------------------------------------------
# Member: account-level summary — declared BEFORE /{card_id} to avoid collision
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/accounts/me/fuel-cards/summary",
    response_model=AccountFuelSummaryResponse,
    summary="Member: get aggregate fuel card statistics for my corporate account",
)
async def get_my_account_fuel_summary(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return account-level aggregate fuel card statistics."""
    account_id = await _resolve_account_id(db, user.id)
    raw = await get_account_fuel_summary(db, account_id=account_id)
    return _to_account_summary(raw)


# ---------------------------------------------------------------------------
# Member: list cards
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/accounts/me/fuel-cards",
    response_model=FuelCardListResponse,
    summary="Member: list fuel cards for my corporate account",
)
async def list_my_fuel_cards(
    is_active: Optional[bool] = Query(None, description="Filter by active status."),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return all fuel cards for the caller's corporate account."""
    account_id = await _resolve_account_id(db, user.id)
    cards = await list_cards(
        db, account_id=account_id, is_active=is_active, limit=limit, offset=offset
    )
    return FuelCardListResponse(
        total=len(cards),
        items=[_to_card_response(c) for c in cards],
    )


# ---------------------------------------------------------------------------
# Admin: issue card (201)
# ---------------------------------------------------------------------------


@router.post(
    "/corporate/accounts/me/fuel-cards",
    response_model=FuelCardResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Admin: issue a new company fuel card",
)
async def issue_my_fuel_card(
    data: FuelCardCreateRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Register a new company fuel card for the caller's corporate account.

    Returns 409 if a card with the same nickname already exists.
    """
    account_id = await _resolve_account_id(db, user.id)
    card = await issue_card(
        db,
        account_id=account_id,
        card_last_four=data.card_last_four,
        card_network=data.card_network,
        nickname=data.nickname,
        issued_by_id=user.id,
        assigned_vehicle_id=data.assigned_vehicle_id,
        assigned_driver_id=data.assigned_driver_id,
        monthly_limit_usd=data.monthly_limit_usd,
        notes=data.notes,
    )
    await db.commit()
    return _to_card_response(card)


# ---------------------------------------------------------------------------
# Member: get single card
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/accounts/me/fuel-cards/{card_id}",
    response_model=FuelCardResponse,
    summary="Member: get a specific fuel card",
)
async def get_my_fuel_card(
    card_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return a single fuel card by id."""
    account_id = await _resolve_account_id(db, user.id)
    card = await get_card(db, account_id=account_id, card_id=card_id)
    return _to_card_response(card)


# ---------------------------------------------------------------------------
# Admin: update card
# ---------------------------------------------------------------------------


@router.put(
    "/corporate/accounts/me/fuel-cards/{card_id}",
    response_model=FuelCardResponse,
    summary="Admin: update a fuel card",
)
async def update_my_fuel_card(
    card_id: int,
    data: FuelCardUpdateRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Partially update a fuel card.  Returns 409 on nickname collision."""
    account_id = await _resolve_account_id(db, user.id)
    kwargs = {k: v for k, v in data.model_dump().items() if v is not None}
    card = await update_card(db, account_id=account_id, card_id=card_id, **kwargs)
    await db.commit()
    return _to_card_response(card)


# ---------------------------------------------------------------------------
# Admin: assign to vehicle
# ---------------------------------------------------------------------------


@router.post(
    "/corporate/accounts/me/fuel-cards/{card_id}/assign-vehicle",
    response_model=FuelCardResponse,
    summary="Admin: assign a fuel card to a fleet vehicle",
)
async def assign_card_to_vehicle(
    card_id: int,
    data: FuelCardAssignVehicleRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Assign a fuel card to a fleet vehicle.

    Returns 409 if the card is already assigned to the same vehicle.
    """
    account_id = await _resolve_account_id(db, user.id)
    card = await assign_to_vehicle(
        db, account_id=account_id, card_id=card_id, vehicle_id=data.vehicle_id
    )
    await db.commit()
    return _to_card_response(card)


# ---------------------------------------------------------------------------
# Admin: assign to driver
# ---------------------------------------------------------------------------


@router.post(
    "/corporate/accounts/me/fuel-cards/{card_id}/assign-driver",
    response_model=FuelCardResponse,
    summary="Admin: associate a fuel card with a driver",
)
async def assign_card_to_driver(
    card_id: int,
    data: FuelCardAssignDriverRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Associate a fuel card with a driver.

    Returns 409 if the card is already assigned to the same driver.
    """
    account_id = await _resolve_account_id(db, user.id)
    card = await assign_to_driver(
        db, account_id=account_id, card_id=card_id, driver_id=data.driver_id
    )
    await db.commit()
    return _to_card_response(card)


# ---------------------------------------------------------------------------
# Admin: unassign
# ---------------------------------------------------------------------------


@router.post(
    "/corporate/accounts/me/fuel-cards/{card_id}/unassign",
    response_model=FuelCardResponse,
    summary="Admin: remove vehicle and driver assignment from a fuel card",
)
async def unassign_fuel_card(
    card_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Remove vehicle and driver assignment from a fuel card."""
    account_id = await _resolve_account_id(db, user.id)
    card = await unassign(
        db, account_id=account_id, card_id=card_id,
        unassign_vehicle=True, unassign_driver=True,
    )
    await db.commit()
    return _to_card_response(card)


# ---------------------------------------------------------------------------
# Admin: deactivate
# ---------------------------------------------------------------------------


@router.post(
    "/corporate/accounts/me/fuel-cards/{card_id}/deactivate",
    response_model=FuelCardResponse,
    summary="Admin: deactivate a fuel card",
)
async def deactivate_my_fuel_card(
    card_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Mark a fuel card as inactive.  Returns 409 if already inactive."""
    account_id = await _resolve_account_id(db, user.id)
    card = await deactivate_card(db, account_id=account_id, card_id=card_id)
    await db.commit()
    return _to_card_response(card)


# ---------------------------------------------------------------------------
# Admin: reactivate
# ---------------------------------------------------------------------------


@router.post(
    "/corporate/accounts/me/fuel-cards/{card_id}/reactivate",
    response_model=FuelCardResponse,
    summary="Admin: reactivate a fuel card",
)
async def reactivate_my_fuel_card(
    card_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Mark a fuel card as active.  Returns 409 if already active."""
    account_id = await _resolve_account_id(db, user.id)
    card = await reactivate_card(db, account_id=account_id, card_id=card_id)
    await db.commit()
    return _to_card_response(card)


# ---------------------------------------------------------------------------
# Admin: record transaction (201)
# ---------------------------------------------------------------------------


@router.post(
    "/corporate/accounts/me/fuel-cards/{card_id}/transactions",
    response_model=FuelTransactionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Admin: record a fuel transaction against a card",
)
async def record_fuel_transaction(
    card_id: int,
    data: FuelTransactionCreateRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Record a fuel transaction against a card.

    Returns 404 if the card is not found.
    Returns 409 if the card is inactive.
    """
    account_id = await _resolve_account_id(db, user.id)
    txn = await record_transaction(
        db,
        account_id=account_id,
        card_id=card_id,
        recorded_by_id=user.id,
        transaction_date=data.transaction_date,
        merchant_name=data.merchant_name,
        fuel_type=data.fuel_type,
        amount_usd=data.amount_usd,
        gallons=data.gallons,
        odometer_miles=data.odometer_miles,
        notes=data.notes,
    )
    await db.commit()
    return _to_txn_response(txn)


# ---------------------------------------------------------------------------
# Member: list transactions for a card
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/accounts/me/fuel-cards/{card_id}/transactions",
    response_model=FuelTransactionListResponse,
    summary="Member: list fuel transactions for a specific card",
)
async def list_fuel_card_transactions(
    card_id: int,
    from_date: Optional[str] = Query(None, description="ISO date YYYY-MM-DD"),
    to_date: Optional[str] = Query(None, description="ISO date YYYY-MM-DD"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return transactions for a specific fuel card, newest first."""
    from datetime import date as date_type
    account_id = await _resolve_account_id(db, user.id)
    from_date_parsed = date_type.fromisoformat(from_date) if from_date else None
    to_date_parsed = date_type.fromisoformat(to_date) if to_date else None
    txns = await list_card_transactions(
        db,
        account_id=account_id,
        card_id=card_id,
        from_date=from_date_parsed,
        to_date=to_date_parsed,
        limit=limit,
        offset=offset,
    )
    return FuelTransactionListResponse(
        total=len(txns),
        items=[_to_txn_response(t) for t in txns],
    )


# ---------------------------------------------------------------------------
# Admin: card-level summary
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/accounts/me/fuel-cards/{card_id}/summary",
    response_model=FuelCardSummaryResponse,
    summary="Admin: get aggregate statistics for a specific fuel card",
)
async def get_my_fuel_card_summary(
    card_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return aggregate spend statistics for a single fuel card."""
    account_id = await _resolve_account_id(db, user.id)
    raw = await get_card_summary(db, account_id=account_id, card_id=card_id)
    return _to_card_summary(raw)


# ---------------------------------------------------------------------------
# Platform-admin: list cards for any account
# ---------------------------------------------------------------------------


@router.get(
    "/admin/corporate/accounts/{account_id}/fuel-cards",
    response_model=FuelCardListResponse,
    summary="Platform admin: list fuel cards for a corporate account",
)
async def platform_admin_list_fuel_cards(
    account_id: int,
    is_active: Optional[bool] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return all fuel cards for any corporate account (platform admin only)."""
    cards = await list_all_platform(
        db,
        account_id=account_id,
        is_active=is_active,
        limit=limit,
        offset=offset,
    )
    return FuelCardListResponse(
        total=len(cards),
        items=[_to_card_response(c) for c in cards],
    )
