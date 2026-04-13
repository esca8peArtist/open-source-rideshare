"""Unit tests for admin cancellation stats schemas and endpoint logic."""

from datetime import datetime, timezone

from app.schemas.admin import (
    CancellationReasonBreakdown,
    CancellationStats,
    CancellationTimeseriesPoint,
)


class TestCancellationReasonBreakdown:
    def test_basic(self):
        b = CancellationReasonBreakdown(reason="Changed plans", count=15)
        assert b.reason == "Changed plans"
        assert b.count == 15

    def test_high_count(self):
        b = CancellationReasonBreakdown(reason="No drivers available", count=9999)
        assert b.count == 9999


class TestCancellationStats:
    def test_active_platform(self):
        stats = CancellationStats(
            total_cancellations=45,
            total_rides=500,
            cancellation_rate=9.0,
            cancellations_today=3,
            cancellations_this_week=18,
            fees_collected=135.00,
            fees_pending=15.00,
            avg_cancel_time_minutes=4.2,
            top_reasons=[
                CancellationReasonBreakdown(reason="Changed plans", count=20),
                CancellationReasonBreakdown(reason="Driver too far", count=12),
                CancellationReasonBreakdown(reason="No drivers available", count=8),
            ],
        )
        assert stats.total_cancellations == 45
        assert stats.total_rides == 500
        assert stats.cancellation_rate == 9.0
        assert stats.cancellations_today == 3
        assert stats.cancellations_this_week == 18
        assert stats.fees_collected == 135.00
        assert stats.fees_pending == 15.00
        assert stats.avg_cancel_time_minutes == 4.2
        assert len(stats.top_reasons) == 3
        assert stats.top_reasons[0].reason == "Changed plans"
        assert stats.top_reasons[0].count == 20

    def test_empty_platform(self):
        stats = CancellationStats(
            total_cancellations=0,
            total_rides=0,
            cancellation_rate=0.0,
            cancellations_today=0,
            cancellations_this_week=0,
            fees_collected=0.0,
            fees_pending=0.0,
            avg_cancel_time_minutes=None,
            top_reasons=[],
        )
        assert stats.total_cancellations == 0
        assert stats.cancellation_rate == 0.0
        assert stats.avg_cancel_time_minutes is None
        assert stats.top_reasons == []

    def test_no_avg_time(self):
        """avg_cancel_time_minutes is optional — None when no data."""
        stats = CancellationStats(
            total_cancellations=5,
            total_rides=100,
            cancellation_rate=5.0,
            cancellations_today=1,
            cancellations_this_week=3,
            fees_collected=0.0,
            fees_pending=0.0,
            top_reasons=[],
        )
        assert stats.avg_cancel_time_minutes is None

    def test_rate_calculation(self):
        """Cancellation rate should make sense relative to totals."""
        stats = CancellationStats(
            total_cancellations=10,
            total_rides=100,
            cancellation_rate=10.0,
            cancellations_today=2,
            cancellations_this_week=5,
            fees_collected=30.00,
            fees_pending=0.0,
            top_reasons=[],
        )
        expected_rate = stats.total_cancellations / stats.total_rides * 100
        assert stats.cancellation_rate == expected_rate

    def test_high_cancellation_rate(self):
        stats = CancellationStats(
            total_cancellations=90,
            total_rides=100,
            cancellation_rate=90.0,
            cancellations_today=10,
            cancellations_this_week=50,
            fees_collected=270.00,
            fees_pending=45.00,
            top_reasons=[
                CancellationReasonBreakdown(reason="No drivers", count=60),
            ],
        )
        assert stats.cancellation_rate == 90.0
        assert stats.fees_collected + stats.fees_pending == 315.00

    def test_roundtrip_serialization(self):
        original = CancellationStats(
            total_cancellations=25,
            total_rides=300,
            cancellation_rate=8.3,
            cancellations_today=4,
            cancellations_this_week=12,
            fees_collected=75.00,
            fees_pending=10.00,
            avg_cancel_time_minutes=3.5,
            top_reasons=[
                CancellationReasonBreakdown(reason="Wait too long", count=10),
            ],
        )
        data = original.model_dump()
        restored = CancellationStats(**data)
        assert restored == original


class TestCancellationTimeseriesPoint:
    def test_basic(self):
        point = CancellationTimeseriesPoint(
            date="2026-04-12",
            cancellations=8,
            fees_collected=24.00,
        )
        assert point.date == "2026-04-12"
        assert point.cancellations == 8
        assert point.fees_collected == 24.00

    def test_zero_day(self):
        point = CancellationTimeseriesPoint(
            date="2026-04-10",
            cancellations=0,
            fees_collected=0.0,
        )
        assert point.cancellations == 0
        assert point.fees_collected == 0.0

    def test_high_volume_day(self):
        point = CancellationTimeseriesPoint(
            date="2026-04-11",
            cancellations=150,
            fees_collected=450.00,
        )
        assert point.cancellations == 150
        assert point.fees_collected == 450.00

    def test_fees_without_cancellations_possible(self):
        """Fee payments can complete on a different day than the cancellation."""
        point = CancellationTimeseriesPoint(
            date="2026-04-09",
            cancellations=0,
            fees_collected=15.00,
        )
        assert point.cancellations == 0
        assert point.fees_collected == 15.00
