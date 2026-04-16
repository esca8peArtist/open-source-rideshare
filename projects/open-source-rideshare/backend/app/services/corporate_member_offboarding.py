"""Service layer for Corporate Member Offboarding.

Provides a structured workflow for offboarding employees from a corporate
account.  Ten cleanup steps are tracked in a JSONB column; each step can be
executed individually and its effects are applied to the relevant tables.

Public surface
--------------
create_offboarding(db, account_id, member_id, initiated_by_id, reason, last_day, notes)
get_offboarding(db, offboarding_id, account_id)
list_offboardings(db, account_id, status_filter)
execute_step(db, offboarding_id, account_id, step_name, executed_by_id)
complete_offboarding(db, offboarding_id, account_id, completed_by_id)
cancel_offboarding(db, offboarding_id, account_id, cancelled_by_id, notes)
get_offboarding_summary(db, offboarding_id, account_id)
list_pending_steps(db, offboarding_id, account_id)
list_account_offboardings_with_status(db, account_id)
list_all_platform(db, account_id_filter)
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.corporate import BusinessAccountMember
from app.models.corporate_approval_chain import (
    CorporateApprovalChain,
    CorporateApprovalChainStep,
)
from app.models.corporate_carpool_group import CorporateCarpoolMember
from app.models.corporate_delegate import CorporateDelegate
from app.models.corporate_employee_invitation import (
    CorporateEmployeeInvitation,
    InvitationStatus,
)
from app.models.corporate_expense_report import CorporateExpenseReport, ExpenseStatus
from app.models.corporate_member_offboarding import (
    OFFBOARDING_STEPS,
    CorporateMemberOffboarding,
    OffboardingStatus,
    _empty_steps_completed,
)
from app.models.corporate_recurring_ride import CorporateRecurringRide
from app.models.corporate_ride_approval import ApprovalStatus, CorporateRideApproval
from app.models.corporate_shift import CorporateShiftAssignment
from app.models.user import User
from app.schemas.corporate_member_offboarding import (
    OffboardingCreate,
    OffboardingListResponse,
    OffboardingOverviewItem,
    OffboardingOverviewResponse,
    OffboardingResponse,
    OffboardingStepDetail,
    OffboardingSummaryResponse,
    OffboardingUpdate,
)

_TERMINAL_STATUSES = {OffboardingStatus.completed, OffboardingStatus.cancelled}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _offboarding_to_response(ob: CorporateMemberOffboarding) -> OffboardingResponse:
    """Convert an ORM offboarding instance to a response schema."""
    return OffboardingResponse(
        id=ob.id,
        account_id=ob.account_id,
        member_id=ob.member_id,
        member_email=ob.member_email,
        member_name=ob.member_name,
        initiated_by_id=ob.initiated_by_id,
        status=ob.status,
        reason=ob.reason,
        last_day=ob.last_day,
        steps_completed=ob.steps_completed,
        notes=ob.notes,
        completed_at=ob.completed_at,
        cancelled_at=ob.cancelled_at,
        cancelled_by_id=ob.cancelled_by_id,
        is_active=ob.is_active,
        created_at=ob.created_at,
        updated_at=ob.updated_at,
    )


async def _get_offboarding_or_404(
    db: AsyncSession, offboarding_id: uuid.UUID, account_id: int
) -> CorporateMemberOffboarding:
    """Return the offboarding record or raise HTTP 404."""
    result = await db.execute(
        select(CorporateMemberOffboarding).where(
            CorporateMemberOffboarding.id == offboarding_id,
            CorporateMemberOffboarding.account_id == account_id,
        )
    )
    ob = result.scalar_one_or_none()
    if ob is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Offboarding record not found.",
        )
    return ob


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Step execution handlers
# ---------------------------------------------------------------------------


async def _execute_deactivate_membership(
    db: AsyncSession, account_id: int, member_id: int
) -> int:
    """Deactivate the BusinessAccountMember record for this employee."""
    result = await db.execute(
        select(BusinessAccountMember).where(
            BusinessAccountMember.account_id == account_id,
            BusinessAccountMember.user_id == member_id,
            BusinessAccountMember.is_active.is_(True),
        )
    )
    records = result.scalars().all()
    for rec in records:
        rec.is_active = False
    return len(records)


async def _execute_close_pending_approvals(
    db: AsyncSession, account_id: int, member_id: int
) -> int:
    """Deny any pending CorporateRideApproval records for this member."""
    result = await db.execute(
        select(CorporateRideApproval).where(
            CorporateRideApproval.account_id == account_id,
            CorporateRideApproval.requester_user_id == member_id,
            CorporateRideApproval.status == ApprovalStatus.PENDING,
        )
    )
    records = result.scalars().all()
    for rec in records:
        rec.status = ApprovalStatus.DENIED
    return len(records)


async def _execute_cancel_pending_invitations(
    db: AsyncSession, account_id: int, member_id: int
) -> int:
    """Revoke any pending CorporateEmployeeInvitation sent by this member."""
    result = await db.execute(
        select(CorporateEmployeeInvitation).where(
            CorporateEmployeeInvitation.account_id == account_id,
            CorporateEmployeeInvitation.invited_by_id == member_id,
            CorporateEmployeeInvitation.status == InvitationStatus.PENDING,
        )
    )
    records = result.scalars().all()
    for rec in records:
        rec.status = InvitationStatus.REVOKED
    return len(records)


async def _execute_deactivate_recurring_rides(
    db: AsyncSession, account_id: int, member_id: int
) -> int:
    """Deactivate all CorporateRecurringRide records for this member."""
    result = await db.execute(
        select(CorporateRecurringRide).where(
            CorporateRecurringRide.account_id == account_id,
            CorporateRecurringRide.member_id == member_id,
            CorporateRecurringRide.is_active.is_(True),
        )
    )
    records = result.scalars().all()
    for rec in records:
        rec.is_active = False
    return len(records)


async def _execute_remove_from_carpool_groups(
    db: AsyncSession, account_id: int, member_id: int
) -> int:
    """Set is_active=False for all CorporateCarpoolMember records."""
    result = await db.execute(
        select(CorporateCarpoolMember).where(
            CorporateCarpoolMember.account_id == account_id,
            CorporateCarpoolMember.member_id == member_id,
            CorporateCarpoolMember.is_active.is_(True),
        )
    )
    records = result.scalars().all()
    for rec in records:
        rec.is_active = False
    return len(records)


async def _execute_remove_from_shifts(
    db: AsyncSession, account_id: int, member_id: int
) -> int:
    """Set is_active=False for all CorporateShiftAssignment records.

    CorporateShiftAssignment.member_id is a FK to corporate_account_members.id,
    so we join through BusinessAccountMember to match by user_id and account_id.
    """
    # Find the BusinessAccountMember record id for this user in this account
    bam_result = await db.execute(
        select(BusinessAccountMember.id).where(
            BusinessAccountMember.account_id == account_id,
            BusinessAccountMember.user_id == member_id,
        )
    )
    bam_ids = [row[0] for row in bam_result.all()]
    if not bam_ids:
        return 0

    result = await db.execute(
        select(CorporateShiftAssignment).where(
            CorporateShiftAssignment.member_id.in_(bam_ids),
            CorporateShiftAssignment.is_active.is_(True),
        )
    )
    records = result.scalars().all()
    for rec in records:
        rec.is_active = False
    return len(records)


async def _execute_revoke_delegations(
    db: AsyncSession, account_id: int, member_id: int
) -> int:
    """Deactivate CorporateDelegate records where this member is principal or delegate."""
    result = await db.execute(
        select(CorporateDelegate).where(
            CorporateDelegate.account_id == account_id,
            or_(
                CorporateDelegate.principal_id == member_id,
                CorporateDelegate.delegate_id == member_id,
            ),
            CorporateDelegate.is_active.is_(True),
        )
    )
    records = result.scalars().all()
    for rec in records:
        rec.is_active = False
    return len(records)


async def _execute_remove_expense_reports(
    db: AsyncSession, account_id: int, member_id: int
) -> int:
    """Mark pending CorporateExpenseReport records as withdrawn."""
    result = await db.execute(
        select(CorporateExpenseReport).where(
            CorporateExpenseReport.account_id == account_id,
            CorporateExpenseReport.submitted_by_id == member_id,
            CorporateExpenseReport.status == ExpenseStatus.PENDING,
        )
    )
    records = result.scalars().all()
    for rec in records:
        rec.status = ExpenseStatus.WITHDRAWN
    return len(records)


async def _execute_transfer_approval_chain_steps(
    db: AsyncSession, account_id: int, member_id: int
) -> int:
    """Flag CorporateApprovalChainStep records where this member is approver.

    Cannot auto-transfer; we count and log for manual action.
    CorporateApprovalChainStep has no direct account_id, so we join through
    CorporateApprovalChain.
    """
    result = await db.execute(
        select(CorporateApprovalChainStep)
        .join(
            CorporateApprovalChain,
            CorporateApprovalChain.id == CorporateApprovalChainStep.chain_id,
        )
        .where(
            CorporateApprovalChain.account_id == account_id,
            CorporateApprovalChainStep.approver_user_id == member_id,
        )
    )
    records = result.scalars().all()
    return len(records)


async def _execute_data_export_generated(
    db: AsyncSession, account_id: int, member_id: int
) -> int:
    """Flag that data export was generated (actual export uses existing endpoint)."""
    # No DB writes required — this step just records that the export was triggered.
    return 0


# ---------------------------------------------------------------------------
# Step dispatch table
# ---------------------------------------------------------------------------

_STEP_HANDLERS = {
    "deactivate_membership": _execute_deactivate_membership,
    "close_pending_approvals": _execute_close_pending_approvals,
    "cancel_pending_invitations": _execute_cancel_pending_invitations,
    "deactivate_recurring_rides": _execute_deactivate_recurring_rides,
    "remove_from_carpool_groups": _execute_remove_from_carpool_groups,
    "remove_from_shifts": _execute_remove_from_shifts,
    "revoke_delegations": _execute_revoke_delegations,
    "remove_expense_reports": _execute_remove_expense_reports,
    "transfer_approval_chain_steps": _execute_transfer_approval_chain_steps,
    "data_export_generated": _execute_data_export_generated,
}


# ---------------------------------------------------------------------------
# Public service functions
# ---------------------------------------------------------------------------


async def create_offboarding(
    db: AsyncSession,
    account_id: int,
    member_id: int,
    initiated_by_id: Optional[int],
    reason: Optional[str] = None,
    last_day=None,
    notes: Optional[str] = None,
) -> OffboardingResponse:
    """Initiate an offboarding workflow for a corporate account member.

    Raises HTTP 404 if the member does not belong to the account.
    Raises HTTP 409 if an active (non-terminal) offboarding already exists for
    this member in this account.

    Args:
        db:               Async database session.
        account_id:       Corporate account ID.
        member_id:        User ID of the employee being offboarded.
        initiated_by_id:  Admin who triggered the offboarding.
        reason:           Optional reason text.
        last_day:         Optional last working day.
        notes:            Optional notes.

    Returns:
        OffboardingResponse for the new record.
    """
    # Verify member belongs to account
    member_result = await db.execute(
        select(BusinessAccountMember).where(
            BusinessAccountMember.account_id == account_id,
            BusinessAccountMember.user_id == member_id,
        )
    )
    membership = member_result.scalar_one_or_none()
    if membership is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Member not found in this corporate account.",
        )

    # Check for existing active offboarding
    existing_result = await db.execute(
        select(CorporateMemberOffboarding).where(
            CorporateMemberOffboarding.account_id == account_id,
            CorporateMemberOffboarding.member_id == member_id,
            CorporateMemberOffboarding.is_active.is_(True),
        )
    )
    if existing_result.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An active offboarding already exists for this member.",
        )

    # Fetch user details for audit fields
    user_result = await db.execute(
        select(User).where(User.id == member_id)
    )
    user = user_result.scalar_one_or_none()
    member_email = (user.email or "") if user else ""
    member_name = user.name if user else str(member_id)

    ob = CorporateMemberOffboarding(
        account_id=account_id,
        member_id=member_id,
        member_email=member_email,
        member_name=member_name,
        initiated_by_id=initiated_by_id,
        status=OffboardingStatus.pending,
        reason=reason,
        last_day=last_day,
        steps_completed=_empty_steps_completed(),
        notes=notes,
        is_active=True,
    )
    db.add(ob)
    await db.commit()
    await db.refresh(ob)
    return _offboarding_to_response(ob)


async def get_offboarding(
    db: AsyncSession,
    offboarding_id: uuid.UUID,
    account_id: int,
) -> OffboardingResponse:
    """Return an offboarding record by ID.

    Raises HTTP 404 if not found or belongs to a different account.
    """
    ob = await _get_offboarding_or_404(db, offboarding_id, account_id)
    return _offboarding_to_response(ob)


async def list_offboardings(
    db: AsyncSession,
    account_id: int,
    status_filter: Optional[OffboardingStatus] = None,
) -> OffboardingListResponse:
    """List all offboarding records for an account, newest-first.

    Optional filter:
      - ``status_filter``: Only return records with this status.
    """
    stmt = select(CorporateMemberOffboarding).where(
        CorporateMemberOffboarding.account_id == account_id
    )
    if status_filter is not None:
        stmt = stmt.where(CorporateMemberOffboarding.status == status_filter)
    stmt = stmt.order_by(CorporateMemberOffboarding.created_at.desc())

    result = await db.execute(stmt)
    items = result.scalars().all()
    return OffboardingListResponse(
        items=[_offboarding_to_response(ob) for ob in items],
        total=len(items),
    )


async def execute_step(
    db: AsyncSession,
    offboarding_id: uuid.UUID,
    account_id: int,
    step_name: str,
    executed_by_id: Optional[int],
) -> OffboardingResponse:
    """Execute a single offboarding cleanup step.

    Applies the cleanup action for the named step, records it in
    ``steps_completed``, and advances status from ``pending`` to
    ``in_progress`` if needed.

    Raises HTTP 404 if the offboarding is not found.
    Raises HTTP 422 if ``step_name`` is not a valid step.
    Raises HTTP 409 if the step is already completed.
    Raises HTTP 409 if the offboarding is in a terminal state.
    """
    ob = await _get_offboarding_or_404(db, offboarding_id, account_id)

    if step_name not in OFFBOARDING_STEPS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid step name: '{step_name}'. "
            f"Valid steps: {', '.join(OFFBOARDING_STEPS)}",
        )

    if ob.status in _TERMINAL_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot execute step on a {ob.status.value} offboarding.",
        )

    step_data = ob.steps_completed.get(step_name, {})
    if step_data.get("completed", False):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Step '{step_name}' is already completed.",
        )

    # Execute the cleanup handler
    handler = _STEP_HANDLERS[step_name]
    member_id = ob.member_id
    count = 0
    if member_id is not None:
        count = await handler(db, account_id, member_id)
    else:
        # Member was deleted; skip actions that require member_id
        count = 0

    # Update steps_completed — must copy the dict to trigger JSONB mutation
    now = _now_utc()
    new_steps = dict(ob.steps_completed)
    new_steps[step_name] = {
        "completed": True,
        "completed_at": now.isoformat(),
        "completed_by_id": executed_by_id,
        "notes": None,
        "count": count,
    }
    ob.steps_completed = new_steps

    # Advance status from pending → in_progress
    if ob.status == OffboardingStatus.pending:
        ob.status = OffboardingStatus.in_progress

    await db.commit()
    await db.refresh(ob)
    return _offboarding_to_response(ob)


async def complete_offboarding(
    db: AsyncSession,
    offboarding_id: uuid.UUID,
    account_id: int,
    completed_by_id: Optional[int],
) -> OffboardingResponse:
    """Mark an offboarding as completed.

    Raises HTTP 409 if already completed or cancelled.
    """
    ob = await _get_offboarding_or_404(db, offboarding_id, account_id)

    if ob.status in _TERMINAL_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Offboarding is already {ob.status.value}.",
        )

    ob.status = OffboardingStatus.completed
    ob.completed_at = _now_utc()
    ob.is_active = False

    await db.commit()
    await db.refresh(ob)
    return _offboarding_to_response(ob)


async def cancel_offboarding(
    db: AsyncSession,
    offboarding_id: uuid.UUID,
    account_id: int,
    cancelled_by_id: Optional[int],
    notes: Optional[str] = None,
) -> OffboardingResponse:
    """Cancel an offboarding workflow.

    Raises HTTP 409 if already completed or cancelled.
    """
    ob = await _get_offboarding_or_404(db, offboarding_id, account_id)

    if ob.status in _TERMINAL_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Offboarding is already {ob.status.value}.",
        )

    ob.status = OffboardingStatus.cancelled
    ob.cancelled_at = _now_utc()
    ob.cancelled_by_id = cancelled_by_id
    ob.is_active = False
    if notes:
        ob.notes = notes

    await db.commit()
    await db.refresh(ob)
    return _offboarding_to_response(ob)


async def update_offboarding(
    db: AsyncSession,
    offboarding_id: uuid.UUID,
    account_id: int,
    data: OffboardingUpdate,
) -> OffboardingResponse:
    """Partially update reason, last_day, and/or notes fields.

    Raises HTTP 404 if not found.
    """
    ob = await _get_offboarding_or_404(db, offboarding_id, account_id)

    update_data = data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(ob, field, value)

    await db.commit()
    await db.refresh(ob)
    return _offboarding_to_response(ob)


def _build_step_details(steps_completed: dict) -> list[OffboardingStepDetail]:
    """Build a list of OffboardingStepDetail from the steps_completed JSONB dict."""
    details = []
    for step_name in OFFBOARDING_STEPS:
        entry = steps_completed.get(step_name, {})
        completed_at_raw = entry.get("completed_at")
        completed_at = None
        if completed_at_raw:
            try:
                completed_at = datetime.fromisoformat(completed_at_raw)
            except (ValueError, TypeError):
                completed_at = None
        details.append(
            OffboardingStepDetail(
                step_name=step_name,
                completed=entry.get("completed", False),
                completed_at=completed_at,
                completed_by_id=entry.get("completed_by_id"),
                notes=entry.get("notes"),
                count=entry.get("count", 0),
            )
        )
    return details


async def get_offboarding_summary(
    db: AsyncSession,
    offboarding_id: uuid.UUID,
    account_id: int,
) -> OffboardingSummaryResponse:
    """Return a detailed summary of an offboarding including step status.

    Raises HTTP 404 if not found.
    """
    ob = await _get_offboarding_or_404(db, offboarding_id, account_id)
    step_details = _build_step_details(ob.steps_completed)
    completed_steps = sum(1 for d in step_details if d.completed)
    pending_steps = [d.step_name for d in step_details if not d.completed]

    return OffboardingSummaryResponse(
        offboarding=_offboarding_to_response(ob),
        total_steps=len(OFFBOARDING_STEPS),
        completed_steps=completed_steps,
        pending_steps=pending_steps,
        step_details=step_details,
    )


async def list_pending_steps(
    db: AsyncSession,
    offboarding_id: uuid.UUID,
    account_id: int,
) -> list[str]:
    """Return the list of step names not yet completed.

    Raises HTTP 404 if not found.
    """
    ob = await _get_offboarding_or_404(db, offboarding_id, account_id)
    return [
        step
        for step in OFFBOARDING_STEPS
        if not ob.steps_completed.get(step, {}).get("completed", False)
    ]


def _to_overview_item(ob: CorporateMemberOffboarding) -> OffboardingOverviewItem:
    """Build an OffboardingOverviewItem from an ORM record."""
    completed_steps = sum(
        1
        for step in OFFBOARDING_STEPS
        if ob.steps_completed.get(step, {}).get("completed", False)
    )
    return OffboardingOverviewItem(
        id=ob.id,
        account_id=ob.account_id,
        member_email=ob.member_email,
        member_name=ob.member_name,
        status=ob.status,
        total_steps=len(OFFBOARDING_STEPS),
        completed_steps=completed_steps,
        last_day=ob.last_day,
        created_at=ob.created_at,
    )


async def list_account_offboardings_with_status(
    db: AsyncSession,
    account_id: int,
) -> OffboardingOverviewResponse:
    """Return all offboardings for an account with step completion counts."""
    result = await db.execute(
        select(CorporateMemberOffboarding)
        .where(CorporateMemberOffboarding.account_id == account_id)
        .order_by(CorporateMemberOffboarding.created_at.desc())
    )
    items = result.scalars().all()
    return OffboardingOverviewResponse(
        items=[_to_overview_item(ob) for ob in items],
        total=len(items),
    )


async def list_all_platform(
    db: AsyncSession,
    account_id_filter: Optional[int] = None,
) -> OffboardingListResponse:
    """Platform-admin: list all offboardings, optionally filtered by account.

    Args:
        db:               Async database session.
        account_id_filter: When provided, only return offboardings for this account.

    Returns:
        OffboardingListResponse ordered newest-first.
    """
    stmt = select(CorporateMemberOffboarding)
    if account_id_filter is not None:
        stmt = stmt.where(
            CorporateMemberOffboarding.account_id == account_id_filter
        )
    stmt = stmt.order_by(CorporateMemberOffboarding.created_at.desc())

    result = await db.execute(stmt)
    items = result.scalars().all()
    return OffboardingListResponse(
        items=[_offboarding_to_response(ob) for ob in items],
        total=len(items),
    )
