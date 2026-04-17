"""Tests for Corporate Member Policy Enforcement.

Covers:
  - Schema validation (BookingPolicyCheckRequest, PolicyViolation,
    BookingPolicyCheckResponse, MonthlySpendResponse)
  - Service: _check_vehicle_category
  - Service: _check_fare_cap (below / at / above cap / above 150%)
  - Service: _check_business_hours (weekday in-hours / weekday evening / weekend)
  - Service: _check_purpose_required
  - Service: _check_purpose_allowed
  - Service: _check_monthly_cap
  - Service: check_booking_against_policy (integrated, mocked DB/deps)
  - Service: no policy at all → ALLOWED
  - Service: multiple violations → most severe wins
  - API: POST /corporate/accounts/me/check-booking → 200
  - API: POST /corporate/accounts/{account_id}/members/{member_id}/check-booking → 200
  - API: GET  /corporate/accounts/{account_id}/members/{member_id}/monthly-spend → 200
  - API: non-member calls /me endpoint → 404
  - API: non-admin calls admin endpoint → 403

No live database is used.  All DB interactions are mocked with AsyncMock /
MagicMock following the pattern used in test_corporate_spending_alerts.py.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.schemas.corporate_member_policy_enforcement import (
    BookingPolicyCheckRequest,
    BookingPolicyCheckResponse,
    MonthlySpendResponse,
    PolicyCheckOutcome,
    PolicyViolation,
)
from app.services.corporate_member_policy_enforcement import (
    _check_business_hours,
    _check_fare_cap,
    _check_monthly_cap,
    _check_purpose_allowed,
    _check_purpose_required,
    _check_vehicle_category,
    check_booking_against_policy,
)

# ---------------------------------------------------------------------------
# Constants / helpers
# ---------------------------------------------------------------------------

MON_0800 = datetime(2026, 4, 13, 8, 0, 0, tzinfo=timezone.utc)   # Monday 08:00 UTC
MON_2100 = datetime(2026, 4, 13, 21, 0, 0, tzinfo=timezone.utc)  # Monday 21:00 UTC (outside)
MON_0659 = datetime(2026, 4, 13, 6, 59, 0, tzinfo=timezone.utc)  # Monday 06:59 UTC (before)
SAT_1000 = datetime(2026, 4, 18, 10, 0, 0, tzinfo=timezone.utc)  # Saturday 10:00 UTC
SUN_1200 = datetime(2026, 4, 19, 12, 0, 0, tzinfo=timezone.utc)  # Sunday 12:00 UTC
FRI_2059 = datetime(2026, 4, 17, 20, 59, 0, tzinfo=timezone.utc) # Friday 20:59 UTC (inside)
THU_0700 = datetime(2026, 4, 16, 7, 0, 0, tzinfo=timezone.utc)   # Thursday 07:00 UTC (inside)


def _make_effective_policy(
    allowed_vehicle_categories=None,
    max_per_ride_usd=None,
    max_per_member_monthly_usd=None,
    require_purpose=False,
    approved_purposes=None,
    business_hours_only=False,
    member_id=10,
    account_id=1,
    has_override=False,
    override_is_active=None,
) -> MagicMock:
    p = MagicMock()
    p.member_id = member_id
    p.account_id = account_id
    p.has_override = has_override
    p.override_is_active = override_is_active
    p.allowed_vehicle_categories = allowed_vehicle_categories
    p.max_per_ride_usd = max_per_ride_usd
    p.max_per_member_monthly_usd = max_per_member_monthly_usd
    p.require_purpose = require_purpose
    p.approved_purposes = approved_purposes
    p.business_hours_only = business_hours_only
    return p


def _make_booking_request(
    vehicle_category="standard",
    estimated_fare_usd=Decimal("25.00"),
    trip_purpose=None,
    requested_at=MON_0800,
) -> BookingPolicyCheckRequest:
    return BookingPolicyCheckRequest(
        vehicle_category=vehicle_category,
        estimated_fare_usd=estimated_fare_usd,
        trip_purpose=trip_purpose,
        requested_at=requested_at,
    )


def _make_db_scalar_none() -> AsyncMock:
    """DB mock where scalar_one_or_none always returns None."""
    db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    db.execute = AsyncMock(return_value=result)
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    return db


def _make_db_scalar_value(value) -> AsyncMock:
    """DB mock where scalar_one_or_none returns a fixed value."""
    db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    db.execute = AsyncMock(return_value=result)
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    return db


def _make_db_sequence(*values) -> AsyncMock:
    """DB mock that returns different values for successive execute calls."""
    db = AsyncMock()
    results = []
    for v in values:
        r = MagicMock()
        r.scalar_one_or_none.return_value = v
        results.append(r)
    db.execute = AsyncMock(side_effect=results)
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    return db


# ===========================================================================
# Schema tests
# ===========================================================================


class TestBookingPolicyCheckRequestSchema:
    """Pydantic validation for BookingPolicyCheckRequest."""

    def test_valid_minimal(self):
        req = BookingPolicyCheckRequest(
            vehicle_category="standard",
            estimated_fare_usd=Decimal("30.00"),
            requested_at=MON_0800,
        )
        assert req.vehicle_category == "standard"
        assert req.trip_purpose is None

    def test_valid_with_purpose(self):
        req = _make_booking_request(trip_purpose="CLIENT_MEETING")
        assert req.trip_purpose == "CLIENT_MEETING"

    def test_fare_must_be_non_negative(self):
        with pytest.raises(Exception):
            BookingPolicyCheckRequest(
                vehicle_category="standard",
                estimated_fare_usd=Decimal("-1.00"),
                requested_at=MON_0800,
            )

    def test_zero_fare_allowed(self):
        req = BookingPolicyCheckRequest(
            vehicle_category="standard",
            estimated_fare_usd=Decimal("0.00"),
            requested_at=MON_0800,
        )
        assert req.estimated_fare_usd == Decimal("0.00")

    def test_vehicle_category_required(self):
        with pytest.raises(Exception):
            BookingPolicyCheckRequest(
                estimated_fare_usd=Decimal("20.00"),
                requested_at=MON_0800,
            )

    def test_requested_at_required(self):
        with pytest.raises(Exception):
            BookingPolicyCheckRequest(
                vehicle_category="standard",
                estimated_fare_usd=Decimal("20.00"),
            )


class TestPolicyViolationSchema:
    """Pydantic validation for PolicyViolation."""

    def test_basic(self):
        v = PolicyViolation(
            field="vehicle_category",
            message="Not allowed.",
            value="luxury",
            limit=["standard", "xl"],
        )
        assert v.field == "vehicle_category"
        assert v.limit == ["standard", "xl"]

    def test_limit_nullable(self):
        v = PolicyViolation(
            field="purpose_required",
            message="Purpose required.",
            value=None,
        )
        assert v.limit is None


class TestPolicyCheckOutcomeEnum:
    def test_allowed(self):
        assert PolicyCheckOutcome.ALLOWED == "allowed"

    def test_requires_approval(self):
        assert PolicyCheckOutcome.REQUIRES_APPROVAL == "requires_approval"

    def test_denied(self):
        assert PolicyCheckOutcome.DENIED == "denied"


class TestBookingPolicyCheckResponseSchema:
    """Pydantic validation for BookingPolicyCheckResponse."""

    def test_no_violations(self):
        resp = BookingPolicyCheckResponse(
            outcome=PolicyCheckOutcome.ALLOWED,
            violations=[],
            monthly_spend_usd=Decimal("100.00"),
            monthly_limit_usd=Decimal("500.00"),
            monthly_remaining_usd=Decimal("400.00"),
            effective_policy_summary={},
        )
        assert resp.outcome == PolicyCheckOutcome.ALLOWED
        assert resp.violations == []

    def test_monthly_limit_nullable(self):
        resp = BookingPolicyCheckResponse(
            outcome=PolicyCheckOutcome.ALLOWED,
            violations=[],
            monthly_spend_usd=Decimal("0.00"),
            monthly_limit_usd=None,
            monthly_remaining_usd=None,
            effective_policy_summary={},
        )
        assert resp.monthly_limit_usd is None
        assert resp.monthly_remaining_usd is None


# ===========================================================================
# Unit tests: individual check functions
# ===========================================================================


class TestCheckVehicleCategory:
    def test_no_restriction_allowed(self):
        assert _check_vehicle_category("luxury", None) is None

    def test_in_allowed_list(self):
        assert _check_vehicle_category("standard", ["standard", "xl"]) is None

    def test_not_in_allowed_list(self):
        v = _check_vehicle_category("luxury", ["standard", "xl"])
        assert v is not None
        assert v.field == "vehicle_category"
        assert "luxury" in v.message

    def test_empty_allowed_list_denies_all(self):
        v = _check_vehicle_category("standard", [])
        assert v is not None

    def test_case_sensitive_mismatch(self):
        v = _check_vehicle_category("Standard", ["standard"])
        assert v is not None


class TestCheckFareCap:
    def test_no_cap(self):
        violation, severity = _check_fare_cap(Decimal("999.00"), None)
        assert violation is None
        assert severity is None

    def test_exactly_at_cap_allowed(self):
        violation, severity = _check_fare_cap(Decimal("50.00"), Decimal("50.00"))
        assert violation is None

    def test_below_cap_allowed(self):
        violation, severity = _check_fare_cap(Decimal("49.99"), Decimal("50.00"))
        assert violation is None

    def test_above_cap_below_150pct_requires_approval(self):
        violation, severity = _check_fare_cap(Decimal("60.00"), Decimal("50.00"))
        assert violation is not None
        assert severity == PolicyCheckOutcome.REQUIRES_APPROVAL
        assert violation.field == "fare_cap"

    def test_exactly_at_150pct_requires_approval(self):
        # 50 * 1.5 = 75 — still at the boundary, not greater than → REQUIRES_APPROVAL
        violation, severity = _check_fare_cap(Decimal("75.00"), Decimal("50.00"))
        assert violation is not None
        assert severity == PolicyCheckOutcome.REQUIRES_APPROVAL

    def test_above_150pct_denied(self):
        violation, severity = _check_fare_cap(Decimal("75.01"), Decimal("50.00"))
        assert violation is not None
        assert severity == PolicyCheckOutcome.DENIED

    def test_well_above_150pct_denied(self):
        violation, severity = _check_fare_cap(Decimal("200.00"), Decimal("50.00"))
        assert violation is not None
        assert severity == PolicyCheckOutcome.DENIED
        assert "denied" in violation.message.lower()


class TestCheckBusinessHours:
    def test_monday_0800_allowed(self):
        assert _check_business_hours(MON_0800) is None

    def test_thursday_0700_allowed(self):
        assert _check_business_hours(THU_0700) is None

    def test_friday_2059_allowed(self):
        assert _check_business_hours(FRI_2059) is None

    def test_monday_2100_denied(self):
        v = _check_business_hours(MON_2100)
        assert v is not None
        assert v.field == "business_hours"

    def test_monday_0659_denied(self):
        v = _check_business_hours(MON_0659)
        assert v is not None

    def test_saturday_1000_denied(self):
        v = _check_business_hours(SAT_1000)
        assert v is not None
        assert "Saturday" in v.message

    def test_sunday_1200_denied(self):
        v = _check_business_hours(SUN_1200)
        assert v is not None

    def test_naive_datetime_treated_as_utc(self):
        # Naive datetime on a Tuesday at 12:00 — should be allowed
        naive_tue = datetime(2026, 4, 14, 12, 0, 0)
        assert _check_business_hours(naive_tue) is None


class TestCheckPurposeRequired:
    def test_purpose_provided(self):
        assert _check_purpose_required("CLIENT_MEETING") is None

    def test_purpose_missing(self):
        v = _check_purpose_required(None)
        assert v is not None
        assert v.field == "purpose_required"


class TestCheckPurposeAllowed:
    def test_no_restriction(self):
        assert _check_purpose_allowed("ANYTHING", None) is None

    def test_in_approved_list(self):
        assert _check_purpose_allowed("CLIENT_MEETING", ["CLIENT_MEETING", "CONFERENCE"]) is None

    def test_not_in_approved_list(self):
        v = _check_purpose_allowed("PERSONAL", ["CLIENT_MEETING", "CONFERENCE"])
        assert v is not None
        assert v.field == "purpose_allowed"
        assert "PERSONAL" in v.message

    def test_no_purpose_provided_with_restriction(self):
        # None purpose with approved list — no violation (purpose_required handles this)
        assert _check_purpose_allowed(None, ["CLIENT_MEETING"]) is None


class TestCheckMonthlyCap:
    def test_no_cap(self):
        assert _check_monthly_cap(Decimal("400.00"), Decimal("50.00"), None) is None

    def test_within_cap(self):
        assert _check_monthly_cap(Decimal("400.00"), Decimal("50.00"), Decimal("500.00")) is None

    def test_exactly_at_cap(self):
        # 450 + 50 = 500 = cap → NOT exceeded (equal is allowed)
        assert _check_monthly_cap(Decimal("450.00"), Decimal("50.00"), Decimal("500.00")) is None

    def test_exceeds_cap(self):
        v = _check_monthly_cap(Decimal("460.00"), Decimal("50.00"), Decimal("500.00"))
        assert v is not None
        assert v.field == "monthly_cap"

    def test_zero_spend_exceeds_tiny_cap(self):
        v = _check_monthly_cap(Decimal("0.00"), Decimal("10.00"), Decimal("5.00"))
        assert v is not None


# ===========================================================================
# Service integration tests (mocked DB)
# ===========================================================================


class TestCheckBookingAgainstPolicy:
    """Integration tests for check_booking_against_policy with mocked dependencies."""

    @pytest.mark.asyncio
    async def test_no_policy_all_allowed(self):
        """When no policy is configured, all bookings should be ALLOWED."""
        policy = _make_effective_policy()
        db = _make_db_sequence(100, None)  # user_id=100, monthly_spend=None

        with patch(
            "app.services.corporate_member_policy_enforcement.get_effective_policy",
            new=AsyncMock(return_value=policy),
        ), patch(
            "app.services.corporate_member_policy_enforcement._get_member_user_id",
            new=AsyncMock(return_value=100),
        ):
            db2 = _make_db_scalar_value(None)  # monthly spend query
            result = await check_booking_against_policy(
                db2, account_id=1, member_id=10,
                request=_make_booking_request(),
            )
        assert result.outcome == PolicyCheckOutcome.ALLOWED
        assert result.violations == []

    @pytest.mark.asyncio
    async def test_vehicle_category_allowed(self):
        policy = _make_effective_policy(allowed_vehicle_categories=["standard", "xl"])
        with patch(
            "app.services.corporate_member_policy_enforcement.get_effective_policy",
            new=AsyncMock(return_value=policy),
        ), patch(
            "app.services.corporate_member_policy_enforcement.get_member_monthly_spend",
            new=AsyncMock(return_value=Decimal("0.00")),
        ):
            db = MagicMock()
            result = await check_booking_against_policy(
                db, account_id=1, member_id=10,
                request=_make_booking_request(vehicle_category="standard"),
            )
        assert result.outcome == PolicyCheckOutcome.ALLOWED

    @pytest.mark.asyncio
    async def test_vehicle_category_denied(self):
        policy = _make_effective_policy(allowed_vehicle_categories=["standard"])
        with patch(
            "app.services.corporate_member_policy_enforcement.get_effective_policy",
            new=AsyncMock(return_value=policy),
        ), patch(
            "app.services.corporate_member_policy_enforcement.get_member_monthly_spend",
            new=AsyncMock(return_value=Decimal("0.00")),
        ):
            db = MagicMock()
            result = await check_booking_against_policy(
                db, account_id=1, member_id=10,
                request=_make_booking_request(vehicle_category="luxury"),
            )
        assert result.outcome == PolicyCheckOutcome.DENIED
        assert any(v.field == "vehicle_category" for v in result.violations)

    @pytest.mark.asyncio
    async def test_fare_below_cap_allowed(self):
        policy = _make_effective_policy(max_per_ride_usd=Decimal("50.00"))
        with patch(
            "app.services.corporate_member_policy_enforcement.get_effective_policy",
            new=AsyncMock(return_value=policy),
        ), patch(
            "app.services.corporate_member_policy_enforcement.get_member_monthly_spend",
            new=AsyncMock(return_value=Decimal("0.00")),
        ):
            result = await check_booking_against_policy(
                MagicMock(), account_id=1, member_id=10,
                request=_make_booking_request(estimated_fare_usd=Decimal("49.99")),
            )
        assert result.outcome == PolicyCheckOutcome.ALLOWED

    @pytest.mark.asyncio
    async def test_fare_at_cap_allowed(self):
        policy = _make_effective_policy(max_per_ride_usd=Decimal("50.00"))
        with patch(
            "app.services.corporate_member_policy_enforcement.get_effective_policy",
            new=AsyncMock(return_value=policy),
        ), patch(
            "app.services.corporate_member_policy_enforcement.get_member_monthly_spend",
            new=AsyncMock(return_value=Decimal("0.00")),
        ):
            result = await check_booking_against_policy(
                MagicMock(), account_id=1, member_id=10,
                request=_make_booking_request(estimated_fare_usd=Decimal("50.00")),
            )
        assert result.outcome == PolicyCheckOutcome.ALLOWED

    @pytest.mark.asyncio
    async def test_fare_above_cap_below_150pct_requires_approval(self):
        policy = _make_effective_policy(max_per_ride_usd=Decimal("50.00"))
        with patch(
            "app.services.corporate_member_policy_enforcement.get_effective_policy",
            new=AsyncMock(return_value=policy),
        ), patch(
            "app.services.corporate_member_policy_enforcement.get_member_monthly_spend",
            new=AsyncMock(return_value=Decimal("0.00")),
        ):
            result = await check_booking_against_policy(
                MagicMock(), account_id=1, member_id=10,
                request=_make_booking_request(estimated_fare_usd=Decimal("60.00")),
            )
        assert result.outcome == PolicyCheckOutcome.REQUIRES_APPROVAL

    @pytest.mark.asyncio
    async def test_fare_above_150pct_denied(self):
        policy = _make_effective_policy(max_per_ride_usd=Decimal("50.00"))
        with patch(
            "app.services.corporate_member_policy_enforcement.get_effective_policy",
            new=AsyncMock(return_value=policy),
        ), patch(
            "app.services.corporate_member_policy_enforcement.get_member_monthly_spend",
            new=AsyncMock(return_value=Decimal("0.00")),
        ):
            result = await check_booking_against_policy(
                MagicMock(), account_id=1, member_id=10,
                request=_make_booking_request(estimated_fare_usd=Decimal("76.00")),
            )
        assert result.outcome == PolicyCheckOutcome.DENIED

    @pytest.mark.asyncio
    async def test_business_hours_monday_morning_allowed(self):
        policy = _make_effective_policy(business_hours_only=True)
        with patch(
            "app.services.corporate_member_policy_enforcement.get_effective_policy",
            new=AsyncMock(return_value=policy),
        ), patch(
            "app.services.corporate_member_policy_enforcement.get_member_monthly_spend",
            new=AsyncMock(return_value=Decimal("0.00")),
        ):
            result = await check_booking_against_policy(
                MagicMock(), account_id=1, member_id=10,
                request=_make_booking_request(requested_at=MON_0800),
            )
        assert result.outcome == PolicyCheckOutcome.ALLOWED

    @pytest.mark.asyncio
    async def test_business_hours_saturday_denied(self):
        policy = _make_effective_policy(business_hours_only=True)
        with patch(
            "app.services.corporate_member_policy_enforcement.get_effective_policy",
            new=AsyncMock(return_value=policy),
        ), patch(
            "app.services.corporate_member_policy_enforcement.get_member_monthly_spend",
            new=AsyncMock(return_value=Decimal("0.00")),
        ):
            result = await check_booking_against_policy(
                MagicMock(), account_id=1, member_id=10,
                request=_make_booking_request(requested_at=SAT_1000),
            )
        assert result.outcome == PolicyCheckOutcome.DENIED
        assert any(v.field == "business_hours" for v in result.violations)

    @pytest.mark.asyncio
    async def test_business_hours_weekday_evening_denied(self):
        policy = _make_effective_policy(business_hours_only=True)
        with patch(
            "app.services.corporate_member_policy_enforcement.get_effective_policy",
            new=AsyncMock(return_value=policy),
        ), patch(
            "app.services.corporate_member_policy_enforcement.get_member_monthly_spend",
            new=AsyncMock(return_value=Decimal("0.00")),
        ):
            result = await check_booking_against_policy(
                MagicMock(), account_id=1, member_id=10,
                request=_make_booking_request(requested_at=MON_2100),
            )
        assert result.outcome == PolicyCheckOutcome.DENIED

    @pytest.mark.asyncio
    async def test_purpose_required_but_missing_denied(self):
        policy = _make_effective_policy(require_purpose=True)
        with patch(
            "app.services.corporate_member_policy_enforcement.get_effective_policy",
            new=AsyncMock(return_value=policy),
        ), patch(
            "app.services.corporate_member_policy_enforcement.get_member_monthly_spend",
            new=AsyncMock(return_value=Decimal("0.00")),
        ):
            result = await check_booking_against_policy(
                MagicMock(), account_id=1, member_id=10,
                request=_make_booking_request(trip_purpose=None),
            )
        assert result.outcome == PolicyCheckOutcome.DENIED
        assert any(v.field == "purpose_required" for v in result.violations)

    @pytest.mark.asyncio
    async def test_purpose_provided_not_in_approved_list_denied(self):
        policy = _make_effective_policy(
            require_purpose=True,
            approved_purposes=["CLIENT_MEETING", "CONFERENCE"],
        )
        with patch(
            "app.services.corporate_member_policy_enforcement.get_effective_policy",
            new=AsyncMock(return_value=policy),
        ), patch(
            "app.services.corporate_member_policy_enforcement.get_member_monthly_spend",
            new=AsyncMock(return_value=Decimal("0.00")),
        ):
            result = await check_booking_against_policy(
                MagicMock(), account_id=1, member_id=10,
                request=_make_booking_request(trip_purpose="PERSONAL"),
            )
        assert result.outcome == PolicyCheckOutcome.DENIED
        assert any(v.field == "purpose_allowed" for v in result.violations)

    @pytest.mark.asyncio
    async def test_monthly_cap_not_exceeded_allowed(self):
        policy = _make_effective_policy(max_per_member_monthly_usd=Decimal("500.00"))
        with patch(
            "app.services.corporate_member_policy_enforcement.get_effective_policy",
            new=AsyncMock(return_value=policy),
        ), patch(
            "app.services.corporate_member_policy_enforcement.get_member_monthly_spend",
            new=AsyncMock(return_value=Decimal("400.00")),
        ):
            result = await check_booking_against_policy(
                MagicMock(), account_id=1, member_id=10,
                request=_make_booking_request(estimated_fare_usd=Decimal("50.00")),
            )
        # 400 + 50 = 450 <= 500 → ALLOWED
        assert result.outcome == PolicyCheckOutcome.ALLOWED

    @pytest.mark.asyncio
    async def test_monthly_cap_exceeded_requires_approval(self):
        policy = _make_effective_policy(max_per_member_monthly_usd=Decimal("500.00"))
        with patch(
            "app.services.corporate_member_policy_enforcement.get_effective_policy",
            new=AsyncMock(return_value=policy),
        ), patch(
            "app.services.corporate_member_policy_enforcement.get_member_monthly_spend",
            new=AsyncMock(return_value=Decimal("460.00")),
        ):
            result = await check_booking_against_policy(
                MagicMock(), account_id=1, member_id=10,
                request=_make_booking_request(estimated_fare_usd=Decimal("50.00")),
            )
        # 460 + 50 = 510 > 500 → REQUIRES_APPROVAL
        assert result.outcome == PolicyCheckOutcome.REQUIRES_APPROVAL
        assert any(v.field == "monthly_cap" for v in result.violations)

    @pytest.mark.asyncio
    async def test_multiple_violations_denied_wins(self):
        """DENIED wins over REQUIRES_APPROVAL when both violations are present."""
        policy = _make_effective_policy(
            allowed_vehicle_categories=["standard"],  # will cause DENIED
            max_per_member_monthly_usd=Decimal("100.00"),  # monthly cap will cause REQUIRES_APPROVAL
        )
        with patch(
            "app.services.corporate_member_policy_enforcement.get_effective_policy",
            new=AsyncMock(return_value=policy),
        ), patch(
            "app.services.corporate_member_policy_enforcement.get_member_monthly_spend",
            new=AsyncMock(return_value=Decimal("90.00")),
        ):
            result = await check_booking_against_policy(
                MagicMock(), account_id=1, member_id=10,
                request=_make_booking_request(
                    vehicle_category="luxury",  # DENIED
                    estimated_fare_usd=Decimal("20.00"),  # pushes over monthly cap
                ),
            )
        assert result.outcome == PolicyCheckOutcome.DENIED
        assert len(result.violations) >= 2

    @pytest.mark.asyncio
    async def test_response_contains_policy_summary(self):
        policy = _make_effective_policy(
            max_per_ride_usd=Decimal("50.00"),
            business_hours_only=True,
        )
        with patch(
            "app.services.corporate_member_policy_enforcement.get_effective_policy",
            new=AsyncMock(return_value=policy),
        ), patch(
            "app.services.corporate_member_policy_enforcement.get_member_monthly_spend",
            new=AsyncMock(return_value=Decimal("0.00")),
        ):
            result = await check_booking_against_policy(
                MagicMock(), account_id=1, member_id=10,
                request=_make_booking_request(),
            )
        assert "business_hours_only" in result.effective_policy_summary
        assert result.effective_policy_summary["business_hours_only"] is True

    @pytest.mark.asyncio
    async def test_monthly_remaining_calculated_correctly(self):
        policy = _make_effective_policy(max_per_member_monthly_usd=Decimal("500.00"))
        with patch(
            "app.services.corporate_member_policy_enforcement.get_effective_policy",
            new=AsyncMock(return_value=policy),
        ), patch(
            "app.services.corporate_member_policy_enforcement.get_member_monthly_spend",
            new=AsyncMock(return_value=Decimal("300.00")),
        ):
            result = await check_booking_against_policy(
                MagicMock(), account_id=1, member_id=10,
                request=_make_booking_request(),
            )
        assert result.monthly_remaining_usd == Decimal("200.00")

    @pytest.mark.asyncio
    async def test_no_monthly_cap_remaining_is_none(self):
        policy = _make_effective_policy()  # no monthly cap
        with patch(
            "app.services.corporate_member_policy_enforcement.get_effective_policy",
            new=AsyncMock(return_value=policy),
        ), patch(
            "app.services.corporate_member_policy_enforcement.get_member_monthly_spend",
            new=AsyncMock(return_value=Decimal("100.00")),
        ):
            result = await check_booking_against_policy(
                MagicMock(), account_id=1, member_id=10,
                request=_make_booking_request(),
            )
        assert result.monthly_limit_usd is None
        assert result.monthly_remaining_usd is None


# ===========================================================================
# API endpoint tests
# ===========================================================================


def _make_fastapi_test_client():
    """Build a TestClient with the FastAPI app."""
    from fastapi.testclient import TestClient
    from app.main import app
    return TestClient(app)


def _make_user(user_id: int = 1, is_admin: bool = False) -> MagicMock:
    u = MagicMock()
    u.id = user_id
    u.is_admin = is_admin
    return u


def _make_membership(account_id: int = 1, member_id: int = 10, user_id: int = 1) -> MagicMock:
    m = MagicMock()
    m.id = member_id
    m.account_id = account_id
    m.user_id = user_id
    m.is_active = True
    return m


VALID_CHECK_PAYLOAD = {
    "vehicle_category": "standard",
    "estimated_fare_usd": "30.00",
    "trip_purpose": "CLIENT_MEETING",
    "requested_at": "2026-04-13T08:00:00Z",
}

ALLOWED_RESPONSE = BookingPolicyCheckResponse(
    outcome=PolicyCheckOutcome.ALLOWED,
    violations=[],
    monthly_spend_usd=Decimal("0.00"),
    monthly_limit_usd=None,
    monthly_remaining_usd=None,
    effective_policy_summary={},
)

MONTHLY_SPEND_RESPONSE_DATA = {
    "member_id": 10,
    "account_id": 1,
    "monthly_spend_usd": "150.00",
    "monthly_limit_usd": "500.00",
    "monthly_remaining_usd": "350.00",
    "period": "2026-04",
}


class TestMemberCheckBookingAPI:
    """POST /corporate/accounts/me/check-booking"""

    def test_returns_200_for_valid_member(self):
        from fastapi.testclient import TestClient
        from app.main import app
        from app.api.deps import get_current_user, get_db

        mock_user = _make_user(user_id=1)
        mock_membership = _make_membership()

        async def override_db():
            db = AsyncMock()
            result = MagicMock()
            result.scalar_one_or_none.return_value = mock_membership
            db.execute = AsyncMock(return_value=result)
            yield db

        app.dependency_overrides[get_db] = override_db
        app.dependency_overrides[get_current_user] = lambda: mock_user

        with patch(
            "app.api.v1.corporate_member_policy_enforcement.check_booking_against_policy",
            new=AsyncMock(return_value=ALLOWED_RESPONSE),
        ):
            client = TestClient(app)
            resp = client.post(
                "/api/v1/corporate/accounts/me/check-booking",
                json=VALID_CHECK_PAYLOAD,
            )

        app.dependency_overrides.clear()
        assert resp.status_code == 200
        assert resp.json()["outcome"] == "allowed"

    def test_non_member_returns_404(self):
        from fastapi.testclient import TestClient
        from app.main import app
        from app.api.deps import get_current_user, get_db

        mock_user = _make_user(user_id=99)

        async def override_db():
            db = AsyncMock()
            result = MagicMock()
            result.scalar_one_or_none.return_value = None  # no membership
            db.execute = AsyncMock(return_value=result)
            yield db

        app.dependency_overrides[get_db] = override_db
        app.dependency_overrides[get_current_user] = lambda: mock_user

        client = TestClient(app)
        resp = client.post(
            "/api/v1/corporate/accounts/me/check-booking",
            json=VALID_CHECK_PAYLOAD,
        )

        app.dependency_overrides.clear()
        assert resp.status_code == 404


class TestAdminCheckBookingAPI:
    """POST /corporate/accounts/{account_id}/members/{member_id}/check-booking"""

    def test_admin_returns_200(self):
        from fastapi.testclient import TestClient
        from app.main import app
        from app.api.deps import get_db, require_admin

        mock_admin = _make_user(user_id=999, is_admin=True)

        async def override_db():
            yield AsyncMock()

        app.dependency_overrides[get_db] = override_db
        app.dependency_overrides[require_admin] = lambda: mock_admin

        with patch(
            "app.api.v1.corporate_member_policy_enforcement.check_booking_against_policy",
            new=AsyncMock(return_value=ALLOWED_RESPONSE),
        ):
            client = TestClient(app)
            resp = client.post(
                "/api/v1/corporate/accounts/1/members/10/check-booking",
                json=VALID_CHECK_PAYLOAD,
            )

        app.dependency_overrides.clear()
        assert resp.status_code == 200

    def test_non_admin_returns_403(self):
        from fastapi.testclient import TestClient
        from app.main import app
        from app.api.deps import get_db, require_admin
        from fastapi import HTTPException

        async def override_db():
            yield AsyncMock()

        def raise_403():
            raise HTTPException(status_code=403, detail="Admin required.")

        app.dependency_overrides[get_db] = override_db
        app.dependency_overrides[require_admin] = raise_403

        client = TestClient(app)
        resp = client.post(
            "/api/v1/corporate/accounts/1/members/10/check-booking",
            json=VALID_CHECK_PAYLOAD,
        )

        app.dependency_overrides.clear()
        assert resp.status_code == 403


class TestAdminMonthlySpendAPI:
    """GET /corporate/accounts/{account_id}/members/{member_id}/monthly-spend"""

    def test_admin_returns_200(self):
        from fastapi.testclient import TestClient
        from app.main import app
        from app.api.deps import get_db, require_admin

        mock_admin = _make_user(user_id=999, is_admin=True)
        mock_effective = _make_effective_policy(max_per_member_monthly_usd=Decimal("500.00"))

        async def override_db():
            yield AsyncMock()

        app.dependency_overrides[get_db] = override_db
        app.dependency_overrides[require_admin] = lambda: mock_admin

        with patch(
            "app.api.v1.corporate_member_policy_enforcement.get_effective_policy",
            new=AsyncMock(return_value=mock_effective),
        ), patch(
            "app.api.v1.corporate_member_policy_enforcement.get_member_monthly_spend",
            new=AsyncMock(return_value=Decimal("150.00")),
        ):
            client = TestClient(app)
            resp = client.get(
                "/api/v1/corporate/accounts/1/members/10/monthly-spend"
            )

        app.dependency_overrides.clear()
        assert resp.status_code == 200
        data = resp.json()
        assert data["monthly_spend_usd"] == "150.00"
        assert data["monthly_limit_usd"] == "500.00"
        assert data["monthly_remaining_usd"] == "350.00"

    def test_non_admin_monthly_spend_returns_403(self):
        from fastapi.testclient import TestClient
        from app.main import app
        from app.api.deps import get_db, require_admin
        from fastapi import HTTPException

        async def override_db():
            yield AsyncMock()

        def raise_403():
            raise HTTPException(status_code=403, detail="Admin required.")

        app.dependency_overrides[get_db] = override_db
        app.dependency_overrides[require_admin] = raise_403

        client = TestClient(app)
        resp = client.get("/api/v1/corporate/accounts/1/members/10/monthly-spend")

        app.dependency_overrides.clear()
        assert resp.status_code == 403
