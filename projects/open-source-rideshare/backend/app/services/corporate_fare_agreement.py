"""Service layer for the Corporate Fare Agreements feature.

Corporate accounts negotiate custom pricing with the platform.  Service
functions handle CRUD for agreements and the compute engine that applies
active agreements to a hypothetical ride fare.

Public surface
--------------
create_fare_agreement(db, account_id, data, created_by_id)
get_fare_agreement(db, account_id, agreement_id)
list_fare_agreements(db, account_id, *, active_only, rate_type, vehicle_type, skip, limit)
update_fare_agreement(db, account_id, agreement_id, data)
delete_fare_agreement(db, account_id, agreement_id)
compute_corporate_fare(db, account_id, base_fare_usd, surge_multiplier, vehicle_type, ride_dt)
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Sequence

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.corporate_fare_agreement import (
    CorporateFareAgreement,
    FareAgreementRateType,
)
from app.schemas.corporate_fare_agreement import (
    AgreementSummary,
    FareAgreementCreate,
    FareAgreementUpdate,
    FareComputeResponse,
)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _get_agreement(
    db: AsyncSession, account_id: int, agreement_id: uuid.UUID
) -> CorporateFareAgreement:
    """Fetch a fare agreement; raise 404 if not found or account mismatch."""
    result = await db.execute(
        select(CorporateFareAgreement).where(
            CorporateFareAgreement.id == agreement_id,
            CorporateFareAgreement.corporate_account_id == account_id,
        )
    )
    agreement = result.scalar_one_or_none()
    if agreement is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Fare agreement not found.",
        )
    return agreement


def _is_valid_at(agreement: CorporateFareAgreement, dt: datetime) -> bool:
    """Return True if the agreement is within its validity window at dt."""
    if agreement.valid_from is not None:
        vf = agreement.valid_from
        if vf.tzinfo is None:
            vf = vf.replace(tzinfo=timezone.utc)
        dt_cmp = dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        if dt_cmp < vf:
            return False
    if agreement.valid_until is not None:
        vu = agreement.valid_until
        if vu.tzinfo is None:
            vu = vu.replace(tzinfo=timezone.utc)
        dt_cmp = dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        if dt_cmp > vu:
            return False
    return True


def _applies_to_vehicle(
    agreement: CorporateFareAgreement, vehicle_type: str | None
) -> bool:
    """Return True if the agreement covers the given vehicle type.

    An agreement with applies_to_vehicle_types=None covers all vehicle types.
    When vehicle_type is None (caller did not specify), match all agreements.
    """
    if agreement.applies_to_vehicle_types is None:
        return True
    if vehicle_type is None:
        return True
    return vehicle_type in agreement.applies_to_vehicle_types


# ---------------------------------------------------------------------------
# Public service functions
# ---------------------------------------------------------------------------


async def create_fare_agreement(
    db: AsyncSession,
    account_id: int,
    data: FareAgreementCreate,
    created_by_id: int | None = None,
) -> CorporateFareAgreement:
    """Create a new fare agreement for the given corporate account."""
    agreement = CorporateFareAgreement(
        corporate_account_id=account_id,
        name=data.name,
        rate_type=FareAgreementRateType(data.rate_type),
        value=data.value,
        applies_to_vehicle_types=data.applies_to_vehicle_types,
        valid_from=data.valid_from,
        valid_until=data.valid_until,
        is_active=True,
        notes=data.notes,
        created_by_id=created_by_id,
    )
    db.add(agreement)
    await db.commit()
    await db.refresh(agreement)
    return agreement


async def get_fare_agreement(
    db: AsyncSession,
    account_id: int,
    agreement_id: uuid.UUID,
) -> CorporateFareAgreement:
    """Fetch a single fare agreement by ID, scoped to account_id."""
    return await _get_agreement(db, account_id, agreement_id)


async def list_fare_agreements(
    db: AsyncSession,
    account_id: int,
    *,
    active_only: bool = False,
    rate_type: FareAgreementRateType | None = None,
    vehicle_type: str | None = None,
    skip: int = 0,
    limit: int = 50,
) -> tuple[Sequence[CorporateFareAgreement], int]:
    """Return paginated fare agreements for an account.

    Filters:
        active_only:  If True, only return is_active=True agreements.
        rate_type:    If set, only return agreements of this type.
        vehicle_type: If set, only return agreements that cover this vehicle
                      category (or have no vehicle-type restriction).
    """
    query = select(CorporateFareAgreement).where(
        CorporateFareAgreement.corporate_account_id == account_id
    )

    if active_only:
        query = query.where(CorporateFareAgreement.is_active.is_(True))
    if rate_type is not None:
        query = query.where(CorporateFareAgreement.rate_type == rate_type)

    total_result = await db.execute(query)
    all_rows = total_result.scalars().all()

    # Vehicle-type filter is applied in Python (JSONB contains-check)
    if vehicle_type is not None:
        all_rows = [r for r in all_rows if _applies_to_vehicle(r, vehicle_type)]

    total = len(all_rows)
    paged = all_rows[skip : skip + limit]
    return paged, total


async def update_fare_agreement(
    db: AsyncSession,
    account_id: int,
    agreement_id: uuid.UUID,
    data: FareAgreementUpdate,
) -> CorporateFareAgreement:
    """Partially update a fare agreement.

    Raises:
        404: Agreement not found.
    """
    agreement = await _get_agreement(db, account_id, agreement_id)

    update_fields = data.model_dump(exclude_unset=True)
    for field, value in update_fields.items():
        setattr(agreement, field, value)

    await db.commit()
    await db.refresh(agreement)
    return agreement


async def delete_fare_agreement(
    db: AsyncSession,
    account_id: int,
    agreement_id: uuid.UUID,
) -> None:
    """Hard-delete a fare agreement.

    Raises:
        404: Agreement not found.
    """
    agreement = await _get_agreement(db, account_id, agreement_id)
    await db.delete(agreement)
    await db.commit()


async def compute_corporate_fare(
    db: AsyncSession,
    account_id: int,
    base_fare_usd: Decimal,
    surge_multiplier: Decimal,
    vehicle_type: str | None = None,
    ride_dt: datetime | None = None,
) -> FareComputeResponse:
    """Apply active fare agreements to a hypothetical ride fare.

    Algorithm:
        1. Load all active agreements for the account.
        2. Filter by vehicle_type and validity at ride_dt.
        3. Among surge_cap agreements: use the *lowest* cap value.
        4. Among flat_discount_pct agreements: use the *highest* discount.
        5. Per-mile / per-minute agreements are not applied here (they need
           distance/duration); they are returned in ``reference_agreements``.

    Returns:
        FareComputeResponse with original and final fare breakdown.
    """
    if ride_dt is None:
        ride_dt = datetime.now(timezone.utc)

    # Load all active agreements for the account
    result = await db.execute(
        select(CorporateFareAgreement).where(
            CorporateFareAgreement.corporate_account_id == account_id,
            CorporateFareAgreement.is_active.is_(True),
        )
    )
    all_agreements = result.scalars().all()

    # Filter by vehicle type and validity window
    applicable = [
        a
        for a in all_agreements
        if _applies_to_vehicle(a, vehicle_type) and _is_valid_at(a, ride_dt)
    ]

    # Separate by rate type
    surge_caps = [
        a for a in applicable if a.rate_type == FareAgreementRateType.surge_cap
    ]
    discounts = [
        a for a in applicable if a.rate_type == FareAgreementRateType.flat_discount_pct
    ]
    reference = [
        a
        for a in applicable
        if a.rate_type
        in (
            FareAgreementRateType.per_mile_rate_usd,
            FareAgreementRateType.per_minute_rate_usd,
        )
    ]

    # Apply surge cap (lowest cap wins)
    adjusted_surge = surge_multiplier
    applied: list[CorporateFareAgreement] = []
    if surge_caps:
        best_cap = min(surge_caps, key=lambda a: a.value)
        if adjusted_surge > best_cap.value:
            adjusted_surge = best_cap.value
            applied.append(best_cap)
        else:
            # Cap exists but doesn't bite — still list it as applied context
            applied.append(best_cap)

    fare_before_discount = base_fare_usd * adjusted_surge

    # Apply flat discount (highest discount wins)
    discount_pct = Decimal("0")
    if discounts:
        best_discount = max(discounts, key=lambda a: a.value)
        discount_pct = best_discount.value
        applied.append(best_discount)

    final_fare = fare_before_discount * (Decimal("1") - discount_pct / Decimal("100"))
    final_fare = final_fare.quantize(Decimal("0.01"))

    def _summary(a: CorporateFareAgreement) -> AgreementSummary:
        return AgreementSummary(
            id=a.id,
            name=a.name,
            rate_type=a.rate_type.value if hasattr(a.rate_type, "value") else a.rate_type,
            value=a.value,
        )

    return FareComputeResponse(
        base_fare_usd=base_fare_usd,
        original_surge_multiplier=surge_multiplier,
        adjusted_surge_multiplier=adjusted_surge,
        fare_before_discount_usd=fare_before_discount,
        discount_pct_applied=discount_pct,
        final_fare_usd=final_fare,
        agreements_applied=[_summary(a) for a in applied],
        reference_agreements=[_summary(a) for a in reference],
    )
