"""Service layer for Corporate Member Onboarding.

Provides a structured checklist for onboarding new employees into a corporate
account.  Ten setup steps are tracked in a JSONB column; nine steps can be
auto-detected from existing data and one requires manual admin confirmation.

Public surface
--------------
create_onboarding(db, account_id, member_id, created_by_id, invitation_id, notes)
get_onboarding(db, onboarding_id, account_id)
get_onboarding_for_member(db, account_id, member_id)
list_onboardings(db, account_id, status_filter)
mark_step_complete(db, onboarding_id, account_id, step_name, marked_by_id, notes)
auto_detect_progress(db, onboarding_id, account_id)
complete_onboarding(db, onboarding_id, account_id, completed_by_id)
update_onboarding(db, onboarding_id, account_id, data)
get_onboarding_summary(db, onboarding_id, account_id)
list_pending_steps(db, onboarding_id, account_id)
list_account_onboardings_with_status(db, account_id)
list_all_platform(db, account_id_filter)
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.corporate import BusinessAccountMember
from app.models.corporate_department import CorporateDepartment, CorporateDepartmentMember
from app.models.corporate_employee_group import CorporateGroupMembership
from app.models.corporate_manager_hierarchy import CorporateManagerRelationship
from app.models.corporate_member_onboarding import (
    AUTO_DETECTABLE_STEPS,
    ONBOARDING_STEPS,
    CorporateMemberOnboarding,
    OnboardingStatus,
    _empty_steps_completed,
)
from app.models.corporate_office_location import CorporateOfficeMembership
from app.models.corporate_travel_policy import CorporatePolicyAcknowledgement
from app.models.corporate_transport_preference import CorporateEmployeeTransportPreference
from app.models.ride import Ride, RideStatus
from app.models.user import User
from app.schemas.corporate_member_onboarding import (
    AutoDetectResult,
    OnboardingCreate,
    OnboardingListResponse,
    OnboardingOverviewItem,
    OnboardingOverviewResponse,
    OnboardingResponse,
    OnboardingStepDetail,
    OnboardingSummaryResponse,
    OnboardingUpdate,
)

_TERMINAL_STATUSES = {OnboardingStatus.completed}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _onboarding_to_response(ob: CorporateMemberOnboarding) -> OnboardingResponse:
    """Convert an ORM onboarding instance to a response schema."""
    return OnboardingResponse(
        id=ob.id,
        account_id=ob.account_id,
        member_id=ob.member_id,
        member_email=ob.member_email,
        member_name=ob.member_name,
        invitation_id=ob.invitation_id,
        created_by_id=ob.created_by_id,
        status=ob.status,
        steps_completed=ob.steps_completed,
        notes=ob.notes,
        completed_at=ob.completed_at,
        is_active=ob.is_active,
        created_at=ob.created_at,
        updated_at=ob.updated_at,
    )


async def _get_onboarding_or_404(
    db: AsyncSession, onboarding_id: uuid.UUID, account_id: int
) -> CorporateMemberOnboarding:
    """Return the onboarding record or raise HTTP 404."""
    result = await db.execute(
        select(CorporateMemberOnboarding).where(
            CorporateMemberOnboarding.id == onboarding_id,
            CorporateMemberOnboarding.account_id == account_id,
        )
    )
    ob = result.scalar_one_or_none()
    if ob is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Onboarding record not found.",
        )
    return ob


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Auto-detection helpers
# ---------------------------------------------------------------------------


async def _detect_membership_activated(
    db: AsyncSession, account_id: int, member_id: int
) -> bool:
    """Check if the member's BusinessAccountMember record is active."""
    result = await db.execute(
        select(BusinessAccountMember).where(
            BusinessAccountMember.account_id == account_id,
            BusinessAccountMember.user_id == member_id,
            BusinessAccountMember.is_active.is_(True),
        )
    )
    return result.scalar_one_or_none() is not None


async def _detect_transport_preferences_set(
    db: AsyncSession, account_id: int, member_id: int
) -> bool:
    """Check if the member has active transport preferences configured."""
    result = await db.execute(
        select(CorporateEmployeeTransportPreference).where(
            CorporateEmployeeTransportPreference.account_id == account_id,
            CorporateEmployeeTransportPreference.member_id == member_id,
            CorporateEmployeeTransportPreference.is_active.is_(True),
        )
    )
    return result.scalar_one_or_none() is not None


