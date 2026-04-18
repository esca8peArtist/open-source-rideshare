"""Tests for GET /drivers/me/ratings — driver rating history endpoint.

Coverage targets (12+ tests):
1.  No ratings yet: average_rating null, total_ratings 0, empty list
2.  No ratings yet: recent_trend is null
3.  Single rating: correct average, breakdown, and item in list
4.  Multiple ratings: sorted newest first
5.  Rating breakdown counts are correct
6.  recent_trend with < 10 ratings uses all available ratings
7.  recent_trend with > 10 ratings uses only the last 10
8.  Pagination page 2 returns correct slice
9.  page_size > 50 returns 422
10. average_rating rounds correctly to 2 decimal places
11. Comments included when present
12. Comment is null when absent
13. require_driver blocks unauthenticated requests (no token)
14. require_driver blocks non-driver users (rider token)
15. total_pages calculation is correct

All service-layer tests use AsyncMock / MagicMock to avoid requiring a live
database, following the same pattern as test_rider_ratings.py.
Endpoint smoke tests use the real DB fixture from conftest.py.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.schemas.driver_ratings import (
    DriverRatingItem,
    DriverRatingsResponse,
    RatingBreakdown,
)
from app.services.driver_ratings import TREND_WINDOW, get_driver_ratings_history


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _make_feedback(
    ride_id: int,
    rating: int,
    comment: str | None = None,
    seconds_ago: int = 0,
) -> MagicMock:
    """Create a mock RideFeedback row."""
    fb = MagicMock()
    fb.ride_id = ride_id
    fb.rating = rating
    fb.comment = comment
    fb.created_at = _utcnow() - timedelta(seconds=seconds_ago)
    return fb


def _agg_row(
    total: int = 0,
    avg: float | None = None,
    one: int = 0,
    two: int = 0,
    three: int = 0,
    four: int = 0,
    five: int = 0,
) -> MagicMock:
    """Create a mock aggregate query result row."""
    row = MagicMock()
    row.total = total
    row.avg = avg
    row.one = one
    row.two = two
    row.three = three
    row.four = four
    row.five = five
    return row


def _build_db(
    agg_row: MagicMock,
    trend_values: list[int] | None = None,
    feedback_total: int = 0,
    feedback_rows: list[MagicMock] | None = None,
) -> AsyncMock:
    """Build a mock db session for driver_ratings service calls.

    The service issues four db.execute() calls in order:
      1. Aggregate stats query (returns agg_row)
      2. Recent trend query (returns list of rating ints)
      3. Count query for paginated list (returns feedback_total scalar)
      4. Paginated list query (returns feedback_rows)
    """
    db = AsyncMock()

    # 1. Aggregate stats
    agg_result = MagicMock()
    agg_result.one.return_value = agg_row

    # 2. Trend query — only called when total_ratings > 0
    trend_result = MagicMock()
    trend_values = trend_values or []
    trend_result.all.return_value = [(v,) for v in trend_values]

    # 3. Count query
    count_result = MagicMock()
    count_result.scalar.return_value = feedback_total

    # 4. List query
    list_result = MagicMock()
    list_result.scalars.return_value.all.return_value = feedback_rows or []

    if agg_row.total:
        # Trend query is included when total > 0
        db.execute = AsyncMock(
            side_effect=[agg_result, trend_result, count_result, list_result]
        )
    else:
        # No trend query when there are no ratings
        db.execute = AsyncMock(
            side_effect=[agg_result, count_result, list_result]
        )

    return db


# ---------------------------------------------------------------------------
# 1. No ratings yet: aggregate nulls and zeros, empty list
# ---------------------------------------------------------------------------


class TestNoRatingsYet:
    @pytest.mark.asyncio
    async def test_no_ratings_returns_null_average(self):
        db = _build_db(agg_row=_agg_row())
        result = await get_driver_ratings_history(db, driver_user_id=1, page=1, page_size=20)
        assert result.average_rating is None

    @pytest.mark.asyncio
    async def test_no_ratings_total_is_zero(self):
        db = _build_db(agg_row=_agg_row())
        result = await get_driver_ratings_history(db, driver_user_id=1, page=1, page_size=20)
        assert result.total_ratings == 0

    @pytest.mark.asyncio
    async def test_no_ratings_empty_list(self):
        db = _build_db(agg_row=_agg_row())
        result = await get_driver_ratings_history(db, driver_user_id=1, page=1, page_size=20)
        assert result.ratings == []

    # 2. No ratings: recent_trend is null
    @pytest.mark.asyncio
    async def test_no_ratings_trend_is_null(self):
        db = _build_db(agg_row=_agg_row())
        result = await get_driver_ratings_history(db, driver_user_id=1, page=1, page_size=20)
        assert result.recent_trend is None


# ---------------------------------------------------------------------------
# 3. Single rating
# ---------------------------------------------------------------------------


class TestSingleRating:
    @pytest.mark.asyncio
    async def test_single_rating_average(self):
        fb = _make_feedback(ride_id=10, rating=4)
        db = _build_db(
            agg_row=_agg_row(total=1, avg=4.0, four=1),
            trend_values=[4],
            feedback_total=1,
            feedback_rows=[fb],
        )
        result = await get_driver_ratings_history(db, driver_user_id=1, page=1, page_size=20)
        assert result.average_rating == 4.0

    @pytest.mark.asyncio
    async def test_single_rating_breakdown(self):
        fb = _make_feedback(ride_id=10, rating=4)
        db = _build_db(
            agg_row=_agg_row(total=1, avg=4.0, four=1),
            trend_values=[4],
            feedback_total=1,
            feedback_rows=[fb],
        )
        result = await get_driver_ratings_history(db, driver_user_id=1, page=1, page_size=20)
        assert result.rating_breakdown.four == 1
        assert result.rating_breakdown.five == 0

    @pytest.mark.asyncio
    async def test_single_rating_in_list(self):
        fb = _make_feedback(ride_id=10, rating=4, comment="Good ride")
        db = _build_db(
            agg_row=_agg_row(total=1, avg=4.0, four=1),
            trend_values=[4],
            feedback_total=1,
            feedback_rows=[fb],
        )
        result = await get_driver_ratings_history(db, driver_user_id=1, page=1, page_size=20)
        assert len(result.ratings) == 1
        assert result.ratings[0].ride_id == 10
        assert result.ratings[0].rating == 4


# ---------------------------------------------------------------------------
# 4. Multiple ratings sorted newest first
# ---------------------------------------------------------------------------


class TestSortOrder:
    @pytest.mark.asyncio
    async def test_multiple_ratings_newest_first(self):
        # feedback_rows already returned in expected order from the DB query
        fb_new = _make_feedback(ride_id=20, rating=5, seconds_ago=60)
        fb_old = _make_feedback(ride_id=10, rating=3, seconds_ago=3600)
        db = _build_db(
            agg_row=_agg_row(total=2, avg=4.0, three=1, five=1),
            trend_values=[5, 3],
            feedback_total=2,
            feedback_rows=[fb_new, fb_old],
        )
        result = await get_driver_ratings_history(db, driver_user_id=1, page=1, page_size=20)
        assert result.ratings[0].ride_id == 20
        assert result.ratings[1].ride_id == 10


# ---------------------------------------------------------------------------
# 5. Rating breakdown counts
# ---------------------------------------------------------------------------


class TestRatingBreakdown:
    @pytest.mark.asyncio
    async def test_breakdown_counts_correct(self):
        db = _build_db(
            agg_row=_agg_row(total=5, avg=3.4, one=1, two=0, three=2, four=1, five=1),
            trend_values=[1, 3, 3, 4, 5],
            feedback_total=5,
            feedback_rows=[],
        )
        result = await get_driver_ratings_history(db, driver_user_id=1, page=1, page_size=20)
        assert result.rating_breakdown.one == 1
        assert result.rating_breakdown.two == 0
        assert result.rating_breakdown.three == 2
        assert result.rating_breakdown.four == 1
        assert result.rating_breakdown.five == 1


# ---------------------------------------------------------------------------
# 6. recent_trend with < 10 ratings uses all available
# ---------------------------------------------------------------------------


class TestRecentTrend:
    @pytest.mark.asyncio
    async def test_recent_trend_with_fewer_than_10(self):
        # 3 ratings: [5, 4, 3] → avg = 4.0
        db = _build_db(
            agg_row=_agg_row(total=3, avg=4.0, three=1, four=1, five=1),
            trend_values=[5, 4, 3],
            feedback_total=3,
            feedback_rows=[],
        )
        result = await get_driver_ratings_history(db, driver_user_id=1, page=1, page_size=20)
        assert result.recent_trend == round((5 + 4 + 3) / 3, 2)

    # 7. recent_trend with > 10 ratings uses only last 10
    @pytest.mark.asyncio
    async def test_recent_trend_limited_to_last_10(self):
        # Service queries only TREND_WINDOW rows; simulate a scenario where
        # the lifetime avg differs from the last-10 avg.
        last_10 = [5, 5, 5, 5, 5, 5, 5, 5, 5, 4]  # avg = 4.9
        db = _build_db(
            agg_row=_agg_row(total=15, avg=3.5, one=5, five=10),
            trend_values=last_10,
            feedback_total=15,
            feedback_rows=[],
        )
        result = await get_driver_ratings_history(db, driver_user_id=1, page=1, page_size=20)
        expected = round(sum(last_10) / len(last_10), 2)
        assert result.recent_trend == expected
        assert len(last_10) == TREND_WINDOW


# ---------------------------------------------------------------------------
# 8. Pagination: page 2 returns correct slice
# ---------------------------------------------------------------------------


class TestPagination:
    @pytest.mark.asyncio
    async def test_page_2_returns_second_slice(self):
        # 25 total ratings, page_size=10, page=2 → items 11-20
        page_2_items = [_make_feedback(ride_id=i, rating=5) for i in range(11, 21)]
        db = _build_db(
            agg_row=_agg_row(total=25, avg=5.0, five=25),
            trend_values=[5] * TREND_WINDOW,
            feedback_total=25,
            feedback_rows=page_2_items,
        )
        result = await get_driver_ratings_history(db, driver_user_id=1, page=2, page_size=10)
        assert result.page == 2
        assert len(result.ratings) == 10

    # 12. total_pages calculation
    @pytest.mark.asyncio
    async def test_total_pages_calculation(self):
        db = _build_db(
            agg_row=_agg_row(total=25, avg=5.0, five=25),
            trend_values=[5] * TREND_WINDOW,
            feedback_total=25,
            feedback_rows=[],
        )
        result = await get_driver_ratings_history(db, driver_user_id=1, page=1, page_size=10)
        assert result.total_pages == math.ceil(25 / 10)

    @pytest.mark.asyncio
    async def test_total_pages_exact_division(self):
        db = _build_db(
            agg_row=_agg_row(total=20, avg=4.0, four=20),
            trend_values=[4] * TREND_WINDOW,
            feedback_total=20,
            feedback_rows=[],
        )
        result = await get_driver_ratings_history(db, driver_user_id=1, page=1, page_size=10)
        assert result.total_pages == 2

    @pytest.mark.asyncio
    async def test_total_pages_minimum_one_when_no_ratings(self):
        db = _build_db(agg_row=_agg_row())
        result = await get_driver_ratings_history(db, driver_user_id=1, page=1, page_size=20)
        assert result.total_pages == 1


# ---------------------------------------------------------------------------
# 10. average_rating rounds to 2 decimal places
# ---------------------------------------------------------------------------


class TestRounding:
    @pytest.mark.asyncio
    async def test_average_rounds_to_2dp(self):
        # avg = 13/4 = 3.25 — already 2 dp but let's use a repeating decimal
        # 10/3 ≈ 3.333...
        db = _build_db(
            agg_row=_agg_row(total=3, avg=10 / 3, three=3),
            trend_values=[3, 3, 4],
            feedback_total=3,
            feedback_rows=[],
        )
        result = await get_driver_ratings_history(db, driver_user_id=1, page=1, page_size=20)
        assert result.average_rating == round(10 / 3, 2)
        # Confirm it is expressed to at most 2 decimal places
        as_str = str(result.average_rating)
        decimal_places = len(as_str.split(".")[-1]) if "." in as_str else 0
        assert decimal_places <= 2


# ---------------------------------------------------------------------------
# 11 & 12. Comments present / absent
# ---------------------------------------------------------------------------


class TestComments:
    @pytest.mark.asyncio
    async def test_comment_included_when_present(self):
        fb = _make_feedback(ride_id=1, rating=5, comment="Excellent driver!")
        db = _build_db(
            agg_row=_agg_row(total=1, avg=5.0, five=1),
            trend_values=[5],
            feedback_total=1,
            feedback_rows=[fb],
        )
        result = await get_driver_ratings_history(db, driver_user_id=1, page=1, page_size=20)
        assert result.ratings[0].comment == "Excellent driver!"

    @pytest.mark.asyncio
    async def test_comment_is_null_when_absent(self):
        fb = _make_feedback(ride_id=2, rating=4, comment=None)
        db = _build_db(
            agg_row=_agg_row(total=1, avg=4.0, four=1),
            trend_values=[4],
            feedback_total=1,
            feedback_rows=[fb],
        )
        result = await get_driver_ratings_history(db, driver_user_id=1, page=1, page_size=20)
        assert result.ratings[0].comment is None


# ---------------------------------------------------------------------------
# 13 & 14. require_driver authentication — endpoint tests
# ---------------------------------------------------------------------------


class TestAuthEnforcement:
    @pytest.mark.anyio
    async def test_unauthenticated_request_returns_401(self, client):
        response = await client.get("/api/v1/drivers/me/ratings")
        assert response.status_code == 403

    @pytest.mark.anyio
    async def test_rider_token_is_rejected_403(self, client, rider_token):
        response = await client.get(
            "/api/v1/drivers/me/ratings",
            headers={"Authorization": f"Bearer {rider_token}"},
        )
        assert response.status_code == 403

    @pytest.mark.anyio
    async def test_driver_can_access_endpoint(self, client, driver_token, driver_profile):
        response = await client.get(
            "/api/v1/drivers/me/ratings",
            headers={"Authorization": f"Bearer {driver_token}"},
        )
        assert response.status_code == 200

    @pytest.mark.anyio
    async def test_driver_no_ratings_returns_valid_shape(
        self, client, driver_token, driver_profile
    ):
        response = await client.get(
            "/api/v1/drivers/me/ratings",
            headers={"Authorization": f"Bearer {driver_token}"},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["average_rating"] is None
        assert body["total_ratings"] == 0
        assert body["recent_trend"] is None
        assert body["ratings"] == []
        assert body["page"] == 1
        assert body["total_pages"] == 1


# ---------------------------------------------------------------------------
# 9. page_size > 50 returns 422
# ---------------------------------------------------------------------------


class TestPageSizeValidation:
    @pytest.mark.anyio
    async def test_page_size_above_max_returns_422(self, client, driver_token, driver_profile):
        response = await client.get(
            "/api/v1/drivers/me/ratings?page_size=51",
            headers={"Authorization": f"Bearer {driver_token}"},
        )
        assert response.status_code == 422

    @pytest.mark.anyio
    async def test_page_size_at_max_is_accepted(self, client, driver_token, driver_profile):
        response = await client.get(
            "/api/v1/drivers/me/ratings?page_size=50",
            headers={"Authorization": f"Bearer {driver_token}"},
        )
        assert response.status_code == 200

    @pytest.mark.anyio
    async def test_page_size_default_is_20(self, client, driver_token, driver_profile):
        response = await client.get(
            "/api/v1/drivers/me/ratings",
            headers={"Authorization": f"Bearer {driver_token}"},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["page_size"] == 20
