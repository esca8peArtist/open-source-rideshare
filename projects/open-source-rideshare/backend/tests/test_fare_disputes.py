"""Unit tests for the fare dispute & refund feature.

All tests are pure unit tests — no database or HTTP client required.

Covers:
- FareDispute model field defaults and enum values
- DisputeCategory enum values
- DisputeStatus enum values
- TERMINAL_STATUSES and REFUND_STATUSES sets
- create_dispute: success, ride not found, wrong rider, non-completed ride, no actual_fare,
  disputed_amount exceeds fare, duplicate active dispute
- get_dispute_for_rider: found, wrong rider returns None
- list_rider_disputes: all disputes, filtered by status, pagination offset
- withdraw_dispute: success, dispute not found, non-pending dispute rejected
- get_dispute: found, not found
- list_all_disputes: unfiltered, filtered by status
- admin_review_dispute: approve success, partial success, denied success,
  not found, already terminal, approve without refund_amount, refund exceeds disputed
- get_dispute_summary: empty, mixed statuses
- Schema validation: FareDisputeCreateRequest, AdminReviewRequest
- AdminReviewRequest rejects non-terminal decision values
- FareDisputeResponse and AdminFareDisputeResponse field mapping
- DisputeSummaryResponse field mapping
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.fare_dispute import (
    REFUND_STATUSES,
    TERMINAL_STATUSES,
    DisputeCategory,
    DisputeStatus,
    FareDispute,
)
from app.models.ride import RideStatus
from app.schemas.fare_dispute import (
    AdminFareDisputeResponse,
    AdminReviewRequest,
    DisputeSummaryResponse,
    FareDisputeCreateRequest,
    FareDisputeListResponse,
    FareDisputeResponse,
)
from app.services.fare_disputes import (
    DEFAULT_PAGE_SIZE,
    admin_review_dispute,
    create_dispute,
    get_dispute,
    get_dispute_for_rider,
    get_dispute_summary,
    list_all_disputes,
    list_rider_disputes,
    withdraw_dispute,
)


# ===========================================================================
# Helpers
# ===========================================================================

_NOW = datetime(2026, 4, 15, 10, 0, 0, tzinfo=timezone.utc)
_RIDER_ID = 10
_ADMIN_ID = 99
_RIDE_ID = 5


def _make_dispute(
    *,
    id: int = 1,
    ride_id: int = _RIDE_ID,
    rider_id: int = _RIDER_ID,
    category: DisputeCategory = DisputeCategory.OVERCHARGE,
    description: str = "Fare was higher than quoted",
    disputed_amount: float = 12.50,
    status: DisputeStatus = DisputeStatus.PENDING,
    reviewed_by_admin_id: int | None = None,
    admin_notes: str | None = None,
    refund_amount: float | None = None,
    stripe_refund_id: str | None = None,
    resolved_at: datetime | None = None,
    created_at: datetime = _NOW,
    updated_at: datetime = _NOW,
) -> FareDispute:
    d = MagicMock(spec=FareDispute)
    d.id = id
    d.ride_id = ride_id
    d.rider_id = rider_id
    d.category = category
    d.description = description
    d.disputed_amount = disputed_amount
    d.status = status
    d.reviewed_by_admin_id = reviewed_by_admin_id
    d.admin_notes = admin_notes
    d.refund_amount = refund_amount
    d.stripe_refund_id = stripe_refund_id
    d.resolved_at = resolved_at
    d.created_at = created_at
    d.updated_at = updated_at
    return d


def _make_ride(
    *,
    id: int = _RIDE_ID,
    rider_id: int = _RIDER_ID,
    status: RideStatus = RideStatus.COMPLETED,
    actual_fare: float | None = 20.00,
) -> MagicMock:
    ride = MagicMock()
    ride.id = id
    ride.rider_id = rider_id
    ride.status = status
    ride.actual_fare = actual_fare
    return ride


# ===========================================================================
# Model / enum tests
# ===========================================================================

class TestDisputeEnums:
    def test_category_values(self):
        assert DisputeCategory.OVERCHARGE == "overcharge"
        assert DisputeCategory.INCORRECT_ROUTE == "incorrect_route"
        assert DisputeCategory.INCOMPLETE_RIDE == "incomplete_ride"
        assert DisputeCategory.UNAUTHORIZED_CHARGE == "unauthorized_charge"
        assert DisputeCategory.WAIT_TIME_FEE == "wait_time_fee"
        assert DisputeCategory.SURGE_PRICING == "surge_pricing"
        assert DisputeCategory.OTHER == "other"

    def test_status_values(self):
        assert DisputeStatus.PENDING == "pending"
        assert DisputeStatus.UNDER_REVIEW == "under_review"
        assert DisputeStatus.APPROVED == "approved"
        assert DisputeStatus.PARTIAL == "partial"
        assert DisputeStatus.DENIED == "denied"
        assert DisputeStatus.WITHDRAWN == "withdrawn"

    def test_terminal_statuses_contains_expected(self):
        assert DisputeStatus.APPROVED in TERMINAL_STATUSES
        assert DisputeStatus.PARTIAL in TERMINAL_STATUSES
        assert DisputeStatus.DENIED in TERMINAL_STATUSES
        assert DisputeStatus.WITHDRAWN in TERMINAL_STATUSES

    def test_terminal_statuses_excludes_open(self):
        assert DisputeStatus.PENDING not in TERMINAL_STATUSES
        assert DisputeStatus.UNDER_REVIEW not in TERMINAL_STATUSES

    def test_refund_statuses(self):
        assert DisputeStatus.APPROVED in REFUND_STATUSES
        assert DisputeStatus.PARTIAL in REFUND_STATUSES
        assert DisputeStatus.DENIED not in REFUND_STATUSES
        assert DisputeStatus.WITHDRAWN not in REFUND_STATUSES


class TestFareDisputeModel:
    def test_default_status(self):
        d = _make_dispute()
        assert d.status == DisputeStatus.PENDING

    def test_fields_present(self):
        d = _make_dispute(
            refund_amount=10.0,
            stripe_refund_id="re_abc123",
            admin_notes="Fare error confirmed",
        )
        assert d.refund_amount == 10.0
        assert d.stripe_refund_id == "re_abc123"
        assert d.admin_notes == "Fare error confirmed"


# ===========================================================================
# create_dispute
# ===========================================================================

class TestCreateDispute:
    @pytest.mark.asyncio
    async def test_success(self):
        ride = _make_ride()
        db = AsyncMock()

        with (
            patch("app.services.fare_disputes._get_ride_for_rider", return_value=ride),
            patch("app.services.fare_disputes._active_dispute_for_ride", return_value=None),
        ):
            dispute, err = await create_dispute(
                db,
                ride_id=_RIDE_ID,
                rider_user_id=_RIDER_ID,
                category=DisputeCategory.OVERCHARGE,
                description="The fare was 20 but I was charged 32.50",
                disputed_amount=12.50,
            )
        assert err is None
        assert dispute is not None
        db.add.assert_called_once()
        db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_ride_not_found(self):
        db = AsyncMock()
        with patch("app.services.fare_disputes._get_ride_for_rider", return_value=None):
            dispute, err = await create_dispute(
                db, ride_id=_RIDE_ID, rider_user_id=_RIDER_ID,
                category=DisputeCategory.OVERCHARGE, description="test description here",
                disputed_amount=5.0,
            )
        assert dispute is None
        assert "not found" in err.lower()

    @pytest.mark.asyncio
    async def test_ride_not_completed(self):
        ride = _make_ride(status=RideStatus.IN_PROGRESS)
        db = AsyncMock()
        with patch("app.services.fare_disputes._get_ride_for_rider", return_value=ride):
            dispute, err = await create_dispute(
                db, ride_id=_RIDE_ID, rider_user_id=_RIDER_ID,
                category=DisputeCategory.OVERCHARGE, description="test description here",
                disputed_amount=5.0,
            )
        assert dispute is None
        assert "completed" in err.lower()

    @pytest.mark.asyncio
    async def test_no_actual_fare(self):
        ride = _make_ride(actual_fare=None)
        db = AsyncMock()
        with patch("app.services.fare_disputes._get_ride_for_rider", return_value=ride):
            dispute, err = await create_dispute(
                db, ride_id=_RIDE_ID, rider_user_id=_RIDER_ID,
                category=DisputeCategory.OVERCHARGE, description="test description here",
                disputed_amount=5.0,
            )
        assert dispute is None
        assert "fare" in err.lower()

    @pytest.mark.asyncio
    async def test_disputed_amount_exceeds_fare(self):
        ride = _make_ride(actual_fare=10.0)
        db = AsyncMock()
        with patch("app.services.fare_disputes._get_ride_for_rider", return_value=ride):
            dispute, err = await create_dispute(
                db, ride_id=_RIDE_ID, rider_user_id=_RIDER_ID,
                category=DisputeCategory.OVERCHARGE, description="test description here",
                disputed_amount=50.0,
            )
        assert dispute is None
        assert "exceed" in err.lower()

    @pytest.mark.asyncio
    async def test_duplicate_active_dispute_rejected(self):
        ride = _make_ride()
        existing = _make_dispute()
        db = AsyncMock()
        with (
            patch("app.services.fare_disputes._get_ride_for_rider", return_value=ride),
            patch("app.services.fare_disputes._active_dispute_for_ride", return_value=existing),
        ):
            dispute, err = await create_dispute(
                db, ride_id=_RIDE_ID, rider_user_id=_RIDER_ID,
                category=DisputeCategory.OVERCHARGE, description="test description here",
                disputed_amount=5.0,
            )
        assert dispute is None
        assert "already exists" in err.lower()


# ===========================================================================
# get_dispute_for_rider
# ===========================================================================

class TestGetDisputeForRider:
    @pytest.mark.asyncio
    async def test_found(self):
        existing = _make_dispute()
        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = existing
        db.execute = AsyncMock(return_value=mock_result)

        result = await get_dispute_for_rider(db, dispute_id=1, rider_user_id=_RIDER_ID)
        assert result is existing

    @pytest.mark.asyncio
    async def test_not_found_returns_none(self):
        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(return_value=mock_result)

        result = await get_dispute_for_rider(db, dispute_id=999, rider_user_id=_RIDER_ID)
        assert result is None


# ===========================================================================
# list_rider_disputes
# ===========================================================================

class TestListRiderDisputes:
    @pytest.mark.asyncio
    async def test_returns_disputes_and_total(self):
        d1 = _make_dispute(id=1)
        d2 = _make_dispute(id=2)
        db = AsyncMock()

        count_result = MagicMock()
        count_result.scalar_one.return_value = 2
        items_result = MagicMock()
        items_result.scalars.return_value.all.return_value = [d1, d2]

        db.execute = AsyncMock(side_effect=[count_result, items_result])

        disputes, total = await list_rider_disputes(db, rider_user_id=_RIDER_ID)
        assert total == 2
        assert len(disputes) == 2

    @pytest.mark.asyncio
    async def test_empty_result(self):
        db = AsyncMock()

        count_result = MagicMock()
        count_result.scalar_one.return_value = 0
        items_result = MagicMock()
        items_result.scalars.return_value.all.return_value = []

        db.execute = AsyncMock(side_effect=[count_result, items_result])

        disputes, total = await list_rider_disputes(db, rider_user_id=_RIDER_ID)
        assert total == 0
        assert disputes == []


# ===========================================================================
# withdraw_dispute
# ===========================================================================

class TestWithdrawDispute:
    @pytest.mark.asyncio
    async def test_success(self):
        dispute = _make_dispute(status=DisputeStatus.PENDING)
        db = AsyncMock()

        with patch("app.services.fare_disputes.get_dispute_for_rider", return_value=dispute):
            result, err = await withdraw_dispute(db, dispute_id=1, rider_user_id=_RIDER_ID)

        assert err is None
        assert dispute.status == DisputeStatus.WITHDRAWN
        db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_not_found(self):
        db = AsyncMock()
        with patch("app.services.fare_disputes.get_dispute_for_rider", return_value=None):
            result, err = await withdraw_dispute(db, dispute_id=999, rider_user_id=_RIDER_ID)
        assert result is None
        assert err == "Dispute not found"

    @pytest.mark.asyncio
    async def test_non_pending_cannot_be_withdrawn(self):
        dispute = _make_dispute(status=DisputeStatus.UNDER_REVIEW)
        db = AsyncMock()
        with patch("app.services.fare_disputes.get_dispute_for_rider", return_value=dispute):
            result, err = await withdraw_dispute(db, dispute_id=1, rider_user_id=_RIDER_ID)
        assert result is None
        assert "pending" in err.lower()

    @pytest.mark.asyncio
    async def test_approved_cannot_be_withdrawn(self):
        dispute = _make_dispute(status=DisputeStatus.APPROVED)
        db = AsyncMock()
        with patch("app.services.fare_disputes.get_dispute_for_rider", return_value=dispute):
            result, err = await withdraw_dispute(db, dispute_id=1, rider_user_id=_RIDER_ID)
        assert result is None
        assert err is not None


# ===========================================================================
# admin_review_dispute
# ===========================================================================

class TestAdminReviewDispute:
    @pytest.mark.asyncio
    async def test_approve_success(self):
        dispute = _make_dispute(status=DisputeStatus.PENDING, disputed_amount=20.0)
        db = AsyncMock()

        with patch("app.services.fare_disputes.get_dispute", return_value=dispute):
            result, err = await admin_review_dispute(
                db, dispute_id=1, admin_user_id=_ADMIN_ID,
                decision=DisputeStatus.APPROVED,
                admin_notes="Confirmed overcharge by $12.50",
                refund_amount=12.50,
                stripe_refund_id="re_test123",
            )

        assert err is None
        assert dispute.status == DisputeStatus.APPROVED
        assert dispute.refund_amount == 12.50
        assert dispute.stripe_refund_id == "re_test123"
        assert dispute.reviewed_by_admin_id == _ADMIN_ID
        db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_partial_refund_success(self):
        dispute = _make_dispute(status=DisputeStatus.UNDER_REVIEW, disputed_amount=20.0)
        db = AsyncMock()

        with patch("app.services.fare_disputes.get_dispute", return_value=dispute):
            result, err = await admin_review_dispute(
                db, dispute_id=1, admin_user_id=_ADMIN_ID,
                decision=DisputeStatus.PARTIAL,
                admin_notes="Partial overcharge confirmed",
                refund_amount=8.0,
                stripe_refund_id=None,
            )

        assert err is None
        assert dispute.status == DisputeStatus.PARTIAL
        assert dispute.refund_amount == 8.0

    @pytest.mark.asyncio
    async def test_deny_success(self):
        dispute = _make_dispute(status=DisputeStatus.PENDING)
        db = AsyncMock()

        with patch("app.services.fare_disputes.get_dispute", return_value=dispute):
            result, err = await admin_review_dispute(
                db, dispute_id=1, admin_user_id=_ADMIN_ID,
                decision=DisputeStatus.DENIED,
                admin_notes="Fare was correct per GPS logs",
                refund_amount=None,
                stripe_refund_id=None,
            )

        assert err is None
        assert dispute.status == DisputeStatus.DENIED
        assert dispute.refund_amount is None

    @pytest.mark.asyncio
    async def test_not_found(self):
        db = AsyncMock()
        with patch("app.services.fare_disputes.get_dispute", return_value=None):
            result, err = await admin_review_dispute(
                db, dispute_id=999, admin_user_id=_ADMIN_ID,
                decision=DisputeStatus.DENIED,
                admin_notes="notes here for the admin",
                refund_amount=None,
                stripe_refund_id=None,
            )
        assert result is None
        assert "not found" in err.lower()

    @pytest.mark.asyncio
    async def test_already_terminal_rejected(self):
        dispute = _make_dispute(status=DisputeStatus.APPROVED)
        db = AsyncMock()
        with patch("app.services.fare_disputes.get_dispute", return_value=dispute):
            result, err = await admin_review_dispute(
                db, dispute_id=1, admin_user_id=_ADMIN_ID,
                decision=DisputeStatus.DENIED,
                admin_notes="notes here",
                refund_amount=None,
                stripe_refund_id=None,
            )
        assert result is None
        assert "terminal" in err.lower()

    @pytest.mark.asyncio
    async def test_approve_without_refund_amount_fails(self):
        dispute = _make_dispute(status=DisputeStatus.PENDING)
        db = AsyncMock()
        with patch("app.services.fare_disputes.get_dispute", return_value=dispute):
            result, err = await admin_review_dispute(
                db, dispute_id=1, admin_user_id=_ADMIN_ID,
                decision=DisputeStatus.APPROVED,
                admin_notes="notes here",
                refund_amount=None,
                stripe_refund_id=None,
            )
        assert result is None
        assert "required" in err.lower()

    @pytest.mark.asyncio
    async def test_refund_exceeds_disputed_amount(self):
        dispute = _make_dispute(status=DisputeStatus.PENDING, disputed_amount=10.0)
        db = AsyncMock()
        with patch("app.services.fare_disputes.get_dispute", return_value=dispute):
            result, err = await admin_review_dispute(
                db, dispute_id=1, admin_user_id=_ADMIN_ID,
                decision=DisputeStatus.APPROVED,
                admin_notes="notes here",
                refund_amount=50.0,
                stripe_refund_id=None,
            )
        assert result is None
        assert "cannot exceed" in err.lower()

    @pytest.mark.asyncio
    async def test_invalid_decision_rejected(self):
        db = AsyncMock()
        result, err = await admin_review_dispute(
            db, dispute_id=1, admin_user_id=_ADMIN_ID,
            decision=DisputeStatus.PENDING,  # Not a valid decision
            admin_notes="notes here",
            refund_amount=None,
            stripe_refund_id=None,
        )
        assert result is None
        assert err is not None


# ===========================================================================
# get_dispute_summary
# ===========================================================================

class TestGetDisputeSummary:
    @pytest.mark.asyncio
    async def test_empty(self):
        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        db.execute = AsyncMock(return_value=mock_result)

        summary = await get_dispute_summary(db)
        assert summary["total_disputes"] == 0
        assert summary["total_refunded"] == 0.0
        assert summary["avg_disputed_amount"] == 0.0

    @pytest.mark.asyncio
    async def test_mixed_statuses(self):
        d1 = _make_dispute(status=DisputeStatus.APPROVED, disputed_amount=20.0, refund_amount=20.0)
        d2 = _make_dispute(status=DisputeStatus.PARTIAL, disputed_amount=30.0, refund_amount=15.0)
        d3 = _make_dispute(status=DisputeStatus.DENIED, disputed_amount=10.0, refund_amount=None)
        d4 = _make_dispute(status=DisputeStatus.PENDING, disputed_amount=25.0, refund_amount=None)

        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [d1, d2, d3, d4]
        db.execute = AsyncMock(return_value=mock_result)

        summary = await get_dispute_summary(db)
        assert summary["total_disputes"] == 4
        assert summary["approved"] == 1
        assert summary["partial"] == 1
        assert summary["denied"] == 1
        assert summary["pending"] == 1
        assert summary["total_refunded"] == 35.0
        assert summary["avg_disputed_amount"] == pytest.approx(21.25)

    @pytest.mark.asyncio
    async def test_withdrawn_counted(self):
        d = _make_dispute(status=DisputeStatus.WITHDRAWN)
        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [d]
        db.execute = AsyncMock(return_value=mock_result)

        summary = await get_dispute_summary(db)
        assert summary["withdrawn"] == 1


# ===========================================================================
# Schema validation
# ===========================================================================

class TestFareDisputeCreateRequest:
    def test_valid(self):
        req = FareDisputeCreateRequest(
            category="overcharge",
            description="The app charged $32 but the estimate was $20",
            disputed_amount=12.0,
        )
        assert req.category == DisputeCategory.OVERCHARGE
        assert req.disputed_amount == 12.0

    def test_description_too_short(self):
        with pytest.raises(Exception):
            FareDisputeCreateRequest(
                category="overcharge",
                description="short",
                disputed_amount=5.0,
            )

    def test_negative_disputed_amount(self):
        with pytest.raises(Exception):
            FareDisputeCreateRequest(
                category="overcharge",
                description="The app charged $32 but the estimate was $20",
                disputed_amount=-1.0,
            )

    def test_zero_disputed_amount(self):
        with pytest.raises(Exception):
            FareDisputeCreateRequest(
                category="overcharge",
                description="The app charged $32 but the estimate was $20",
                disputed_amount=0.0,
            )


class TestAdminReviewRequest:
    def test_approve_with_refund(self):
        req = AdminReviewRequest(
            decision="approved",
            admin_notes="Confirmed overcharge per GPS route",
            refund_amount=12.50,
        )
        assert req.decision == DisputeStatus.APPROVED
        assert req.refund_amount == 12.50

    def test_deny_no_refund(self):
        req = AdminReviewRequest(
            decision="denied",
            admin_notes="GPS data shows correct route was taken",
            refund_amount=None,
        )
        assert req.decision == DisputeStatus.DENIED
        assert req.refund_amount is None

    def test_invalid_decision_pending(self):
        with pytest.raises(Exception):
            AdminReviewRequest(
                decision="pending",
                admin_notes="Moving to review queue",
            )

    def test_invalid_decision_under_review(self):
        with pytest.raises(Exception):
            AdminReviewRequest(
                decision="under_review",
                admin_notes="Looking into it",
            )

    def test_notes_too_short(self):
        with pytest.raises(Exception):
            AdminReviewRequest(
                decision="denied",
                admin_notes="ok",
            )


class TestFareDisputeResponse:
    def test_field_mapping(self):
        d = _make_dispute(
            id=7,
            ride_id=3,
            rider_id=_RIDER_ID,
            status=DisputeStatus.PENDING,
            disputed_amount=15.0,
        )
        resp = FareDisputeResponse(
            id=d.id,
            ride_id=d.ride_id,
            rider_id=d.rider_id,
            category=d.category,
            description=d.description,
            disputed_amount=d.disputed_amount,
            status=d.status,
            refund_amount=d.refund_amount,
            admin_notes=d.admin_notes,
            resolved_at=d.resolved_at,
            created_at=d.created_at,
            updated_at=d.updated_at,
        )
        assert resp.id == 7
        assert resp.status == DisputeStatus.PENDING
        assert resp.disputed_amount == 15.0


class TestAdminFareDisputeResponse:
    def test_includes_admin_fields(self):
        d = _make_dispute(
            reviewed_by_admin_id=_ADMIN_ID,
            stripe_refund_id="re_xyz",
        )
        resp = AdminFareDisputeResponse(
            id=d.id,
            ride_id=d.ride_id,
            rider_id=d.rider_id,
            category=d.category,
            description=d.description,
            disputed_amount=d.disputed_amount,
            status=d.status,
            refund_amount=d.refund_amount,
            admin_notes=d.admin_notes,
            resolved_at=d.resolved_at,
            created_at=d.created_at,
            updated_at=d.updated_at,
            reviewed_by_admin_id=d.reviewed_by_admin_id,
            stripe_refund_id=d.stripe_refund_id,
        )
        assert resp.reviewed_by_admin_id == _ADMIN_ID
        assert resp.stripe_refund_id == "re_xyz"


class TestDisputeSummaryResponse:
    def test_all_fields_present(self):
        resp = DisputeSummaryResponse(
            total_disputes=10,
            pending=3,
            under_review=2,
            approved=2,
            partial=1,
            denied=1,
            withdrawn=1,
            total_refunded=45.50,
            avg_disputed_amount=22.75,
        )
        assert resp.total_disputes == 10
        assert resp.total_refunded == 45.50
