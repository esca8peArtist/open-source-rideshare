"""Service layer for Corporate Account Contract management.

Provides CRUD and lifecycle operations for service agreements between the
platform and corporate clients.  Authorisation is the caller's responsibility;
these functions operate purely on data.

Public surface
--------------
create_contract(db, account_id, data, admin_id) -> ContractResponse
get_contract(db, contract_id) -> ContractResponse
get_active_contract(db, account_id) -> ContractResponse | None
list_contracts(db, account_id, status_filter, skip, limit) -> ContractListResponse
update_contract(db, contract_id, data, admin_id) -> ContractResponse
activate_contract(db, contract_id, admin_id) -> ContractResponse
terminate_contract(db, contract_id, admin_id, reason) -> ContractResponse
list_expiring_contracts(db, within_days, skip, limit) -> ContractListResponse
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.corporate_account_contract import (
    CorporateAccountContract,
    ContractStatus,
)
from app.schemas.corporate_account_contract import (
    ContractCreate,
    ContractListResponse,
    ContractResponse,
    ContractUpdate,
)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _to_response(contract: CorporateAccountContract) -> ContractResponse:
    """Convert a model instance to a ContractResponse schema object."""
    return ContractResponse(
        id=contract.id,
        account_id=contract.account_id,
        contract_number=contract.contract_number,
        status=contract.status.value if hasattr(contract.status, "value") else contract.status,
        contract_start_date=contract.contract_start_date,
        contract_end_date=contract.contract_end_date,
        auto_renews=contract.auto_renews,
        renewal_term_days=contract.renewal_term_days,
        renewal_notice_days=contract.renewal_notice_days,
        committed_monthly_rides=contract.committed_monthly_rides,
        committed_monthly_spend_usd=contract.committed_monthly_spend_usd,
        negotiated_discount_pct=contract.negotiated_discount_pct,
        account_manager_name=contract.account_manager_name,
        account_manager_email=contract.account_manager_email,
        contract_document_url=contract.contract_document_url,
        notes=contract.notes,
        signed_by_name=contract.signed_by_name,
        signed_at=contract.signed_at,
        activated_at=contract.activated_at,
        terminated_at=contract.terminated_at,
        termination_reason=contract.termination_reason,
        created_by_id=contract.created_by_id,
        updated_by_id=contract.updated_by_id,
        created_at=contract.created_at,
        updated_at=contract.updated_at,
    )


async def _auto_generate_contract_number(
    db: AsyncSession, account_id: int
) -> str:
    """Generate a unique contract number for the given account.

    Format: ``CONTRACT-{account_id:04d}-{YYYYMM}-{sequence}`` where sequence
    is the count of existing contracts for this account plus one.
    """
    count: int = await db.scalar(
        select(func.count()).where(
            CorporateAccountContract.account_id == account_id
        )
    ) or 0
    sequence = count + 1
    month_str = datetime.now().strftime("%Y%m")
    return f"CONTRACT-{account_id:04d}-{month_str}-{sequence}"


async def _get_contract_or_404(
    db: AsyncSession, contract_id: int
) -> CorporateAccountContract:
    """Fetch a contract by primary key; raise HTTP 404 if not found."""
    result = await db.execute(
        select(CorporateAccountContract).where(
            CorporateAccountContract.id == contract_id
        )
    )
    contract = result.scalars().first()
    if contract is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Contract {contract_id} not found.",
        )
    return contract


# ---------------------------------------------------------------------------
# Public service functions
# ---------------------------------------------------------------------------


async def create_contract(
    db: AsyncSession,
    account_id: int,
    data: ContractCreate,
    admin_id: int,
) -> ContractResponse:
    """Create a new draft contract for a corporate account.

    Args:
        db:         Async database session.
        account_id: Target corporate account.
        data:       Validated create payload.
        admin_id:   ID of the admin performing the operation.

    Returns:
        ContractResponse for the newly created draft.

    Raises:
        HTTPException 409: If an active contract already exists for this account.
    """
    # Guard: only one active contract per account.
    active_count: int = await db.scalar(
        select(func.count()).where(
            CorporateAccountContract.account_id == account_id,
            CorporateAccountContract.status == ContractStatus.active,
        )
    ) or 0
    if active_count > 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An active contract already exists for this account.",
        )

    contract_number = data.contract_number
    if not contract_number:
        contract_number = await _auto_generate_contract_number(db, account_id)

    contract = CorporateAccountContract(
        account_id=account_id,
        contract_number=contract_number,
        status=ContractStatus.draft,
        contract_start_date=data.contract_start_date,
        contract_end_date=data.contract_end_date,
        auto_renews=data.auto_renews,
        renewal_term_days=data.renewal_term_days,
        renewal_notice_days=data.renewal_notice_days,
        committed_monthly_rides=data.committed_monthly_rides,
        committed_monthly_spend_usd=data.committed_monthly_spend_usd,
        negotiated_discount_pct=data.negotiated_discount_pct,
        account_manager_name=data.account_manager_name,
        account_manager_email=data.account_manager_email,
        contract_document_url=data.contract_document_url,
        notes=data.notes,
        signed_by_name=data.signed_by_name,
        signed_at=data.signed_at,
        created_by_id=admin_id,
        updated_by_id=admin_id,
    )
    db.add(contract)
    await db.commit()
    await db.refresh(contract)
    return _to_response(contract)


async def get_contract(
    db: AsyncSession,
    contract_id: int,
) -> ContractResponse:
    """Fetch a single contract by ID.

    Args:
        db:          Async database session.
        contract_id: Primary key of the target contract.

    Returns:
        ContractResponse.

    Raises:
        HTTPException 404: If no contract with this ID exists.
    """
    contract = await _get_contract_or_404(db, contract_id)
    return _to_response(contract)


async def get_active_contract(
    db: AsyncSession,
    account_id: int,
) -> ContractResponse | None:
    """Return the active contract for an account, or None if none exists.

    Args:
        db:         Async database session.
        account_id: Target corporate account.

    Returns:
        ContractResponse if an active contract exists, otherwise None.
    """
    result = await db.execute(
        select(CorporateAccountContract).where(
            CorporateAccountContract.account_id == account_id,
            CorporateAccountContract.status == ContractStatus.active,
        )
    )
    contract = result.scalars().first()
    if contract is None:
        return None
    return _to_response(contract)


async def list_contracts(
    db: AsyncSession,
    account_id: int,
    status_filter: ContractStatus | None = None,
    skip: int = 0,
    limit: int = 50,
) -> ContractListResponse:
    """List contracts for a corporate account, optionally filtered by status.

    Args:
        db:            Async database session.
        account_id:    Target corporate account.
        status_filter: When provided, restrict results to this status.
        skip:          Number of records to skip (offset pagination).
        limit:         Maximum number of records to return.

    Returns:
        ContractListResponse with contracts and total count.
    """
    base_query = select(CorporateAccountContract).where(
        CorporateAccountContract.account_id == account_id
    )
    count_query = select(func.count()).where(
        CorporateAccountContract.account_id == account_id
    )

    if status_filter is not None:
        base_query = base_query.where(
            CorporateAccountContract.status == status_filter
        )
        count_query = count_query.where(
            CorporateAccountContract.status == status_filter
        )

    total: int = await db.scalar(count_query) or 0
    result = await db.execute(
        base_query.order_by(CorporateAccountContract.id.desc())
        .offset(skip)
        .limit(limit)
    )
    contracts = result.scalars().all()
    return ContractListResponse(
        contracts=[_to_response(c) for c in contracts],
        total=total,
    )


async def update_contract(
    db: AsyncSession,
    contract_id: int,
    data: ContractUpdate,
    admin_id: int,
) -> ContractResponse:
    """Partially update a draft or active contract.

    Args:
        db:          Async database session.
        contract_id: Primary key of the target contract.
        data:        Validated partial update payload.
        admin_id:    ID of the admin performing the operation.

    Returns:
        Updated ContractResponse.

    Raises:
        HTTPException 404: If no contract with this ID exists.
        HTTPException 409: If the contract is terminated or expired (immutable).
    """
    contract = await _get_contract_or_404(db, contract_id)

    if contract.status in (ContractStatus.terminated, ContractStatus.expired):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot edit a contract with status '{contract.status.value}'.",
        )

    update_data = data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(contract, field, value)
    contract.updated_by_id = admin_id

    await db.commit()
    await db.refresh(contract)
    return _to_response(contract)


async def activate_contract(
    db: AsyncSession,
    contract_id: int,
    admin_id: int,
) -> ContractResponse:
    """Activate a draft contract.

    Any existing active contract for the same account is moved to ``expired``
    before the new contract is activated.

    Args:
        db:          Async database session.
        contract_id: Primary key of the contract to activate.
        admin_id:    ID of the admin performing the operation.

    Returns:
        Updated ContractResponse with status=active.

    Raises:
        HTTPException 404: If no contract with this ID exists.
        HTTPException 409: If the contract is not in draft status.
    """
    contract = await _get_contract_or_404(db, contract_id)

    if contract.status != ContractStatus.draft:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Only draft contracts can be activated; current status is '{contract.status.value}'.",
        )

    # Deactivate (expire) any existing active contract for this account.
    prior_result = await db.execute(
        select(CorporateAccountContract).where(
            CorporateAccountContract.account_id == contract.account_id,
            CorporateAccountContract.status == ContractStatus.active,
        )
    )
    for prior in prior_result.scalars().all():
        prior.status = ContractStatus.expired

    contract.status = ContractStatus.active
    contract.activated_at = datetime.now(tz=timezone.utc)
    contract.updated_by_id = admin_id

    await db.commit()
    await db.refresh(contract)
    return _to_response(contract)


async def terminate_contract(
    db: AsyncSession,
    contract_id: int,
    admin_id: int,
    reason: str,
) -> ContractResponse:
    """Terminate an active contract.

    Args:
        db:          Async database session.
        contract_id: Primary key of the contract to terminate.
        admin_id:    ID of the admin performing the operation.
        reason:      Mandatory explanation for the termination.

    Returns:
        Updated ContractResponse with status=terminated.

    Raises:
        HTTPException 404: If no contract with this ID exists.
        HTTPException 409: If the contract is not currently active.
    """
    contract = await _get_contract_or_404(db, contract_id)

    if contract.status != ContractStatus.active:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Only active contracts can be terminated; current status is '{contract.status.value}'.",
        )

    contract.status = ContractStatus.terminated
    contract.terminated_at = datetime.now(tz=timezone.utc)
    contract.termination_reason = reason
    contract.updated_by_id = admin_id

    await db.commit()
    await db.refresh(contract)
    return _to_response(contract)


async def list_expiring_contracts(
    db: AsyncSession,
    within_days: int = 30,
    skip: int = 0,
    limit: int = 50,
) -> ContractListResponse:
    """List active contracts whose end date falls within the given window.

    Args:
        db:          Async database session.
        within_days: Look-ahead window in days (default 30).
        skip:        Offset for pagination.
        limit:       Maximum records to return.

    Returns:
        ContractListResponse containing contracts expiring within the window.
    """
    cutoff = date.today() + timedelta(days=within_days)

    base_query = select(CorporateAccountContract).where(
        CorporateAccountContract.status == ContractStatus.active,
        CorporateAccountContract.contract_end_date.isnot(None),
        CorporateAccountContract.contract_end_date <= cutoff,
    )
    count_query = select(func.count()).where(
        CorporateAccountContract.status == ContractStatus.active,
        CorporateAccountContract.contract_end_date.isnot(None),
        CorporateAccountContract.contract_end_date <= cutoff,
    )

    total: int = await db.scalar(count_query) or 0
    result = await db.execute(
        base_query.order_by(CorporateAccountContract.contract_end_date.asc())
        .offset(skip)
        .limit(limit)
    )
    contracts = result.scalars().all()
    return ContractListResponse(
        contracts=[_to_response(c) for c in contracts],
        total=total,
    )
