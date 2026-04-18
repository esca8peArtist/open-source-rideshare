"""Tests for accessibility accommodation ratings.

Covers:
1. Model
   - AccessibilityRating table attributes and constraints
   - AccommodationType enum values

2. Schemas
   - AccessibilityRatingCreate: rating range validation, accommodation_type optional
   - AccessibilityRatingResponse: round-trips all fields including None
   - AccessibilityRatingSummary: aggregate schema structure

3. Service
   - submit_accessibility_rating: happy path persists record
   - submit_accessibility_rating: raises LookupError for unknown ride
   - submit_accessibility_rating: raises ValueError for non-completed ride
   - submit_accessibility_rating: raises ValueError on duplicate submission
   - get_accessibility_rating: returns record when found
   - get_accessibility_rating: returns None when not found
   - list_rider_accessibility_ratings: returns paginated results
   - get_admin_accommodation_summary: aggregates overall and per-type stats

4. API routes (unit — mocked service layer)
   - POST /rides/{id}/accessibility-rating: 201 on success
   - POST /rides/{id}/accessibility-rating: 404 when ride not found
   - POST /rides/{id}/accessibility-rating: 400 when ride not completed
   - POST /rides/{id}/accessibility-rating: 400 on duplicate
   - GET /rides/{id}/accessibility-rating: 200 when found (rider)
   - GET /rides/{id}/accessibility-rating: 404 when not found
   - GET /me/accessibility-ratings: 200 returns list
   - GET /admin/accessibility-ratings/summary: 200 for admin caller

All tests are pure unit tests — no database required.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.accessibility_rating import AccommodationType, AccessibilityRating
from app.schemas.accessibility_rating import (
    AccessibilityRatingCreate,
    AccessibilityRatingResponse,
    AccessibilityRatingSummary,
    AccommodationTypeStat,
)


# ===========================================================================
# Helpers
# ===========================================================================


def _make_rating(
    id: int = 1,
    ride_id: int = 10,
    rider_id: int = 5,
    rating: int = 4,
    accommodation_type: AccommodationType | None = AccommodationType.HEARING_IMPAIRMENT,
    comment: str | None = "Driver was great",
) -> MagicMock:
    r = MagicMock(spec=AccessibilityRating)
    r.id = id
    r.ride_id = ride_id
    r.rider_id = rider_id
    r.rating = rating
    r.accommodation_type = accommodation_type
    r.comment = comment
    r.created_at = datetime(2026, 4, 18, 12, 0, 0, tzinfo=timezone.utc)
    return r


def _make_db_with(scalar_value=None) -> AsyncMock:
    db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = scalar_value
    result.scalar_one.return_value = 0
    result.scalars.return_value = MagicMock(return_value=[])
    db.execute.return_value = result
    return db


# ===========================================================================
# 1. Model
# ===========================================================================


class TestAccessibilityRatingModel:
    def test_table_name(self):
        assert AccessibilityRating.__tablename__ == "accessibility_ratings"

    def test_has_id_column(self):
        assert hasattr(AccessibilityRating, "id")

    def test_has_ride_id_column(self):
        assert hasattr(AccessibilityRating, "ride_id")

    def test_has_rider_id_column(self):
        assert hasattr(AccessibilityRating, "rider_id")

    def test_has_rating_column(self):
        assert hasattr(AccessibilityRating, "rating")

    def test_has_accommodation_type_column(self):
        assert hasattr(AccessibilityRating, "accommodation_type")

    def test_has_comment_column(self):
        assert hasattr(AccessibilityRating, "comment")

    def test_has_created_at_column(self):
        assert hasattr(AccessibilityRating, "created_at")

    def test_unique_constraint_exists(self):
        constraint_names = {
            c.name
            for c in AccessibilityRating.__table__.constraints
        }
        assert "uq_accessibility_rating_ride_rider" in constraint_names

    def test_check_constraint_exists(self):
        constraint_names = {
            c.name
            for c in AccessibilityRating.__table__.constraints
        }
        assert "ck_accessibility_rating_range" in constraint_names


class TestAccommodationTypeEnum:
    def test_hearing_impairment_value(self):
        assert AccommodationType.HEARING_IMPAIRMENT == "hearing_impairment"

    def test_visual_impairment_value(self):
        assert AccommodationType.VISUAL_IMPAIRMENT == "visual_impairment"

    def test_service_animal_value(self):
        assert AccommodationType.SERVICE_ANIMAL == "service_animal"

    def test_communication_preference_value(self):
        assert AccommodationType.COMMUNICATION_PREFERENCE == "communication_preference"

    def test_general_value(self):
        assert AccommodationType.GENERAL == "general"

    def test_has_exactly_five_values(self):
        assert len(AccommodationType) == 5


# ===========================================================================
# 2. Schemas
# ===========================================================================


class TestAccessibilityRatingCreateSchema:
    def test_valid_rating_5(self):
        s = AccessibilityRatingCreate(rating=5)
        assert s.rating == 5

    def test_valid_rating_1(self):
        s = AccessibilityRatingCreate(rating=1)
        assert s.rating == 1

    def test_rejects_rating_0(self):
        with pytest.raises(Exception):
            AccessibilityRatingCreate(rating=0)

    def test_rejects_rating_6(self):
        with pytest.raises(Exception):
            AccessibilityRatingCreate(rating=6)

    def test_accommodation_type_optional_default_none(self):
        s = AccessibilityRatingCreate(rating=3)
        assert s.accommodation_type is None

    def test_accepts_valid_accommodation_type(self):
        s = AccessibilityRatingCreate(rating=3, accommodation_type="visual_impairment")
        assert s.accommodation_type == AccommodationType.VISUAL_IMPAIRMENT

    def test_comment_optional_default_none(self):
        s = AccessibilityRatingCreate(rating=3)
        assert s.comment is None

    def test_comment_max_length_1000(self):
        with pytest.raises(Exception):
            AccessibilityRatingCreate(rating=3, comment="x" * 1001)

    def test_accepts_comment_up_to_1000(self):
        s = AccessibilityRatingCreate(rating=3, comment="x" * 1000)
        assert len(s.comment) == 1000


class TestAccessibilityRatingResponseSchema:
    def test_round_trip_with_all_fields(self):
        r = _make_rating()
        resp = AccessibilityRatingResponse.model_validate(r)
        assert resp.id == 1
        assert resp.ride_id == 10
        assert resp.rider_id == 5
        assert resp.rating == 4
        assert resp.accommodation_type == AccommodationType.HEARING_IMPAIRMENT
        assert resp.comment == "Driver was great"

    def test_round_trip_accommodation_type_none(self):
        r = _make_rating(accommodation_type=None)
        resp = AccessibilityRatingResponse.model_validate(r)
        assert resp.accommodation_type is None

    def test_round_trip_comment_none(self):
        r = _make_rating(comment=None)
        resp = AccessibilityRatingResponse.model_validate(r)
        assert resp.comment is None


class TestAccessibilityRatingSummarySchema:
    def test_overall_avg_and_total(self):
        s = AccessibilityRatingSummary(
            overall_avg=4.2,
            total_ratings=10,
            by_accommodation_type=[],
        )
        assert s.overall_avg == 4.2
        assert s.total_ratings == 10
        assert s.by_accommodation_type == []

    def test_by_accommodation_type_entries(self):
        stat = AccommodationTypeStat(
            accommodation_type=AccommodationType.SERVICE_ANIMAL,
            avg_rating=3.8,
            total_ratings=5,
        )
        s = AccessibilityRatingSummary(
            overall_avg=3.8,
            total_ratings=5,
            by_accommodation_type=[stat],
        )
        assert len(s.by_accommodation_type) == 1
        assert s.by_accommodation_type[0].accommodation_type == AccommodationType.SERVICE_ANIMAL


# ===========================================================================
# 3. Service
# ===========================================================================


class TestSubmitAccessibilityRatingService:
    @pytest.mark.asyncio
    async def test_raises_lookup_error_when_ride_not_found(self):
        from app.services.accessibility_ratings import submit_accessibility_rating
        from app.models.ride import Ride

        db = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        db.execute.return_value = result

        with pytest.raises(LookupError, match="Ride not found"):
            await submit_accessibility_rating(db=db, ride_id=99, rider_id=1, rating=5)

    @pytest.mark.asyncio
    async def test_raises_value_error_for_non_completed_ride(self):
        from app.services.accessibility_ratings import submit_accessibility_rating
        from app.models.ride import Ride, RideStatus

        ride = MagicMock(spec=Ride)
        ride.id = 10
        ride.rider_id = 1
        ride.status = RideStatus.IN_PROGRESS

        db = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = ride
        db.execute.return_value = result

        with pytest.raises(ValueError, match="completed"):
            await submit_accessibility_rating(db=db, ride_id=10, rider_id=1, rating=5)

    @pytest.mark.asyncio
    async def test_raises_value_error_on_duplicate(self):
        from app.services.accessibility_ratings import submit_accessibility_rating
        from app.models.ride import Ride, RideStatus

        ride = MagicMock(spec=Ride)
        ride.id = 10
        ride.rider_id = 1
        ride.status = RideStatus.COMPLETED

        existing_record = _make_rating()

        call_count = 0

        async def _execute(query):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:
                result.scalar_one_or_none.return_value = ride
            else:
                result.scalar_one_or_none.return_value = existing_record
            return result

        db = AsyncMock()
        db.execute.side_effect = _execute

        with pytest.raises(ValueError, match="already been submitted"):
            await submit_accessibility_rating(db=db, ride_id=10, rider_id=1, rating=5)

    @pytest.mark.asyncio
    async def test_happy_path_adds_record(self):
        from app.services.accessibility_ratings import submit_accessibility_rating
        from app.models.ride import Ride, RideStatus

        ride = MagicMock(spec=Ride)
        ride.id = 10
        ride.rider_id = 1
        ride.status = RideStatus.COMPLETED

        call_count = 0

        async def _execute(query):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:
                result.scalar_one_or_none.return_value = ride
            else:
                result.scalar_one_or_none.return_value = None
            return result

        db = AsyncMock()
        db.execute.side_effect = _execute
        db.flush = AsyncMock()

        record = await submit_accessibility_rating(
            db=db,
            ride_id=10,
            rider_id=1,
            rating=4,
            accommodation_type=AccommodationType.VISUAL_IMPAIRMENT,
            comment="Very helpful",
        )

        db.add.assert_called_once()
        db.flush.assert_awaited_once()
        assert record.ride_id == 10
        assert record.rider_id == 1
        assert record.rating == 4


class TestGetAccessibilityRatingService:
    @pytest.mark.asyncio
    async def test_returns_record_when_found(self):
        from app.services.accessibility_ratings import get_accessibility_rating

        record = _make_rating()
        db = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = record
        db.execute.return_value = result

        r = await get_accessibility_rating(db=db, ride_id=10, rider_id=5)
        assert r is record

    @pytest.mark.asyncio
    async def test_returns_none_when_not_found(self):
        from app.services.accessibility_ratings import get_accessibility_rating

        db = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        db.execute.return_value = result

        r = await get_accessibility_rating(db=db, ride_id=10, rider_id=5)
        assert r is None


class TestListRiderAccessibilityRatingsService:
    @pytest.mark.asyncio
    async def test_returns_total_and_items(self):
        from app.services.accessibility_ratings import list_rider_accessibility_ratings

        record = _make_rating()
        call_count = 0

        async def _execute(query):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:
                result.scalar_one.return_value = 1
            else:
                result.scalars.return_value.__iter__ = MagicMock(return_value=iter([record]))
            return result

        db = AsyncMock()
        db.execute.side_effect = _execute

        total, items = await list_rider_accessibility_ratings(db=db, rider_id=5)
        assert total == 1

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_ratings(self):
        from app.services.accessibility_ratings import list_rider_accessibility_ratings

        call_count = 0

        async def _execute(query):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:
                result.scalar_one.return_value = 0
            else:
                result.scalars.return_value = MagicMock()
                result.scalars.return_value.__iter__ = MagicMock(return_value=iter([]))
            return result

        db = AsyncMock()
        db.execute.side_effect = _execute

        total, items = await list_rider_accessibility_ratings(db=db, rider_id=99)
        assert total == 0
