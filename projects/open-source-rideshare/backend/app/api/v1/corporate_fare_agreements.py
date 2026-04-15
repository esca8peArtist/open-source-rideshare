"""Corporate Fare Agreements API endpoints.

Corporate accounts negotiate custom pricing with the platform.  Agreements
define rate adjustments (surge caps, flat discounts, per-mile / per-minute
rates) scoped to a vehicle category and optional validity window.

The /compute endpoint previews how active agreements will adjust a
hypothetical ride fare — useful for employee-facing cost-estimate flows.

Member endpoints (account admin required):
  POST   /corporate/accounts/me/fare-agreements                      — create
  GET    /corporate/accounts/me/fare-agreements                      — list
  GET    /corporate/accounts/me/fare-agreements/compute              — compute fare
  GET    /corporate/accounts/me/fare-agreements/{id}                 — get one
  PATCH  /corporate/accounts/me/fare-agreements/{id}                 — update
  DELETE /corporate/accounts/me/fare-agreements/{id}                 — delete
  POST   /corporate/accounts/me/fare-agreements/{id}/deactivate      — soft-disable

Platform-admin endpoints:
  GET    /admin/corporate/accounts/{account_id}/fare-agreements          — list
  GET    /admin/corporate/accounts/{account_id}/fare-agreements/compute  — compute
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, require_admin
from app.models.corporate import BusinessAccountMember
from app.models.corporate_fare_agreement import FareAgreementRateType
from app.models.user import User
from app.schemas.corporate_fare_agreement import (
    FareAgreementCreate,
    FareAgreementListResponse,
    FareAgreementResponse,
    FareAgreementUpdate,
    FareComputeResponse,
)
from app.services.corporate_fare_agreement import (
    compute_corporate_fare,
    create_fare_agreement,
    delete_fare_agreement,
    get_fare_agreement,
    list_fare_agreements,
    update_fare_agreement,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["corporate-fare-agreements"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _get_member_account_id(db: AsyncSession, user_id: int) -> int:
    """Return the corporate account ID the user belongs to.

    Raises HTTP 404 if the user is not an active member of any account.
    """
    result = await db.execute(
        select(BusinessAccountMember).where(
            BusinessAccountMember.user_id == user_id,
            BusinessAccountMember.is_active.is_(True),
        )
    )
    membership = result.scalar_one_or_none()
    if membership is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="You are not a member of any corporate account.",
        )
    return membership.account_id


def _to_response(agreement) -> FareAgreementResponse:
    return FareAgreementResponse(
        id=agreement.id,
        corporate_account_id=agreement.corporate_account_id,
        name=agreement.name,
        rate_type=(
            agreement.rate_type.value
            if hasattr(agreement.rate_type, "value")
            else agreement.rate_type
        ),
        value=agreement.value,
        applies_to_vehicle_types=agreement.applies_to_vehicle_types,
        valid_from=agreement.valid_from,
        valid_until=agreement.valid_until,
        is_active=agreement.is_active,
        notes=agreement.notes,
        created_by_id=agreement.created_by_id,
        created_at=agreement.created_at,
        updated_at=agreement.updated_at,
    )


# ---------------------------------------------------------------------------
# Member routes
# ---------------------------------------------------------------------------


@router.post(
    "/corporate/accounts/me/fare-agreements",
    response_model=FareAgreementResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a fare agreement for your corporate account",
)
async def create_my_fare_agreement(
    data: FareAgreementCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create a negotiated pricing agreement for the caller's corporate account.

    Admin role within the account is required.
    """
    account_id = await _get_member_account_id(db, current_user.id)
    agreement = await create_fare_agreement(
        db, account_id, data, created_by_id=current_user.id
    )
    return _to_response(agreement)