async def _detect_department_assigned(
    db: AsyncSession, account_id: int, member_id: int
) -> bool:
    """Check if the member is in any department within this account."""
    result = await db.execute(
        select(CorporateDepartmentMember)
        .join(CorporateDepartment, CorporateDepartment.id == CorporateDepartmentMember.department_id)
        .where(
            CorporateDepartment.account_id == account_id,
            CorporateDepartmentMember.user_id == member_id,
        )
    )
    return result.scalar_one_or_none() is not None


async def _get_bam_id(
    db: AsyncSession, account_id: int, member_id: int
) -> Optional[int]:
    """Return BusinessAccountMember.id for this user in this account, or None."""
    result = await db.execute(
        select(BusinessAccountMember.id).where(
            BusinessAccountMember.account_id == account_id,
            BusinessAccountMember.user_id == member_id,
        )
    )
    row = result.first()
    return row[0] if row else None


async def _detect_office_assigned(
    db: AsyncSession, account_id: int, member_id: int
) -> bool:
    """Check if the member is assigned to any active office."""
    bam_id = await _get_bam_id(db, account_id, member_id)
    if bam_id is None:
        return False
    result = await db.execute(
        select(CorporateOfficeMembership).where(
            CorporateOfficeMembership.account_id == account_id,
            CorporateOfficeMembership.member_id == bam_id,
            CorporateOfficeMembership.is_active.is_(True),
        )
    )
    return result.scalar_one_or_none() is not None


async def _detect_group_assigned(
    db: AsyncSession, account_id: int, member_id: int
) -> bool:
    """Check if the member belongs to any employee group in this account."""
    bam_id = await _get_bam_id(db, account_id, member_id)
    if bam_id is None:
        return False
    result = await db.execute(
        select(CorporateGroupMembership).where(
            CorporateGroupMembership.member_id == bam_id,
        )
    )
    return result.scalar_one_or_none() is not None


async def _detect_policy_acknowledged(
    db: AsyncSession, account_id: int, member_id: int
) -> bool:
    """Check if the member has acknowledged any travel policy for this account."""
    result = await db.execute(
        select(CorporatePolicyAcknowledgement).where(
            CorporatePolicyAcknowledgement.account_id == account_id,
            CorporatePolicyAcknowledgement.member_id == member_id,
        )
    )
    return result.scalar_one_or_none() is not None


async def _detect_manager_assigned(
    db: AsyncSession, account_id: int, member_id: int
) -> bool:
    """Check if the member has an active direct or dotted-line manager."""
    bam_id = await _get_bam_id(db, account_id, member_id)
    if bam_id is None:
        return False
    result = await db.execute(
        select(CorporateManagerRelationship).where(
            CorporateManagerRelationship.account_id == account_id,
            CorporateManagerRelationship.employee_member_id == bam_id,
            CorporateManagerRelationship.is_active.is_(True),
        )
    )
    return result.scalar_one_or_none() is not None


async def _detect_cost_center_configured(
    db: AsyncSession, account_id: int, member_id: int
) -> bool:
    """Check if the member's transport preferences have a default cost center set."""
    result = await db.execute(
        select(CorporateEmployeeTransportPreference).where(
            CorporateEmployeeTransportPreference.account_id == account_id,
            CorporateEmployeeTransportPreference.member_id == member_id,
            CorporateEmployeeTransportPreference.is_active.is_(True),
            CorporateEmployeeTransportPreference.default_cost_center_id.isnot(None),
        )
    )
    return result.scalar_one_or_none() is not None


async def _detect_first_corporate_ride(
    db: AsyncSession, account_id: int, member_id: int
) -> bool:
    """Check if the member has completed at least one corporate-billed ride."""
    result = await db.execute(
        select(Ride).where(
            Ride.rider_id == member_id,
            Ride.corporate_account_id == account_id,
            Ride.status == RideStatus.COMPLETED,
        )
    )
    return result.scalar_one_or_none() is not None


# ---------------------------------------------------------------------------
# Auto-detect dispatch table
# ---------------------------------------------------------------------------

_AUTO_DETECT_HANDLERS = {
    "membership_activated": _detect_membership_activated,
    "transport_preferences_set": _detect_transport_preferences_set,
    "department_assigned": _detect_department_assigned,
    "office_assigned": _detect_office_assigned,
    "group_assigned": _detect_group_assigned,
    "policy_acknowledged": _detect_policy_acknowledged,
    "manager_assigned": _detect_manager_assigned,
    "cost_center_configured": _detect_cost_center_configured,
    "first_corporate_ride": _detect_first_corporate_ride,
}


