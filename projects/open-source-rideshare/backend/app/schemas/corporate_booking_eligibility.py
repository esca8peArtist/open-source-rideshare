"""Pydantic v2 schemas for Corporate Booking Eligibility Check.

Before a corporate ride is booked, the eligibility check orchestrates all
existing policy infrastructure (effective policy, blackout periods, ride
quotas, spend limits, auto-approval rules, and approval chains) and returns
a single consolidated verdict.

Public surface
--------------
BookingRideParams           — request body for an eligibility check.
QuotaCheckSummary           — per-period quota result embedded in the response.
DeptBudgetCheckSummary      — per-department budget result embedded in the response.
BookingEligibilityResponse  — full eligibility verdict with per-check breakdowns.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import List, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Request schema
# ---------------------------------------------------------------------------


class BookingRideParams(BaseModel):
    """Parameters describing the ride the member wants to book.

    Used as the request body for all three eligibility-check endpoints.

    Attributes:
        vehicle_category:    Requested vehicle type (e.g. "standard", "xl").
        estimated_cost_usd:  Estimated fare in USD; must be positive.
        trip_purpose_id:     Optional trip purpose PK — used for auto-approval
                             rule evaluation.
        trip_purpose_code:   Optional purpose code string (e.g. "CLIENT_MEETING")
                             — used for policy approved_purposes check.
        cost_center_id:      Optional cost center PK — used for auto-approval
                             rule evaluation and approval chain lookup.
        ride_dt:             Proposed ride datetime in UTC.  Defaults to the
                             current time when None.
    """

    vehicle_category: str
    estimated_cost_usd: Decimal = Field(..., gt=0)
    trip_purpose_id: Optional[int] = None
    trip_purpose_code: Optional[str] = None
    cost_center_id: Optional[int] = None
    ride_dt: Optional[datetime] = None


# ---------------------------------------------------------------------------
# Embedded response schema
# ---------------------------------------------------------------------------


class QuotaCheckSummary(BaseModel):
    """Summary of one quota period check embedded in the eligibility response.

    Attributes:
        period:               Time window: "daily", "weekly", or "monthly".
        quota_active:         Whether a quota is actively enforced for this period.
        max_rides:            Maximum rides allowed per period (0 if no quota).
        current_period_rides: Rides already taken in the current period.
        remaining_rides:      Rides left before the limit is reached.
        quota_exceeded:       True when the limit has been reached or passed.
    """

    period: str
    quota_active: bool
    max_rides: int
    current_period_rides: int
    remaining_rides: int
    quota_exceeded: bool


class DeptBudgetCheckSummary(BaseModel):
    """Summary of one department's budget check embedded in the eligibility response.

    Attributes:
        department_id:            PK of the CorporateDepartment row.
        department_name:          Human-readable department name.
        monthly_budget_usd:       The department's monthly spend cap in USD.
        current_month_spend_usd:  Sum of actual_fare for all rides this calendar
                                  month by members of this department under the
                                  corporate account.
        budget_remaining_usd:     Remaining budget (monthly_budget_usd minus
                                  current_month_spend_usd, floored at zero).
        budget_exceeded:          True when current_month_spend_usd >=
                                  monthly_budget_usd.
    """

    department_id: int
    department_name: str
    monthly_budget_usd: Decimal
    current_month_spend_usd: Decimal
    budget_remaining_usd: Decimal
    budget_exceeded: bool


# ---------------------------------------------------------------------------
# Response schema
# ---------------------------------------------------------------------------


class BookingEligibilityResponse(BaseModel):
    """Full eligibility verdict with per-check breakdowns.

    The top-level ``eligible`` flag is the authoritative answer.  All
    other fields explain *why* a ride was rejected or conditionally approved.

    Top-level verdict
    -----------------
    eligible:              True when the ride may proceed (possibly with
                           approval).
    requires_approval:     True when a manual approval chain must be started.
    auto_approved:         True when an auto-approval rule matched and bypassed
                           the manual approval chain.
    auto_approval_rule_id: PK of the matched auto-approval rule, or None.
    approval_chain_id:     PK of the applicable approval chain (set only when
                           requires_approval=True), or None.

    Policy check
    ------------
    policy_check_passed:    True when the ride satisfies the effective 3-tier
                            policy.
    policy_violation_reason: Human-readable explanation when policy fails.

    Blackout check
    --------------
    in_blackout:              True when the ride_dt falls inside at least one
                              active blackout period.
    blackout_override_allowed: True when at least one matching blackout period
                               permits an override.
    blackout_requires_approval: True when the override itself requires approval.
    blackout_period_ids:      PKs of the matching blackout periods.

    Quota checks
    ------------
    quota_checks:     One QuotaCheckSummary per period (daily/weekly/monthly).
    any_quota_exceeded: True when at least one period quota has been exceeded.

    Monthly spend
    -------------
    monthly_spend_limit_usd:  Member's personal monthly spend cap, or None if
                               no cap is set.
    current_month_spend_usd:  Sum of actual_fare for completed corporate rides
                               by this member in the current calendar month.
    spend_remaining_usd:      Remaining allowance (None when no limit is set).
    spend_limit_exceeded:     True when current_month_spend_usd >=
                               monthly_spend_limit_usd.

    Department budget
    -----------------
    dept_budget_exceeded:  True when at least one department the member belongs
                           to has exhausted its monthly_budget.
    dept_budget_details:   One DeptBudgetCheckSummary per department that has a
                           monthly_budget set.  Empty when the member belongs to
                           no departments with a budget cap.

    Onboarding
    ----------
    onboarding_incomplete:    True when an active (non-completed) onboarding
                              record exists for this member and the
                              ``policy_acknowledged`` step has not been marked
                              complete.  False when no onboarding record exists
                              (onboarding is optional/admin-initiated) or when
                              onboarding status is 'completed'.
    onboarding_pending_steps: Names of all steps where ``completed == False``
                              in the active onboarding record.  Empty when
                              onboarding_incomplete is False.

    Denial reasons
    --------------
    denial_reasons: Human-readable list of all reasons the ride was rejected.
                    Empty when eligible=True.
    """

    eligible: bool
    requires_approval: bool
    auto_approved: bool
    auto_approval_rule_id: Optional[int]
    approval_chain_id: Optional[int]

    # Policy
    policy_check_passed: bool
    policy_violation_reason: Optional[str]

    # Blackout
    in_blackout: bool
    blackout_override_allowed: bool
    blackout_requires_approval: bool
    blackout_period_ids: List[int]

    # Quotas
    quota_checks: List[QuotaCheckSummary]
    any_quota_exceeded: bool

    # Monthly spend
    monthly_spend_limit_usd: Optional[Decimal]
    current_month_spend_usd: Decimal
    spend_remaining_usd: Optional[Decimal]
    spend_limit_exceeded: bool

    # Department budget
    dept_budget_exceeded: bool = False
    dept_budget_details: List[DeptBudgetCheckSummary] = []

    # Onboarding
    onboarding_incomplete: bool = False
    onboarding_pending_steps: List[str] = []

    # Denial summary
    denial_reasons: List[str]
