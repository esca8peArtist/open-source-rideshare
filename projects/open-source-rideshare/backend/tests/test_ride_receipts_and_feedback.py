"""Unit tests for ride receipts and feedback APIs.

Tests cover:
- app/schemas/receipt.py — RideReceiptResponse and nested models
- app/schemas/feedback.py — SubmitFeedbackRequest, FeedbackResponse (categories parsing),
  FeedbackPaginatedResponse
- app/api/v1/receipts.py — GET /rides/{id}/receipt
- app/api/v1/ride_feedback.py:
    POST /rides/{id}/feedback
    GET  /rides/{id}/feedback/mine
    GET  /riders/me/feedback
    GET  /drivers/me/feedback
    GET  /admin/feedback
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.models.feedback import FeedbackCategory, RideFeedback
from app.models.ride import Ride, RideStatus
from app.models.user import User, UserRole
from app.schemas.feedback import (
    FeedbackPaginatedResponse,
    FeedbackResponse,
    SubmitFeedbackRequest,
)
from app.schemas.ride import (
    ReceiptDriverInfo,
    ReceiptFareBreakdown,
    ReceiptPaymentInfo,
    RideReceiptResponse,
)

NOW = datetime(2026, 4, 15, 12, 0, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_user(user_id: int = 1, role: UserRole = UserRole.RIDER, name: str = "Test User") -> User:
    u = MagicMock(spec=User)
    u.id = user_id
    u.role = role
    u.name = name
    return u


def _make_ride(
    ride_id: int = 1,
    rider_id: int = 10,
    driver_id: int = 20,
    status: RideStatus = RideStatus.COMPLETED,
) -> Ride:
    r = MagicMock(spec=Ride)
    r.id = ride_id
    r.rider_id = rider_id
    r.driver_id = driver_id
    r.status = status
    return r


def _make_feedback(
    fb_id: int = 1,
    ride_id: int = 1,
    user_id: int = 10,
    role: str = "rider",
    rating: int = 5,
    comment: str | None = "Great ride",
    categories: str | None = None,
) -> RideFeedback:
    fb = MagicMock(spec=RideFeedback)
    fb.id = fb_id
    fb.ride_id = ride_id
    fb.user_id = user_id
    fb.role = role
    fb.rating = rating
    fb.comment = comment
    fb.categories = categories
    fb.created_at = NOW
    return fb


def _receipt_dict(ride_id: int = 1) -> dict:
    return {
        "ride_id": ride_id,
        "status": "completed",
        "receipt_number": f"OR-{ride_id:08d}",
        "pickup_address": "100 Start St",
        "dropoff_address": "200 End Ave",
        "distance_km": 7.5,
        "duration_min": 11.0,
        "fare_breakdown": {
            "base": 2.50,
            "distance": 7.50,
            "time": 2.20,
            "multiplier": 1.0,
            "multiplier_label": None,
            "subtotal": 12.20,
            "platform_fee": 0.0,
            "total": 12.20,
        },
        "promo_code": None,
        "promo_discount": 0.0,
        "tip": 2.0,
        "total_charged": 14.20,
        "payment": None,
        "driver": None,
        "requested_at": NOW,
        "started_at": NOW,
        "completed_at": NOW,
        "rider_rating_given": None,
        "cooperative_name": "OpenRide",
        "currency": "USD",
    }


# ===========================================================================
# Schema: RideReceiptResponse
# ===========================================================================


class TestRideReceiptResponseSchema:
    def test_minimal_valid(self):
        data = RideReceiptResponse(
            ride_id=1,
            status="completed",
            receipt_number="OR-00000001",
            pickup_address="A",
            dropoff_address="B",
            distance_km=5.0,
            duration_min=8.0,
            fare_breakdown={
                "base": 2.50,
                "distance": 5.0,
                "time": 1.6,
                "multiplier": 1.0,
                "subtotal": 9.10,
                "total": 9.10,
            },
            total_charged=9.10,
            requested_at=NOW,
        )
        assert data.ride_id == 1
        assert data.payment is None
        assert data.driver is None
        assert data.promo_code is None
        assert data.cooperative_name == "OpenRide"
        assert data.currency == "USD"

    def test_defaults(self):
        data = RideReceiptResponse(
            ride_id=2,
            status="completed",
            receipt_number="OR-00000002",
            pickup_address="X",
            dropoff_address="Y",
            distance_km=3.0,
            duration_min=5.0,
            fare_breakdown={"base": 2.5, "distance": 3.0, "time": 1.0, "multiplier": 1.0, "subtotal": 6.5, "total": 6.5},
            total_charged=6.5,
            requested_at=NOW,
        )
        assert data.promo_discount == 0.0
        assert data.tip == 0.0
        assert data.started_at is None
        assert data.completed_at is None
        assert data.rider_rating_given is None

    def test_with_payment_and_driver(self):
        data = RideReceiptResponse(
            ride_id=3,
            status="completed",
            receipt_number="OR-00000003",
            pickup_address="A",
            dropoff_address="B",
            distance_km=10.0,
            duration_min=15.0,
            fare_breakdown={"base": 2.5, "distance": 10.0, "time": 3.0, "multiplier": 1.0, "subtotal": 15.5, "total": 15.5},
            total_charged=17.0,
            tip=1.5,
            payment={
                "payment_method": "card",
                "payment_status": "completed",
                "amount_charged": 15.5,
                "platform_fee": 0.5,
                "driver_payout": 15.0,
                "tip": 1.5,
                "promo_discount": 0.0,
                "total_charged": 17.0,
            },
            driver={
                "name": "Alice Driver",
                "rating": 4.9,
                "vehicle": "Blue Honda Civic",
                "license_plate": "ABCD-123",
            },
            requested_at=NOW,
        )
        assert data.payment is not None
        assert data.payment.amount_charged == 15.5
        assert data.driver is not None
        assert data.driver.name == "Alice Driver"

    def test_with_promo(self):
        data = RideReceiptResponse(
            ride_id=4,
            status="completed",
            receipt_number="OR-00000004",
            pickup_address="A",
            dropoff_address="B",
            distance_km=5.0,
            duration_min=8.0,
            fare_breakdown={"base": 2.5, "distance": 5.0, "time": 1.6, "multiplier": 1.0, "subtotal": 9.1, "total": 9.1},
            promo_code="PROMO20",
            promo_discount=2.0,
            total_charged=7.1,
            requested_at=NOW,
        )
        assert data.promo_code == "PROMO20"
        assert data.promo_discount == 2.0

    def test_fare_breakdown_nested_fields(self):
        bd = ReceiptFareBreakdown(
            base=2.5, distance=10.0, time=3.0,
            multiplier=1.5, multiplier_label="Surge",
            subtotal=23.25, platform_fee=1.0, total=24.25,
        )
        assert bd.multiplier == 1.5
        assert bd.multiplier_label == "Surge"
        assert bd.platform_fee == 1.0

    def test_fare_breakdown_defaults(self):
        bd = ReceiptFareBreakdown(
            base=2.5, distance=5.0, time=1.6, subtotal=9.1, total=9.1,
        )
        assert bd.multiplier == 1.0
        assert bd.multiplier_label is None
        assert bd.platform_fee == 0.0

    def test_receipt_payment_info(self):
        pi = ReceiptPaymentInfo(
            payment_status="completed",
            amount_charged=15.0,
            platform_fee=0.5,
            driver_payout=14.5,
            total_charged=15.0,
        )
        assert pi.payment_method == "card"
        assert pi.tip == 0.0
        assert pi.promo_discount == 0.0

    def test_receipt_driver_info(self):
        di = ReceiptDriverInfo(
            name="Bob",
            rating=4.7,
            vehicle="Silver Ford Focus",
            license_plate="XY-999",
        )
        assert di.name == "Bob"
        assert di.rating == 4.7


# ===========================================================================
# Schema: SubmitFeedbackRequest
# ===========================================================================


class TestSubmitFeedbackRequestSchema:
    def test_minimal_valid(self):
        req = SubmitFeedbackRequest(rating=4)
        assert req.rating == 4
        assert req.comment is None
        assert req.categories is None
        assert req.tip_amount == 0.0

    def test_full_fields(self):
        req = SubmitFeedbackRequest(
            rating=5,
            comment="Excellent driver",
            categories=["safety", "timeliness"],
            tip_amount=3.0,
        )
        assert req.rating == 5
        assert req.categories == ["safety", "timeliness"]
        assert req.tip_amount == 3.0

    def test_rejects_rating_below_1(self):
        with pytest.raises(Exception):
            SubmitFeedbackRequest(rating=0)

    def test_rejects_rating_above_5(self):
        with pytest.raises(Exception):
            SubmitFeedbackRequest(rating=6)

    def test_rejects_invalid_category(self):
        with pytest.raises(Exception):
            SubmitFeedbackRequest(rating=3, categories=["invalid_cat"])

    def test_all_valid_categories(self):
        cats = ["safety", "cleanliness", "navigation", "professionalism",
                "vehicle_condition", "communication", "pricing", "timeliness", "other"]
        req = SubmitFeedbackRequest(rating=3, categories=cats)
        assert len(req.categories) == 9


# ===========================================================================
# Schema: FeedbackResponse categories parsing
# ===========================================================================


class TestFeedbackResponseSchema:
    def test_categories_from_list(self):
        resp = FeedbackResponse(
            id=1, ride_id=1, user_id=10, role="rider",
            rating=4, categories=["safety", "cleanliness"],
            created_at=NOW,
        )
        assert resp.categories == ["safety", "cleanliness"]

    def test_categories_from_comma_string(self):
        resp = FeedbackResponse(
            id=2, ride_id=1, user_id=10, role="rider",
            rating=5, categories="safety,timeliness",
            created_at=NOW,
        )
        assert resp.categories == ["safety", "timeliness"]

    def test_categories_none(self):
        resp = FeedbackResponse(
            id=3, ride_id=1, user_id=10, role="driver",
            rating=3, categories=None,
            created_at=NOW,
        )
        assert resp.categories is None

    def test_categories_empty_string_produces_empty(self):
        resp = FeedbackResponse(
            id=4, ride_id=1, user_id=10, role="rider",
            rating=2, categories="",
            created_at=NOW,
        )
        # empty string should result in an empty list (no non-empty segments)
        assert resp.categories == []

    def test_optional_comment_none(self):
        resp = FeedbackResponse(
            id=5, ride_id=1, user_id=10, role="rider",
            rating=5, created_at=NOW,
        )
        assert resp.comment is None

    def test_paginated_response(self):
        items = [
            FeedbackResponse(id=1, ride_id=1, user_id=10, role="rider", rating=5, created_at=NOW),
            FeedbackResponse(id=2, ride_id=2, user_id=10, role="rider", rating=4, created_at=NOW),
        ]
        paginated = FeedbackPaginatedResponse(items=items, total=2, limit=20, offset=0)
        assert paginated.total == 2
        assert len(paginated.items) == 2
        assert paginated.limit == 20
        assert paginated.offset == 0


# ===========================================================================
# Router: GET /rides/{id}/receipt
# ===========================================================================


class TestReceiptsRouter:
    @pytest.mark.asyncio
    async def test_returns_receipt_on_success(self):
        from app.api.v1.receipts import get_ride_receipt

        user = _make_user(user_id=10)
        db = AsyncMock()
        receipt = _receipt_dict(ride_id=1)

        with patch(
            "app.api.v1.receipts.generate_receipt",
            new_callable=AsyncMock,
            return_value=receipt,
        ) as mock_gen:
            result = await get_ride_receipt(ride_id=1, user=user, db=db)
            mock_gen.assert_awaited_once_with(1, 10, db)
            assert result.ride_id == 1
            assert result.receipt_number == "OR-00000001"
            assert result.total_charged == 14.20

    @pytest.mark.asyncio
    async def test_raises_404_when_none_returned(self):
        from app.api.v1.receipts import get_ride_receipt

        user = _make_user(user_id=10)
        db = AsyncMock()

        with patch(
            "app.api.v1.receipts.generate_receipt",
            new_callable=AsyncMock,
            return_value=None,
        ):
            with pytest.raises(HTTPException) as exc_info:
                await get_ride_receipt(ride_id=999, user=user, db=db)
            assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_driver_can_access_receipt(self):
        from app.api.v1.receipts import get_ride_receipt

        driver = _make_user(user_id=20, role=UserRole.DRIVER)
        db = AsyncMock()
        receipt = _receipt_dict(ride_id=5)

        with patch(
            "app.api.v1.receipts.generate_receipt",
            new_callable=AsyncMock,
            return_value=receipt,
        ) as mock_gen:
            result = await get_ride_receipt(ride_id=5, user=driver, db=db)
            mock_gen.assert_awaited_once_with(5, 20, db)
            assert result.ride_id == 5

    @pytest.mark.asyncio
    async def test_receipt_with_payment_info(self):
        from app.api.v1.receipts import get_ride_receipt

        user = _make_user(user_id=10)
        db = AsyncMock()
        receipt = _receipt_dict(ride_id=2)
        receipt["payment"] = {
            "payment_method": "card",
            "payment_status": "completed",
            "amount_charged": 12.20,
            "platform_fee": 0.5,
            "driver_payout": 11.70,
            "tip": 2.0,
            "promo_discount": 0.0,
            "total_charged": 14.20,
        }

        with patch(
            "app.api.v1.receipts.generate_receipt",
            new_callable=AsyncMock,
            return_value=receipt,
        ):
            result = await get_ride_receipt(ride_id=2, user=user, db=db)
            assert result.payment is not None
            assert result.payment.amount_charged == 12.20

    def test_router_has_receipt_route(self):
        from app.api.v1.receipts import router

        paths = {route.path for route in router.routes}
        assert "/rides/{ride_id}/receipt" in paths

    def test_receipt_endpoint_is_get(self):
        from app.api.v1.receipts import router

        get_routes = [
            r for r in router.routes
            if hasattr(r, "methods") and "GET" in r.methods
            and r.path == "/rides/{ride_id}/receipt"
        ]
        assert len(get_routes) == 1


# ===========================================================================
# Router: POST /rides/{id}/feedback
# ===========================================================================


class TestPostRideFeedback:
    @pytest.mark.asyncio
    async def test_rider_submits_feedback_success(self):
        from app.api.v1.ride_feedback import post_ride_feedback

        user = _make_user(user_id=10, role=UserRole.RIDER)
        db = AsyncMock()
        ride = _make_ride(rider_id=10, driver_id=20)
        fb = _make_feedback(user_id=10, role="rider")

        execute_result = MagicMock()
        execute_result.scalar_one_or_none.return_value = ride
        db.execute = AsyncMock(return_value=execute_result)

        req = SubmitFeedbackRequest(rating=5, comment="Great!")

        with patch(
            "app.api.v1.ride_feedback._submit_feedback",
            new_callable=AsyncMock,
            return_value=fb,
        ) as mock_submit:
            result = await post_ride_feedback(ride_id=1, req=req, user=user, db=db)
            mock_submit.assert_awaited_once()
            call_kwargs = mock_submit.call_args.kwargs
            assert call_kwargs["role"] == "rider"
            assert result.rating == 5

    @pytest.mark.asyncio
    async def test_driver_submits_feedback_success(self):
        from app.api.v1.ride_feedback import post_ride_feedback

        user = _make_user(user_id=20, role=UserRole.DRIVER)
        db = AsyncMock()
        ride = _make_ride(rider_id=10, driver_id=20)
        fb = _make_feedback(fb_id=2, user_id=20, role="driver", rating=4)

        execute_result = MagicMock()
        execute_result.scalar_one_or_none.return_value = ride
        db.execute = AsyncMock(return_value=execute_result)

        req = SubmitFeedbackRequest(rating=4)

        with patch(
            "app.api.v1.ride_feedback._submit_feedback",
            new_callable=AsyncMock,
            return_value=fb,
        ) as mock_submit:
            result = await post_ride_feedback(ride_id=1, req=req, user=user, db=db)
            call_kwargs = mock_submit.call_args.kwargs
            assert call_kwargs["role"] == "driver"
            assert result.rating == 4

    @pytest.mark.asyncio
    async def test_non_participant_raises_403(self):
        from app.api.v1.ride_feedback import post_ride_feedback

        user = _make_user(user_id=99)
        db = AsyncMock()
        ride = _make_ride(rider_id=10, driver_id=20)

        execute_result = MagicMock()
        execute_result.scalar_one_or_none.return_value = ride
        db.execute = AsyncMock(return_value=execute_result)

        req = SubmitFeedbackRequest(rating=3)

        with pytest.raises(HTTPException) as exc_info:
            await post_ride_feedback(ride_id=1, req=req, user=user, db=db)
        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_ride_not_found_raises_404(self):
        from app.api.v1.ride_feedback import post_ride_feedback

        user = _make_user(user_id=10)
        db = AsyncMock()

        execute_result = MagicMock()
        execute_result.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(return_value=execute_result)

        req = SubmitFeedbackRequest(rating=3)

        with pytest.raises(HTTPException) as exc_info:
            await post_ride_feedback(ride_id=999, req=req, user=user, db=db)
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_duplicate_feedback_raises_400(self):
        from app.api.v1.ride_feedback import post_ride_feedback

        user = _make_user(user_id=10)
        db = AsyncMock()
        ride = _make_ride(rider_id=10, driver_id=20)

        execute_result = MagicMock()
        execute_result.scalar_one_or_none.return_value = ride
        db.execute = AsyncMock(return_value=execute_result)

        req = SubmitFeedbackRequest(rating=5)

        with patch(
            "app.api.v1.ride_feedback._submit_feedback",
            new_callable=AsyncMock,
            side_effect=ValueError("Feedback already submitted for this ride"),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await post_ride_feedback(ride_id=1, req=req, user=user, db=db)
            assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_permission_error_raises_403(self):
        from app.api.v1.ride_feedback import post_ride_feedback

        user = _make_user(user_id=10)
        db = AsyncMock()
        ride = _make_ride(rider_id=10, driver_id=20)

        execute_result = MagicMock()
        execute_result.scalar_one_or_none.return_value = ride
        db.execute = AsyncMock(return_value=execute_result)

        req = SubmitFeedbackRequest(rating=5)

        with patch(
            "app.api.v1.ride_feedback._submit_feedback",
            new_callable=AsyncMock,
            side_effect=PermissionError("Not authorized"),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await post_ride_feedback(ride_id=1, req=req, user=user, db=db)
            assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_categories_passed_through(self):
        from app.api.v1.ride_feedback import post_ride_feedback

        user = _make_user(user_id=10)
        db = AsyncMock()
        ride = _make_ride(rider_id=10, driver_id=20)
        fb = _make_feedback(user_id=10, categories="safety,cleanliness")

        execute_result = MagicMock()
        execute_result.scalar_one_or_none.return_value = ride
        db.execute = AsyncMock(return_value=execute_result)

        req = SubmitFeedbackRequest(rating=5, categories=["safety", "cleanliness"])

        with patch(
            "app.api.v1.ride_feedback._submit_feedback",
            new_callable=AsyncMock,
            return_value=fb,
        ) as mock_submit:
            result = await post_ride_feedback(ride_id=1, req=req, user=user, db=db)
            call_kwargs = mock_submit.call_args.kwargs
            assert call_kwargs["categories"] == ["safety", "cleanliness"]
            assert result.categories == ["safety", "cleanliness"]


# ===========================================================================
# Router: GET /rides/{id}/feedback/mine
# ===========================================================================


class TestGetMyRideFeedback:
    @pytest.mark.asyncio
    async def test_returns_own_feedback(self):
        from app.api.v1.ride_feedback import get_my_ride_feedback

        user = _make_user(user_id=10)
        db = AsyncMock()
        ride = _make_ride(rider_id=10, driver_id=20)
        fb = _make_feedback(user_id=10, role="rider", rating=5)

        execute_result = MagicMock()
        execute_result.scalar_one_or_none.return_value = ride
        db.execute = AsyncMock(return_value=execute_result)

        with patch(
            "app.api.v1.ride_feedback.get_ride_feedback",
            new_callable=AsyncMock,
            return_value=[fb],
        ):
            result = await get_my_ride_feedback(ride_id=1, user=user, db=db)
            assert result.user_id == 10
            assert result.rating == 5

    @pytest.mark.asyncio
    async def test_returns_404_when_no_feedback(self):
        from app.api.v1.ride_feedback import get_my_ride_feedback

        user = _make_user(user_id=10)
        db = AsyncMock()
        ride = _make_ride(rider_id=10, driver_id=20)

        execute_result = MagicMock()
        execute_result.scalar_one_or_none.return_value = ride
        db.execute = AsyncMock(return_value=execute_result)

        with patch(
            "app.api.v1.ride_feedback.get_ride_feedback",
            new_callable=AsyncMock,
            return_value=[],
        ):
            with pytest.raises(HTTPException) as exc_info:
                await get_my_ride_feedback(ride_id=1, user=user, db=db)
            assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_ride_not_found_returns_404(self):
        from app.api.v1.ride_feedback import get_my_ride_feedback

        user = _make_user(user_id=10)
        db = AsyncMock()

        execute_result = MagicMock()
        execute_result.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(return_value=execute_result)

        with pytest.raises(HTTPException) as exc_info:
            await get_my_ride_feedback(ride_id=999, user=user, db=db)
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_filters_to_current_user_only(self):
        from app.api.v1.ride_feedback import get_my_ride_feedback

        user = _make_user(user_id=10)
        db = AsyncMock()
        ride = _make_ride(rider_id=10, driver_id=20)
        other_fb = _make_feedback(fb_id=1, user_id=20, role="driver")
        own_fb = _make_feedback(fb_id=2, user_id=10, role="rider")

        execute_result = MagicMock()
        execute_result.scalar_one_or_none.return_value = ride
        db.execute = AsyncMock(return_value=execute_result)

        with patch(
            "app.api.v1.ride_feedback.get_ride_feedback",
            new_callable=AsyncMock,
            return_value=[other_fb, own_fb],
        ):
            result = await get_my_ride_feedback(ride_id=1, user=user, db=db)
            assert result.user_id == 10
            assert result.id == 2


# ===========================================================================
# Router: GET /riders/me/feedback
# ===========================================================================


class TestListRiderFeedback:
    @pytest.mark.asyncio
    async def test_returns_paginated_results(self):
        from app.api.v1.ride_feedback import list_rider_feedback

        user = _make_user(user_id=10, role=UserRole.RIDER)
        db = AsyncMock()
        fb1 = _make_feedback(fb_id=1, user_id=10, rating=5)
        fb2 = _make_feedback(fb_id=2, user_id=10, rating=4)

        with patch(
            "app.api.v1.ride_feedback.get_user_feedback",
            new_callable=AsyncMock,
            return_value=([fb1, fb2], 2),
        ) as mock_get:
            result = await list_rider_feedback(limit=20, offset=0, user=user, db=db)
            mock_get.assert_awaited_once_with(
                user_id=10, role="rider", db=db, limit=20, offset=0
            )
            assert result.total == 2
            assert len(result.items) == 2
            assert result.limit == 20
            assert result.offset == 0

    @pytest.mark.asyncio
    async def test_empty_history(self):
        from app.api.v1.ride_feedback import list_rider_feedback

        user = _make_user(user_id=10)
        db = AsyncMock()

        with patch(
            "app.api.v1.ride_feedback.get_user_feedback",
            new_callable=AsyncMock,
            return_value=([], 0),
        ):
            result = await list_rider_feedback(limit=20, offset=0, user=user, db=db)
            assert result.total == 0
            assert result.items == []

    @pytest.mark.asyncio
    async def test_pagination_offset(self):
        from app.api.v1.ride_feedback import list_rider_feedback

        user = _make_user(user_id=10)
        db = AsyncMock()

        with patch(
            "app.api.v1.ride_feedback.get_user_feedback",
            new_callable=AsyncMock,
            return_value=([], 50),
        ) as mock_get:
            result = await list_rider_feedback(limit=10, offset=20, user=user, db=db)
            mock_get.assert_awaited_once_with(
                user_id=10, role="rider", db=db, limit=10, offset=20
            )
            assert result.total == 50
            assert result.limit == 10
            assert result.offset == 20


# ===========================================================================
# Router: GET /drivers/me/feedback
# ===========================================================================


class TestListDriverFeedback:
    @pytest.mark.asyncio
    async def test_returns_paginated_results(self):
        from app.api.v1.ride_feedback import list_driver_feedback

        user = _make_user(user_id=20, role=UserRole.DRIVER)
        db = AsyncMock()
        fb1 = _make_feedback(fb_id=3, user_id=20, role="driver", rating=5)

        with patch(
            "app.api.v1.ride_feedback.get_user_feedback",
            new_callable=AsyncMock,
            return_value=([fb1], 1),
        ) as mock_get:
            result = await list_driver_feedback(limit=20, offset=0, user=user, db=db)
            mock_get.assert_awaited_once_with(
                user_id=20, role="driver", db=db, limit=20, offset=0
            )
            assert result.total == 1
            assert result.items[0].role == "driver"

    @pytest.mark.asyncio
    async def test_empty_driver_history(self):
        from app.api.v1.ride_feedback import list_driver_feedback

        user = _make_user(user_id=20, role=UserRole.DRIVER)
        db = AsyncMock()

        with patch(
            "app.api.v1.ride_feedback.get_user_feedback",
            new_callable=AsyncMock,
            return_value=([], 0),
        ):
            result = await list_driver_feedback(limit=20, offset=0, user=user, db=db)
            assert result.total == 0
            assert result.items == []


# ===========================================================================
# Router: GET /admin/feedback
# ===========================================================================


class TestAdminListFeedback:
    @pytest.mark.asyncio
    async def test_admin_gets_all_feedback(self):
        from app.api.v1.ride_feedback import admin_list_feedback

        admin = _make_user(user_id=1, role=UserRole.ADMIN)
        db = AsyncMock()
        fb1 = _make_feedback(fb_id=1, user_id=10)
        fb2 = _make_feedback(fb_id=2, user_id=20, role="driver")

        count_result = MagicMock()
        count_result.scalar.return_value = 2
        rows_result = MagicMock()
        rows_result.scalars.return_value.all.return_value = [fb1, fb2]

        db.execute = AsyncMock(side_effect=[count_result, rows_result])

        result = await admin_list_feedback(
            ride_id=None, user_id=None, role=None,
            limit=20, offset=0, _admin=admin, db=db,
        )
        assert result.total == 2
        assert len(result.items) == 2

    @pytest.mark.asyncio
    async def test_admin_empty_results(self):
        from app.api.v1.ride_feedback import admin_list_feedback

        admin = _make_user(user_id=1, role=UserRole.ADMIN)
        db = AsyncMock()

        count_result = MagicMock()
        count_result.scalar.return_value = 0
        rows_result = MagicMock()
        rows_result.scalars.return_value.all.return_value = []

        db.execute = AsyncMock(side_effect=[count_result, rows_result])

        result = await admin_list_feedback(
            ride_id=None, user_id=None, role=None,
            limit=20, offset=0, _admin=admin, db=db,
        )
        assert result.total == 0
        assert result.items == []

    @pytest.mark.asyncio
    async def test_admin_feedback_pagination_metadata(self):
        from app.api.v1.ride_feedback import admin_list_feedback

        admin = _make_user(user_id=1, role=UserRole.ADMIN)
        db = AsyncMock()

        count_result = MagicMock()
        count_result.scalar.return_value = 100
        rows_result = MagicMock()
        rows_result.scalars.return_value.all.return_value = []

        db.execute = AsyncMock(side_effect=[count_result, rows_result])

        result = await admin_list_feedback(
            ride_id=None, user_id=None, role=None,
            limit=10, offset=30, _admin=admin, db=db,
        )
        assert result.total == 100
        assert result.limit == 10
        assert result.offset == 30


# ===========================================================================
# Router structure tests
# ===========================================================================


class TestRideFeedbackRouterStructure:
    def test_router_tag(self):
        from app.api.v1.ride_feedback import router

        assert "ride-feedback" in router.tags

    def test_post_feedback_route_exists(self):
        from app.api.v1.ride_feedback import router

        post_routes = [
            r for r in router.routes
            if hasattr(r, "methods") and "POST" in r.methods
            and r.path == "/rides/{ride_id}/feedback"
        ]
        assert len(post_routes) == 1

    def test_get_my_feedback_route_exists(self):
        from app.api.v1.ride_feedback import router

        get_routes = [
            r for r in router.routes
            if hasattr(r, "methods") and "GET" in r.methods
            and r.path == "/rides/{ride_id}/feedback/mine"
        ]
        assert len(get_routes) == 1

    def test_rider_history_route_exists(self):
        from app.api.v1.ride_feedback import router

        get_routes = [
            r for r in router.routes
            if hasattr(r, "methods") and "GET" in r.methods
            and r.path == "/riders/me/feedback"
        ]
        assert len(get_routes) == 1

    def test_driver_history_route_exists(self):
        from app.api.v1.ride_feedback import router

        get_routes = [
            r for r in router.routes
            if hasattr(r, "methods") and "GET" in r.methods
            and r.path == "/drivers/me/feedback"
        ]
        assert len(get_routes) == 1

    def test_admin_feedback_route_exists(self):
        from app.api.v1.ride_feedback import router

        get_routes = [
            r for r in router.routes
            if hasattr(r, "methods") and "GET" in r.methods
            and r.path == "/admin/feedback"
        ]
        assert len(get_routes) == 1