@router.get(
    "/corporate/accounts/me/fare-agreements",
    response_model=FareAgreementListResponse,
    summary="List fare agreements for your corporate account",
)
async def list_my_fare_agreements(
    active_only: bool = Query(False, description="Only return active agreements."),
    rate_type: FareAgreementRateType | None = Query(
        None, description="Filter by rate type."
    ),
    vehicle_type: str | None = Query(
        None, description="Filter by vehicle category."
    ),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return fare agreements for the caller's corporate account."""
    account_id = await _get_member_account_id(db, current_user.id)
    agreements, total = await list_fare_agreements(
        db,
        account_id,
        active_only=active_only,
        rate_type=rate_type,
        vehicle_type=vehicle_type,
        skip=skip,
        limit=limit,
    )
    return FareAgreementListResponse(
        items=[_to_response(a) for a in agreements],
        total=total,
    )


@router.get(
    "/corporate/accounts/me/fare-agreements/compute",
    response_model=FareComputeResponse,
    summary="Preview adjusted fare after applying active agreements",
)
async def compute_my_fare(
    base_fare_usd: Decimal = Query(
        ..., gt=Decimal("0"), description="Base fare before surge (in USD)."
    ),
    surge_multiplier: Decimal = Query(
        Decimal("1.0"), ge=Decimal("1.0"), description="Current surge multiplier."
    ),
    vehicle_type: str | None = Query(
        None, description="Vehicle category to match agreements against."
    ),
    ride_dt: datetime | None = Query(
        None, description="Ride datetime for validity check (ISO 8601); defaults to now."
    ),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Compute the final fare after applying all active, applicable fare agreements.

    Useful for building cost-estimate flows in the employee booking UI.
    """
    account_id = await _get_member_account_id(db, current_user.id)
    return await compute_corporate_fare(
        db,
        account_id,
        base_fare_usd=base_fare_usd,
        surge_multiplier=surge_multiplier,
        vehicle_type=vehicle_type,
        ride_dt=ride_dt,
    )


@router.get(
    "/corporate/accounts/me/fare-agreements/{agreement_id}",
    response_model=FareAgreementResponse,
    summary="Get a specific fare agreement",
)
async def get_my_fare_agreement(
    agreement_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Fetch a single fare agreement by ID."""
    account_id = await _get_member_account_id(db, current_user.id)
    agreement = await get_fare_agreement(db, account_id, agreement_id)
    return _to_response(agreement)


@router.patch(
    "/corporate/accounts/me/fare-agreements/{agreement_id}",
    response_model=FareAgreementResponse,
    summary="Update a fare agreement",
)
async def update_my_fare_agreement(
    agreement_id: uuid.UUID,
    data: FareAgreementUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Partially update a fare agreement."""
    account_id = await _get_member_account_id(db, current_user.id)
    agreement = await update_fare_agreement(db, account_id, agreement_id, data)
    return _to_response(agreement)


@router.delete(
    "/corporate/accounts/me/fare-agreements/{agreement_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a fare agreement",
)
async def delete_my_fare_agreement(
    agreement_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Hard-delete a fare agreement."""
    account_id = await _get_member_account_id(db, current_user.id)
    await delete_fare_agreement(db, account_id, agreement_id)


@router.post(
    "/corporate/accounts/me/fare-agreements/{agreement_id}/deactivate",
    response_model=FareAgreementResponse,
    summary="Soft-deactivate a fare agreement without deleting it",
)
async def deactivate_my_fare_agreement(
    agreement_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Set is_active=False on the fare agreement.

    The record remains and can be re-activated with PATCH.
    """
    account_id = await _get_member_account_id(db, current_user.id)
    agreement = await update_fare_agreement(
        db, account_id, agreement_id, FareAgreementUpdate(is_active=False)
    )
    return _to_response(agreement)


# ---------------------------------------------------------------------------
# Platform-admin routes
# ---------------------------------------------------------------------------


@router.get(
    "/admin/corporate/accounts/{account_id}/fare-agreements",
    response_model=FareAgreementListResponse,
    summary="[Admin] List fare agreements for any corporate account",
    dependencies=[Depends(require_admin)],
)
async def admin_list_fare_agreements(
    account_id: int,
    active_only: bool = Query(False),
    rate_type: FareAgreementRateType | None = Query(None),
    vehicle_type: str | None = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    """List fare agreements for any corporate account (platform admin only)."""
    agreements, total = await list_fare_agreements(
        db,
        account_id,
        active_only=active_only,
        rate_type=rate_type,
        vehicle_type=vehicle_type,
        skip=skip,
        limit=limit,
    )
    return FareAgreementListResponse(
        items=[_to_response(a) for a in agreements],
        total=total,
    )


@router.get(
    "/admin/corporate/accounts/{account_id}/fare-agreements/compute",
    response_model=FareComputeResponse,
    summary="[Admin] Compute adjusted fare for any corporate account",
    dependencies=[Depends(require_admin)],
)
async def admin_compute_fare(
    account_id: int,
    base_fare_usd: Decimal = Query(..., gt=Decimal("0")),
    surge_multiplier: Decimal = Query(Decimal("1.0"), ge=Decimal("1.0")),
    vehicle_type: str | None = Query(None),
    ride_dt: datetime | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """Compute the adjusted fare for any corporate account (platform admin only)."""
    return await compute_corporate_fare(
        db,
        account_id,
        base_fare_usd=base_fare_usd,
        surge_multiplier=surge_multiplier,
        vehicle_type=vehicle_type,
        ride_dt=ride_dt,
    )
