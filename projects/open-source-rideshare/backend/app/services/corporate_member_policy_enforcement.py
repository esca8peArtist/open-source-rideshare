"""Service layer for Corporate Member Policy Enforcement.

Validates a proposed ride booking against a corporate member's effective
ride policy before the booking is confirmed.

The effective policy is the merged result of the account-level
``CorporateRidePolicy`` and any active ``CorporateMemberPolicyOverride``
for the member, as computed by ``get_effective_policy``.

Public surface
--------------
check_booking_against_policy(db, account_id, member_id, request)
    -> BookingPolicyCheckResponse

get_member_monthly_spend(db, account_id, member_id)
    -> Decimal
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.corporate import BusinessAccountMember
from app.models.ride import Ride, RideStatus
from app.schemas.corporate_member_policy_enforcement import (
    BookingPolicyCheckRequest,
    BookingPolicyCheckResponse,
    PolicyCheckOutcome,
    PolicyViolation,
)
from app.services.corporate_member_policy_override import get_effective_policy

# Business-hours window (UTC): Mon–Fri 07:00–21:00
_BIZ_HOUR_START = 7   # inclusive
_BIZ_HOUR_END = 21    # exclusive (21:00 is already outside)

# Fare cap grace ratio: fares up to this multiple of the cap get REQUIRES_APPROVAL
# instead of DENIED. e.g. 1.5 means 150 % of cap.
_FARE_APPROVAL_RATIO = Decimal("1.5")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _get_member_user_id(db: AsyncSession, account_id: int, member_id: int) -> int | None:
    """Return the user_id for a BusinessAccountMember row, or None if not found."""
    result = await db.execute(
        select(BusinessAccountMember.user_id).where(
            BusinessAccountMember.id == member_id,
            BusinessAccountMember.account_id == account_id,
        )
    )
    return result.scalar_one_or_none()


async def get_member_monthly_spend(
    db: AsyncSession,
    account_id: int,
    member_id: int,
) -> Decimal:
    """Return the member's total ride spend for the current calendar month (UTC).

    Sums ``actual_fare`` (falling back to ``estimated_fare``) for rides that
    are COMPLETED or IN_PROGRESS, belong to this corporate account, and were
    created in the current calendar month.

    If no ride table rows are found, returns Decimal("0.00").

    Args:
        db:         Async database session.
        account_id: Corporate account ID.
        member_id:  The BusinessAccountMember.id whose spend is requested.

    Returns:
        Total spend in USD as a Decimal.
    """
    user_id = await _get_member_user_id(db, account_id, member_id)
    if user_id is None:
        return Decimal("0.00")

    now_utc = datetime.now(timezone.utc)
    year = now_utc.year
    month = now_utc.month

    # Sum actual_fare where available, otherwise estimated_fare.
    # The rides table links a ride to a corporate account via corporate_account_id.
    # NOTE: the rides.corporate_account_id FK references corporate_accounts (legacy)
    # while corporate accounts are stored in corporate_accounts_v2.  We match on
    # rider_id (user_id) and filter by month/year of requested_at, since the legacy
    # FK may point to a different table.  If the project migrates to a unified
    # account table, update this query accordingly.
    fare_expr = func.coalesce(Ride.actual_fare, Ride.estimated_fare)

    result = await db.execute(
        select(func.sum(fare_expr)).where(
            Ride.rider_id == user_id,
            Ride.status.in_([RideStatus.COMPLETED, RideStatus.IN_PROGRESS]),
            func.extract("year", Ride.requested_at) == year,
            func.extract("month", Ride.requested_at) == month,
        )
    )
    total = result.scalar_one_or_none()
    if total is None:
        return Decimal("0.00")
    return Decimal(str(total)).quantize(Decimal("0.01"))


# ---------------------------------------------------------------------------
# Violation checkers
# ---------------------------------------------------------------------------


def _check_vehicle_category(
    vehicle_category: str,
    allowed: list[str] | None,
) -> PolicyViolation | None:
    """Return a DENIED violation if vehicle_category is not in the allowed list."""
    if allowed is None:
        return None
    if vehicle_category not in allowed:
        return PolicyViolation(
            field="vehicle_category",
            message=(
                f"Vehicle category '{vehicle_category}' is not permitted. "
                f"Allowed categories: {allowed}."
            ),
            value=vehicle_category,
            limit=allowed,
        )
    return None


def _check_fare_cap(
    fare: Decimal,
    cap: Decimal | None,
) -> tuple[PolicyViolation | None, PolicyCheckOutcome | None]:
    """Return (violation, severity) for a fare vs. cap check.

    Returns:
        (violation, DENIED) if fare > 150 % of cap.
        (violation, REQUIRES_APPROVAL) if cap < fare <= 150 % of cap.
        (None, None) if fare is within cap.
    """
    if cap is None:
        return None, None
    if fare <= cap:
        return None, None

    threshold_150 = cap * _FARE_APPROVAL_RATIO
    if fare > threshold_150:
        return (
            PolicyViolation(
                field="fare_cap",
                message=(
                    f"Estimated fare ${fare} exceeds the per-ride limit "
                    f"(${cap}) by more than 50% — booking denied."
                ),
                value=fare,
                limit=cap,
            ),
            PolicyCheckOutcome.DENIED,
        )
    # Between cap and 150 % of cap → soft block
    return (
        PolicyViolation(
            field="fare_cap",
            message=(
                f"Estimated fare ${fare} exceeds the per-ride limit (${cap}) "
                "— manager approval required."
            ),
            value=fare,
            limit=cap,
        ),
        PolicyCheckOutcome.REQUIRES_APPROVAL,
    )


def _check_business_hours(requested_at: datetime) -> PolicyViolation | None:
    """Return a DENIED violation if requested_at is outside Mon–Fri 07:00–21:00 UTC."""
    # Normalise to UTC
    if requested_at.tzinfo is not None:
        dt = requested_at.astimezone(timezone.utc)
    else:
        dt = requested_at.replace(tzinfo=timezone.utc)

    # weekday(): 0=Mon, 6=Sun
    is_weekday = dt.weekday() < 5
    in_hours = _BIZ_HOUR_START <= dt.hour < _BIZ_HOUR_END

    if is_weekday and in_hours:
        return None

    day_name = dt.strftime("%A")
    time_str = dt.strftime("%H:%M UTC")
    return PolicyViolation(
        field="business_hours",
        message=(
            f"Bookings are restricted to business hours (Mon–Fri 07:00–21:00 UTC). "
            f"Requested at {day_name} {time_str}."
        ),
        value=requested_at.isoformat(),
        limit="Mon–Fri 07:00–21:00 UTC",
    )


def _check_purpose_required(trip_purpose: str | None) -> PolicyViolation | None:
    """Return a DENIED violation if trip_purpose is missing when required."""
    if trip_purpose is not None:
        return None
    return PolicyViolation(
        field="purpose_required",
        message="A trip purpose is required for corporate bookings under this policy.",
        value=None,
        limit="trip_purpose must be provided",
    )


def _check_purpose_allowed(
    trip_purpose: str | None,
    approved: list[str] | None,
) -> PolicyViolation | None:
    """Return a DENIED violation if trip_purpose is not in the approved list."""
    if approved is None or trip_purpose is None:
        return None
    if trip_purpose not in approved:
        return PolicyViolation(
            field="purpose_allowed",
            message=(
                f"Trip purpose '{trip_purpose}' is not in the approved list: {approved}."
            ),
            value=trip_purpose,
            limit=approved,
        )
    return None


def _check_monthly_cap(
    current_spend: Decimal,
    estimated_fare: Decimal,
    cap: Decimal | None,
) -> PolicyViolation | None:
    """Return a REQUIRES_APPROVAL violation if adding this fare would exceed the monthly cap."""
    if cap is None:
        return None
    projected = current_spend + estimated_fare
    if projected > cap:
        return PolicyViolation(
            field="monthly_cap",
            message=(
                f"This ride (${estimated_fare}) would bring monthly spend to "
                f"${projected}, exceeding the monthly cap of ${cap}. "
                "Manager approval required."
            ),
            value=str(projected),
            limit=cap,
        )
    return None


# ---------------------------------------------------------------------------
# Public service function
# ---------------------------------------------------------------------------


async def check_booking_against_policy(
    db: AsyncSession,
    account_id: int,
    member_id: int,
    request: BookingPolicyCheckRequest,
) -> BookingPolicyCheckResponse:
    """Validate a proposed booking against the member's effective ride policy.

    Checks each policy dimension in order, collecting all violations.  The
    final outcome is the most severe violation encountered:

    * Any DENIED violation → DENIED (hard block).
    * Only REQUIRES_APPROVAL violations → REQUIRES_APPROVAL.
    * No violations → ALLOWED.

    Args:
        db:         Async database session.
        account_id: Corporate account ID.
        member_id:  The BusinessAccountMember.id of the rider.
        request:    Details of the proposed booking.

    Returns:
        BookingPolicyCheckResponse with the outcome and all violations.
    """
    effective = await get_effective_policy(db, account_id, member_id)

    # Monthly spend (for reporting and cap check)
    monthly_spend = await get_member_monthly_spend(db, account_id, member_id)
    monthly_limit = effective.max_per_member_monthly_usd

    violations: list[PolicyViolation] = []
    # Track which violations are DENIED vs REQUIRES_APPROVAL
    denied_violations: list[PolicyViolation] = []
    approval_violations: list[PolicyViolation] = []

    # --- 1. Vehicle category ---
    vc_violation = _check_vehicle_category(
        request.vehicle_category, effective.allowed_vehicle_categories
    )
    if vc_violation:
        denied_violations.append(vc_violation)

    # --- 2. Fare cap ---
    fare_violation, fare_severity = _check_fare_cap(
        request.estimated_fare_usd, effective.max_per_ride_usd
    )
    if fare_violation:
        if fare_severity == PolicyCheckOutcome.DENIED:
            denied_violations.append(fare_violation)
        else:
            approval_violations.append(fare_violation)

    # --- 3. Business hours ---
    if effective.business_hours_only:
        bh_violation = _check_business_hours(request.requested_at)
        if bh_violation:
            denied_violations.append(bh_violation)

    # --- 4. Purpose required ---
    if effective.require_purpose:
        pr_violation = _check_purpose_required(request.trip_purpose)
        if pr_violation:
            denied_violations.append(pr_violation)

    # --- 5. Approved purposes ---
    pa_violation = _check_purpose_allowed(
        request.trip_purpose, effective.approved_purposes
    )
    if pa_violation:
        denied_violations.append(pa_violation)

    # --- 6. Monthly cap ---
    mc_violation = _check_monthly_cap(
        monthly_spend, request.estimated_fare_usd, monthly_limit
    )
    if mc_violation:
        approval_violations.append(mc_violation)

    # Collect all violations (denied first for readability)
    violations = denied_violations + approval_violations

    # Determine outcome
    if denied_violations:
        outcome = PolicyCheckOutcome.DENIED
    elif approval_violations:
        outcome = PolicyCheckOutcome.REQUIRES_APPROVAL
    else:
        outcome = PolicyCheckOutcome.ALLOWED

    # Monthly remaining
    if monthly_limit is not None:
        monthly_remaining: Decimal | None = max(
            Decimal("0.00"), monthly_limit - monthly_spend
        )
    else:
        monthly_remaining = None

    # Snapshot of the policy that was applied
    policy_summary = {
        "allowed_vehicle_categories": effective.allowed_vehicle_categories,
        "max_per_ride_usd": str(effective.max_per_ride_usd) if effective.max_per_ride_usd else None,
        "max_per_member_monthly_usd": str(monthly_limit) if monthly_limit else None,
        "require_purpose": effective.require_purpose,
        "approved_purposes": effective.approved_purposes,
        "business_hours_only": effective.business_hours_only,
        "has_member_override": effective.has_override,
        "override_is_active": effective.override_is_active,
    }

    return BookingPolicyCheckResponse(
        outcome=outcome,
        violations=violations,
        monthly_spend_usd=monthly_spend,
        monthly_limit_usd=monthly_limit,
        monthly_remaining_usd=monthly_remaining,
        effective_policy_summary=policy_summary,
    )
