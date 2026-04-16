"""Service layer for Corporate Travel Policy & Acknowledgement.

Corporate accounts publish versioned travel policy documents.  At most one
policy may be active per account at any time.  Activating a new policy
automatically deactivates the previously active one.

When ``requires_acknowledgement`` is True, employees must call
``acknowledge_policy`` before booking corporate rides.

Public surface
--------------
create_policy(db, account_id, created_by_id, data) -> TravelPolicyResponse
get_policy(db, account_id, policy_id) -> TravelPolicyResponse
get_active_policy(db, account_id) -> TravelPolicyResponse | None
list_policies(db, account_id) -> TravelPolicyListResponse
update_policy(db, account_id, policy_id, data) -> TravelPolicyResponse
activate_policy(db, account_id, policy_id) -> TravelPolicyResponse
deactivate_policy(db, account_id, policy_id) -> TravelPolicyResponse
delete_policy(db, account_id, policy_id) -> None
acknowledge_policy(db, account_id, member_id, policy_id) -> AcknowledgementResponse
get_member_acknowledgement_status(db, account_id, member_id)
    -> MemberAcknowledgementStatus
get_acknowledgement_summary(db, account_id, policy_id) -> AcknowledgementSummary
list_all_platform(db, account_id) -> TravelPolicyListResponse
"""

from __future__ import annotations

from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.corporate_travel_policy import (
    CorporatePolicyAcknowledgement,
    CorporateTravelPolicy,
)
from app.schemas.corporate_travel_policy import (
    AcknowledgementResponse,
    AcknowledgementSummary,
    MemberAcknowledgementStatus,
    TravelPolicyCreate,
    TravelPolicyListResponse,
    TravelPolicyResponse,
    TravelPolicyUpdate,
)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _policy_to_response(policy: CorporateTravelPolicy) -> TravelPolicyResponse:
    """Convert a CorporateTravelPolicy ORM instance to a response schema."""
    return TravelPolicyResponse(
        id=policy.id,
        account_id=policy.account_id,
        title=policy.title,
        content=policy.content,
        version_number=policy.version_number,
        is_active=policy.is_active,
        requires_acknowledgement=policy.requires_acknowledgement,
        effective_date=policy.effective_date,
        created_by_id=policy.created_by_id,
        created_at=policy.created_at,
        updated_at=policy.updated_at,
    )


def _ack_to_response(ack: CorporatePolicyAcknowledgement) -> AcknowledgementResponse:
    """Convert an acknowledgement ORM instance to a response schema."""
    return AcknowledgementResponse(
        id=ack.id,
        policy_id=ack.policy_id,
        member_id=ack.member_id,
        account_id=ack.account_id,
        acknowledged_at=ack.acknowledged_at,
    )


async def _get_policy(
    db: AsyncSession,
    account_id: int,
    policy_id: int,
) -> CorporateTravelPolicy | None:
    """Return the policy for this (account, id) or None."""
    result = await db.execute(
        select(CorporateTravelPolicy).where(
            CorporateTravelPolicy.id == policy_id,
            CorporateTravelPolicy.account_id == account_id,
        )
    )
    return result.scalar_one_or_none()


async def _get_policy_or_404(
    db: AsyncSession,
    account_id: int,
    policy_id: int,
) -> CorporateTravelPolicy:
    """Return the policy or raise HTTP 404."""
    policy = await _get_policy(db, account_id, policy_id)
    if policy is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Travel policy not found.",
        )
    return policy


async def _get_active_policy_row(
    db: AsyncSession,
    account_id: int,
) -> CorporateTravelPolicy | None:
    """Return the active policy row for an account or None."""
    result = await db.execute(
        select(CorporateTravelPolicy).where(
            CorporateTravelPolicy.account_id == account_id,
            CorporateTravelPolicy.is_active == True,  # noqa: E712
        )
    )
    return result.scalar_one_or_none()


# ---------------------------------------------------------------------------
# Public service functions
# ---------------------------------------------------------------------------


