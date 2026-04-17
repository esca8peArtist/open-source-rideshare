"""Tests for the ride feedback service and endpoint logic.

Covers:
  - RideFeedback ORM model structure
  - submit_feedback (async service with mocked DB)
  - get_ride_feedback (async service with mocked DB)
  - get_user_feedback (async service with mocked DB)
  - Pydantic schemas (FeedbackCreate / SubmitFeedbackRequest, FeedbackResponse,
    FeedbackPaginatedResponse)
  - Endpoint function logic from app.api.v1.ride_feedback (direct calls,
    no test client, mocked DB and auth deps)

No live database is used. All DB interactions are mocked with AsyncMock /
MagicMock following the same pattern established in test_fare_splits.py.
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.models.feedback import FeedbackCategory, RideFeedback
from app.models.ride import Ride, RideStatus
from app.schemas.feedback import (
    FeedbackPaginatedResponse,
    FeedbackResponse,
    SubmitFeedbackRequest,
)
from app.services.feedback import (
    get_ride_feedback,
    get_user_feedback,
    submit_feedback,
)

# Also import endpoint functions under test
from app.api.v1.ride_feedback import (
    admin_list_feedback,
    get_my_ride_feedback,
    post_ride_feedback,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_UTC = timezone.utc


def _now() -> datetime:
    return datetime.now(_UTC)


def _make_ride(
    ride_id=1,
    rider_id=10,
    driver_id=20,
    status=RideStatus.COMPLETED,
) -> MagicMock:
    r = MagicMock(spec=Ride)
    r.id = ride_id
    r.rider_id = rider_id
    r.driver_id = driver_id
    r.status = status
    r.driver_rating = None
    r.rider_rating = None
    r.tip_amount = 0.0
    return r


def _make_feedback(
    fb_id=1,
    ride_id=1,
    user_id=10,
    role="rider",
    rating=5,
    comment="Great ride",
    categories=None,
    created_at=None,
) -> MagicMock:
    fb = MagicMock(spec=RideFeedback)
    fb.id = fb_id
    fb.ride_id = ride_id
    fb.user_id = user_id
    fb.role = role
    fb.rating = rating
    fb.comment = comment
    fb.categories = categories
    fb.created_at = created_at or _now()
    return fb


def _make_user(user_id=10) -> MagicMock:
    u = MagicMock()
    u.id = user_id
    return u


def _db_for_submit(ride=None, existing_feedback=None):
    """Build a mock DB session for submit_feedback calls.

    Sequence:
      0. Ride lookup (scalar_one_or_none)
      1. Duplicate feedback check (scalar_one_or_none)
    """
    db = AsyncMock()
    call_count = [0]

    async def mock_execute(stmt):
        result = MagicMock()
        idx = call_count[0]
        call_count[0] += 1

        if idx == 0:
            result.scalar_one_or_none.return_value = ride
        elif idx == 1:
            result.scalar_one_or_none.return_value = existing_feedback
        else:
            result.scalar_one_or_none.return_value = None

        return result

    db.execute = AsyncMock(side_effect=mock_execute)
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    return db


def _db_for_get_ride_feedback(feedback_list):
    db = AsyncMock()
    result = MagicMock()
    scalars = MagicMock()
    scalars.all.return_value = feedback_list
    result.scalars.return_value = scalars
    db.execute = AsyncMock(return_value=result)
    return db


def _db_for_get_user_feedback(feedback_list, total=None):
    """Mock DB for get_user_feedback (two queries: count + fetch)."""
    db = AsyncMock()
    call_count = [0]

    async def mock_execute(stmt):
        result = MagicMock()
        idx = call_count[0]
        call_count[0] += 1

        if idx == 0:
            # Count query
            result.scalar.return_value = total if total is not None else len(feedback_list)
        else:
            scalars = MagicMock()
            scalars.all.return_value = feedback_list
            result.scalars.return_value = scalars

        return result

    db.execute = AsyncMock(side_effect=mock_execute)
    return db


# ===========================================================================
# TestRideFeedbackModel
# ===========================================================================


class TestRideFeedbackModel:
    """Tests verifying the RideFeedback ORM table structure."""

    def _cols(self):
        return {c.name for c in RideFeedback.__table__.columns}

    def test_table_name(self):
        assert RideFeedback.__tablename__ == "ride_feedback"

    def test_has_id(self):
        assert "id" in self._cols()

    def test_has_ride_id(self):
        assert "ride_id" in self._cols()

    def test_has_user_id(self):
        assert "user_id" in self._cols()

    def test_has_role(self):
        assert "role" in self._cols()

    def test_has_rating(self):
        assert "rating" in self._cols()

    def test_has_comment(self):
        assert "comment" in self._cols()

    def test_has_categories(self):
        assert "categories" in self._cols()

    def test_has_created_at(self):
        assert "created_at" in self._cols()

    def test_ride_id_is_indexed(self):
        col = RideFeedback.__table__.columns["ride_id"]
        assert col.index is True

    def test_user_id_is_indexed(self):
        col = RideFeedback.__table__.columns["user_id"]
        assert col.index is True

    def test_ride_id_has_fk(self):
        col = RideFeedback.__table__.columns["ride_id"]
        targets = {fk.target_fullname for fk in col.foreign_keys}
        assert "rides.id" in targets

    def test_user_id_has_fk(self):
        col = RideFeedback.__table__.columns["user_id"]
        targets = {fk.target_fullname for fk in col.foreign_keys}
        assert "users.id" in targets

    def test_feedback_category_enum_values(self):
        expected = {
            "safety", "cleanliness", "navigation", "professionalism",
            "vehicle_condition", "communication", "pricing", "timeliness", "other",
        }
        actual = {c.value for c in FeedbackCategory}
        assert actual == expected


# ===========================================================================
# TestSubmitFeedback
# ===========================================================================


class TestSubmitFeedback:
    """Tests for the submit_feedback service function (async, mocked DB)."""

    @pytest.mark.asyncio
    async def test_ride_not_found_raises_value_error(self):
        db = _db_for_submit(ride=None)
        with pytest.raises(ValueError, match="Ride not found"):
            await submit_feedback(
                ride_id=1, user_id=10, role="rider",
                rating=5, comment=None, categories=None, tip_amount=0.0, db=db,
            )

    @pytest.mark.asyncio
    async def test_non_completed_ride_raises_value_error(self):
        ride = _make_ride(status=RideStatus.IN_PROGRESS)
        db = _db_for_submit(ride=ride)
        with pytest.raises(ValueError, match="completed"):
            await submit_feedback(
                ride_id=1, user_id=10, role="rider",
                rating=4, comment=None, categories=None, tip_amount=0.0, db=db,
            )

    @pytest.mark.asyncio
    async def test_rider_not_participant_raises_permission_error(self):
        ride = _make_ride(rider_id=99, driver_id=20)
        db = _db_for_submit(ride=ride)
        with pytest.raises(PermissionError):
            await submit_feedback(
                ride_id=1, user_id=10, role="rider",  # user_id 10 != rider_id 99
                rating=5, comment=None, categories=None, tip_amount=0.0, db=db,
            )

    @pytest.mark.asyncio
    async def test_driver_not_participant_raises_permission_error(self):
        ride = _make_ride(rider_id=10, driver_id=99)
        db = _db_for_submit(ride=ride)
        with pytest.raises(PermissionError):
            await submit_feedback(
                ride_id=1, user_id=20, role="driver",  # user_id 20 != driver_id 99
                rating=5, comment=None, categories=None, tip_amount=0.0, db=db,
            )

    @pytest.mark.asyncio
    async def test_duplicate_feedback_raises_value_error(self):
        ride = _make_ride()
        existing = _make_feedback()
        db = _db_for_submit(ride=ride, existing_feedback=existing)
        with pytest.raises(ValueError, match="already"):
            await submit_feedback(
                ride_id=1, user_id=10, role="rider",
                rating=5, comment=None, categories=None, tip_amount=0.0, db=db,
            )

    @pytest.mark.asyncio
    async def test_rider_feedback_success_adds_record(self):
        ride = _make_ride(rider_id=10, driver_id=20)
        db = _db_for_submit(ride=ride, existing_feedback=None)
        with patch("app.services.ratings.update_driver_rating_avg", new_callable=AsyncMock):
            await submit_feedback(
                ride_id=1, user_id=10, role="rider",
                rating=4, comment="Smooth ride", categories=None, tip_amount=2.0, db=db,
            )
        db.add.assert_called_once()

    @pytest.mark.asyncio
    async def test_rider_feedback_syncs_driver_rating(self):
        ride = _make_ride(rider_id=10, driver_id=20)
        db = _db_for_submit(ride=ride, existing_feedback=None)
        with patch("app.services.ratings.update_driver_rating_avg", new_callable=AsyncMock):
            await submit_feedback(
                ride_id=1, user_id=10, role="rider",
                rating=3, comment=None, categories=None, tip_amount=0.0, db=db,
            )
        assert ride.driver_rating == 3

    @pytest.mark.asyncio
    async def test_driver_feedback_success_adds_record(self):
        ride = _make_ride(rider_id=10, driver_id=20)
        db = _db_for_submit(ride=ride, existing_feedback=None)
        await submit_feedback(
            ride_id=1, user_id=20, role="driver",
            rating=5, comment="Polite rider", categories=None, tip_amount=0.0, db=db,
        )
        db.add.assert_called_once()

    @pytest.mark.asyncio
    async def test_driver_feedback_syncs_rider_rating(self):
        ride = _make_ride(rider_id=10, driver_id=20)
        db = _db_for_submit(ride=ride, existing_feedback=None)
        await submit_feedback(
            ride_id=1, user_id=20, role="driver",
            rating=2, comment=None, categories=None, tip_amount=0.0, db=db,
        )
        assert ride.rider_rating == 2

    @pytest.mark.asyncio
    async def test_categories_stored_as_comma_separated(self):
        ride = _make_ride(rider_id=10, driver_id=20)
        db = _db_for_submit(ride=ride, existing_feedback=None)
        with patch("app.services.ratings.update_driver_rating_avg", new_callable=AsyncMock):
            await submit_feedback(
                ride_id=1, user_id=10, role="rider",
                rating=5, comment=None,
                categories=["safety", "cleanliness"],
                tip_amount=0.0, db=db,
            )
        added = db.add.call_args[0][0]
        assert added.categories == "safety,cleanliness"

    @pytest.mark.asyncio
    async def test_tip_amount_stored_for_rider(self):
        ride = _make_ride(rider_id=10, driver_id=20)
        db = _db_for_submit(ride=ride, existing_feedback=None)
        with patch("app.services.ratings.update_driver_rating_avg", new_callable=AsyncMock):
            await submit_feedback(
                ride_id=1, user_id=10, role="rider",
                rating=5, comment=None, categories=None, tip_amount=3.50, db=db,
            )
        assert ride.tip_amount == 3.50

    @pytest.mark.asyncio
    async def test_no_tip_for_driver(self):
        ride = _make_ride(rider_id=10, driver_id=20)
        db = _db_for_submit(ride=ride, existing_feedback=None)
        tip_before = ride.tip_amount
        await submit_feedback(
            ride_id=1, user_id=20, role="driver",
            rating=5, comment=None, categories=None, tip_amount=5.00, db=db,
        )
        # Driver submitting feedback should not modify tip_amount
        assert ride.tip_amount == tip_before

    @pytest.mark.asyncio
    async def test_none_categories_stored_as_none(self):
        ride = _make_ride(rider_id=10, driver_id=20)
        db = _db_for_submit(ride=ride, existing_feedback=None)
        with patch("app.services.ratings.update_driver_rating_avg", new_callable=AsyncMock):
            await submit_feedback(
                ride_id=1, user_id=10, role="rider",
                rating=5, comment=None, categories=None, tip_amount=0.0, db=db,
            )
        added = db.add.call_args[0][0]
        assert added.categories is None


# ===========================================================================
# TestGetRideFeedback
# ===========================================================================


class TestGetRideFeedback:
    """Tests for get_ride_feedback service function (async, mocked DB)."""

    @pytest.mark.asyncio
    async def test_returns_list_for_ride(self):
        feedback = [_make_feedback(fb_id=1), _make_feedback(fb_id=2)]
        db = _db_for_get_ride_feedback(feedback)
        result = await get_ride_feedback(ride_id=1, db=db)
        assert result == feedback

    @pytest.mark.asyncio
    async def test_empty_list_when_no_feedback(self):
        db = _db_for_get_ride_feedback([])
        result = await get_ride_feedback(ride_id=1, db=db)
        assert result == []

    @pytest.mark.asyncio
    async def test_returns_all_roles(self):
        rider_fb = _make_feedback(user_id=10, role="rider")
        driver_fb = _make_feedback(user_id=20, role="driver")
        db = _db_for_get_ride_feedback([rider_fb, driver_fb])
        result = await get_ride_feedback(ride_id=1, db=db)
        assert len(result) == 2


# ===========================================================================
# TestGetUserFeedback
# ===========================================================================


class TestGetUserFeedback:
    """Tests for get_user_feedback service function (async, mocked DB)."""

    @pytest.mark.asyncio
    async def test_returns_paginated_results(self):
        feedback = [_make_feedback(fb_id=i) for i in range(1, 4)]
        db = _db_for_get_user_feedback(feedback, total=3)
        items, total = await get_user_feedback(user_id=10, role=None, db=db)
        assert items == feedback
        assert total == 3

    @pytest.mark.asyncio
    async def test_returns_total_count(self):
        feedback = [_make_feedback()]
        db = _db_for_get_user_feedback(feedback, total=42)
        _, total = await get_user_feedback(user_id=10, role=None, db=db)
        assert total == 42

    @pytest.mark.asyncio
    async def test_filters_by_role(self):
        feedback = [_make_feedback(role="rider")]
        db = _db_for_get_user_feedback(feedback, total=1)
        items, _ = await get_user_feedback(user_id=10, role="rider", db=db)
        assert len(items) == 1

    @pytest.mark.asyncio
    async def test_no_role_filter_returns_all(self):
        feedback = [_make_feedback(role="rider"), _make_feedback(role="driver")]
        db = _db_for_get_user_feedback(feedback, total=2)
        items, _ = await get_user_feedback(user_id=10, role=None, db=db)
        assert len(items) == 2

    @pytest.mark.asyncio
    async def test_returns_zero_total_for_empty(self):
        db = _db_for_get_user_feedback([], total=0)
        items, total = await get_user_feedback(user_id=999, role=None, db=db)
        assert items == []
        assert total == 0


# ===========================================================================
# TestFeedbackSchemas
# ===========================================================================


class TestFeedbackSchemas:
    """Pydantic validation tests for feedback-related schemas."""

    def test_valid_rating_1_to_5(self):
        for r in range(1, 6):
            req = SubmitFeedbackRequest(rating=r)
            assert req.rating == r

    def test_rating_below_1_raises(self):
        with pytest.raises(Exception):
            SubmitFeedbackRequest(rating=0)

    def test_rating_above_5_raises(self):
        with pytest.raises(Exception):
            SubmitFeedbackRequest(rating=6)

    def test_valid_categories(self):
        req = SubmitFeedbackRequest(rating=4, categories=["safety", "cleanliness"])
        assert "safety" in req.categories

    def test_invalid_category_raises(self):
        with pytest.raises(Exception):
            SubmitFeedbackRequest(rating=4, categories=["not_a_real_category"])

    def test_feedback_response_parses_comma_separated_categories(self):
        resp = FeedbackResponse(
            id=1, ride_id=1, user_id=10, role="rider",
            rating=5, comment=None,
            categories="safety,cleanliness",
            created_at=_now(),
        )
        assert resp.categories == ["safety", "cleanliness"]

    def test_feedback_response_none_categories(self):
        resp = FeedbackResponse(
            id=1, ride_id=1, user_id=10, role="rider",
            rating=5, comment=None,
            categories=None,
            created_at=_now(),
        )
        assert resp.categories is None

    def test_feedback_response_list_categories_unchanged(self):
        resp = FeedbackResponse(
            id=1, ride_id=1, user_id=10, role="rider",
            rating=4, comment=None,
            categories=["navigation"],
            created_at=_now(),
        )
        assert resp.categories == ["navigation"]

    def test_submit_request_tip_defaults_to_zero(self):
        req = SubmitFeedbackRequest(rating=5)
        assert req.tip_amount == 0.0

    def test_submit_request_comment_optional(self):
        req = SubmitFeedbackRequest(rating=3)
        assert req.comment is None

    def test_paginated_response_fields(self):
        resp = FeedbackPaginatedResponse(items=[], total=0, limit=20, offset=0)
        assert resp.total == 0
        assert resp.limit == 20
        assert resp.offset == 0
        assert resp.items == []

    def test_paginated_response_with_items(self):
        fb = FeedbackResponse(
            id=1, ride_id=1, user_id=10, role="rider",
            rating=5, comment=None, categories=None, created_at=_now(),
        )
        resp = FeedbackPaginatedResponse(items=[fb], total=1, limit=20, offset=0)
        assert len(resp.items) == 1

    def test_feedback_response_from_attributes(self):
        assert FeedbackResponse.model_config.get("from_attributes") is True


# ===========================================================================
# TestRideFeedbackEndpointLogic
# ===========================================================================


class TestRideFeedbackEndpointLogic:
    """Tests for endpoint functions in app.api.v1.ride_feedback.

    Endpoint functions are called directly (not via ASGI test client).
    DB and auth dependencies are replaced with AsyncMock / MagicMock.
    """

    # -----------------------------------------------------------------------
    # POST /rides/{ride_id}/feedback
    # -----------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_post_feedback_ride_not_found(self):
        db = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(return_value=result)

        user = _make_user(user_id=10)
        req = SubmitFeedbackRequest(rating=5)

        with pytest.raises(HTTPException) as exc_info:
            await post_ride_feedback(ride_id=99, req=req, user=user, db=db)
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_post_feedback_not_participant(self):
        ride = _make_ride(rider_id=50, driver_id=60)
        db = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = ride
        db.execute = AsyncMock(return_value=result)

        user = _make_user(user_id=10)  # neither rider nor driver
        req = SubmitFeedbackRequest(rating=5)

        with pytest.raises(HTTPException) as exc_info:
            await post_ride_feedback(ride_id=1, req=req, user=user, db=db)
        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_post_feedback_rider_role_inferred(self):
        ride = _make_ride(rider_id=10, driver_id=20)

        db = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = ride
        db.execute = AsyncMock(return_value=result)

        user = _make_user(user_id=10)  # matches rider_id
        req = SubmitFeedbackRequest(rating=4)

        # Patch _submit_feedback at the API module level so we can inspect the
        # role argument without triggering the real service (and its lazy import).
        with patch("app.api.v1.ride_feedback._submit_feedback") as mock_submit:
            mock_fb = _make_feedback(user_id=10, role="rider")
            mock_submit.return_value = mock_fb

            await post_ride_feedback(ride_id=1, req=req, user=user, db=db)

            # Confirm role="rider" was passed to _submit_feedback
            call_kwargs = mock_submit.call_args.kwargs
            assert call_kwargs.get("role") == "rider"

    @pytest.mark.asyncio
    async def test_post_feedback_driver_role_inferred(self):
        ride = _make_ride(rider_id=10, driver_id=20)

        db = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = ride
        db.execute = AsyncMock(return_value=result)

        user = _make_user(user_id=20)  # matches driver_id
        req = SubmitFeedbackRequest(rating=3)

        with patch("app.api.v1.ride_feedback._submit_feedback") as mock_submit:
            mock_fb = _make_feedback(user_id=20, role="driver")
            mock_submit.return_value = mock_fb

            await post_ride_feedback(ride_id=1, req=req, user=user, db=db)

            call_kwargs = mock_submit.call_args
            role_arg = (
                call_kwargs.kwargs.get("role")
                if call_kwargs.kwargs
                else call_kwargs[1].get("role")
            )
            assert role_arg == "driver"

    @pytest.mark.asyncio
    async def test_post_feedback_value_error_returns_400(self):
        ride = _make_ride(rider_id=10, driver_id=20)

        db = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = ride
        db.execute = AsyncMock(return_value=result)

        user = _make_user(user_id=10)
        req = SubmitFeedbackRequest(rating=5)

        with patch(
            "app.api.v1.ride_feedback._submit_feedback",
            side_effect=ValueError("Feedback already submitted"),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await post_ride_feedback(ride_id=1, req=req, user=user, db=db)
            assert exc_info.value.status_code == 400

    # -----------------------------------------------------------------------
    # GET /rides/{ride_id}/feedback/mine
    # -----------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_get_my_feedback_ride_not_found(self):
        db = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(return_value=result)

        user = _make_user(user_id=10)
        with pytest.raises(HTTPException) as exc_info:
            await get_my_ride_feedback(ride_id=99, user=user, db=db)
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_get_my_feedback_no_entry_returns_404(self):
        ride = _make_ride(rider_id=10)

        db = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = ride
        db.execute = AsyncMock(return_value=result)

        user = _make_user(user_id=10)

        with patch(
            "app.api.v1.ride_feedback.get_ride_feedback",
            new_callable=AsyncMock,
            return_value=[],
        ):
            with pytest.raises(HTTPException) as exc_info:
                await get_my_ride_feedback(ride_id=1, user=user, db=db)
            assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_get_my_feedback_returns_own_feedback(self):
        ride = _make_ride(rider_id=10)
        my_fb = _make_feedback(user_id=10, role="rider", rating=5)
        other_fb = _make_feedback(user_id=20, role="driver", rating=4)

        db = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = ride
        db.execute = AsyncMock(return_value=result)

        user = _make_user(user_id=10)

        with patch(
            "app.api.v1.ride_feedback.get_ride_feedback",
            new_callable=AsyncMock,
            return_value=[my_fb, other_fb],
        ):
            response = await get_my_ride_feedback(ride_id=1, user=user, db=db)

        assert response.user_id == 10
        assert response.rating == 5

    @pytest.mark.asyncio
    async def test_get_my_feedback_other_user_no_entry(self):
        ride = _make_ride(rider_id=10)
        other_fb = _make_feedback(user_id=20, role="driver", rating=4)

        db = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = ride
        db.execute = AsyncMock(return_value=result)

        user = _make_user(user_id=10)  # different from other_fb's user

        with patch(
            "app.api.v1.ride_feedback.get_ride_feedback",
            new_callable=AsyncMock,
            return_value=[other_fb],  # only driver's feedback exists
        ):
            with pytest.raises(HTTPException) as exc_info:
                await get_my_ride_feedback(ride_id=1, user=user, db=db)
            assert exc_info.value.status_code == 404

    # -----------------------------------------------------------------------
    # GET /admin/feedback
    # -----------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_admin_list_feedback_no_filters(self):
        fb_list = [_make_feedback(fb_id=i) for i in range(1, 4)]

        call_count = [0]

        async def mock_execute(stmt):
            result = MagicMock()
            idx = call_count[0]
            call_count[0] += 1
            if idx == 0:
                result.scalar.return_value = 3
            else:
                scalars = MagicMock()
                scalars.all.return_value = fb_list
                result.scalars.return_value = scalars
            return result

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=mock_execute)

        admin = _make_user(user_id=1)
        response = await admin_list_feedback(
            ride_id=None, user_id=None, role=None,
            limit=20, offset=0, _admin=admin, db=db,
        )
        assert response.total == 3
        assert len(response.items) == 3

    @pytest.mark.asyncio
    async def test_admin_list_feedback_ride_id_filter(self):
        fb = _make_feedback(ride_id=7)

        call_count = [0]

        async def mock_execute(stmt):
            result = MagicMock()
            idx = call_count[0]
            call_count[0] += 1
            if idx == 0:
                result.scalar.return_value = 1
            else:
                scalars = MagicMock()
                scalars.all.return_value = [fb]
                result.scalars.return_value = scalars
            return result

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=mock_execute)

        admin = _make_user(user_id=1)
        response = await admin_list_feedback(
            ride_id=7, user_id=None, role=None,
            limit=20, offset=0, _admin=admin, db=db,
        )
        assert response.total == 1
        assert response.items[0].ride_id == 7

    @pytest.mark.asyncio
    async def test_admin_list_feedback_role_filter(self):
        fb = _make_feedback(role="driver")

        call_count = [0]

        async def mock_execute(stmt):
            result = MagicMock()
            idx = call_count[0]
            call_count[0] += 1
            if idx == 0:
                result.scalar.return_value = 1
            else:
                scalars = MagicMock()
                scalars.all.return_value = [fb]
                result.scalars.return_value = scalars
            return result

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=mock_execute)

        admin = _make_user(user_id=1)
        response = await admin_list_feedback(
            ride_id=None, user_id=None, role="driver",
            limit=20, offset=0, _admin=admin, db=db,
        )
        assert response.total == 1
        assert response.items[0].role == "driver"

    @pytest.mark.asyncio
    async def test_admin_list_feedback_empty_result(self):
        call_count = [0]

        async def mock_execute(stmt):
            result = MagicMock()
            idx = call_count[0]
            call_count[0] += 1
            if idx == 0:
                result.scalar.return_value = 0
            else:
                scalars = MagicMock()
                scalars.all.return_value = []
                result.scalars.return_value = scalars
            return result

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=mock_execute)

        admin = _make_user(user_id=1)
        response = await admin_list_feedback(
            ride_id=None, user_id=None, role=None,
            limit=20, offset=0, _admin=admin, db=db,
        )
        assert response.total == 0
        assert response.items == []

    @pytest.mark.asyncio
    async def test_admin_list_feedback_returns_paginated_response(self):
        call_count = [0]

        async def mock_execute(stmt):
            result = MagicMock()
            idx = call_count[0]
            call_count[0] += 1
            if idx == 0:
                result.scalar.return_value = 0
            else:
                scalars = MagicMock()
                scalars.all.return_value = []
                result.scalars.return_value = scalars
            return result

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=mock_execute)

        admin = _make_user(user_id=1)
        response = await admin_list_feedback(
            ride_id=None, user_id=None, role=None,
            limit=10, offset=5, _admin=admin, db=db,
        )
        assert isinstance(response, FeedbackPaginatedResponse)
        assert response.limit == 10
        assert response.offset == 5
