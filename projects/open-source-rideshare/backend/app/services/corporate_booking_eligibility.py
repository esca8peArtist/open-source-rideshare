"""Service layer for the Corporate Booking Eligibility Check.

Orchestrates all existing corporate policy infrastructure into a single
pre-booking eligibility check.  Before booking a ride, a member (or admin)
calls ``check_booking_eligibility`` to determine:

  * Is the ride eligible?
  * Does it need manual approval?
  * Was it auto-approved?

Policy layers evaluated (in order):
  0. Onboarding completion          (policy_acknowledged step must be done)
  1. 3-tier effective ride policy  (vehicle category, per-ride cost, purpose,
                                    business hours)
  2. Blackout periods               (hard block or override-with-approval)
  3. Ride count quotas              (daily / weekly / monthly)
  4. Monthly spend limit            (per-member cap from BusinessAccountMember)
  5. Department monthly budget      (aggregate cap across all dept members)
  6. Auto-approval rules            (bypass manual approval when matched)
  7. Approval chains                (manual workflow when no auto-approval)

Public surface
--------------
check_booking_eligibility(db, account_id, member_id, params)
    -> BookingEligibilityResponse
_get_current_month_member_spend(db, account_id, user_id)
    -> Decimal
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.corporate import BusinessAccountMember
from app.models.corporate_department import CorporateDepartment, CorporateDepartmentMember
from app.models.corporate_member_onboarding import CorporateMemberOnboarding
from app.models.ride import Ride
from app.schemas.corporate_booking_eligibility import (
    BookingEligibilityResponse,
    BookingRideParams,
    DeptBudgetCheckSummary,
    QuotaCheckSummary,
)
from app.services.corporate_approval_chain import find_applicable_chain
from app.services.corporate_auto_approval_rule import evaluate_auto_approval
from app.services.corporate_blackout_period import check_booking_blackout
from app.services.corporate_department_ride_policy import (
    get_effective_policy_for_member,
)
from app.services.corporate_member_ride_quota import get_quota_usage

# Business hours window (UTC)
_BH_START_HOUR = 7   # 07:00 UTC inclusive
_BH_END_HOUR = 21    # 21:00 UTC exclusive (i.e., before 21:00)
# Weekday range: 0=Monday … 4=Friday
_BH_WEEKDAY_MAX = 4  # Friday


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _get_member_or_404(
    db: AsyncSession, account_id: int, member_id: int
) -> BusinessAccountMember:
    """Fetch a BusinessAccountMember by PK within an account.

    Args:
        db:         Database session.
        account_id: Corporate account to scope the lookup.
        member_id:  BusinessAccountMember primary key.

    Returns:
        The matching BusinessAccountMember row.

    Raises:
        HTTPException 404: When no matching member is found.
    """
    result = await db.execute(
        select(BusinessAccountMember).where(
            BusinessAccountMember.id == member_id,
            BusinessAccountMember.account_id == account_id,
        )
    )
    member = result.scalar_one_or_none()
    if member is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Corporate account member not found.",
        )
    return member


def _is_business_hours(dt: datetime) -> bool:
    """Return True when *dt* falls within Mon-Fri 07:00-20:59 UTC.

    Args:
        dt: The datetime to test.  If naive, treated as UTC.

    Returns:
        True when inside business hours.
    """
    # Normalise to UTC-aware if needed
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return (
        dt.weekday() <= _BH_WEEKDAY_MAX
        and _BH_START_HOUR <= dt.hour < _BH_END_HOUR
    )


async def _get_current_month_member_spend(
    db: AsyncSession, account_id: int, user_id: int
) -> Decimal:
    """Return the sum of actual_fare for completed corporate rides this month.

    Counts rides where:
      * rider_id = user_id
      * corporate_account_id = account_id
      * actual_fare IS NOT NULL
      * completed_at IS NOT NULL
      * date(completed_at) >= first day of the current calendar month (UTC)

    Args:
        db:         Database session.
        account_id: Corporate account to scope the lookup.
        user_id:    Rider user ID (FK to users table).

    Returns:
        Total spend as a Decimal; zero when no qualifying rides exist.
    """
    now = datetime.now(tz=timezone.utc)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    result = await db.execute(
        select(func.coalesce(func.sum(Ride.actual_fare), 0)).where(
            Ride.rider_id == user_id,
            Ride.corporate_account_id == account_id,
            Ride.actual_fare.is_not(None),
            Ride.completed_at.is_not(None),
            Ride.completed_at >= month_start,
        )
    )
    raw = result.scalar_one()
    return Decimal(str(raw))


async def _get_department_budget_checks(
    db: AsyncSession, account_id: int, user_id: int
) -> list[DeptBudgetCheckSummary]:
    """Return a budget summary for each department the user belongs to that has a cap.

    For each CorporateDepartment (scoped to account_id) where:
      * the user is a CorporateDepartmentMember, AND
      * monthly_budget IS NOT NULL

    sums actual_fare for all Rides this calendar month where
    corporate_account_id = account_id AND rider_id is any member of that
    department.

    Args:
        db:         Database session.
        account_id: Corporate account to scope the lookup.
        user_id:    The user whose department memberships should be checked.

    Returns:
        One DeptBudgetCheckSummary per qualifying department; empty list when
        the user belongs to no departments with a monthly_budget set.
    """
    now = datetime.now(tz=timezone.utc)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    # Fetch all departments (with budgets) that this user belongs to
    dept_result = await db.execute(
        select(CorporateDepartment)
        .join(
            CorporateDepartmentMember,
            CorporateDepartmentMember.department_id == CorporateDepartment.id,
        )
        .where(
            CorporateDepartmentMember.user_id == user_id,
            CorporateDepartment.account_id == account_id,
            CorporateDepartment.monthly_budget.is_not(None),
        )
    )
    departments = dept_result.scalars().all()

    summaries: list[DeptBudgetCheckSummary] = []
    for dept in departments:
        # Sum rides this month for all members of this department
        spend_result = await db.execute(
            select(func.coalesce(func.sum(Ride.actual_fare), 0))
            .join(
                CorporateDepartmentMember,
                CorporateDepartmentMember.user_id == Ride.rider_id,
            )
            .where(
                CorporateDepartmentMember.department_id == dept.id,
                Ride.corporate_account_id == account_id,
                Ride.actual_fare.is_not(None),
                Ride.completed_at.is_not(None),
                Ride.completed_at >= month_start,
            )
        )
        raw_spend = spend_result.scalar_one()
        current_spend = Decimal(str(raw_spend))
        budget = Decimal(str(dept.monthly_budget))
        remaining = max(Decimal("0"), budget - current_spend)
        exceeded = current_spend >= budget

        summaries.append(
            DeptBudgetCheckSummary(
                department_id=dept.id,
                department_name=dept.name,
                monthly_budget_usd=budget,
                current_month_spend_usd=current_spend,
                budget_remaining_usd=remaining,
                budget_exceeded=exceeded,
            )
        )

    return summaries


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def check_booking_eligibility(
    db: AsyncSession,
    account_id: int,
    member_id: int,
    params: BookingRideParams,
) -> BookingEligibilityResponse:
    """Evaluate whether a proposed ride is eligible for corporate booking.

    Runs all policy checks in sequence and assembles a consolidated verdict.

    Args:
        db:         Database session.
        account_id: Corporate account to evaluate against.
        member_id:  BusinessAccountMember primary key (NOT user_id).
        params:     Ride parameters describing the proposed booking.

    Returns:
        BookingEligibilityResponse with a full per-check breakdown.

    Raises:
        HTTPException 404: When the member is not found in the account.
    """
    denial_reasons: list[str] = []

    # ------------------------------------------------------------------
    # 1. Resolve member and user_id
    # ------------------------------------------------------------------
    member = await _get_member_or_404(db, account_id, member_id)
    user_id: int = member.user_id

    # Default ride_dt to now if not supplied
    ride_dt: datetime = params.ride_dt or datetime.now(tz=timezone.utc)

    # ------------------------------------------------------------------
    # 0. Onboarding completion check (Step 0 — runs before policy)
    # ------------------------------------------------------------------
    onboarding_incomplete = False
    onboarding_pending_steps: list[str] = []

    onboarding_result = await db.execute(
        select(CorporateMemberOnboarding).where(
            CorporateMemberOnboarding.member_id == user_id,
            CorporateMemberOnboarding.account_id == account_id,
            CorporateMemberOnboarding.status != "completed",
        )
    )
    active_onboarding = onboarding_result.scalar_one_or_none()

    if active_onboarding is not None:
        steps = active_onboarding.steps_completed or {}
        # Collect all steps that are not yet complete
        onboarding_pending_steps = [
            step_name
            for step_name, step_data in steps.items()
            if not step_data.get("completed", False)
        ]
        policy_ack = steps.get("policy_acknowledged", {})
        if not policy_ack.get("completed", False):
            onboarding_incomplete = True
            denial_reasons.append(
                "Corporate policy acknowledgement is required before booking. "
                "Please complete your onboarding checklist."
            )

    # ------------------------------------------------------------------
    # 2. Effective policy check (3-tier)
    # ------------------------------------------------------------------
    effective_policy = await get_effective_policy_for_member(db, account_id, member_id)

    policy_check_passed = True
    policy_violation_reason: Optional[str] = None

    def _fail_policy(reason: str) -> None:
        nonlocal policy_check_passed, policy_violation_reason
        policy_check_passed = False
        policy_violation_reason = reason
        denial_reasons.append(reason)

    # Vehicle category
    if (
        effective_policy.allowed_vehicle_categories is not None
        and params.vehicle_category not in effective_policy.allowed_vehicle_categories
    ):
        _fail_policy(
            f"Vehicle category '{params.vehicle_category}' is not in the "
            f"allowed categories: {effective_policy.allowed_vehicle_categories}."
        )

    # Per-ride cost cap
    if (
        effective_policy.max_per_ride_usd is not None
        and params.estimated_cost_usd > effective_policy.max_per_ride_usd
    ):
        _fail_policy(
            f"Estimated cost ${params.estimated_cost_usd} exceeds the "
            f"per-ride limit of ${effective_policy.max_per_ride_usd}."
        )

    # Purpose required
    if effective_policy.require_purpose and params.trip_purpose_code is None:
        _fail_policy("A trip purpose code is required for this account.")

    # Purpose in approved list
    if (
        effective_policy.approved_purposes is not None
        and params.trip_purpose_code is not None
        and params.trip_purpose_code not in effective_policy.approved_purposes
    ):
        _fail_policy(
            f"Trip purpose '{params.trip_purpose_code}' is not in the "
            f"approved purposes: {effective_policy.approved_purposes}."
        )

    # Business hours restriction
    if effective_policy.business_hours_only and not _is_business_hours(ride_dt):
        _fail_policy(
            "Rides are restricted to business hours (Mon-Fri 07:00-21:00 UTC)."
        )

    # ------------------------------------------------------------------
    # 3. Blackout check
    # ------------------------------------------------------------------
    blackout_periods = await check_booking_blackout(db, account_id, ride_dt)

    in_blackout = len(blackout_periods) > 0
    blackout_override_allowed = False
    blackout_requires_approval = False
    blackout_period_ids: list[int] = []

    if in_blackout:
        for bp in blackout_periods:
            blackout_period_ids.append(bp.id)
            if bp.override_allowed:
                blackout_override_allowed = True
            if bp.override_requires_approval:
                blackout_requires_approval = True

        if not blackout_override_allowed:
            denial_reasons.append(
                "The requested ride time falls within a blackout period and "
                "overrides are not permitted."
            )

    # ------------------------------------------------------------------
    # 4. Quota checks (daily / weekly / monthly)
    # ------------------------------------------------------------------
    quota_checks: list[QuotaCheckSummary] = []
    any_quota_exceeded = False

    for period in ("daily", "weekly", "monthly"):
        quota_result = await get_quota_usage(db, account_id, user_id, period)
        quota_checks.append(
            QuotaCheckSummary(
                period=period,
                quota_active=quota_result.quota_active,
                max_rides=quota_result.max_rides,
                current_period_rides=quota_result.current_period_rides,
                remaining_rides=quota_result.remaining_rides,
                quota_exceeded=quota_result.quota_exceeded,
            )
        )
        if quota_result.quota_exceeded:
            any_quota_exceeded = True
            denial_reasons.append(
                f"The {period} ride quota has been exceeded "
                f"({quota_result.current_period_rides}/{quota_result.max_rides} rides used)."
            )

    # ------------------------------------------------------------------
    # 5. Monthly spend limit
    # ------------------------------------------------------------------
    monthly_spend_limit_usd: Optional[Decimal] = member.monthly_spend_limit
    current_month_spend_usd = await _get_current_month_member_spend(
        db, account_id, user_id
    )

    spend_remaining_usd: Optional[Decimal] = None
    spend_limit_exceeded = False

    if monthly_spend_limit_usd is not None:
        spend_remaining_usd = max(
            Decimal("0"), monthly_spend_limit_usd - current_month_spend_usd
        )
        if current_month_spend_usd >= monthly_spend_limit_usd:
            spend_limit_exceeded = True
            denial_reasons.append(
                f"Monthly spend limit of ${monthly_spend_limit_usd} has been "
                f"reached (current spend: ${current_month_spend_usd})."
            )

    # ------------------------------------------------------------------
    # 5b. Department monthly budget check
    # ------------------------------------------------------------------
    dept_budget_details = await _get_department_budget_checks(db, account_id, user_id)
    dept_budget_exceeded = False

    for dept_summary in dept_budget_details:
        if dept_summary.budget_exceeded:
            dept_budget_exceeded = True
            denial_reasons.append(
                f"Department '{dept_summary.department_name}' monthly budget of "
                f"${dept_summary.monthly_budget_usd} has been reached "
                f"(current spend: ${dept_summary.current_month_spend_usd})."
            )

    # ------------------------------------------------------------------
    # 6. Auto-approval evaluation
    # ------------------------------------------------------------------
    auto_approved, matched_rule = await evaluate_auto_approval(
        db,
        account_id,
        member_id,
        float(params.estimated_cost_usd),
        params.trip_purpose_id,
        params.cost_center_id,
        ride_dt,
    )

    auto_approval_rule_id: Optional[int] = matched_rule.id if matched_rule else None

    # ------------------------------------------------------------------
    # 7. Approval chain lookup (only when not auto-approved)
    # ------------------------------------------------------------------
    approval_chain_id: Optional[int] = None
    requires_approval = False

    if not auto_approved:
        applicable_chain = await find_applicable_chain(
            db,
            account_id,
            estimated_cost_usd=float(params.estimated_cost_usd),
            cost_center_id=params.cost_center_id,
        )
        if applicable_chain is not None:
            approval_chain_id = applicable_chain.id
            requires_approval = True

    # ------------------------------------------------------------------
    # 8. Final eligibility verdict
    # ------------------------------------------------------------------
    blackout_hard_block = in_blackout and not blackout_override_allowed

    eligible = (
        not onboarding_incomplete
        and policy_check_passed
        and not any_quota_exceeded
        and not spend_limit_exceeded
        and not dept_budget_exceeded
        and not blackout_hard_block
    )

    return BookingEligibilityResponse(
        eligible=eligible,
        requires_approval=requires_approval,
        auto_approved=auto_approved,
        auto_approval_rule_id=auto_approval_rule_id,
        approval_chain_id=approval_chain_id,
        policy_check_passed=policy_check_passed,
        policy_violation_reason=policy_violation_reason,
        in_blackout=in_blackout,
        blackout_override_allowed=blackout_override_allowed,
        blackout_requires_approval=blackout_requires_approval,
        blackout_period_ids=blackout_period_ids,
        quota_checks=quota_checks,
        any_quota_exceeded=any_quota_exceeded,
        monthly_spend_limit_usd=monthly_spend_limit_usd,
        current_month_spend_usd=current_month_spend_usd,
        spend_remaining_usd=spend_remaining_usd,
        spend_limit_exceeded=spend_limit_exceeded,
        dept_budget_exceeded=dept_budget_exceeded,
        dept_budget_details=dept_budget_details,
        onboarding_incomplete=onboarding_incomplete,
        onboarding_pending_steps=onboarding_pending_steps,
        denial_reasons=denial_reasons,
    )