async def create_policy(
    db: AsyncSession,
    account_id: int,
    created_by_id: Optional[int],
    data: TravelPolicyCreate,
) -> TravelPolicyResponse:
    """Create a new (inactive) travel policy for the account.

    The policy is created in draft state (``is_active=False``).
    Admins must call ``activate_policy`` to make it effective.
    """
    policy = CorporateTravelPolicy(
        account_id=account_id,
        title=data.title,
        content=data.content,
        version_number=data.version_number,
        is_active=False,
        requires_acknowledgement=data.requires_acknowledgement,
        effective_date=data.effective_date,
        created_by_id=created_by_id,
    )
    db.add(policy)
    await db.commit()
    await db.refresh(policy)
    return _policy_to_response(policy)


async def get_policy(
    db: AsyncSession,
    account_id: int,
    policy_id: int,
) -> TravelPolicyResponse:
    """Return a specific policy by ID.

    Raises HTTP 404 if not found or belongs to a different account.
    """
    policy = await _get_policy_or_404(db, account_id, policy_id)
    return _policy_to_response(policy)


async def get_active_policy(
    db: AsyncSession,
    account_id: int,
) -> Optional[TravelPolicyResponse]:
    """Return the active policy for the account, or None if none is active."""
    policy = await _get_active_policy_row(db, account_id)
    return _policy_to_response(policy) if policy is not None else None


async def list_policies(
    db: AsyncSession,
    account_id: int,
    is_active: Optional[bool] = None,
) -> TravelPolicyListResponse:
    """List all travel policies for the account, newest first.

    Optional filter:
      - ``is_active``: True → only active; False → only inactive/draft.
    """
    stmt = select(CorporateTravelPolicy).where(
        CorporateTravelPolicy.account_id == account_id
    )
    if is_active is not None:
        stmt = stmt.where(CorporateTravelPolicy.is_active == is_active)
    stmt = stmt.order_by(CorporateTravelPolicy.created_at.desc())

    result = await db.execute(stmt)
    policies = result.scalars().all()
    return TravelPolicyListResponse(
        items=[_policy_to_response(p) for p in policies],
        total=len(policies),
    )


async def update_policy(
    db: AsyncSession,
    account_id: int,
    policy_id: int,
    data: TravelPolicyUpdate,
) -> TravelPolicyResponse:
    """Partially update a draft (inactive) travel policy.

    Raises HTTP 404 if the policy does not exist.
    Raises HTTP 409 if the policy is currently active — activate/deactivate
    first.
    """
    policy = await _get_policy_or_404(db, account_id, policy_id)
    if policy.is_active:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot update an active policy. Deactivate it first.",
        )
    update_data = data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(policy, field, value)
    await db.commit()
    await db.refresh(policy)
    return _policy_to_response(policy)


async def activate_policy(
    db: AsyncSession,
    account_id: int,
    policy_id: int,
) -> TravelPolicyResponse:
    """Activate a policy, deactivating any previously active policy.

    Raises HTTP 404 if the policy is not found.
    Raises HTTP 409 if the policy is already active.
    """
    policy = await _get_policy_or_404(db, account_id, policy_id)
    if policy.is_active:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Policy is already active.",
        )
    # Deactivate any currently active policy for this account.
    current_active = await _get_active_policy_row(db, account_id)
    if current_active is not None:
        current_active.is_active = False

    policy.is_active = True
    await db.commit()
    await db.refresh(policy)
    return _policy_to_response(policy)


async def deactivate_policy(
    db: AsyncSession,
    account_id: int,
    policy_id: int,
) -> TravelPolicyResponse:
    """Deactivate a policy (move it back to draft/inactive).

    Raises HTTP 404 if not found.
    Raises HTTP 409 if already inactive.
    """
    policy = await _get_policy_or_404(db, account_id, policy_id)
    if not policy.is_active:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Policy is already inactive.",
        )
    policy.is_active = False
    await db.commit()
    await db.refresh(policy)
    return _policy_to_response(policy)


