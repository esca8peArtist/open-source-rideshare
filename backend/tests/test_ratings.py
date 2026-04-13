"""Unit tests for the rating aggregation service.

Tests rating data structures and the cancellation-policy-integrated schemas.
DB-dependent rating queries are covered by integration tests.
"""

import pytest

from app.schemas.driver import RatingDistributionResponse, RatingsSummaryResponse
from app.schemas.ride import CancelResponse
from app.services.ratings import RatingDistribution, RatingsSummary


class TestRatingDistribution:
    def test_defaults_to_zero(self):
        d = RatingDistribution()
        assert d.one_star == 0
        assert d.two_star == 0
        assert d.three_star == 0
        assert d.four_star == 0
        assert d.five_star == 0

    def test_custom_values(self):
        d = RatingDistribution(one_star=2, two_star=1, three_star=5, four_star=10, five_star=20)
        assert d.one_star == 2
        assert d.five_star == 20

    def test_frozen(self):
        d = RatingDistribution()
        with pytest.raises(AttributeError):
            d.one_star = 5


class TestRatingsSummary:
    def test_basic_summary(self):
        s = RatingsSummary(
            average=4.5,
            total_ratings=100,
            distribution=RatingDistribution(five_star=60, four_star=30, three_star=10),
            recent_average=4.7,
            recent_count=20,
        )
        assert s.average == 4.5
        assert s.total_ratings == 100
        assert s.recent_average == 4.7
        assert s.recent_count == 20

    def test_no_recent_when_few_rides(self):
        s = RatingsSummary(
            average=5.0,
            total_ratings=3,
            distribution=RatingDistribution(five_star=3),
            recent_average=None,
            recent_count=3,
        )
        assert s.recent_average is None

    def test_frozen(self):
        s = RatingsSummary(
            average=4.0,
            total_ratings=10,
            distribution=RatingDistribution(),
            recent_average=None,
            recent_count=0,
        )
        with pytest.raises(AttributeError):
            s.average = 3.0


class TestRatingDistributionResponse:
    def test_defaults(self):
        r = RatingDistributionResponse()
        assert r.one_star == 0
        assert r.five_star == 0

    def test_from_dict(self):
        r = RatingDistributionResponse(one_star=1, two_star=2, three_star=3, four_star=4, five_star=5)
        assert r.one_star == 1
        assert r.five_star == 5


class TestRatingsSummaryResponse:
    def test_full_response(self):
        r = RatingsSummaryResponse(
            average=4.8,
            total_ratings=50,
            distribution=RatingDistributionResponse(five_star=40, four_star=10),
            recent_average=4.9,
            recent_count=20,
        )
        assert r.average == 4.8
        assert r.distribution.five_star == 40
        assert r.recent_average == 4.9

    def test_minimal_response(self):
        r = RatingsSummaryResponse(
            average=5.0,
            total_ratings=0,
            distribution=RatingDistributionResponse(),
        )
        assert r.recent_average is None
        assert r.recent_count == 0


class TestCancelResponseSchema:
    def test_default_values(self):
        r = CancelResponse(status="cancelled")
        assert r.cancellation_fee == 0.0
        assert r.fee_reason == ""

    def test_with_fee(self):
        r = CancelResponse(status="cancelled", cancellation_fee=3.0, fee_reason="driver en route")
        assert r.cancellation_fee == 3.0
        assert r.fee_reason == "driver en route"
