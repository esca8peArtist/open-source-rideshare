from datetime import datetime, timedelta, timezone

import pytest

from app.schemas.admin import (
    DriverMetrics,
    PeakDayEntry,
    PeakHourEntry,
    RideFunnelMetrics,
    RideMetrics,
    RideTimingMetrics,
    TopDriverEntry,
)


# ---- RideFunnelMetrics Schema Tests ----


class TestRideFunnelMetrics:
    def test_basic_funnel(self):
        funnel = RideFunnelMetrics(
            total_requested=100,
            total_matched=85,
            total_completed=75,
            total_cancelled=15,
            match_rate=85.0,
            completion_rate=88.24,
            cancellation_rate=15.0,
        )
        assert funnel.total_requested == 100
        assert funnel.total_matched == 85
        assert funnel.total_completed == 75
        assert funnel.total_cancelled == 15
        assert funnel.match_rate == 85.0
        assert funnel.completion_rate == 88.24
        assert funnel.cancellation_rate == 15.0

    def test_zero_rides_funnel(self):
        funnel = RideFunnelMetrics(
            total_requested=0,
            total_matched=0,
            total_completed=0,
            total_cancelled=0,
            match_rate=0.0,
            completion_rate=0.0,
            cancellation_rate=0.0,
        )
        assert funnel.total_requested == 0
        assert funnel.match_rate == 0.0

    def test_perfect_funnel(self):
        funnel = RideFunnelMetrics(
            total_requested=50,
            total_matched=50,
            total_completed=50,
            total_cancelled=0,
            match_rate=100.0,
            completion_rate=100.0,
            cancellation_rate=0.0,
        )
        assert funnel.match_rate == 100.0
        assert funnel.completion_rate == 100.0
        assert funnel.cancellation_rate == 0.0


class TestRideTimingMetrics:
    def test_with_all_timings(self):
        timing = RideTimingMetrics(
            avg_wait_seconds=45.3,
            avg_pickup_seconds=180.5,
            avg_ride_duration_seconds=1200.0,
            avg_total_seconds=1425.8,
        )
        assert timing.avg_wait_seconds == 45.3
        assert timing.avg_pickup_seconds == 180.5
        assert timing.avg_ride_duration_seconds == 1200.0
        assert timing.avg_total_seconds == 1425.8

    def test_with_null_timings(self):
        timing = RideTimingMetrics()
        assert timing.avg_wait_seconds is None
        assert timing.avg_pickup_seconds is None
        assert timing.avg_ride_duration_seconds is None
        assert timing.avg_total_seconds is None

    def test_partial_timings(self):
        timing = RideTimingMetrics(
            avg_wait_seconds=30.0,
            avg_ride_duration_seconds=900.0,
        )
        assert timing.avg_wait_seconds == 30.0
        assert timing.avg_pickup_seconds is None
        assert timing.avg_ride_duration_seconds == 900.0


class TestPeakEntries:
    def test_peak_hour_entry(self):
        entry = PeakHourEntry(hour=17, rides=42)
        assert entry.hour == 17
        assert entry.rides == 42

    def test_peak_day_entry(self):
        entry = PeakDayEntry(day_of_week="Friday", rides=230)
        assert entry.day_of_week == "Friday"
        assert entry.rides == 230


class TestRideMetrics:
    def test_full_ride_metrics(self):
        metrics = RideMetrics(
            period="month",
            funnel=RideFunnelMetrics(
                total_requested=1000,
                total_matched=900,
                total_completed=800,
                total_cancelled=120,
                match_rate=90.0,
                completion_rate=88.89,
                cancellation_rate=12.0,
            ),
            timing=RideTimingMetrics(
                avg_wait_seconds=38.5,
                avg_pickup_seconds=195.2,
                avg_ride_duration_seconds=1100.0,
                avg_total_seconds=1333.7,
            ),
            avg_distance_km=8.5,
            avg_fare=18.75,
            peak_hours=[
                PeakHourEntry(hour=17, rides=85),
                PeakHourEntry(hour=8, rides=72),
            ],
            peak_days=[
                PeakDayEntry(day_of_week="Friday", rides=180),
                PeakDayEntry(day_of_week="Saturday", rides=165),
            ],
        )
        assert metrics.period == "month"
        assert metrics.funnel.total_requested == 1000
        assert metrics.timing.avg_wait_seconds == 38.5
        assert metrics.avg_distance_km == 8.5
        assert metrics.avg_fare == 18.75
        assert len(metrics.peak_hours) == 2
        assert metrics.peak_hours[0].hour == 17
        assert len(metrics.peak_days) == 2
        assert metrics.peak_days[0].day_of_week == "Friday"

    def test_ride_metrics_no_data(self):
        metrics = RideMetrics(
            period="week",
            funnel=RideFunnelMetrics(
                total_requested=0,
                total_matched=0,
                total_completed=0,
                total_cancelled=0,
                match_rate=0.0,
                completion_rate=0.0,
                cancellation_rate=0.0,
            ),
            timing=RideTimingMetrics(),
            avg_distance_km=None,
            avg_fare=None,
            peak_hours=[],
            peak_days=[],
        )
        assert metrics.avg_distance_km is None
        assert metrics.avg_fare is None
        assert metrics.peak_hours == []

    def test_ride_metrics_week_period(self):
        metrics = RideMetrics(
            period="week",
            funnel=RideFunnelMetrics(
                total_requested=50,
                total_matched=45,
                total_completed=40,
                total_cancelled=5,
                match_rate=90.0,
                completion_rate=88.89,
                cancellation_rate=10.0,
            ),
            timing=RideTimingMetrics(avg_wait_seconds=25.0),
            peak_hours=[],
            peak_days=[],
        )
        assert metrics.period == "week"

    def test_ride_metrics_year_period(self):
        metrics = RideMetrics(
            period="year",
            funnel=RideFunnelMetrics(
                total_requested=12000,
                total_matched=11000,
                total_completed=10000,
                total_cancelled=1200,
                match_rate=91.67,
                completion_rate=90.91,
                cancellation_rate=10.0,
            ),
            timing=RideTimingMetrics(
                avg_wait_seconds=42.0,
                avg_pickup_seconds=200.0,
                avg_ride_duration_seconds=1050.0,
                avg_total_seconds=1292.0,
            ),
            avg_distance_km=9.2,
            avg_fare=20.50,
            peak_hours=[PeakHourEntry(hour=h, rides=100 - h) for h in range(24)],
            peak_days=[PeakDayEntry(day_of_week=d, rides=100) for d in ["Monday", "Tuesday"]],
        )
        assert len(metrics.peak_hours) == 24
        assert metrics.peak_hours[0].hour == 0


