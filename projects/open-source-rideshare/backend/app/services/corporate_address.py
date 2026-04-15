"""Service layer for Corporate Address Book.

Enterprise admins maintain a shared library of named locations — offices, client
sites, airports, hotels — that employees can browse and select when booking rides.
Each address can auto-tag rides with a default cost center and trip purpose.

Public surface
--------------
create_corporate_address(db, account_id, user_id, data)
get_corporate_address(db, account_id, address_id)
list_corporate_addresses(db, account_id, active_only, skip, limit)
search_corporate_addresses(db, account_id, query, skip, limit)
update_corporate_address(db, account_id, address_id, user_id, data)
deactivate_corporate_address(db, account_id, address_id, user_id)
delete_corporate_address(db, account_id, address_id, user_id)
"""

from __future__ import annotations

from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.corporate import BusinessAccountMember, MemberRole
from app.models.corporate_address import CorporateAddress
from app.models.corporate_cost_center import CorporateCostCenter
from app.models.corporate_trip_purpose import CorporateTripPurpose
from app.schemas.corporate_address import (
    CorporateAddressCreate,
    CorporateAddressListResponse,
    CorporateAddressResponse,
    CorporateAddressUpdate,
)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _require_admin(
    db: AsyncSession,
    account_id: int,
    user_id: int,
) -> BusinessAccountMember:
    """Raise HTTP 403 if the user is not an active admin of the account."""
    result = await db.execute(
        select(BusinessAccountMember).where(
            BusinessAccountMember.account_id == account_id,
            BusinessAccountMember.user_id == user_id,
            BusinessAccountMember.role == MemberRole.ADMIN,
            BusinessAccountMember.is_active.is_(True),
        )
    )
    member = result.scalar_one_or_none()
    if member is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only account admins can manage the address book.",
        )
    return member


async def _require_member(
    db: AsyncSession,
    account_id: int,
    user_id: int,
) -> BusinessAccountMember:
    """Raise HTTP 403 if the user is not an active member of the account."""
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
            detail="You are not an active member of this corporate account.",
        )
    return member


async def _get_address_or_404(
    db: AsyncSession,
    account_id: int,
    address_id: int,
) -> CorporateAddress:
    """Return the address or raise HTTP 404 if not found / wrong account."""
    result = await db.execute(
        select(CorporateAddress).where(
            CorporateAddress.id == address_id,
            CorporateAddress.account_id == account_id,
        )
    )
    addr = result.scalar_one_or_none()
    if addr is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Address not found.",
        )
    return addr


async def _validate_fks(
    db: AsyncSession,
    account_id: int,
    cost_center_id: Optional[int],
    trip_purpose_id: Optional[int],
) -> None:
    """Raise HTTP 400 if referenced cost center or trip purpose don't belong to the account."""
    if cost_center_id is not None:
        result = await db.execute(
            select(CorporateCostCenter.id).where(
                CorporateCostCenter.id == cost_center_id,
                CorporateCostCenter.account_id == account_id,
            )
        )
        if result.scalar_one_or_none() is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cost center not found in this account.",
            )

    if trip_purpose_id is not None:
        result = await db.execute(
            select(CorporateTripPurpose.id).where(
                CorporateTripPurpose.id == trip_purpose_id,
                CorporateTripPurpose.account_id == account_id,
            )
        )
        if result.scalar_one_or_none() is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Trip purpose not found in this account.",
            )


# ---------------------------------------------------------------------------
# Public service functions
# ---------------------------------------------------------------------------


async def create_corporate_address(
    db: AsyncSession,
    account_id: int,
    user_id: int,
    data: CorporateAddressCreate,
) -> CorporateAddressResponse:
    """Create a new address in the account's address book (admin only)."""
    await _require_admin(db, account_id, user_id)
    await _validate_fks(db, account_id, data.default_cost_center_id, data.default_trip_purpose_id)

    addr = CorporateAddress(
        account_id=account_id,
        name=data.name,
        address_line_1=data.address_line_1,
        address_line_2=data.address_line_2,
        city=data.city,
        state=data.state,
        zip_code=data.zip_code,
        country=data.country,
        latitude=data.latitude,
        longitude=data.longitude,
        notes=data.notes,
        is_pickup_point=data.is_pickup_point,
        is_dropoff_point=data.is_dropoff_point,
        default_cost_center_id=data.default_cost_center_id,
        default_trip_purpose_id=data.default_trip_purpose_id,
        is_active=True,
        created_by_id=user_id,
    )
    db.add(addr)
    await db.commit()
    await db.refresh(addr)
    return CorporateAddressResponse.model_validate(addr)


