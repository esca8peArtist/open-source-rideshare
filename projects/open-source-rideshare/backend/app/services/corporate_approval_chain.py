"""Service layer for Corporate Multi-Level Approval Chains.

Approval chains allow corporate account admins to define configurable
multi-step approval workflows.  Rides matching chain criteria must be
approved by a sequence of admins before the employee can book.

All functions are async and require a SQLAlchemy ``AsyncSession``.

Public surface
--------------
create_chain(db, account_id, data, created_by_id)              -> ApprovalChainResponse
get_chain(db, chain_id, account_id)                            -> ApprovalChainResponse
list_chains(db, account_id, *, is_active)                      -> list[ApprovalChainResponse]
update_chain(db, chain_id, account_id, data)                   -> ApprovalChainResponse
deactivate_chain(db, chain_id, account_id)                     -> ApprovalChainResponse
delete_chain(db, chain_id, account_id)                         -> None
find_applicable_chain(db, account_id, *, estimated_cost_usd,
                      cost_center_id)                          -> ApprovalChainResponse | None
start_chain_request(db, chain_id, account_id, requester_id,
                    data)                                      -> ChainRequestResponse
get_chain_request(db, request_id, account_id)                  -> ChainRequestResponse
list_requests(db, account_id, *, status, requester_id)         -> list[ChainRequestResponse]
list_pending_for_approver(db, account_id, approver_id)         -> list[ChainRequestResponse]
decide_step(db, request_id, account_id, approver_id,
            decision, note)                                    -> ChainRequestResponse
cancel_request(db, request_id, account_id, requester_id)       -> ChainRequestResponse
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.corporate_approval_chain import (
    CorporateApprovalChain,
    CorporateApprovalChainRequest,
    CorporateApprovalChainStep,
    CorporateApprovalChainStepDecision,
)
from app.schemas.corporate_approval_chain import (
    ApprovalChainCreate,
    ApprovalChainResponse,
    ApprovalChainStepResponse,
    ApprovalChainUpdate,
    ChainRequestCreate,
    ChainRequestResponse,
    StepDecisionResponse,
)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _step_to_response(step: CorporateApprovalChainStep) -> ApprovalChainStepResponse:
    """Convert an ORM step row to ApprovalChainStepResponse."""
    return ApprovalChainStepResponse.model_validate(step)


def _decision_to_response(
    decision: CorporateApprovalChainStepDecision,
) -> StepDecisionResponse:
    """Convert an ORM decision row to StepDecisionResponse."""
    return StepDecisionResponse.model_validate(decision)


def _chain_to_response(
    chain: CorporateApprovalChain,
    steps: list[CorporateApprovalChainStep],
) -> ApprovalChainResponse:
    """Convert an ORM chain row (with pre-loaded steps) to ApprovalChainResponse."""
    data = ApprovalChainResponse.model_validate(chain)
    data.steps = [_step_to_response(s) for s in steps]
    return data


def _request_to_response(
    request: CorporateApprovalChainRequest,
    decisions: list[CorporateApprovalChainStepDecision],
    total_steps: int,
) -> ChainRequestResponse:
    """Convert an ORM request row to ChainRequestResponse."""
    return ChainRequestResponse(
        id=request.id,
        chain_id=request.chain_id,
        account_id=request.account_id,
        requester_id=request.requester_id,
        current_step_order=request.current_step_order,
        status=request.status,
        estimated_cost_usd=request.estimated_cost_usd,
        cost_center_id=request.cost_center_id,
        purpose=request.purpose,
        destination_description=request.destination_description,
        final_decision_at=request.final_decision_at,
        final_decision_by_id=request.final_decision_by_id,
        created_at=request.created_at,
        decisions=[_decision_to_response(d) for d in decisions],
        total_steps=total_steps,
    )


async def _load_chain_steps(
    db: AsyncSession,
    chain_id: int,
) -> list[CorporateApprovalChainStep]:
    """Load steps for a chain ordered by step_order."""
    result = await db.execute(
        select(CorporateApprovalChainStep)
        .where(CorporateApprovalChainStep.chain_id == chain_id)
        .order_by(CorporateApprovalChainStep.step_order)
    )
    return list(result.scalars().all())


async def _load_request_decisions(
    db: AsyncSession,
    request_id: int,
) -> list[CorporateApprovalChainStepDecision]:
    """Load decisions for a request ordered by step_order."""
    result = await db.execute(
        select(CorporateApprovalChainStepDecision)
        .where(CorporateApprovalChainStepDecision.request_id == request_id)
        .order_by(CorporateApprovalChainStepDecision.step_order)
    )
    return list(result.scalars().all())


# ---------------------------------------------------------------------------
# Public service functions — chain management
# ---------------------------------------------------------------------------


async def create_chain(
    db: AsyncSession,
    account_id: int,
    data: ApprovalChainCreate,
    created_by_id: int,
) -> ApprovalChainResponse:
    """Create a new approval chain with its steps in a single transaction.

    Validates that step_order values are sequential starting from 1.

    Args:
        db:             Async DB session.
        account_id:     Corporate account the chain belongs to.
        data:           Chain creation payload including steps.
        created_by_id:  User ID of the admin creating the chain.

    Returns:
        ApprovalChainResponse for the newly created chain.

    Raises:
        HTTP 422 if steps are not sequential starting from 1.
    """
    # Validate step order is sequential from 1
    orders = sorted(s.step_order for s in data.steps)
    if orders != list(range(1, len(orders) + 1)):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Step order values must be sequential starting from 1.",
        )

    chain = CorporateApprovalChain(
        account_id=account_id,
        created_by_id=created_by_id,
        name=data.name,
        description=data.description,
        min_cost_usd=data.min_cost_usd,
        applies_to_all_cost_centers=data.applies_to_all_cost_centers,
        cost_center_ids=data.cost_center_ids,
        is_active=True,
    )
    db.add(chain)
    await db.flush()  # get chain.id without committing

    steps: list[CorporateApprovalChainStep] = []
    for step_data in sorted(data.steps, key=lambda s: s.step_order):
        step = CorporateApprovalChainStep(
            chain_id=chain.id,
            step_order=step_data.step_order,
            approver_type=step_data.approver_type.value,
            approver_user_id=step_data.approver_user_id,
            timeout_hours=step_data.timeout_hours,
            escalation_action=step_data.escalation_action.value,
            description=step_data.description,
        )
        db.add(step)
        steps.append(step)

    await db.commit()
    await db.refresh(chain)
    for step in steps:
        await db.refresh(step)

    return _chain_to_response(chain, steps)


async def get_chain(
    db: AsyncSession,
    chain_id: int,
    account_id: int,
) -> ApprovalChainResponse:
    """Return a single chain by ID, scoped to the given account.

    Args:
        db:         Async DB session.
        chain_id:   ID of the chain to fetch.
        account_id: Account scope guard.

    Returns:
        ApprovalChainResponse with steps.

    Raises:
        HTTP 404 if chain not found or belongs to a different account.
    """
    result = await db.execute(
        select(CorporateApprovalChain).where(
            and_(
                CorporateApprovalChain.id == chain_id,
                CorporateApprovalChain.account_id == account_id,
            )
        )
    )
    chain = result.scalar_one_or_none()
    if chain is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Approval chain not found.",
        )
    steps = await _load_chain_steps(db, chain_id)
    return _chain_to_response(chain, steps)


async def list_chains(
    db: AsyncSession,
    account_id: int,
    *,
    is_active: Optional[bool] = None,
) -> list[ApprovalChainResponse]:
    """List chains for a corporate account with optional is_active filter.

    Args:
        db:         Async DB session.
        account_id: Corporate account to query.
        is_active:  Optional filter; None returns all chains.

    Returns:
        List of ApprovalChainResponse sorted by id descending.
    """
    filters = [CorporateApprovalChain.account_id == account_id]
    if is_active is not None:
        filters.append(CorporateApprovalChain.is_active.is_(is_active))

    result = await db.execute(
        select(CorporateApprovalChain)
        .where(and_(*filters))
        .order_by(CorporateApprovalChain.id.desc())
    )
    chains = list(result.scalars().all())

    responses = []
    for chain in chains:
        steps = await _load_chain_steps(db, chain.id)
        responses.append(_chain_to_response(chain, steps))
    return responses


async def update_chain(
    db: AsyncSession,
    chain_id: int,
    account_id: int,
    data: ApprovalChainUpdate,
) -> ApprovalChainResponse:
    """Partially update a chain; replace all steps if steps are provided.

    Args:
        db:         Async DB session.
        chain_id:   Chain to update.
        account_id: Account scope guard.
        data:       Fields to update; non-None values are applied.

    Returns:
        Updated ApprovalChainResponse.

    Raises:
        HTTP 404 if chain not found or belongs to a different account.
        HTTP 422 if new steps are not sequential starting from 1.
    """
    result = await db.execute(
        select(CorporateApprovalChain).where(
            and_(
                CorporateApprovalChain.id == chain_id,
                CorporateApprovalChain.account_id == account_id,
            )
        )
    )
    chain = result.scalar_one_or_none()
    if chain is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Approval chain not found.",
        )

    # Apply scalar field updates
    if data.name is not None:
        chain.name = data.name
    if data.description is not None:
        chain.description = data.description
    if data.min_cost_usd is not None:
        chain.min_cost_usd = data.min_cost_usd
    if data.applies_to_all_cost_centers is not None:
        chain.applies_to_all_cost_centers = data.applies_to_all_cost_centers
    if data.cost_center_ids is not None:
        chain.cost_center_ids = data.cost_center_ids
    if data.is_active is not None:
        chain.is_active = data.is_active

    # Replace steps if provided
    if data.steps is not None:
        orders = sorted(s.step_order for s in data.steps)
        if orders != list(range(1, len(orders) + 1)):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Step order values must be sequential starting from 1.",
            )
        # Delete existing steps
        old_steps_result = await db.execute(
            select(CorporateApprovalChainStep).where(
                CorporateApprovalChainStep.chain_id == chain_id
            )
        )
        for old_step in old_steps_result.scalars().all():
            await db.delete(old_step)
        await db.flush()

        for step_data in sorted(data.steps, key=lambda s: s.step_order):
            step = CorporateApprovalChainStep(
                chain_id=chain_id,
                step_order=step_data.step_order,
                approver_type=step_data.approver_type.value,
                approver_user_id=step_data.approver_user_id,
                timeout_hours=step_data.timeout_hours,
                escalation_action=step_data.escalation_action.value,
                description=step_data.description,
            )
            db.add(step)

    await db.commit()
    await db.refresh(chain)
    steps = await _load_chain_steps(db, chain_id)
    return _chain_to_response(chain, steps)


async def deactivate_chain(
    db: AsyncSession,
    chain_id: int,
    account_id: int,
) -> ApprovalChainResponse:
    """Mark an approval chain as inactive.

    Args:
        db:         Async DB session.
        chain_id:   Chain to deactivate.
        account_id: Account scope guard.

    Returns:
        Updated ApprovalChainResponse.

    Raises:
        HTTP 404 if chain not found or belongs to a different account.
        HTTP 409 if chain is already inactive.
    """
    result = await db.execute(
        select(CorporateApprovalChain).where(
            and_(
                CorporateApprovalChain.id == chain_id,
                CorporateApprovalChain.account_id == account_id,
            )
        )
    )
    chain = result.scalar_one_or_none()
    if chain is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Approval chain not found.",
        )
    if not chain.is_active:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Approval chain is already inactive.",
        )

    chain.is_active = False
    await db.commit()
    await db.refresh(chain)
    steps = await _load_chain_steps(db, chain_id)
    return _chain_to_response(chain, steps)


async def delete_chain(
    db: AsyncSession,
    chain_id: int,
    account_id: int,
) -> None:
    """Permanently delete an approval chain.

    Args:
        db:         Async DB session.
        chain_id:   Chain to delete.
        account_id: Account scope guard.

    Raises:
        HTTP 404 if chain not found or belongs to a different account.
        HTTP 409 if there are pending requests referencing this chain.
    """
    result = await db.execute(
        select(CorporateApprovalChain).where(
            and_(
                CorporateApprovalChain.id == chain_id,
                CorporateApprovalChain.account_id == account_id,
            )
        )
    )
    chain = result.scalar_one_or_none()
    if chain is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Approval chain not found.",
        )

    # Check for pending requests
    pending_result = await db.execute(
        select(CorporateApprovalChainRequest).where(
            and_(
                CorporateApprovalChainRequest.chain_id == chain_id,
                CorporateApprovalChainRequest.status == "pending",
            )
        )
    )
    if pending_result.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot delete a chain with pending approval requests.",
        )

    await db.delete(chain)
    await db.commit()


async def find_applicable_chain(
    db: AsyncSession,
    account_id: int,
    *,
    estimated_cost_usd: Optional[float] = None,
    cost_center_id: Optional[int] = None,
) -> Optional[ApprovalChainResponse]:
    """Find the most specific active chain applicable to a given ride context.

    Returns the FIRST active chain (ordered by min_cost_usd desc) where:
      - min_cost_usd is None OR estimated_cost_usd >= min_cost_usd
      - applies_to_all_cost_centers=True OR cost_center_id is in cost_center_ids

    Args:
        db:                  Async DB session.
        account_id:          Corporate account to query.
        estimated_cost_usd:  Estimated ride cost.
        cost_center_id:      Cost center for the ride.

    Returns:
        The most specific matching ApprovalChainResponse, or None.
    """
    result = await db.execute(
        select(CorporateApprovalChain)
        .where(
            and_(
                CorporateApprovalChain.account_id == account_id,
                CorporateApprovalChain.is_active.is_(True),
            )
        )
        .order_by(CorporateApprovalChain.min_cost_usd.desc().nullslast())
    )
    chains = list(result.scalars().all())

    for chain in chains:
        # Check cost threshold
        if chain.min_cost_usd is not None:
            if estimated_cost_usd is None or estimated_cost_usd < float(chain.min_cost_usd):
                continue

        # Check cost center scope
        if not chain.applies_to_all_cost_centers:
            if cost_center_id is None:
                continue
            ids = chain.cost_center_ids or []
            if cost_center_id not in ids:
                continue

        steps = await _load_chain_steps(db, chain.id)
        return _chain_to_response(chain, steps)

    return None


# ---------------------------------------------------------------------------
# Public service functions — request management
# ---------------------------------------------------------------------------


async def start_chain_request(
    db: AsyncSession,
    chain_id: int,
    account_id: int,
    requester_id: int,
    data: ChainRequestCreate,
) -> ChainRequestResponse:
    """Start a new multi-step approval request on the given chain.

    Args:
        db:           Async DB session.
        chain_id:     Chain to run (must belong to account_id).
        account_id:   Account scope guard.
        requester_id: Employee initiating the request.
        data:         Request creation payload.

    Returns:
        ChainRequestResponse in pending status at step 1.

    Raises:
        HTTP 404 if chain not found or belongs to a different account.
        HTTP 409 if the chain is inactive.
    """
    result = await db.execute(
        select(CorporateApprovalChain).where(
            and_(
                CorporateApprovalChain.id == chain_id,
                CorporateApprovalChain.account_id == account_id,
            )
        )
    )
    chain = result.scalar_one_or_none()
    if chain is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Approval chain not found.",
        )
    if not chain.is_active:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot start a request on an inactive chain.",
        )

    steps = await _load_chain_steps(db, chain_id)

    request = CorporateApprovalChainRequest(
        chain_id=chain_id,
        account_id=account_id,
        requester_id=requester_id,
        current_step_order=1,
        status="pending",
        estimated_cost_usd=data.estimated_cost_usd,
        cost_center_id=data.cost_center_id,
        purpose=data.purpose,
        destination_description=data.destination_description,
    )
    db.add(request)
    await db.commit()
    await db.refresh(request)

    return _request_to_response(request, [], len(steps))


async def get_chain_request(
    db: AsyncSession,
    request_id: int,
    account_id: int,
) -> ChainRequestResponse:
    """Return a single approval request by ID, scoped to the given account.

    Args:
        db:         Async DB session.
        request_id: Request to fetch.
        account_id: Account scope guard.

    Returns:
        ChainRequestResponse with decisions.

    Raises:
        HTTP 404 if not found or belongs to a different account.
    """
    result = await db.execute(
        select(CorporateApprovalChainRequest).where(
            and_(
                CorporateApprovalChainRequest.id == request_id,
                CorporateApprovalChainRequest.account_id == account_id,
            )
        )
    )
    request = result.scalar_one_or_none()
    if request is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Approval request not found.",
        )

    decisions = await _load_request_decisions(db, request_id)
    total_steps = 0
    if request.chain_id is not None:
        steps = await _load_chain_steps(db, request.chain_id)
        total_steps = len(steps)

    return _request_to_response(request, decisions, total_steps)


async def list_requests(
    db: AsyncSession,
    account_id: int,
    *,
    status: Optional[str] = None,
    requester_id: Optional[int] = None,
) -> list[ChainRequestResponse]:
    """List approval requests for a corporate account with optional filters.

    Args:
        db:           Async DB session.
        account_id:   Corporate account to query.
        status:       Optional status filter.
        requester_id: Optional requester filter.

    Returns:
        List of ChainRequestResponse sorted by id descending.
    """
    filters = [CorporateApprovalChainRequest.account_id == account_id]
    if status is not None:
        filters.append(CorporateApprovalChainRequest.status == status)
    if requester_id is not None:
        filters.append(CorporateApprovalChainRequest.requester_id == requester_id)

    result = await db.execute(
        select(CorporateApprovalChainRequest)
        .where(and_(*filters))
        .order_by(CorporateApprovalChainRequest.id.desc())
    )
    requests = list(result.scalars().all())

    responses = []
    for req in requests:
        decisions = await _load_request_decisions(db, req.id)
        total_steps = 0
        if req.chain_id is not None:
            steps = await _load_chain_steps(db, req.chain_id)
            total_steps = len(steps)
        responses.append(_request_to_response(req, decisions, total_steps))
    return responses


async def list_pending_for_approver(
    db: AsyncSession,
    account_id: int,
    approver_id: int,
) -> list[ChainRequestResponse]:
    """Return pending requests where the current step targets this approver.

    A step targets the approver when:
      - approver_type = "any_admin" (any admin can approve), OR
      - approver_type = "specific_user" AND approver_user_id = approver_id

    Args:
        db:          Async DB session.
        account_id:  Account scope guard.
        approver_id: User ID of the potential approver.

    Returns:
        List of ChainRequestResponse.
    """
    # Fetch all pending requests for the account
    result = await db.execute(
        select(CorporateApprovalChainRequest).where(
            and_(
                CorporateApprovalChainRequest.account_id == account_id,
                CorporateApprovalChainRequest.status == "pending",
            )
        )
    )
    pending_requests = list(result.scalars().all())

    responses = []
    for req in pending_requests:
        if req.chain_id is None:
            continue
        # Load current step
        step_result = await db.execute(
            select(CorporateApprovalChainStep).where(
                and_(
                    CorporateApprovalChainStep.chain_id == req.chain_id,
                    CorporateApprovalChainStep.step_order == req.current_step_order,
                )
            )
        )
        step = step_result.scalar_one_or_none()
        if step is None:
            continue

        if step.approver_type == "any_admin":
            pass  # Any admin qualifies
        elif step.approver_type == "specific_user":
            if step.approver_user_id != approver_id:
                continue
        else:
            continue

        decisions = await _load_request_decisions(db, req.id)
        steps = await _load_chain_steps(db, req.chain_id)
        responses.append(_request_to_response(req, decisions, len(steps)))

    return responses


async def decide_step(
    db: AsyncSession,
    request_id: int,
    account_id: int,
    approver_id: int,
    decision: str,
    note: Optional[str] = None,
) -> ChainRequestResponse:
    """Record an approval decision for the current step of a request.

    If the decision is "approved" and there is a next step, the request
    advances.  If there is no next step, the request is fully approved.
    If the decision is "denied", the request is immediately closed as denied.

    Args:
        db:          Async DB session.
        request_id:  Request to decide on.
        account_id:  Account scope guard.
        approver_id: User making the decision.
        decision:    "approved" or "denied".
        note:        Optional note.

    Returns:
        Updated ChainRequestResponse.

    Raises:
        HTTP 404 if request not found or belongs to a different account.
        HTTP 409 if request status != "pending".
        HTTP 403 if step is specific_user and approver_id does not match.
    """
    result = await db.execute(
        select(CorporateApprovalChainRequest).where(
            and_(
                CorporateApprovalChainRequest.id == request_id,
                CorporateApprovalChainRequest.account_id == account_id,
            )
        )
    )
    request = result.scalar_one_or_none()
    if request is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Approval request not found.",
        )
    if request.status != "pending":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Request is not pending (current status: {request.status}).",
        )

    # Load current step
    step_result = await db.execute(
        select(CorporateApprovalChainStep).where(
            and_(
                CorporateApprovalChainStep.chain_id == request.chain_id,
                CorporateApprovalChainStep.step_order == request.current_step_order,
            )
        )
    )
    current_step = step_result.scalar_one_or_none()
    if current_step is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Current step definition not found.",
        )

    # Authorisation check for specific_user steps
    if (
        current_step.approver_type == "specific_user"
        and current_step.approver_user_id != approver_id
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not the designated approver for this step.",
        )

    now = datetime.now(tz=timezone.utc)

    # Record the decision
    step_decision = CorporateApprovalChainStepDecision(
        request_id=request_id,
        step_order=request.current_step_order,
        approver_id=approver_id,
        decision=decision,
        note=note,
        decided_at=now,
    )
    db.add(step_decision)

    if decision == "denied":
        request.status = "denied"
        request.final_decision_at = now
        request.final_decision_by_id = approver_id
    elif decision == "approved":
        # Check if there is a next step
        next_step_result = await db.execute(
            select(CorporateApprovalChainStep).where(
                and_(
                    CorporateApprovalChainStep.chain_id == request.chain_id,
                    CorporateApprovalChainStep.step_order
                    == request.current_step_order + 1,
                )
            )
        )
        next_step = next_step_result.scalar_one_or_none()
        if next_step is not None:
            request.current_step_order += 1
        else:
            # Last step approved — request is fully approved
            request.status = "approved"
            request.final_decision_at = now
            request.final_decision_by_id = approver_id

    await db.flush()
    await db.commit()
    await db.refresh(request)

    decisions = await _load_request_decisions(db, request_id)
    total_steps = 0
    if request.chain_id is not None:
        steps = await _load_chain_steps(db, request.chain_id)
        total_steps = len(steps)
    return _request_to_response(request, decisions, total_steps)


async def cancel_request(
    db: AsyncSession,
    request_id: int,
    account_id: int,
    requester_id: int,
) -> ChainRequestResponse:
    """Cancel a pending approval request.

    Args:
        db:           Async DB session.
        request_id:   Request to cancel.
        account_id:   Account scope guard.
        requester_id: User cancelling the request (typically the requester).

    Returns:
        Updated ChainRequestResponse in cancelled status.

    Raises:
        HTTP 404 if request not found or belongs to a different account.
        HTTP 409 if request status != "pending".
    """
    result = await db.execute(
        select(CorporateApprovalChainRequest).where(
            and_(
                CorporateApprovalChainRequest.id == request_id,
                CorporateApprovalChainRequest.account_id == account_id,
            )
        )
    )
    request = result.scalar_one_or_none()
    if request is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Approval request not found.",
        )
    if request.status != "pending":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Request is not pending (current status: {request.status}).",
        )

    request.status = "cancelled"
    await db.commit()
    await db.refresh(request)

    decisions = await _load_request_decisions(db, request_id)
    total_steps = 0
    if request.chain_id is not None:
        steps = await _load_chain_steps(db, request.chain_id)
        total_steps = len(steps)
    return _request_to_response(request, decisions, total_steps)


# ---------------------------------------------------------------------------
# Platform-admin helpers
# ---------------------------------------------------------------------------


async def list_all_chains(
    db: AsyncSession,
    *,
    account_id: Optional[int] = None,
    limit: int = 200,
    offset: int = 0,
) -> list[ApprovalChainResponse]:
    """List chains across all accounts (platform-admin use).

    Args:
        db:         Async DB session.
        account_id: Optional filter to a single account.
        limit:      Maximum rows (default 200).
        offset:     Pagination offset (default 0).

    Returns:
        List of ApprovalChainResponse.
    """
    filters = []
    if account_id is not None:
        filters.append(CorporateApprovalChain.account_id == account_id)

    query = select(CorporateApprovalChain).order_by(
        CorporateApprovalChain.id.desc()
    )
    if filters:
        query = query.where(and_(*filters))
    query = query.limit(limit).offset(offset)

    result = await db.execute(query)
    chains = list(result.scalars().all())

    responses = []
    for chain in chains:
        steps = await _load_chain_steps(db, chain.id)
        responses.append(_chain_to_response(chain, steps))
    return responses


async def list_all_requests(
    db: AsyncSession,
    *,
    account_id: Optional[int] = None,
    limit: int = 200,
    offset: int = 0,
) -> list[ChainRequestResponse]:
    """List requests across all accounts (platform-admin use).

    Args:
        db:         Async DB session.
        account_id: Optional filter to a single account.
        limit:      Maximum rows (default 200).
        offset:     Pagination offset (default 0).

    Returns:
        List of ChainRequestResponse.
    """
    filters = []
    if account_id is not None:
        filters.append(CorporateApprovalChainRequest.account_id == account_id)

    query = select(CorporateApprovalChainRequest).order_by(
        CorporateApprovalChainRequest.id.desc()
    )
    if filters:
        query = query.where(and_(*filters))
    query = query.limit(limit).offset(offset)

    result = await db.execute(query)
    requests = list(result.scalars().all())

    responses = []
    for req in requests:
        decisions = await _load_request_decisions(db, req.id)
        total_steps = 0
        if req.chain_id is not None:
            steps = await _load_chain_steps(db, req.chain_id)
            total_steps = len(steps)
        responses.append(_request_to_response(req, decisions, total_steps))
    return responses