# ---- DriverMetrics Schema Tests ----


class TestTopDriverEntry:
    def test_basic(self):
        entry = TopDriverEntry(
            driver_id=42,
            driver_name="Alice Smith",
            total_trips=350,
            rating_avg=4.92,
            completed_in_period=45,
        )
        assert entry.driver_id == 42
        assert entry.driver_name == "Alice Smith"
        assert entry.total_trips == 350
        assert entry.rating_avg == 4.92
        assert entry.completed_in_period == 45

    def test_without_name(self):
        entry = TopDriverEntry(
            driver_id=1,
            total_trips=10,
            rating_avg=4.0,
            completed_in_period=3,
        )
        assert entry.driver_name is None

    def test_new_driver(self):
        entry = TopDriverEntry(
            driver_id=99,
            driver_name="New Driver",
            total_trips=1,
            rating_avg=5.0,
            completed_in_period=1,
        )
        assert entry.total_trips == 1


class TestDriverMetrics:
    def test_full_driver_metrics(self):
        metrics = DriverMetrics(
            period="month",
            total_drivers=200,
            approved_drivers=180,
            online_now=45,
            avg_rating=4.65,
            avg_trips_per_driver=75.3,
            rides_per_active_driver=12.5,
            top_drivers=[
                TopDriverEntry(
                    driver_id=1,
                    driver_name="Top Driver",
                    total_trips=500,
                    rating_avg=4.95,
                    completed_in_period=60,
                ),
            ],
            rating_distribution={"1-2": 2, "2-3": 5, "3-4": 15, "4-4.5": 80, "4.5-5": 78},
        )
        assert metrics.total_drivers == 200
        assert metrics.approved_drivers == 180
        assert metrics.online_now == 45
        assert metrics.avg_rating == 4.65
        assert metrics.avg_trips_per_driver == 75.3
        assert metrics.rides_per_active_driver == 12.5
        assert len(metrics.top_drivers) == 1
        assert metrics.top_drivers[0].driver_name == "Top Driver"
        assert len(metrics.rating_distribution) == 5

    def test_no_drivers(self):
        metrics = DriverMetrics(
            period="week",
            total_drivers=0,
            approved_drivers=0,
            online_now=0,
            avg_rating=None,
            avg_trips_per_driver=None,
            rides_per_active_driver=None,
            top_drivers=[],
            rating_distribution={},
        )
        assert metrics.total_drivers == 0
        assert metrics.avg_rating is None
        assert metrics.avg_trips_per_driver is None
        assert metrics.rides_per_active_driver is None
        assert metrics.top_drivers == []

    def test_all_drivers_online(self):
        metrics = DriverMetrics(
            period="month",
            total_drivers=10,
            approved_drivers=10,
            online_now=10,
            avg_rating=4.5,
            avg_trips_per_driver=50.0,
            rides_per_active_driver=8.0,
            top_drivers=[],
            rating_distribution={"4.5-5": 10},
        )
        assert metrics.online_now == metrics.total_drivers

    def test_multiple_top_drivers(self):
        top = [
            TopDriverEntry(
                driver_id=i,
                driver_name=f"Driver {i}",
                total_trips=100 + i * 10,
                rating_avg=4.5 + i * 0.05,
                completed_in_period=20 + i,
            )
            for i in range(10)
        ]
        metrics = DriverMetrics(
            period="year",
            total_drivers=500,
            approved_drivers=450,
            online_now=100,
            avg_rating=4.3,
            avg_trips_per_driver=120.0,
            rides_per_active_driver=15.0,
            top_drivers=top,
            rating_distribution={"3-4": 50, "4-4.5": 200, "4.5-5": 200},
        )
        assert len(metrics.top_drivers) == 10
        assert metrics.top_drivers[0].driver_id == 0
        assert metrics.top_drivers[9].driver_id == 9

    def test_unapproved_drivers_excluded_from_ratio(self):
        """Verify schema supports approved != total scenario."""
        metrics = DriverMetrics(
            period="month",
            total_drivers=100,
            approved_drivers=60,
            online_now=20,
            avg_rating=4.2,
            avg_trips_per_driver=30.0,
            rides_per_active_driver=5.0,
            top_drivers=[],
            rating_distribution={"4-4.5": 40, "4.5-5": 20},
        )
        assert metrics.approved_drivers < metrics.total_drivers