async def get_corporate_address(
    db: AsyncSession,
    account_id: int,
    address_id: int,
    user_id: int,
) -> CorporateAddressResponse:
    """Retrieve a single address (any active member may read)."""
    await _require_member(db, account_id, user_id)
    addr = await _get_address_or_404(db, account_id, address_id)
    return CorporateAddressResponse.model_validate(addr)


async def list_corporate_addresses(
    db: AsyncSession,
    account_id: int,
    user_id: int,
    active_only: bool = True,
    skip: int = 0,
    limit: int = 50,
) -> CorporateAddressListResponse:
    """List addresses in the account's address book (any active member may read)."""
    await _require_member(db, account_id, user_id)

    base_q = select(CorporateAddress).where(
        CorporateAddress.account_id == account_id
    )
    if active_only:
        base_q = base_q.where(CorporateAddress.is_active.is_(True))

    count_result = await db.execute(
        select(func.count()).select_from(base_q.subquery())
    )
    total = count_result.scalar_one()

    result = await db.execute(
        base_q.order_by(CorporateAddress.name).offset(skip).limit(limit)
    )
    addresses = result.scalars().all()
    return CorporateAddressListResponse(
        addresses=[CorporateAddressResponse.model_validate(a) for a in addresses],
        total=total,
    )


async def search_corporate_addresses(
    db: AsyncSession,
    account_id: int,
    user_id: int,
    query: str,
    skip: int = 0,
    limit: int = 50,
) -> CorporateAddressListResponse:
    """Search addresses by name, city, or street address (any active member)."""
    await _require_member(db, account_id, user_id)

    ilike = f"%{query}%"
    base_q = select(CorporateAddress).where(
        CorporateAddress.account_id == account_id,
        CorporateAddress.is_active.is_(True),
        or_(
            CorporateAddress.name.ilike(ilike),
            CorporateAddress.city.ilike(ilike),
            CorporateAddress.address_line_1.ilike(ilike),
        ),
    )

    count_result = await db.execute(
        select(func.count()).select_from(base_q.subquery())
    )
    total = count_result.scalar_one()

    result = await db.execute(
        base_q.order_by(CorporateAddress.name).offset(skip).limit(limit)
    )
    addresses = result.scalars().all()
    return CorporateAddressListResponse(
        addresses=[CorporateAddressResponse.model_validate(a) for a in addresses],
        total=total,
    )


async def update_corporate_address(
    db: AsyncSession,
    account_id: int,
    address_id: int,
    user_id: int,
    data: CorporateAddressUpdate,
) -> CorporateAddressResponse:
    """Partially update an address (admin only)."""
    await _require_admin(db, account_id, user_id)
    addr = await _get_address_or_404(db, account_id, address_id)

    # Validate FKs only for fields being changed
    await _validate_fks(
        db,
        account_id,
        data.default_cost_center_id,
        data.default_trip_purpose_id,
    )

    updates = data.model_dump(exclude_unset=True)
    for field, value in updates.items():
        setattr(addr, field, value)

    await db.commit()
    await db.refresh(addr)
    return CorporateAddressResponse.model_validate(addr)


async def deactivate_corporate_address(
    db: AsyncSession,
    account_id: int,
    address_id: int,
    user_id: int,
) -> CorporateAddressResponse:
    """Soft-delete an address — hidden from employees but retained in records (admin only)."""
    await _require_admin(db, account_id, user_id)
    addr = await _get_address_or_404(db, account_id, address_id)

    if not addr.is_active:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Address is already inactive.",
        )

    addr.is_active = False
    await db.commit()
    await db.refresh(addr)
    return CorporateAddressResponse.model_validate(addr)


async def delete_corporate_address(
    db: AsyncSession,
    account_id: int,
    address_id: int,
    user_id: int,
) -> None:
    """Hard-delete an address from the address book (admin only)."""
    await _require_admin(db, account_id, user_id)
    addr = await _get_address_or_404(db, account_id, address_id)
    await db.delete(addr)
    await db.commit()


async def list_all_corporate_addresses(
    db: AsyncSession,
    account_id: int,
    skip: int = 0,
    limit: int = 50,
) -> CorporateAddressListResponse:
    """Platform-admin: list all addresses for an account regardless of active state."""
    base_q = select(CorporateAddress).where(
        CorporateAddress.account_id == account_id
    )

    count_result = await db.execute(
        select(func.count()).select_from(base_q.subquery())
    )
    total = count_result.scalar_one()

    result = await db.execute(
        base_q.order_by(CorporateAddress.name).offset(skip).limit(limit)
    )
    addresses = result.scalars().all()
    return CorporateAddressListResponse(
        addresses=[CorporateAddressResponse.model_validate(a) for a in addresses],
        total=total,
    )
