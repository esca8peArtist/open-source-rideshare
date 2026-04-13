"""Unit tests for driver earnings schemas and daily earnings breakdown."""

from datetime import date

from app.schemas.driver import (
    DailyEarningsPoint,
    EarningsResponse,
    EarningsSummary,
    EarningsTrip,
)


class TestEarningsSummary:
    def test_basic_earnings(self):
        summary = EarningsSummary(
            total_fares=250.00,
            total_tips=35.50,
            total_cancellation_fees=9.00,
            total_earnings=294.50,
            trip_count=20,
            average_fare=12.50,
            average_tip=1.78,
            period_start=date(2026, 4, 5),
            period_end=date(2026, 4, 12),
        )
        assert summary.total_fares == 250.00
        assert summary.total_tips == 35.50
        assert summary.total_cancellation_fees == 9.00
        assert summary.total_earnings == 294.50
        assert summary.trip_count == 20
        assert summary.average_fare == 12.50

    def test_zero_earnings(self):
        summary = EarningsSummary(
            total_fares=0.0,
            total_tips=0.0,
            total_cancellation_fees=0.0,
            total_earnings=0.0,
            trip_count=0,
            average_fare=0.0,
            average_tip=0.0,
            period_start=date(2026, 4, 12),
            period_end=date(2026, 4, 12),
        )
        assert summary.total_earnings == 0.0
        assert summary.trip_count == 0

    def test_cancellation_fees_default_zero(self):
        """total_cancellation_fees defaults to 0.0 for backward compat."""
        summary = EarningsSummary(
            total_fares=100.00,
            total_tips=10.00,
            total_earnings=110.00,
            trip_count=5,
            average_fare=20.00,
            average_tip=2.00,
            period_start=date(2026, 4, 5),
            period_end=date(2026, 4, 12),
        )
        assert summary.total_cancellation_fees == 0.0

    def test_earnings_add_up(self):
        summary = EarningsSummary(
            total_fares=100.00,
            total_tips=15.00,
            total_cancellation_fees=6.00,
            total_earnings=121.00,
            trip_count=8,
            average_fare=12.50,
            average_tip=1.88,
            period_start=date(2026, 4, 1),
            period_end=date(2026, 4, 12),
        )
        expected = summary.total_fares + summary.total_tips + summary.total_cancellation_fees
        assert summary.total_earnings == expected

    def test_roundtrip_serialization(self):
        original = EarningsSummary(
            total_fares=150.00,
            total_tips=20.00,
            total_cancellation_fees=5.00,
            total_earnings=175.00,
            trip_count=10,
            average_fare=15.00,
            average_tip=2.00,
            period_start=date(2026, 4, 5),
            period_end=date(2026, 4, 12),
        )
        data = original.model_dump()
        restored = EarningsSummary(**data)
        assert restored == original


class TestEarningsTrip:
    def test_completed_trip(self):
        from datetime import datetime, timezone
        trip = EarningsTrip(
            ride_id=42,
            pickup_address="123 Main St",
            dropoff_address="456 Oak Ave",
            fare=18.50,
            tip=3.00,
            total=21.50,
            distance_km=5.2,
            duration_min=12.0,
            completed_at=datetime(2026, 4, 12, 10, 30, tzinfo=timezone.utc),
        )
        assert trip.ride_id == 42
        assert trip.total == 21.50

    def test_no_tip_trip(self):
        trip = EarningsTrip(
            ride_id=43,
            pickup_address="A",
            dropoff_address="B",
            fare=12.00,
            tip=0.0,
            total=12.00,
            distance_km=3.0,
            duration_min=8.0,
            completed_at=None,
        )
        assert trip.tip == 0.0
        assert trip.total == trip.fare


class TestEarningsResponse:
    def test_with_trips(self):
        summary = EarningsSummary(
            total_fares=30.00,
            total_tips=5.00,
            total_cancellation_fees=3.00,
            total_earnings=38.00,
            trip_count=2,
            average_fare=15.00,
            average_tip=2.50,
            period_start=date(2026, 4, 12),
            period_end=date(2026, 4, 12),
        )
        trips = [
            EarningsTrip(
                ride_id=i,
                pickup_address=f"P{i}",
                dropoff_address=f"D{i}",
                fare=15.00,
                tip=2.50,
                total=17.50,
                distance_km=4.0,
                duration_min=10.0,
                completed_at=None,
            )
            for i in range(2)
        ]
        resp = EarningsResponse(summary=summary, trips=trips)
        assert len(resp.trips) == 2
        assert resp.summary.total_earnings == 38.00

    def test_empty_earnings(self):
        summary = EarningsSummary(
            total_fares=0.0,
            total_tips=0.0,
            total_earnings=0.0,
            trip_count=0,
            average_fare=0.0,
            average_tip=0.0,
            period_start=date(2026, 4, 12),
            period_end=date(2026, 4, 12),
        )
        resp = EarningsResponse(summary=summary, trips=[])
        assert resp.trips == []
        assert resp.summary.trip_count == 0


class TestDailyEarningsPoint:
    def test_basic(self):
        point = DailyEarningsPoint(
            date="2026-04-12",
            fares=85.00,
            tips=12.50,
            cancellation_fees=3.00,
            total=100.50,
            trips=6,
        )
        assert point.date == "2026-04-12"
        assert point.fares == 85.00
        assert point.tips == 12.50
        assert point.cancellation_fees == 3.00
        assert point.total == 100.50
        assert point.trips == 6

    def test_zero_day(self):
        point = DailyEarningsPoint(
            date="2026-04-10",
            fares=0.0,
            tips=0.0,
            cancellation_fees=0.0,
            total=0.0,
            trips=0,
        )
        assert point.total == 0.0
        assert point.trips == 0

    def test_cancellation_only_day(self):
        """Driver can earn from cancellation fees even with no completed trips."""
        point = DailyEarningsPoint(
            date="2026-04-11",
            fares=0.0,
            tips=0.0,
            cancellation_fees=5.00,
            total=5.00,
            trips=0,
        )
        assert point.trips == 0
        assert point.total == 5.00
        assert point.cancellation_fees == 5.00

    def test_total_adds_up(self):
        point = DailyEarningsPoint(
            date="2026-04-12",
            fares=50.00,
            tips=8.00,
            cancellation_fees=3.00,
            total=61.00,
            trips=4,
        )
        expected = point.fares + point.tips + point.cancellation_fees
        assert point.total == expected