async def delete_policy(
    db: AsyncSession,
    account_id: int,
    policy_id: int,
) -> None:
    """Hard-delete a travel policy.

    Raises HTTP 404 if not found.
    Raises HTTP 409 if the policy is active — deactivate it first.
    """
    policy = await _get_policy_or_404(db, account_id, policy_id)
    if policy.is_active:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot delete an active policy. Deactivate it first.",
        )
    await db.delete(policy)
    await db.commit()


async def acknowledge_policy(
    db: AsyncSession,
    account_id: int,
    member_id: int,
    policy_id: int,
) -> AcknowledgementResponse:
    """Record an employee's acknowledgement of a travel policy.

    Raises HTTP 404 if the policy does not exist or is not active.
    Raises HTTP 409 if the member has already acknowledged this policy.
    """
    policy = await _get_policy_or_404(db, account_id, policy_id)
    if not policy.is_active:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Travel policy is not active.",
        )

    # Check for duplicate acknowledgement.
    existing = await db.execute(
        select(CorporatePolicyAcknowledgement).where(
            CorporatePolicyAcknowledgement.policy_id == policy_id,
            CorporatePolicyAcknowledgement.member_id == member_id,
        )
    )
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="You have already acknowledged this policy.",
        )

    ack = CorporatePolicyAcknowledgement(
        policy_id=policy_id,
        member_id=member_id,
        account_id=account_id,
    )
    db.add(ack)
    await db.commit()
    await db.refresh(ack)
    return _ack_to_response(ack)


async def get_member_acknowledgement_status(
    db: AsyncSession,
    account_id: int,
    member_id: int,
) -> MemberAcknowledgementStatus:
    """Return a member's acknowledgement status for the current active policy.

    If no active policy exists, returns ``policy_id=None``,
    ``has_acknowledged=False``.
    """
    active_policy = await _get_active_policy_row(db, account_id)
    if active_policy is None:
        return MemberAcknowledgementStatus(
            member_id=member_id,
            policy_id=None,
            has_acknowledged=False,
            acknowledged_at=None,
            requires_acknowledgement=False,
        )

    result = await db.execute(
        select(CorporatePolicyAcknowledgement).where(
            CorporatePolicyAcknowledgement.policy_id == active_policy.id,
            CorporatePolicyAcknowledgement.member_id == member_id,
        )
    )
    ack = result.scalar_one_or_none()

    return MemberAcknowledgementStatus(
        member_id=member_id,
        policy_id=active_policy.id,
        has_acknowledged=ack is not None,
        acknowledged_at=ack.acknowledged_at if ack is not None else None,
        requires_acknowledgement=active_policy.requires_acknowledgement,
    )


async def get_acknowledgement_summary(
    db: AsyncSession,
    account_id: int,
    policy_id: int,
) -> AcknowledgementSummary:
    """Return all acknowledgements for a specific policy.

    Raises HTTP 404 if the policy is not found for this account.
    """
    await _get_policy_or_404(db, account_id, policy_id)

    result = await db.execute(
        select(CorporatePolicyAcknowledgement).where(
            CorporatePolicyAcknowledgement.policy_id == policy_id,
        ).order_by(CorporatePolicyAcknowledgement.acknowledged_at)
    )
    acks = result.scalars().all()

    return AcknowledgementSummary(
        policy_id=policy_id,
        total_acknowledged=len(acks),
        acknowledgements=[_ack_to_response(a) for a in acks],
    )


async def list_all_platform(
    db: AsyncSession,
    account_id: Optional[int] = None,
) -> TravelPolicyListResponse:
    """Platform-admin: list all travel policies, optionally filtered by account."""
    stmt = select(CorporateTravelPolicy)
    if account_id is not None:
        stmt = stmt.where(CorporateTravelPolicy.account_id == account_id)
    stmt = stmt.order_by(
        CorporateTravelPolicy.account_id,
        CorporateTravelPolicy.created_at.desc(),
    )
    result = await db.execute(stmt)
    policies = result.scalars().all()
    return TravelPolicyListResponse(
        items=[_policy_to_response(p) for p in policies],
        total=len(policies),
    )