# ---------------------------------------------------------------------------
# Public service functions
# ---------------------------------------------------------------------------


async def create_onboarding(
    db: AsyncSession,
    account_id: int,
    member_id: int,
    created_by_id: Optional[int],
    invitation_id: Optional[uuid.UUID] = None,
    notes: Optional[str] = None,
) -> OnboardingResponse:
    """Create an onboarding tracker for a new corporate account member.

    Raises HTTP 404 if the member does not belong to the account.
    Raises HTTP 409 if an active onboarding already exists for this member.

    Args:
        db:             Async database session.
        account_id:     Corporate account ID.
        member_id:      User ID of the employee being onboarded.
        created_by_id:  Admin who created the tracker.
        invitation_id:  Optional link to the invitation used to join.
        notes:          Optional notes.

    Returns:
        OnboardingResponse for the new record.
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

    # Check for existing active onboarding
    existing_result = await db.execute(
        select(CorporateMemberOnboarding).where(
            CorporateMemberOnboarding.account_id == account_id,
            CorporateMemberOnboarding.member_id == member_id,
            CorporateMemberOnboarding.is_active.is_(True),
        )
    )
    if existing_result.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An active onboarding already exists for this member.",
        )

    # Fetch user details for audit fields
    user_result = await db.execute(select(User).where(User.id == member_id))
    user = user_result.scalar_one_or_none()
    member_email = (user.email or "") if user else ""
    member_name = user.name if user else str(member_id)

    ob = CorporateMemberOnboarding(
        account_id=account_id,
        member_id=member_id,
        member_email=member_email,
        member_name=member_name,
        invitation_id=invitation_id,
        created_by_id=created_by_id,
        status=OnboardingStatus.pending,
        steps_completed=_empty_steps_completed(),
        notes=notes,
        is_active=True,
    )
    db.add(ob)
    await db.commit()
    await db.refresh(ob)
    return _onboarding_to_response(ob)


async def get_onboarding(
    db: AsyncSession,
    onboarding_id: uuid.UUID,
    account_id: int,
) -> OnboardingResponse:
    """Return an onboarding record by ID.

    Raises HTTP 404 if not found or belongs to a different account.
    """
    ob = await _get_onboarding_or_404(db, onboarding_id, account_id)
    return _onboarding_to_response(ob)


async def get_onboarding_for_member(
    db: AsyncSession,
    account_id: int,
    member_id: int,
) -> OnboardingResponse:
    """Return the active or most recent onboarding for a specific member.

    Raises HTTP 404 if no onboarding exists for this member.
    """
    result = await db.execute(
        select(CorporateMemberOnboarding)
        .where(
            CorporateMemberOnboarding.account_id == account_id,
            CorporateMemberOnboarding.member_id == member_id,
        )
        .order_by(
            CorporateMemberOnboarding.is_active.desc(),
            CorporateMemberOnboarding.created_at.desc(),
        )
        .limit(1)
    )
    ob = result.scalar_one_or_none()
    if ob is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No onboarding found for this member.",
        )
    return _onboarding_to_response(ob)


async def list_onboardings(
    db: AsyncSession,
    account_id: int,
    status_filter: Optional[OnboardingStatus] = None,
) -> OnboardingListResponse:
    """List all onboarding records for an account, newest-first.

    Optional filter:
      - ``status_filter``: Only return records with this status.
    """
    stmt = select(CorporateMemberOnboarding).where(
        CorporateMemberOnboarding.account_id == account_id
    )
    if status_filter is not None:
        stmt = stmt.where(CorporateMemberOnboarding.status == status_filter)
    stmt = stmt.order_by(CorporateMemberOnboarding.created_at.desc())

    result = await db.execute(stmt)
    items = result.scalars().all()
    return OnboardingListResponse(
        items=[_onboarding_to_response(ob) for ob in items],
        total=len(items),
    )


async def mark_step_complete(
    db: AsyncSession,
    onboarding_id: uuid.UUID,
    account_id: int,
    step_name: str,
    marked_by_id: Optional[int],
    notes: Optional[str] = None,
) -> OnboardingResponse:
    """Manually mark an onboarding step as complete.

    Advances status from ``pending`` to ``in_progress`` when the first step
    is marked.  Auto-completes the tracker when all steps are done.

    Raises HTTP 404 if the onboarding is not found.
    Raises HTTP 422 if ``step_name`` is not a valid step.
    Raises HTTP 409 if the step is already completed.
    Raises HTTP 409 if the onboarding is already completed.
    """
    ob = await _get_onboarding_or_404(db, onboarding_id, account_id)

    if step_name not in ONBOARDING_STEPS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid step name: '{step_name}'. "
            f"Valid steps: {', '.join(ONBOARDING_STEPS)}",
        )

    if ob.status in _TERMINAL_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot mark step on a {ob.status.value} onboarding.",
        )

    step_data = ob.steps_completed.get(step_name, {})
    if step_data.get("completed", False):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Step '{step_name}' is already completed.",
        )

    now = _now_utc()
    new_steps = dict(ob.steps_completed)
    new_steps[step_name] = {
        "completed": True,
        "completed_at": now.isoformat(),
        "completed_by_id": marked_by_id,
        "notes": notes,
        "auto_detected": False,
    }
    ob.steps_completed = new_steps

    # Advance status from pending → in_progress
    if ob.status == OnboardingStatus.pending:
        ob.status = OnboardingStatus.in_progress

    # Auto-complete if all steps done
    all_done = all(
        new_steps.get(s, {}).get("completed", False) for s in ONBOARDING_STEPS
    )
    if all_done:
        ob.status = OnboardingStatus.completed
        ob.completed_at = now
        ob.is_active = False

    await db.commit()
    await db.refresh(ob)
    return _onboarding_to_response(ob)


async def auto_detect_progress(
    db: AsyncSession,
    onboarding_id: uuid.UUID,
    account_id: int,
) -> AutoDetectResult:
    """Scan the member's data and auto-mark completed steps.

    Checks nine detectable steps against existing data.  Only marks steps that
    are currently incomplete — already-complete steps are unchanged.  The
    ``onboarding_complete_confirmed`` step is never auto-detected.

    Raises HTTP 404 if the onboarding is not found.
    Raises HTTP 409 if the onboarding is already completed.
    """
    ob = await _get_onboarding_or_404(db, onboarding_id, account_id)

    if ob.status in _TERMINAL_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot auto-detect on a {ob.status.value} onboarding.",
        )

    member_id = ob.member_id
    newly_detected: list[str] = []
    already_completed: list[str] = []
    still_pending: list[str] = []

    now = _now_utc()
    new_steps = dict(ob.steps_completed)

    for step_name in ONBOARDING_STEPS:
        step_data = new_steps.get(step_name, {})
        if step_data.get("completed", False):
            already_completed.append(step_name)
            continue

        if step_name not in AUTO_DETECTABLE_STEPS or member_id is None:
            still_pending.append(step_name)
            continue

        handler = _AUTO_DETECT_HANDLERS[step_name]
        detected = await handler(db, account_id, member_id)

        if detected:
            new_steps[step_name] = {
                "completed": True,
                "completed_at": now.isoformat(),
                "completed_by_id": None,
                "notes": "Auto-detected",
                "auto_detected": True,
            }
            newly_detected.append(step_name)
        else:
            still_pending.append(step_name)

    ob.steps_completed = new_steps

    # Advance status from pending → in_progress if any step was detected
    if newly_detected and ob.status == OnboardingStatus.pending:
        ob.status = OnboardingStatus.in_progress

    # Auto-complete if all steps done
    all_done = all(
        new_steps.get(s, {}).get("completed", False) for s in ONBOARDING_STEPS
    )
    if all_done:
        ob.status = OnboardingStatus.completed
        ob.completed_at = now
        ob.is_active = False

    await db.commit()
    await db.refresh(ob)

    return AutoDetectResult(
        newly_detected=newly_detected,
        already_completed=already_completed,
        still_pending=still_pending,
        onboarding=_onboarding_to_response(ob),
    )


async def complete_onboarding(
    db: AsyncSession,
    onboarding_id: uuid.UUID,
    account_id: int,
    completed_by_id: Optional[int],
) -> OnboardingResponse:
    """Force-complete an onboarding tracker.

    Raises HTTP 409 if already completed.
    """
    ob = await _get_onboarding_or_404(db, onboarding_id, account_id)

    if ob.status in _TERMINAL_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Onboarding is already {ob.status.value}.",
        )

    ob.status = OnboardingStatus.completed
    ob.completed_at = _now_utc()
    ob.is_active = False

    await db.commit()
    await db.refresh(ob)
    return _onboarding_to_response(ob)


async def update_onboarding(
    db: AsyncSession,
    onboarding_id: uuid.UUID,
    account_id: int,
    data: OnboardingUpdate,
) -> OnboardingResponse:
    """Partially update notes for an onboarding record.

    Raises HTTP 404 if not found.
    """
    ob = await _get_onboarding_or_404(db, onboarding_id, account_id)

    update_data = data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(ob, field, value)

    await db.commit()
    await db.refresh(ob)
    return _onboarding_to_response(ob)


def _build_step_details(steps_completed: dict) -> list[OnboardingStepDetail]:
    """Build a list of OnboardingStepDetail from the steps_completed JSONB dict."""
    details = []
    for step_name in ONBOARDING_STEPS:
        entry = steps_completed.get(step_name, {})
        completed_at_raw = entry.get("completed_at")
        completed_at = None
        if completed_at_raw:
            try:
                completed_at = datetime.fromisoformat(completed_at_raw)
            except (ValueError, TypeError):
                completed_at = None
        details.append(
            OnboardingStepDetail(
                step_name=step_name,
                completed=entry.get("completed", False),
                completed_at=completed_at,
                completed_by_id=entry.get("completed_by_id"),
                notes=entry.get("notes"),
                auto_detected=entry.get("auto_detected", False),
            )
        )
    return details


async def get_onboarding_summary(
    db: AsyncSession,
    onboarding_id: uuid.UUID,
    account_id: int,
) -> OnboardingSummaryResponse:
    """Return a detailed summary of an onboarding including step status.

    Raises HTTP 404 if not found.
    """
    ob = await _get_onboarding_or_404(db, onboarding_id, account_id)
    step_details = _build_step_details(ob.steps_completed)
    completed_steps = sum(1 for d in step_details if d.completed)
    pending_steps = [d.step_name for d in step_details if not d.completed]

    return OnboardingSummaryResponse(
        onboarding=_onboarding_to_response(ob),
        total_steps=len(ONBOARDING_STEPS),
        completed_steps=completed_steps,
        pending_steps=pending_steps,
        step_details=step_details,
    )


async def list_pending_steps(
    db: AsyncSession,
    onboarding_id: uuid.UUID,
    account_id: int,
) -> list[str]:
    """Return the list of step names not yet completed.

    Raises HTTP 404 if not found.
    """
    ob = await _get_onboarding_or_404(db, onboarding_id, account_id)
    return [
        step
        for step in ONBOARDING_STEPS
        if not ob.steps_completed.get(step, {}).get("completed", False)
    ]


def _to_overview_item(ob: CorporateMemberOnboarding) -> OnboardingOverviewItem:
    """Build an OnboardingOverviewItem from an ORM record."""
    completed_steps = sum(
        1
        for step in ONBOARDING_STEPS
        if ob.steps_completed.get(step, {}).get("completed", False)
    )
    return OnboardingOverviewItem(
        id=ob.id,
        account_id=ob.account_id,
        member_email=ob.member_email,
        member_name=ob.member_name,
        status=ob.status,
        total_steps=len(ONBOARDING_STEPS),
        completed_steps=completed_steps,
        created_at=ob.created_at,
    )


async def list_account_onboardings_with_status(
    db: AsyncSession,
    account_id: int,
) -> OnboardingOverviewResponse:
    """Return all onboardings for an account with step completion counts."""
    result = await db.execute(
        select(CorporateMemberOnboarding)
        .where(CorporateMemberOnboarding.account_id == account_id)
        .order_by(CorporateMemberOnboarding.created_at.desc())
    )
    items = result.scalars().all()
    return OnboardingOverviewResponse(
        items=[_to_overview_item(ob) for ob in items],
        total=len(items),
    )


async def list_all_platform(
    db: AsyncSession,
    account_id_filter: Optional[int] = None,
) -> OnboardingListResponse:
    """Platform-admin: list all onboardings, optionally filtered by account.

    Args:
        db:               Async database session.
        account_id_filter: When provided, only return onboardings for this account.

    Returns:
        OnboardingListResponse ordered newest-first.
    """
    stmt = select(CorporateMemberOnboarding)
    if account_id_filter is not None:
        stmt = stmt.where(
            CorporateMemberOnboarding.account_id == account_id_filter
        )
    stmt = stmt.order_by(CorporateMemberOnboarding.created_at.desc())

    result = await db.execute(stmt)
    items = result.scalars().all()
    return OnboardingListResponse(
        items=[_onboarding_to_response(ob) for ob in items],
        total=len(items),
    )
