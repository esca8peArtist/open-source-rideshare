"""Unit tests for the feedback and disputes system.

Tests cover:
- Feedback schemas (create, response, validation)
- Dispute schemas (create, resolve, response, validation)
- Feedback service (submit, get, duplicate prevention)
- Dispute service (file, resolve, update status, list)
- Admin schemas (dispute stats, feedback stats)
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.feedback import (
    Dispute,
    DisputeStatus,
    DisputeType,
    FeedbackCategory,
    RideFeedback,
)
from app.models.ride import Ride, RideStatus
from app.schemas.feedback import (
    DisputeCreate,
    DisputeListResponse,
    DisputeResolve,
    DisputeResponse,
    FeedbackCreate,
    FeedbackListResponse,
    FeedbackResponse,
)
from app.schemas.admin import (
    AdminDisputeResponse,
    AdminDisputeListResponse,
    AdminFeedbackResponse,
    AdminFeedbackListResponse,
    DisputeStats,
    FeedbackStats,
)
from app.services.feedback import submit_feedback, get_ride_feedback, get_user_feedback
from app.services.disputes import (
    file_dispute,
    get_dispute,
    list_disputes,
    update_dispute_status,
    resolve_dispute,
    get_user_disputes,
)

NOW = datetime(2026, 4, 12, 14, 0, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_db():
    """Create a mock async session with common patterns."""
    db = AsyncMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    return db


def _scalar_result(value):
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    return result


def _scalar_value(value):
    """Mock for select(func.count()) — returns .scalar() directly."""
    result = MagicMock()
    result.scalar.return_value = value
    return result


def _scalars_result(items):
    result = MagicMock()
    scalars = MagicMock()
    scalars.all.return_value = items
    result.scalars.return_value = scalars
    return result


def _mock_ride(ride_id=1, rider_id=10, driver_id=20, status=RideStatus.COMPLETED):
    ride = MagicMock(spec=Ride)
    ride.id = ride_id
    ride.rider_id = rider_id
    ride.driver_id = driver_id
    ride.status = status
    ride.pickup_address = "123 Main St"
    ride.dropoff_address = "456 Oak Ave"
    ride.estimated_fare = 15.50
    ride.actual_fare = 14.00
    ride.driver_rating = None
    ride.rider_rating = None
    ride.tip_amount = 0.0
    return ride


def _mock_feedback(fb_id=1, ride_id=1, user_id=10, role="rider", rating=5):
    fb = MagicMock(spec=RideFeedback)
    fb.id = fb_id
    fb.ride_id = ride_id
    fb.user_id = user_id
    fb.role = role
    fb.rating = rating
    fb.comment = "Great ride!"
    fb.categories = "cleanliness,professionalism"
    fb.created_at = NOW
    return fb


def _mock_dispute(
    dispute_id=1,
    ride_id=1,
    filed_by=10,
    dtype=DisputeType.FARE,
    dstatus=DisputeStatus.OPEN,
):
    d = MagicMock(spec=Dispute)
    d.id = dispute_id
    d.ride_id = ride_id
    d.filed_by = filed_by
    d.dispute_type = dtype
    d.status = dstatus
    d.description = "The fare was incorrect"
    d.resolution_notes = None
    d.resolved_by = None
    d.refund_amount = None
    d.created_at = NOW
    d.updated_at = NOW
    d.resolved_at = None
    return d


# ===========================================================================
# Feedback Schema Tests
# ===========================================================================


class TestFeedbackCreateSchema:
    def test_valid_feedback(self):
        fb = FeedbackCreate(rating=5, comment="Great ride!")
        assert fb.rating == 5
        assert fb.comment == "Great ride!"
        assert fb.categories is None
        assert fb.tip_amount == 0.0

    def test_with_categories(self):
        fb = FeedbackCreate(
            rating=4,
            categories=["cleanliness", "professionalism"],
        )
        assert fb.categories == ["cleanliness", "professionalism"]

    def test_with_tip(self):
        fb = FeedbackCreate(rating=5, tip_amount=3.50)
        assert fb.tip_amount == 3.50

    def test_rejects_rating_below_1(self):
        with pytest.raises(Exception):
            FeedbackCreate(rating=0)

    def test_rejects_rating_above_5(self):
        with pytest.raises(Exception):
            FeedbackCreate(rating=6)

    def test_rejects_invalid_category(self):
        with pytest.raises(Exception):
            FeedbackCreate(rating=4, categories=["invalid_category"])

    def test_accepts_all_valid_categories(self):
        all_cats = [
            "safety", "cleanliness", "navigation", "professionalism",
            "vehicle_condition", "communication", "pricing", "timeliness", "other",
        ]
        fb = FeedbackCreate(rating=3, categories=all_cats)
        assert len(fb.categories) == 9

    def test_minimal_valid(self):
        fb = FeedbackCreate(rating=1)
        assert fb.rating == 1
        assert fb.comment is None


class TestFeedbackResponseSchema:
    def test_construction(self):
        resp = FeedbackResponse(
            id=1,
            ride_id=1,
            user_id=10,
            role="rider",
            rating=5,
            comment="Good",
            categories=["safety"],
            created_at=NOW,
        )
        assert resp.id == 1
        assert resp.role == "rider"

    def test_without_optional_fields(self):
        resp = FeedbackResponse(
            id=1,
            ride_id=1,
            user_id=10,
            role="driver",
            rating=4,
            created_at=NOW,
        )
        assert resp.comment is None
        assert resp.categories is None


class TestFeedbackListResponseSchema:
    def test_construction(self):
        resp = FeedbackListResponse(feedback=[], total=0)
        assert resp.total == 0
        assert resp.feedback == []


# ===========================================================================
# Dispute Schema Tests
# ===========================================================================


class TestDisputeCreateSchema:
    def test_valid_dispute(self):
        d = DisputeCreate(
            dispute_type="fare",
            description="I was overcharged for this ride",
        )
        assert d.dispute_type == "fare"
        assert d.description == "I was overcharged for this ride"

    def test_all_valid_types(self):
        valid_types = [
            "fare", "route", "driver_behavior", "rider_behavior",
            "safety_concern", "property_damage", "lost_item",
            "cancellation_fee", "other",
        ]
        for t in valid_types:
            d = DisputeCreate(dispute_type=t, description="A valid description here")
            assert d.dispute_type == t

    def test_rejects_invalid_type(self):
        with pytest.raises(Exception):
            DisputeCreate(dispute_type="invalid", description="Some description")

    def test_rejects_short_description(self):
        with pytest.raises(Exception):
            DisputeCreate(dispute_type="fare", description="short")

    def test_rejects_long_description(self):
        with pytest.raises(Exception):
            DisputeCreate(dispute_type="fare", description="x" * 2001)

    def test_strips_description_whitespace(self):
        d = DisputeCreate(
            dispute_type="fare",
            description="  I was overcharged  ",
        )
        assert d.description == "I was overcharged"

    def test_exactly_10_chars(self):
        d = DisputeCreate(dispute_type="fare", description="1234567890")
        assert len(d.description) == 10


class TestDisputeResolveSchema:
    def test_valid_resolution(self):
        r = DisputeResolve(
            status="resolved_rider_favor",
            resolution_notes="Rider was overcharged — issuing refund",
            refund_amount=5.00,
        )
        assert r.status == "resolved_rider_favor"
        assert r.refund_amount == 5.00

    def test_all_valid_statuses(self):
        valid = [
            "resolved_rider_favor", "resolved_driver_favor",
            "resolved_partial", "dismissed",
        ]
        for s in valid:
            r = DisputeResolve(
                status=s,
                resolution_notes="Notes for this resolution",
            )
            assert r.status == s

    def test_rejects_invalid_status(self):
        with pytest.raises(Exception):
            DisputeResolve(status="open", resolution_notes="Some notes")

    def test_rejects_short_notes(self):
        with pytest.raises(Exception):
            DisputeResolve(status="dismissed", resolution_notes="No")

    def test_no_refund_by_default(self):
        r = DisputeResolve(
            status="dismissed",
            resolution_notes="No merit to this claim",
        )
        assert r.refund_amount is None


class TestDisputeResponseSchema:
    def test_construction(self):
        resp = DisputeResponse(
            id=1,
            ride_id=1,
            filed_by=10,
            dispute_type="fare",
            status="open",
            description="Overcharged",
            created_at=NOW,
            updated_at=NOW,
        )
        assert resp.id == 1
        assert resp.resolved_at is None


class TestDisputeListResponseSchema:
    def test_construction(self):
        resp = DisputeListResponse(disputes=[], total=0)
        assert resp.total == 0


# ===========================================================================
# Admin Schema Tests
# ===========================================================================


class TestAdminDisputeResponseSchema:
    def test_construction(self):
        resp = AdminDisputeResponse(
            id=1,
            ride_id=1,
            filed_by=10,
            filer_name="Test Rider",
            filer_role="rider",
            dispute_type="fare",
            status="open",
            description="Overcharged",
            created_at=NOW,
            updated_at=NOW,
            ride_pickup="123 Main St",
            ride_dropoff="456 Oak Ave",
            ride_fare=15.50,
        )
        assert resp.filer_name == "Test Rider"
        assert resp.ride_fare == 15.50

    def test_optional_fields_default_none(self):
        resp = AdminDisputeResponse(
            id=1,
            ride_id=1,
            filed_by=10,
            dispute_type="fare",
            status="open",
            description="Overcharged",
            created_at=NOW,
            updated_at=NOW,
        )
        assert resp.filer_name is None
        assert resp.resolver_name is None
        assert resp.ride_fare is None


class TestDisputeStatsSchema:
    def test_construction(self):
        stats = DisputeStats(
            open_count=5,
            under_review_count=2,
            resolved_today=3,
            total_disputes=100,
            avg_resolution_hours=4.5,
            refunds_issued_total=250.00,
            top_dispute_types=[{"type": "fare", "count": 30}],
        )
        assert stats.open_count == 5
        assert stats.avg_resolution_hours == 4.5


class TestAdminFeedbackResponseSchema:
    def test_construction(self):
        resp = AdminFeedbackResponse(
            id=1,
            ride_id=1,
            user_id=10,
            user_name="Test Rider",
            role="rider",
            rating=5,
            comment="Great!",
            categories=["cleanliness"],
            created_at=NOW,
            ride_pickup="123 Main St",
            ride_dropoff="456 Oak Ave",
        )
        assert resp.user_name == "Test Rider"


class TestFeedbackStatsSchema:
    def test_construction(self):
        stats = FeedbackStats(
            total_feedback=200,
            avg_driver_rating=4.5,
            avg_rider_rating=4.7,
            feedback_today=12,
            rating_distribution={"1": 2, "2": 5, "3": 20, "4": 80, "5": 93},
            top_categories=[{"category": "cleanliness", "count": 50}],
        )
        assert stats.total_feedback == 200


# ===========================================================================
# Feedback Service Tests
# ===========================================================================


class TestSubmitFeedback:
    @pytest.mark.asyncio
    async def test_rider_submits_feedback(self):
        db = _mock_db()
        ride = _mock_ride(ride_id=1, rider_id=10, driver_id=20)
        # First execute: ride lookup, Second: duplicate check
        db.execute = AsyncMock(
            side_effect=[_scalar_result(ride), _scalar_result(None)]
        )

        with patch("app.services.ratings.update_driver_rating_avg", new_callable=AsyncMock):
            feedback = await submit_feedback(
                ride_id=1, user_id=10, role="rider",
                rating=5, comment="Great!", categories=["cleanliness"],
                tip_amount=2.00, db=db,
            )

        db.add.assert_called_once()
        added = db.add.call_args[0][0]
        assert added.ride_id == 1
        assert added.user_id == 10
        assert added.role == "rider"
        assert added.rating == 5
        assert added.categories == "cleanliness"
        assert ride.driver_rating == 5
        assert ride.tip_amount == 2.00

    @pytest.mark.asyncio
    async def test_driver_submits_feedback(self):
        db = _mock_db()
        ride = _mock_ride(ride_id=1, rider_id=10, driver_id=20)
        db.execute = AsyncMock(
            side_effect=[_scalar_result(ride), _scalar_result(None)]
        )

        feedback = await submit_feedback(
            ride_id=1, user_id=20, role="driver",
            rating=4, comment=None, categories=None,
            tip_amount=0, db=db,
        )

        db.add.assert_called_once()
        assert ride.rider_rating == 4

    @pytest.mark.asyncio
    async def test_rejects_nonexistent_ride(self):
        db = _mock_db()
        db.execute = AsyncMock(return_value=_scalar_result(None))

        with pytest.raises(ValueError, match="Ride not found"):
            await submit_feedback(
                ride_id=999, user_id=10, role="rider",
                rating=5, comment=None, categories=None,
                tip_amount=0, db=db,
            )

    @pytest.mark.asyncio
    async def test_rejects_non_completed_ride(self):
        db = _mock_db()
        ride = _mock_ride(status=RideStatus.IN_PROGRESS)
        db.execute = AsyncMock(return_value=_scalar_result(ride))

        with pytest.raises(ValueError, match="completed"):
            await submit_feedback(
                ride_id=1, user_id=10, role="rider",
                rating=5, comment=None, categories=None,
                tip_amount=0, db=db,
            )

    @pytest.mark.asyncio
    async def test_rejects_unauthorized_rider(self):
        db = _mock_db()
        ride = _mock_ride(rider_id=10, driver_id=20)
        db.execute = AsyncMock(return_value=_scalar_result(ride))

        with pytest.raises(PermissionError, match="Not authorized"):
            await submit_feedback(
                ride_id=1, user_id=99, role="rider",
                rating=5, comment=None, categories=None,
                tip_amount=0, db=db,
            )

    @pytest.mark.asyncio
    async def test_rejects_unauthorized_driver(self):
        db = _mock_db()
        ride = _mock_ride(rider_id=10, driver_id=20)
        db.execute = AsyncMock(return_value=_scalar_result(ride))

        with pytest.raises(PermissionError, match="Not authorized"):
            await submit_feedback(
                ride_id=1, user_id=99, role="driver",
                rating=5, comment=None, categories=None,
                tip_amount=0, db=db,
            )

    @pytest.mark.asyncio
    async def test_rejects_duplicate_feedback(self):
        db = _mock_db()
        ride = _mock_ride(rider_id=10)
        existing_fb = _mock_feedback()
        db.execute = AsyncMock(
            side_effect=[_scalar_result(ride), _scalar_result(existing_fb)]
        )

        with pytest.raises(ValueError, match="already submitted"):
            await submit_feedback(
                ride_id=1, user_id=10, role="rider",
                rating=5, comment=None, categories=None,
                tip_amount=0, db=db,
            )

    @pytest.mark.asyncio
    async def test_multiple_categories_joined(self):
        db = _mock_db()
        ride = _mock_ride(rider_id=10, driver_id=20)
        db.execute = AsyncMock(
            side_effect=[_scalar_result(ride), _scalar_result(None)]
        )

        with patch("app.services.ratings.update_driver_rating_avg", new_callable=AsyncMock):
            await submit_feedback(
                ride_id=1, user_id=10, role="rider",
                rating=3, comment=None,
                categories=["safety", "navigation", "pricing"],
                tip_amount=0, db=db,
            )

        added = db.add.call_args[0][0]
        assert added.categories == "safety,navigation,pricing"


class TestGetRideFeedback:
    @pytest.mark.asyncio
    async def test_returns_feedback_list(self):
        db = _mock_db()
        fb1 = _mock_feedback(fb_id=1)
        fb2 = _mock_feedback(fb_id=2, user_id=20, role="driver", rating=4)
        db.execute = AsyncMock(return_value=_scalars_result([fb1, fb2]))

        items = await get_ride_feedback(ride_id=1, db=db)
        assert len(items) == 2

    @pytest.mark.asyncio
    async def test_returns_empty_for_no_feedback(self):
        db = _mock_db()
        db.execute = AsyncMock(return_value=_scalars_result([]))

        items = await get_ride_feedback(ride_id=1, db=db)
        assert items == []


class TestGetUserFeedback:
    @pytest.mark.asyncio
    async def test_returns_paginated_results(self):
        db = _mock_db()
        fb = _mock_feedback()
        db.execute = AsyncMock(
            side_effect=[_scalar_value(1), _scalars_result([fb])]
        )

        items, total = await get_user_feedback(user_id=10, role="rider", db=db)
        assert total == 1
        assert len(items) == 1

    @pytest.mark.asyncio
    async def test_returns_empty(self):
        db = _mock_db()
        db.execute = AsyncMock(
            side_effect=[_scalar_value(0), _scalars_result([])]
        )

        items, total = await get_user_feedback(user_id=10, role=None, db=db)
        assert total == 0
        assert items == []


# ===========================================================================
# Dispute Service Tests
# ===========================================================================


class TestFileDispute:
    @pytest.mark.asyncio
    async def test_file_dispute_as_rider(self):
        db = _mock_db()
        ride = _mock_ride(ride_id=1, rider_id=10, driver_id=20)
        db.execute = AsyncMock(
            side_effect=[_scalar_result(ride), _scalar_result(None)]
        )

        dispute = await file_dispute(
            ride_id=1, user_id=10,
            dispute_type="fare",
            description="I was overcharged for this trip",
            db=db,
        )
        db.add.assert_called_once()
        added = db.add.call_args[0][0]
        assert added.ride_id == 1
        assert added.filed_by == 10
        assert added.dispute_type == DisputeType.FARE
        assert added.status == DisputeStatus.OPEN

    @pytest.mark.asyncio
    async def test_file_dispute_as_driver(self):
        db = _mock_db()
        ride = _mock_ride(ride_id=1, rider_id=10, driver_id=20)
        db.execute = AsyncMock(
            side_effect=[_scalar_result(ride), _scalar_result(None)]
        )

        dispute = await file_dispute(
            ride_id=1, user_id=20,
            dispute_type="rider_behavior",
            description="The rider was abusive during the trip",
            db=db,
        )
        db.add.assert_called_once()

    @pytest.mark.asyncio
    async def test_file_dispute_on_cancelled_ride(self):
        db = _mock_db()
        ride = _mock_ride(status=RideStatus.CANCELLED)
        db.execute = AsyncMock(
            side_effect=[_scalar_result(ride), _scalar_result(None)]
        )

        dispute = await file_dispute(
            ride_id=1, user_id=10,
            dispute_type="cancellation_fee",
            description="I should not have been charged a fee",
            db=db,
        )
        db.add.assert_called_once()

    @pytest.mark.asyncio
    async def test_rejects_nonexistent_ride(self):
        db = _mock_db()
        db.execute = AsyncMock(return_value=_scalar_result(None))

        with pytest.raises(ValueError, match="Ride not found"):
            await file_dispute(
                ride_id=999, user_id=10,
                dispute_type="fare",
                description="Some description here",
                db=db,
            )

    @pytest.mark.asyncio
    async def test_rejects_in_progress_ride(self):
        db = _mock_db()
        ride = _mock_ride(status=RideStatus.IN_PROGRESS)
        db.execute = AsyncMock(return_value=_scalar_result(ride))

        with pytest.raises(ValueError, match="completed or cancelled"):
            await file_dispute(
                ride_id=1, user_id=10,
                dispute_type="fare",
                description="Some description here",
                db=db,
            )

    @pytest.mark.asyncio
    async def test_rejects_non_participant(self):
        db = _mock_db()
        ride = _mock_ride(rider_id=10, driver_id=20)
        db.execute = AsyncMock(return_value=_scalar_result(ride))

        with pytest.raises(PermissionError, match="Not authorized"):
            await file_dispute(
                ride_id=1, user_id=99,
                dispute_type="fare",
                description="Some description here",
                db=db,
            )

    @pytest.mark.asyncio
    async def test_rejects_duplicate_open_dispute(self):
        db = _mock_db()
        ride = _mock_ride(rider_id=10)
        existing = _mock_dispute()
        db.execute = AsyncMock(
            side_effect=[_scalar_result(ride), _scalar_result(existing)]
        )

        with pytest.raises(ValueError, match="open dispute already exists"):
            await file_dispute(
                ride_id=1, user_id=10,
                dispute_type="fare",
                description="Some description here",
                db=db,
            )


class TestGetDispute:
    @pytest.mark.asyncio
    async def test_returns_dispute(self):
        db = _mock_db()
        d = _mock_dispute()
        db.execute = AsyncMock(return_value=_scalar_result(d))

        result = await get_dispute(dispute_id=1, db=db)
        assert result is d

    @pytest.mark.asyncio
    async def test_returns_none_for_missing(self):
        db = _mock_db()
        db.execute = AsyncMock(return_value=_scalar_result(None))

        result = await get_dispute(dispute_id=999, db=db)
        assert result is None


class TestListDisputes:
    @pytest.mark.asyncio
    async def test_returns_paginated(self):
        db = _mock_db()
        d1 = _mock_dispute(dispute_id=1)
        d2 = _mock_dispute(dispute_id=2)
        db.execute = AsyncMock(
            side_effect=[_scalar_value(2), _scalars_result([d1, d2])]
        )

        items, total = await list_disputes(db=db)
        assert total == 2
        assert len(items) == 2

    @pytest.mark.asyncio
    async def test_empty_results(self):
        db = _mock_db()
        db.execute = AsyncMock(
            side_effect=[_scalar_value(0), _scalars_result([])]
        )

        items, total = await list_disputes(db=db)
        assert total == 0
        assert items == []


class TestUpdateDisputeStatus:
    @pytest.mark.asyncio
    async def test_move_to_under_review(self):
        db = _mock_db()
        d = _mock_dispute(dstatus=DisputeStatus.OPEN)
        db.execute = AsyncMock(return_value=_scalar_result(d))

        result = await update_dispute_status(
            dispute_id=1, new_status="under_review", db=db,
        )
        assert d.status == DisputeStatus.UNDER_REVIEW

    @pytest.mark.asyncio
    async def test_not_found_returns_none(self):
        db = _mock_db()
        db.execute = AsyncMock(return_value=_scalar_result(None))

        result = await update_dispute_status(
            dispute_id=999, new_status="under_review", db=db,
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_rejects_non_open_dispute(self):
        db = _mock_db()
        d = _mock_dispute(dstatus=DisputeStatus.UNDER_REVIEW)
        db.execute = AsyncMock(return_value=_scalar_result(d))

        with pytest.raises(ValueError, match="only review open"):
            await update_dispute_status(
                dispute_id=1, new_status="under_review", db=db,
            )


class TestResolveDispute:
    @pytest.mark.asyncio
    async def test_resolve_rider_favor(self):
        db = _mock_db()
        d = _mock_dispute(dstatus=DisputeStatus.OPEN)
        db.execute = AsyncMock(return_value=_scalar_result(d))

        result = await resolve_dispute(
            dispute_id=1, admin_id=100,
            resolution_status="resolved_rider_favor",
            resolution_notes="Rider was overcharged",
            refund_amount=5.00,
            db=db,
        )
        assert d.status == DisputeStatus.RESOLVED_RIDER_FAVOR
        assert d.resolved_by == 100
        assert d.refund_amount == 5.00
        assert d.resolved_at is not None

    @pytest.mark.asyncio
    async def test_resolve_under_review_dispute(self):
        db = _mock_db()
        d = _mock_dispute(dstatus=DisputeStatus.UNDER_REVIEW)
        db.execute = AsyncMock(return_value=_scalar_result(d))

        result = await resolve_dispute(
            dispute_id=1, admin_id=100,
            resolution_status="dismissed",
            resolution_notes="No evidence of overcharge",
            refund_amount=None,
            db=db,
        )
        assert d.status == DisputeStatus.DISMISSED
        assert d.refund_amount is None

    @pytest.mark.asyncio
    async def test_not_found_returns_none(self):
        db = _mock_db()
        db.execute = AsyncMock(return_value=_scalar_result(None))

        result = await resolve_dispute(
            dispute_id=999, admin_id=100,
            resolution_status="dismissed",
            resolution_notes="Notes",
            refund_amount=None,
            db=db,
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_rejects_already_resolved(self):
        db = _mock_db()
        d = _mock_dispute(dstatus=DisputeStatus.RESOLVED_RIDER_FAVOR)
        db.execute = AsyncMock(return_value=_scalar_result(d))

        with pytest.raises(ValueError, match="already resolved"):
            await resolve_dispute(
                dispute_id=1, admin_id=100,
                resolution_status="dismissed",
                resolution_notes="Notes",
                refund_amount=None,
                db=db,
            )


class TestGetUserDisputes:
    @pytest.mark.asyncio
    async def test_returns_paginated(self):
        db = _mock_db()
        d = _mock_dispute()
        db.execute = AsyncMock(
            side_effect=[_scalar_value(1), _scalars_result([d])]
        )

        items, total = await get_user_disputes(user_id=10, db=db)
        assert total == 1
        assert len(items) == 1

    @pytest.mark.asyncio
    async def test_returns_empty(self):
        db = _mock_db()
        db.execute = AsyncMock(
            side_effect=[_scalar_value(0), _scalars_result([])]
        )

        items, total = await get_user_disputes(user_id=99, db=db)
        assert total == 0
        assert items == []


# ===========================================================================
# Model Enum Tests
# ===========================================================================


class TestFeedbackCategory:
    def test_all_categories_exist(self):
        expected = {
            "safety", "cleanliness", "navigation", "professionalism",
            "vehicle_condition", "communication", "pricing", "timeliness", "other",
        }
        actual = {c.value for c in FeedbackCategory}
        assert actual == expected


class TestDisputeType:
    def test_all_types_exist(self):
        expected = {
            "fare", "route", "driver_behavior", "rider_behavior",
            "safety_concern", "property_damage", "lost_item",
            "cancellation_fee", "other",
        }
        actual = {t.value for t in DisputeType}
        assert actual == expected


class TestDisputeStatus:
    def test_all_statuses_exist(self):
        expected = {
            "open", "under_review", "resolved_rider_favor",
            "resolved_driver_favor", "resolved_partial", "dismissed",
        }
        actual = {s.value for s in DisputeStatus}
        assert actual == expected
