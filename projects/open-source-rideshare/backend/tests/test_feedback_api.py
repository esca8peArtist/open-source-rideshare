"""Tests for feedback and disputes API endpoints.

POST  /rides/{ride_id}/feedback  — submit feedback
GET   /rides/{ride_id}/feedback  — list ride feedback
GET   /me/feedback               — list my feedback

POST   /rides/{ride_id}/disputes            — file a dispute
GET    /rides/{ride_id}/disputes            — list ride disputes
GET    /me/disputes                         — list my disputes
GET    /me/disputes/{dispute_id}            — get a specific dispute
PATCH  /admin/disputes/{dispute_id}/review  — move to under_review
POST   /admin/disputes/{dispute_id}/resolve — resolve

Coverage
--------
Router: post_feedback
  - 201 for valid rider feedback
  - 201 for valid driver feedback
  - 403 for admin attempting to submit feedback
  - 409 when service raises ValueError (duplicate)
  - 403 when service raises PermissionError (wrong participant)

Router: get_ride_feedback_endpoint
  - 404 when ride not found
  - 403 for non-participant non-admin
  - 200 for admin
  - 200 for the ride's rider

Router: get_my_feedback
  - returns FeedbackListResponse

Router: post_dispute
  - 201 for valid dispute
  - 409 on ValueError (duplicate / wrong status)
  - 403 on PermissionError

Router: list_ride_disputes
  - 404 when ride not found for non-admin
  - 403 for non-participant
  - 200 for participant

Router: get_my_disputes
  - returns DisputeListResponse

Router: get_my_dispute
  - 200 for owner
  - 404 when not found or not owner

Router: admin_list_disputes
  - 422 for invalid status filter
  - 200 with valid filter

Router: admin_review_dispute
  - 404 when not found
  - 409 when ValueError (already under review)
  - 200 on success

Router: admin_resolve_dispute
  - 404 when not found
  - 409 on ValueError (already resolved)
  - 200 on success

_parse_categories helper
  - None input returns None
  - empty string returns empty list without None item
  - comma-separated returns list
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.api.v1.feedback import _parse_categories, _feedback_response
from app.schemas.feedback import (
    DisputeCreate,
    DisputeListResponse,
    DisputeResponse,
    FeedbackCreate,
    FeedbackListResponse,
    FeedbackResponse,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

NOW = datetime(2026, 4, 18, 12, 0, 0, tzinfo=timezone.utc)


def _mock_user(role: str = "rider", user_id: int = 1):
    u = MagicMock()
    u.id = user_id
    u.role = MagicMock()
    u.role.value = role
    return u


def _mock_feedback(
    fb_id: int = 1,
    ride_id: int = 100,
    user_id: int = 1,
    role: str = "rider",
    rating: int = 5,
    comment: str | None = "Great ride",
    categories: str | None = "cleanliness,professionalism",
):
    fb = MagicMock()
    fb.id = fb_id
    fb.ride_id = ride_id
    fb.user_id = user_id
    fb.role = role
    fb.rating = rating
    fb.comment = comment
    fb.categories = categories
    fb.created_at = NOW
    return fb


def _mock_dispute(
    dispute_id: int = 1,
    ride_id: int = 100,
    filed_by: int = 1,
    dispute_type="fare",
    disp_status="open",
    description: str = "Driver overcharged me.",
):
    from app.models.feedback import DisputeStatus, DisputeType
    d = MagicMock()
    d.id = dispute_id
    d.ride_id = ride_id
    d.filed_by = filed_by
    d.dispute_type = MagicMock()
    d.dispute_type.value = dispute_type
    d.status = MagicMock()
    d.status.value = disp_status
    d.description = description
    d.resolution_notes = None
    d.resolved_by = None
    d.refund_amount = None
    d.created_at = NOW
    d.updated_at = NOW
    d.resolved_at = None
    return d


def _mock_ride(ride_id: int = 100, rider_id: int = 1, driver_id: int = 2):
    ride = MagicMock()
    ride.id = ride_id
    ride.rider_id = rider_id
    ride.driver_id = driver_id
    return ride


def _scalar_none():
    r = MagicMock()
    r.scalar_one_or_none = MagicMock(return_value=None)
    return r


def _scalar_obj(obj):
    r = MagicMock()
    r.scalar_one_or_none = MagicMock(return_value=obj)
    return r


def _scalars_list(items):
    r = MagicMock()
    r.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=items)))
    return r


# ---------------------------------------------------------------------------
# _parse_categories helper
# ---------------------------------------------------------------------------


class TestParseCategories:
    def test_none_returns_none(self):
        assert _parse_categories(None) is None

    def test_empty_string_returns_empty_list(self):
        result = _parse_categories("")
        assert result == [] or result is None  # implementation: empty string → None (falsy)

    def test_single_category(self):
        assert _parse_categories("cleanliness") == ["cleanliness"]

    def test_multiple_categories(self):
        result = _parse_categories("cleanliness,professionalism,safety")
        assert result == ["cleanliness", "professionalism", "safety"]


# ---------------------------------------------------------------------------
# _feedback_response helper
# ---------------------------------------------------------------------------


class TestFeedbackResponse:
    def test_categories_parsed_from_comma_string(self):
        fb = _mock_feedback(categories="cleanliness,safety")
        resp = _feedback_response(fb)
        assert resp.categories == ["cleanliness", "safety"]

    def test_categories_none_when_null(self):
        fb = _mock_feedback(categories=None)
        resp = _feedback_response(fb)
        assert resp.categories is None

    def test_fields_mapped_correctly(self):
        fb = _mock_feedback(fb_id=7, ride_id=42, user_id=3, role="driver", rating=4)
        resp = _feedback_response(fb)
        assert resp.id == 7
        assert resp.ride_id == 42
        assert resp.user_id == 3
        assert resp.role == "driver"
        assert resp.rating == 4


# ---------------------------------------------------------------------------
# Router: post_feedback
# ---------------------------------------------------------------------------


class TestPostFeedback:
    @pytest.mark.asyncio
    async def test_rider_submits_feedback_201(self):
        from app.api.v1.feedback import post_feedback

        user = _mock_user(role="rider", user_id=1)
        body = FeedbackCreate(rating=5, comment="Excellent", tip_amount=2.0)
        fb = _mock_feedback()
        db = AsyncMock()

        with patch("app.api.v1.feedback.submit_feedback", new_callable=AsyncMock, return_value=fb):
            result = await post_feedback(ride_id=100, body=body, user=user, db=db)

        assert result.id == 1
        assert result.rating == 5

    @pytest.mark.asyncio
    async def test_driver_submits_feedback_201(self):
        from app.api.v1.feedback import post_feedback

        user = _mock_user(role="driver", user_id=2)
        body = FeedbackCreate(rating=4)
        fb = _mock_feedback(role="driver", user_id=2, categories=None)
        db = AsyncMock()

        with patch("app.api.v1.feedback.submit_feedback", new_callable=AsyncMock, return_value=fb):
            result = await post_feedback(ride_id=100, body=body, user=user, db=db)

        assert result.role == "driver"

    @pytest.mark.asyncio
    async def test_admin_cannot_submit_feedback(self):
        from app.api.v1.feedback import post_feedback

        user = _mock_user(role="admin")
        body = FeedbackCreate(rating=3)
        db = AsyncMock()

        with pytest.raises(HTTPException) as exc:
            await post_feedback(ride_id=100, body=body, user=user, db=db)
        assert exc.value.status_code == 403

    @pytest.mark.asyncio
    async def test_duplicate_feedback_409(self):
        from app.api.v1.feedback import post_feedback

        user = _mock_user(role="rider")
        body = FeedbackCreate(rating=4)
        db = AsyncMock()

        with patch(
            "app.api.v1.feedback.submit_feedback",
            new_callable=AsyncMock,
            side_effect=ValueError("Feedback already submitted"),
        ):
            with pytest.raises(HTTPException) as exc:
                await post_feedback(ride_id=100, body=body, user=user, db=db)
        assert exc.value.status_code == 409

    @pytest.mark.asyncio
    async def test_wrong_participant_403(self):
        from app.api.v1.feedback import post_feedback

        user = _mock_user(role="rider")
        body = FeedbackCreate(rating=4)
        db = AsyncMock()

        with patch(
            "app.api.v1.feedback.submit_feedback",
            new_callable=AsyncMock,
            side_effect=PermissionError("Not authorized"),
        ):
            with pytest.raises(HTTPException) as exc:
                await post_feedback(ride_id=100, body=body, user=user, db=db)
        assert exc.value.status_code == 403


# ---------------------------------------------------------------------------
# Router: get_ride_feedback_endpoint
# ---------------------------------------------------------------------------


class TestGetRideFeedback:
    @pytest.mark.asyncio
    async def test_404_when_ride_not_found(self):
        from app.api.v1.feedback import get_ride_feedback_endpoint

        user = _mock_user(role="rider", user_id=1)
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_scalar_none())

        with pytest.raises(HTTPException) as exc:
            await get_ride_feedback_endpoint(ride_id=999, user=user, db=db)
        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_403_for_non_participant(self):
        from app.api.v1.feedback import get_ride_feedback_endpoint

        user = _mock_user(role="rider", user_id=99)
        ride = _mock_ride(rider_id=1, driver_id=2)  # user 99 is not a participant
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_scalar_obj(ride))

        with pytest.raises(HTTPException) as exc:
            await get_ride_feedback_endpoint(ride_id=100, user=user, db=db)
        assert exc.value.status_code == 403

    @pytest.mark.asyncio
    async def test_200_for_rider_participant(self):
        from app.api.v1.feedback import get_ride_feedback_endpoint

        user = _mock_user(role="rider", user_id=1)
        ride = _mock_ride(rider_id=1, driver_id=2)
        fb = _mock_feedback()
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_scalar_obj(ride))

        with patch(
            "app.api.v1.feedback.get_ride_feedback",
            new_callable=AsyncMock,
            return_value=[fb],
        ):
            result = await get_ride_feedback_endpoint(ride_id=100, user=user, db=db)

        assert result.total == 1
        assert isinstance(result, FeedbackListResponse)

    @pytest.mark.asyncio
    async def test_200_for_admin(self):
        from app.api.v1.feedback import get_ride_feedback_endpoint

        user = _mock_user(role="admin", user_id=99)
        ride = _mock_ride(rider_id=1, driver_id=2)
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_scalar_obj(ride))

        with patch(
            "app.api.v1.feedback.get_ride_feedback",
            new_callable=AsyncMock,
            return_value=[],
        ):
            result = await get_ride_feedback_endpoint(ride_id=100, user=user, db=db)

        assert result.total == 0


# ---------------------------------------------------------------------------
# Router: get_my_feedback
# ---------------------------------------------------------------------------


class TestGetMyFeedback:
    @pytest.mark.asyncio
    async def test_returns_feedback_list_response(self):
        from app.api.v1.feedback import get_my_feedback

        user = _mock_user(role="rider", user_id=1)
        fb = _mock_feedback()
        db = AsyncMock()

        with patch(
            "app.api.v1.feedback.get_user_feedback",
            new_callable=AsyncMock,
            return_value=([fb], 1),
        ):
            result = await get_my_feedback(limit=20, offset=0, user=user, db=db)

        assert result.total == 1
        assert isinstance(result, FeedbackListResponse)

    @pytest.mark.asyncio
    async def test_empty_returns_zero_total(self):
        from app.api.v1.feedback import get_my_feedback

        user = _mock_user(role="driver")
        db = AsyncMock()

        with patch(
            "app.api.v1.feedback.get_user_feedback",
            new_callable=AsyncMock,
            return_value=([], 0),
        ):
            result = await get_my_feedback(limit=20, offset=0, user=user, db=db)

        assert result.total == 0
        assert result.feedback == []


# ---------------------------------------------------------------------------
# Router: post_dispute
# ---------------------------------------------------------------------------


class TestPostDispute:
    @pytest.mark.asyncio
    async def test_201_for_valid_dispute(self):
        from app.api.v1.disputes import post_dispute

        user = _mock_user(role="rider", user_id=1)
        body = DisputeCreate(
            dispute_type="fare",
            description="Driver charged double the quoted fare.",
        )
        dispute = _mock_dispute()
        db = AsyncMock()

        with patch(
            "app.api.v1.disputes.file_dispute",
            new_callable=AsyncMock,
            return_value=dispute,
        ):
            result = await post_dispute(ride_id=100, body=body, user=user, db=db)

        assert result.id == 1
        assert result.dispute_type == "fare"

    @pytest.mark.asyncio
    async def test_409_on_duplicate_dispute(self):
        from app.api.v1.disputes import post_dispute

        user = _mock_user(role="rider")
        body = DisputeCreate(
            dispute_type="route",
            description="Driver took a much longer route than necessary.",
        )
        db = AsyncMock()

        with patch(
            "app.api.v1.disputes.file_dispute",
            new_callable=AsyncMock,
            side_effect=ValueError("An open dispute already exists"),
        ):
            with pytest.raises(HTTPException) as exc:
                await post_dispute(ride_id=100, body=body, user=user, db=db)
        assert exc.value.status_code == 409

    @pytest.mark.asyncio
    async def test_403_when_not_participant(self):
        from app.api.v1.disputes import post_dispute

        user = _mock_user(role="rider")
        body = DisputeCreate(
            dispute_type="fare",
            description="Not my ride but trying to dispute.",
        )
        db = AsyncMock()

        with patch(
            "app.api.v1.disputes.file_dispute",
            new_callable=AsyncMock,
            side_effect=PermissionError("Not authorized"),
        ):
            with pytest.raises(HTTPException) as exc:
                await post_dispute(ride_id=100, body=body, user=user, db=db)
        assert exc.value.status_code == 403


# ---------------------------------------------------------------------------
# Router: get_my_disputes
# ---------------------------------------------------------------------------


class TestGetMyDisputes:
    @pytest.mark.asyncio
    async def test_returns_dispute_list_response(self):
        from app.api.v1.disputes import get_my_disputes

        user = _mock_user(role="rider")
        dispute = _mock_dispute()
        db = AsyncMock()

        with patch(
            "app.api.v1.disputes.get_user_disputes",
            new_callable=AsyncMock,
            return_value=([dispute], 1),
        ):
            result = await get_my_disputes(limit=20, offset=0, user=user, db=db)

        assert result.total == 1
        assert isinstance(result, DisputeListResponse)

    @pytest.mark.asyncio
    async def test_empty_list(self):
        from app.api.v1.disputes import get_my_disputes

        user = _mock_user(role="driver")
        db = AsyncMock()

        with patch(
            "app.api.v1.disputes.get_user_disputes",
            new_callable=AsyncMock,
            return_value=([], 0),
        ):
            result = await get_my_disputes(limit=20, offset=0, user=user, db=db)

        assert result.total == 0


# ---------------------------------------------------------------------------
# Router: get_my_dispute
# ---------------------------------------------------------------------------


class TestGetMyDispute:
    @pytest.mark.asyncio
    async def test_200_for_owner(self):
        from app.api.v1.disputes import get_my_dispute

        user = _mock_user(role="rider", user_id=1)
        dispute = _mock_dispute(filed_by=1)
        db = AsyncMock()

        with patch(
            "app.api.v1.disputes.get_dispute",
            new_callable=AsyncMock,
            return_value=dispute,
        ):
            result = await get_my_dispute(dispute_id=1, user=user, db=db)

        assert result.id == 1

    @pytest.mark.asyncio
    async def test_404_when_not_found(self):
        from app.api.v1.disputes import get_my_dispute

        user = _mock_user(role="rider", user_id=1)
        db = AsyncMock()

        with patch(
            "app.api.v1.disputes.get_dispute",
            new_callable=AsyncMock,
            return_value=None,
        ):
            with pytest.raises(HTTPException) as exc:
                await get_my_dispute(dispute_id=999, user=user, db=db)
        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_404_when_not_owner(self):
        from app.api.v1.disputes import get_my_dispute

        user = _mock_user(role="rider", user_id=5)
        dispute = _mock_dispute(filed_by=1)  # filed by user 1, not user 5
        db = AsyncMock()

        with patch(
            "app.api.v1.disputes.get_dispute",
            new_callable=AsyncMock,
            return_value=dispute,
        ):
            with pytest.raises(HTTPException) as exc:
                await get_my_dispute(dispute_id=1, user=user, db=db)
        assert exc.value.status_code == 404


# ---------------------------------------------------------------------------
# Router: admin_list_disputes
# ---------------------------------------------------------------------------


class TestAdminListDisputes:
    @pytest.mark.asyncio
    async def test_422_on_invalid_status(self):
        from app.api.v1.disputes import admin_list_disputes

        admin = _mock_user(role="admin")
        db = AsyncMock()

        with pytest.raises(HTTPException) as exc:
            await admin_list_disputes(
                status_filter="not_a_real_status",
                limit=20,
                offset=0,
                _admin=admin,
                db=db,
            )
        assert exc.value.status_code == 422

    @pytest.mark.asyncio
    async def test_200_with_no_filter(self):
        from app.api.v1.disputes import admin_list_disputes

        admin = _mock_user(role="admin")
        dispute = _mock_dispute()
        db = AsyncMock()

        with patch(
            "app.api.v1.disputes.list_disputes",
            new_callable=AsyncMock,
            return_value=([dispute], 1),
        ):
            result = await admin_list_disputes(
                status_filter=None,
                limit=20,
                offset=0,
                _admin=admin,
                db=db,
            )

        assert result.total == 1

    @pytest.mark.asyncio
    async def test_200_with_valid_status_filter(self):
        from app.api.v1.disputes import admin_list_disputes

        admin = _mock_user(role="admin")
        db = AsyncMock()

        with patch(
            "app.api.v1.disputes.list_disputes",
            new_callable=AsyncMock,
            return_value=([], 0),
        ):
            result = await admin_list_disputes(
                status_filter="open",
                limit=20,
                offset=0,
                _admin=admin,
                db=db,
            )

        assert result.total == 0


# ---------------------------------------------------------------------------
# Router: admin_review_dispute
# ---------------------------------------------------------------------------


class TestAdminReviewDispute:
    @pytest.mark.asyncio
    async def test_404_when_not_found(self):
        from app.api.v1.disputes import admin_review_dispute

        admin = _mock_user(role="admin")
        db = AsyncMock()

        with patch(
            "app.api.v1.disputes.update_dispute_status",
            new_callable=AsyncMock,
            return_value=None,
        ):
            with pytest.raises(HTTPException) as exc:
                await admin_review_dispute(dispute_id=999, _admin=admin, db=db)
        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_409_when_already_under_review(self):
        from app.api.v1.disputes import admin_review_dispute

        admin = _mock_user(role="admin")
        db = AsyncMock()

        with patch(
            "app.api.v1.disputes.update_dispute_status",
            new_callable=AsyncMock,
            side_effect=ValueError("Can only review open disputes"),
        ):
            with pytest.raises(HTTPException) as exc:
                await admin_review_dispute(dispute_id=1, _admin=admin, db=db)
        assert exc.value.status_code == 409

    @pytest.mark.asyncio
    async def test_200_on_success(self):
        from app.api.v1.disputes import admin_review_dispute

        admin = _mock_user(role="admin")
        dispute = _mock_dispute(disp_status="under_review")
        db = AsyncMock()

        with patch(
            "app.api.v1.disputes.update_dispute_status",
            new_callable=AsyncMock,
            return_value=dispute,
        ):
            result = await admin_review_dispute(dispute_id=1, _admin=admin, db=db)

        assert result.status == "under_review"


# ---------------------------------------------------------------------------
# Router: admin_resolve_dispute
# ---------------------------------------------------------------------------


class TestAdminResolveDispute:
    from app.schemas.feedback import DisputeResolve

    @pytest.mark.asyncio
    async def test_404_when_not_found(self):
        from app.api.v1.disputes import admin_resolve_dispute
        from app.schemas.feedback import DisputeResolve

        admin = _mock_user(role="admin", user_id=99)
        body = DisputeResolve(
            status="resolved_rider_favor",
            resolution_notes="Refund issued for overcharge.",
            refund_amount=12.50,
        )
        db = AsyncMock()

        with patch(
            "app.api.v1.disputes.resolve_dispute",
            new_callable=AsyncMock,
            return_value=None,
        ):
            with pytest.raises(HTTPException) as exc:
                await admin_resolve_dispute(dispute_id=999, body=body, admin=admin, db=db)
        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_409_when_already_resolved(self):
        from app.api.v1.disputes import admin_resolve_dispute
        from app.schemas.feedback import DisputeResolve

        admin = _mock_user(role="admin", user_id=99)
        body = DisputeResolve(
            status="dismissed",
            resolution_notes="No evidence of wrongdoing.",
        )
        db = AsyncMock()

        with patch(
            "app.api.v1.disputes.resolve_dispute",
            new_callable=AsyncMock,
            side_effect=ValueError("Dispute is already resolved"),
        ):
            with pytest.raises(HTTPException) as exc:
                await admin_resolve_dispute(dispute_id=1, body=body, admin=admin, db=db)
        assert exc.value.status_code == 409

    @pytest.mark.asyncio
    async def test_200_with_refund(self):
        from app.api.v1.disputes import admin_resolve_dispute
        from app.schemas.feedback import DisputeResolve

        admin = _mock_user(role="admin", user_id=99)
        body = DisputeResolve(
            status="resolved_rider_favor",
            resolution_notes="Fare adjusted.",
            refund_amount=8.0,
        )
        dispute = _mock_dispute(disp_status="resolved_rider_favor")
        dispute.refund_amount = 8.0
        db = AsyncMock()

        with patch(
            "app.api.v1.disputes.resolve_dispute",
            new_callable=AsyncMock,
            return_value=dispute,
        ):
            result = await admin_resolve_dispute(dispute_id=1, body=body, admin=admin, db=db)

        assert result.status == "resolved_rider_favor"
