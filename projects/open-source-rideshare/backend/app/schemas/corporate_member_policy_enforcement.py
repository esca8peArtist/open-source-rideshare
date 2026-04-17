"""Pydantic schemas for the Corporate Member Policy Enforcement API.

Used by the booking engine to validate a proposed ride booking against a
member's effective policy before the booking is submitted.
"""

from __future__ import annotations

import enum
from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field


class BookingPolicyCheckRequest(BaseModel):
    """What the booking engine sends for pre-booking policy validation.

    Attributes:
        vehicle_category:   The vehicle category being requested (e.g. "standard").
        estimated_fare_usd: Estimated fare for the proposed ride.
        trip_purpose:       Optional trip purpose supplied by the rider.
        requested_at:       When the booking is requested (used for business_hours check).
    """

    vehicle_category: str = Field(..., description="Vehicle category being requested, e.g. 'standard', 'xl'.")
    estimated_fare_usd: Decimal = Field(..., ge=0, description="Estimated fare in USD.")
    trip_purpose: str | None = Field(None, description="Trip purpose supplied by the rider, if any.")
    requested_at: datetime = Field(..., description="UTC datetime when the booking is requested.")


class PolicyViolation(BaseModel):
    """A single policy dimension that the booking violates.

    Attributes:
        field:   The policy dimension that failed, e.g. 'vehicle_category', 'fare_cap'.
        message: Human-readable description of the violation.
        value:   The value that failed the check (e.g. the requested vehicle category).
        limit:   The policy limit that was exceeded, if applicable.
    """

    field: str
    message: str
    value: Any
    limit: Any | None = None


class PolicyCheckOutcome(str, enum.Enum):
    """Result classification for a policy check.

    ALLOWED:          Booking may proceed without any approval.
    REQUIRES_APPROVAL: Booking can proceed but requires manager sign-off.
    DENIED:           Booking is hard-blocked by policy.
    """

    ALLOWED = "allowed"
    REQUIRES_APPROVAL = "requires_approval"
    DENIED = "denied"


class BookingPolicyCheckResponse(BaseModel):
    """Result of a pre-booking policy check.

    Attributes:
        outcome:                   Overall decision (allowed / requires_approval / denied).
        violations:                List of policy dimensions that were violated (empty if ALLOWED).
        monthly_spend_usd:         Member's total spend in the current calendar month.
        monthly_limit_usd:         Monthly cap from the account policy (None if uncapped).
        monthly_remaining_usd:     Remaining monthly budget (None if uncapped).
        effective_policy_summary:  Snapshot of the policy that was evaluated.
    """

    outcome: PolicyCheckOutcome
    violations: list[PolicyViolation]
    monthly_spend_usd: Decimal
    monthly_limit_usd: Decimal | None
    monthly_remaining_usd: Decimal | None
    effective_policy_summary: dict


class MonthlySpendResponse(BaseModel):
    """A member's current-month spend vs. their policy cap.

    Attributes:
        member_id:          The member whose spend is reported.
        account_id:         The corporate account.
        monthly_spend_usd:  Total spend so far this calendar month.
        monthly_limit_usd:  Policy cap (None if uncapped).
        monthly_remaining_usd: Remaining budget (None if uncapped).
        period:             ISO year-month string, e.g. "2026-04".
    """

    member_id: int
    account_id: int
    monthly_spend_usd: Decimal
    monthly_limit_usd: Decimal | None
    monthly_remaining_usd: Decimal | None
    period: str
