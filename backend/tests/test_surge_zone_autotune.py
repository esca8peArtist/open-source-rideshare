"""Tests for surge zone auto-tuning service and endpoints.

Covers:
- _get_active_hours: same-day, overnight, degenerate windows
- _recommend_multiplier: all demand_ratio branches (very high, high, low, normal)
- _clamp_multiplier: floor and ceiling enforcement
- compute_auto_tune_recommendations: no zones, single zone, multiple zones,
    insufficient data, no platform data, increase / decrease / no_change actions
- apply_auto_tune_recommendations: apply all, apply subset, skip no_change,
    skip insufficient_data, zone not found at apply time
- AutoTune endpoint schemas: preview response, apply request, apply response
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, time, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.schemas.surge_zone_autotune import (
    AutoTuneAction,
    AutoTuneApplyDetail,
    AutoTuneApplyRequest,
    AutoTuneApplyResponse,
    AutoTunePreviewResponse,
    SurgeZoneRecommendation,
)
from app.services.surge_zone_autotune import (
    _clamp_multiplier,
    _get_active_hours,
    _recommend_multiplier,
    compute_auto_tune_recommendations,
    apply_auto_tune_recommendations,
)


# ===========================================================================
# Fixtures / helpers
# ===========================================================================


def _make_zone(**kwargs):
    """Build a minimal mock SurgePricingZone."""
    z = MagicMock()
    z.id = kwargs.get("id", uuid.uuid4())
    z.name = kwargs.get("name", "Test Zone")
    z.multiplier = kwargs.get("multiplier", 1.5)
    z.is_active = kwargs.get("is_active", True)
    z.start_time = kwargs.get("start_time", None)
    z.end_time = kwargs.get("end_time", None)
    z.days_of_week = kwargs.get("days_of_week", None)
    z.polygon = kwargs.get("polygon", None)
    z.center_lat = kwargs.get("center_lat", None)
    z.center_lon = kwargs.get("center_lon", None)
    z.radius_km = kwargs.get("radius_km", None)
    z.description = kwargs.get("description", None)
    z.created_at = kwargs.get("created_at", datetime.now(timezone.utc))
    z.updated_at = kwargs.get("updated_at", datetime.now(timezone.utc))
    return z


def _make_demand_response(
    rides_per_hour: dict[int, int] | None = None,
) -> MagicMock:
    """Build a mock DemandByHourResponse.

    Args:
        rides_per_hour: mapping of hour → ride_count.
            Missing hours default to 0. Defaults to uniform 10 rides/hr.
    """
    from app.schemas.demand_heatmap import DemandByHourResponse, DemandHourSlot

    if rides_per_hour is None:
        rides_per_hour = {h: 10 for h in range(24)}

    slots = []
    for h in range(24):
        count = rides_per_hour.get(h, 0)
        slots.append(
            DemandHourSlot(
                hour=h,
                hour_label=f"{h:02d}:00",
                total_rides=count,
                completed_rides=count,
                cancelled_rides=0,
                avg_fare=None,
                avg_wait_minutes=None,
            )
        )
    total = sum(s.total_rides for s in slots)
    from app.schemas.demand_heatmap import DemandByHourFilters
    return DemandByHourResponse(
        slots=slots,
        total_rides=total,
        peak_hour=max(slots, key=lambda s: s.total_rides).hour if total > 0 else None,
        generated_at=datetime.now(timezone.utc),
        filters=DemandByHourFilters(start_date=None, end_date=None, day_of_week=None),
    )


# ===========================================================================
# _get_active_hours
# ===========================================================================


class TestGetActiveHours:
    def test_same_day_window(self):
        result = _get_active_hours(time(8, 0), time(10, 0))
        assert result == [8, 9]

    def test_single_hour_window(self):
        result = _get_active_hours(time(17, 0), time(18, 0))
        assert result == [17]

    def test_overnight_window(self):
        result = _get_active_hours(time(22, 0), time(6, 0))
        assert result == [22, 23, 0, 1, 2, 3, 4, 5]

    def test_overnight_starts_at_23(self):
        result = _get_active_hours(time(23, 0), time(2, 0))
        assert result == [23, 0, 1]

    def test_degenerate_same_start_end(self):
        # start == end is ambiguous; returns empty
        result = _get_active_hours(time(12, 0), time(12, 0))
        assert result == []

    def test_morning_rush(self):
        result = _get_active_hours(time(7, 0), time(9, 0))
        assert result == [7, 8]

    def test_returns_list_of_ints(self):
        result = _get_active_hours(time(0, 0), time(3, 0))
        assert all(isinstance(h, int) for h in result)

    def test_full_day_equivalent_not_returned(self):
        # 00:00 – 24:00 can't be expressed with time; 23:00 – 23:00 is degenerate
        result = _get_active_hours(time(23, 0), time(23, 0))
        assert result == []


# ===========================================================================
# _clamp_multiplier
# ===========================================================================


class TestClampMultiplier:
    def test_clamps_below_minimum(self):
        assert _clamp_multiplier(0.5) == 1.0

    def test_clamps_above_maximum(self):
        assert _clamp_multiplier(15.0) == 10.0

    def test_passes_through_valid(self):
        assert _clamp_multiplier(2.5) == 2.5

    def test_rounds_to_two_decimal_places(self):
        assert _clamp_multiplier(1.999999) == 2.0

    def test_minimum_boundary(self):
        assert _clamp_multiplier(1.0) == 1.0

    def test_maximum_boundary(self):
        assert _clamp_multiplier(10.0) == 10.0


# ===========================================================================
# _recommend_multiplier
# ===========================================================================


class TestRecommendMultiplier:
    def test_very_high_demand_increases_large(self):
        new, action = _recommend_multiplier(1.5, demand_ratio=2.5)
        assert action == AutoTuneAction.increase
        assert new == 1.7  # 1.5 + 0.20

    def test_high_demand_increases_small(self):
        new, action = _recommend_multiplier(1.5, demand_ratio=1.6)
        assert action == AutoTuneAction.increase
        assert new == 1.6  # 1.5 + 0.10

    def test_low_demand_decreases(self):
        new, action = _recommend_multiplier(1.5, demand_ratio=0.4)
        assert action == AutoTuneAction.decrease
        assert new == 1.4  # 1.5 - 0.10

    def test_normal_demand_no_change(self):
        new, action = _recommend_multiplier(1.5, demand_ratio=1.0)
        assert action == AutoTuneAction.no_change
        assert new == 1.5

    def test_exactly_at_ratio_thresholds_high(self):
        # ratio == 1.5 triggers small increase
        new, action = _recommend_multiplier(1.5, demand_ratio=1.5)
        assert action == AutoTuneAction.increase

    def test_exactly_at_ratio_thresholds_very_high(self):
        # ratio == 2.0 triggers large increase
        new, action = _recommend_multiplier(1.5, demand_ratio=2.0)
        assert action == AutoTuneAction.increase
        assert new == 1.7

    def test_exactly_at_ratio_threshold_low(self):
        # ratio == 0.5 triggers decrease
        new, action = _recommend_multiplier(1.5, demand_ratio=0.5)
        assert action == AutoTuneAction.decrease

    def test_clamped_at_maximum(self):
        # Already at max — can't increase
        new, action = _recommend_multiplier(10.0, demand_ratio=3.0)
        assert new == 10.0
        assert action == AutoTuneAction.no_change  # capped, no effective change

    def test_clamped_at_minimum(self):
        # Already at min — can't decrease
        new, action = _recommend_multiplier(1.0, demand_ratio=0.3)
        assert new == 1.0
        assert action == AutoTuneAction.no_change  # capped, no effective change

    def test_result_type(self):
        new, action = _recommend_multiplier(1.5, demand_ratio=1.0)
        assert isinstance(new, float)
        assert isinstance(action, AutoTuneAction)


# ===========================================================================
# compute_auto_tune_recommendations
# ===========================================================================


class TestComputeAutoTuneRecommendations:
    """Unit tests using fully mocked DB and service dependencies."""

    def _make_db(self, zones, demand_response):
        """Build an AsyncSession mock that returns the given zones and demand."""
        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = zones
        db.execute = AsyncMock(return_value=mock_result)
        return db

    @pytest.mark.asyncio
    async def test_no_active_zones(self):
        db = self._make_db([], _make_demand_response())
        with patch(
            "app.services.surge_zone_autotune.list_zones", new=AsyncMock(return_value=[])
        ), patch(
            "app.services.surge_zone_autotune.get_demand_by_hour",
            new=AsyncMock(return_value=_make_demand_response()),
        ):
            result = await compute_auto_tune_recommendations(db)

        assert result.total_zones == 0
        assert result.recommendations == []
        assert result.zones_to_increase == 0
        assert result.zones_to_decrease == 0

    @pytest.mark.asyncio
    async def test_zone_with_high_demand_window(self):
        """Zone active 7:00-9:00 with high demand → increase recommendation."""
        zone = _make_zone(
            multiplier=1.5,
            start_time=time(7, 0),
            end_time=time(9, 0),
        )
        # Hours 7 and 8 have very high demand (50 rides/hr vs. platform avg ~10)
        rides = {h: 10 for h in range(24)}
        rides[7] = 50
        rides[8] = 50

        demand = _make_demand_response(rides)
        with patch(
            "app.services.surge_zone_autotune.list_zones", new=AsyncMock(return_value=[zone])
        ), patch(
            "app.services.surge_zone_autotune.get_demand_by_hour",
            new=AsyncMock(return_value=demand),
        ):
            result = await compute_auto_tune_recommendations(db=AsyncMock(), min_sample_size=1)

        assert result.total_zones == 1
        rec = result.recommendations[0]
        assert rec.action == AutoTuneAction.increase
        assert rec.recommended_multiplier > rec.current_multiplier
        assert result.zones_to_increase == 1

    @pytest.mark.asyncio
    async def test_zone_with_low_demand_window(self):
        """Zone active overnight (1:00-4:00) with low demand → decrease."""
        zone = _make_zone(
            multiplier=2.0,
            start_time=time(1, 0),
            end_time=time(4, 0),
        )
        rides = {h: 20 for h in range(24)}
        rides[1] = 2
        rides[2] = 2
        rides[3] = 2

        demand = _make_demand_response(rides)
        with patch(
            "app.services.surge_zone_autotune.list_zones", new=AsyncMock(return_value=[zone])
        ), patch(
            "app.services.surge_zone_autotune.get_demand_by_hour",
            new=AsyncMock(return_value=demand),
        ):
            result = await compute_auto_tune_recommendations(db=AsyncMock(), min_sample_size=1)

        rec = result.recommendations[0]
        assert rec.action == AutoTuneAction.decrease
        assert rec.recommended_multiplier < rec.current_multiplier
        assert result.zones_to_decrease == 1

    @pytest.mark.asyncio
    async def test_insufficient_data(self):
        """Zone with very low ride count → insufficient_data."""
        zone = _make_zone(multiplier=1.5, start_time=time(8, 0), end_time=time(10, 0))
        rides = {h: 0 for h in range(24)}  # No rides at all

        with patch(
            "app.services.surge_zone_autotune.list_zones", new=AsyncMock(return_value=[zone])
        ), patch(
            "app.services.surge_zone_autotune.get_demand_by_hour",
            new=AsyncMock(return_value=_make_demand_response(rides)),
        ):
            result = await compute_auto_tune_recommendations(db=AsyncMock(), min_sample_size=10)

        rec = result.recommendations[0]
        assert rec.action == AutoTuneAction.insufficient_data
        assert rec.recommended_multiplier == rec.current_multiplier
        assert result.zones_insufficient_data == 1

    @pytest.mark.asyncio
    async def test_no_platform_data(self):
        """When platform has zero rides, zones get no_change."""
        zone = _make_zone(multiplier=1.5)
        rides = {h: 0 for h in range(24)}

        with patch(
            "app.services.surge_zone_autotune.list_zones", new=AsyncMock(return_value=[zone])
        ), patch(
            "app.services.surge_zone_autotune.get_demand_by_hour",
            new=AsyncMock(return_value=_make_demand_response(rides)),
        ):
            result = await compute_auto_tune_recommendations(db=AsyncMock(), min_sample_size=0)

        rec = result.recommendations[0]
        assert rec.action == AutoTuneAction.no_change
        assert rec.platform_avg_rides == 0.0

    @pytest.mark.asyncio
    async def test_zone_no_time_window_uses_all_hours(self):
        """Zone with no start/end time uses all 24 hours for demand ratio."""
        zone = _make_zone(multiplier=1.5, start_time=None, end_time=None)
        # Uniform demand → ratio == 1.0 → no_change
        with patch(
            "app.services.surge_zone_autotune.list_zones", new=AsyncMock(return_value=[zone])
        ), patch(
            "app.services.surge_zone_autotune.get_demand_by_hour",
            new=AsyncMock(return_value=_make_demand_response()),
        ):
            result = await compute_auto_tune_recommendations(db=AsyncMock(), min_sample_size=1)

        rec = result.recommendations[0]
        # All 24 hours are in scope; uniform demand → demand_ratio == 1.0
        assert rec.demand_ratio is not None
        assert abs(rec.demand_ratio - 1.0) < 0.01
        assert rec.action == AutoTuneAction.no_change

    @pytest.mark.asyncio
    async def test_multiple_zones_mixed_actions(self):
        """Multiple zones can independently get different recommendations."""
        zone_high = _make_zone(name="High Demand", multiplier=1.5, start_time=time(7, 0), end_time=time(9, 0))
        zone_low = _make_zone(name="Low Demand", multiplier=2.0, start_time=time(2, 0), end_time=time(4, 0))

        rides = {h: 10 for h in range(24)}
        rides[7] = 50
        rides[8] = 50
        rides[2] = 1
        rides[3] = 1

        with patch(
            "app.services.surge_zone_autotune.list_zones",
            new=AsyncMock(return_value=[zone_high, zone_low]),
        ), patch(
            "app.services.surge_zone_autotune.get_demand_by_hour",
            new=AsyncMock(return_value=_make_demand_response(rides)),
        ):
            result = await compute_auto_tune_recommendations(db=AsyncMock(), min_sample_size=1)

        assert result.total_zones == 2
        actions = {r.zone_name: r.action for r in result.recommendations}
        assert actions["High Demand"] == AutoTuneAction.increase
        assert actions["Low Demand"] == AutoTuneAction.decrease

    @pytest.mark.asyncio
    async def test_lookback_days_parameter_passed_through(self):
        """lookback_days configures the date range passed to get_demand_by_hour."""
        zone = _make_zone()
        captured = {}

        async def fake_demand(db, start_date=None, end_date=None, day_of_week=None):
            captured["start_date"] = start_date
            captured["end_date"] = end_date
            return _make_demand_response()

        with patch(
            "app.services.surge_zone_autotune.list_zones", new=AsyncMock(return_value=[zone])
        ), patch(
            "app.services.surge_zone_autotune.get_demand_by_hour", new=fake_demand
        ):
            await compute_auto_tune_recommendations(db=AsyncMock(), lookback_days=7, min_sample_size=0)

        from datetime import timedelta
        expected_start = date.today() - timedelta(days=7)
        assert captured["start_date"] == expected_start

    @pytest.mark.asyncio
    async def test_recommendation_fields_present(self):
        zone = _make_zone(multiplier=1.5)
        with patch(
            "app.services.surge_zone_autotune.list_zones", new=AsyncMock(return_value=[zone])
        ), patch(
            "app.services.surge_zone_autotune.get_demand_by_hour",
            new=AsyncMock(return_value=_make_demand_response()),
        ):
            result = await compute_auto_tune_recommendations(db=AsyncMock(), min_sample_size=0)

        rec = result.recommendations[0]
        assert rec.zone_id == zone.id
        assert rec.zone_name == zone.name
        assert isinstance(rec.current_multiplier, float)
        assert isinstance(rec.recommended_multiplier, float)
        assert isinstance(rec.recommendation_reason, str)
        assert isinstance(rec.data_points, int)

    @pytest.mark.asyncio
    async def test_degenerate_time_window_falls_back_to_all_hours(self):
        """Zone with start_time == end_time uses all 24 hours."""
        zone = _make_zone(
            multiplier=1.5,
            start_time=time(12, 0),
            end_time=time(12, 0),  # degenerate
        )
        with patch(
            "app.services.surge_zone_autotune.list_zones", new=AsyncMock(return_value=[zone])
        ), patch(
            "app.services.surge_zone_autotune.get_demand_by_hour",
            new=AsyncMock(return_value=_make_demand_response()),
        ):
            result = await compute_auto_tune_recommendations(db=AsyncMock(), min_sample_size=0)

        rec = result.recommendations[0]
        # All 24 hours used → uniform demand → ratio ~1.0 → no_change
        assert rec.action == AutoTuneAction.no_change


# ===========================================================================
# apply_auto_tune_recommendations
# ===========================================================================


class TestApplyAutoTuneRecommendations:
    @pytest.mark.asyncio
    async def test_applies_increase_recommendation(self):
        zone_id = uuid.uuid4()
        zone = _make_zone(id=zone_id, name="Rush Zone", multiplier=1.5, start_time=time(7, 0), end_time=time(9, 0))

        rides = {h: 10 for h in range(24)}
        rides[7] = 60
        rides[8] = 60

        async def fake_update(db, z_id, **kwargs):
            updated = MagicMock()
            updated.id = z_id
            updated.name = zone.name
            updated.multiplier = kwargs.get("multiplier", zone.multiplier)
            return updated

        with patch(
            "app.services.surge_zone_autotune.list_zones", new=AsyncMock(return_value=[zone])
        ), patch(
            "app.services.surge_zone_autotune.get_demand_by_hour",
            new=AsyncMock(return_value=_make_demand_response(rides)),
        ), patch(
            "app.services.surge_zone_autotune.update_zone", new=fake_update
        ):
            result = await apply_auto_tune_recommendations(
                db=AsyncMock(), min_sample_size=1
            )

        assert result.applied == 1
        assert result.skipped == 0
        detail = result.details[0]
        assert detail.applied is True
        assert detail.new_multiplier > detail.old_multiplier

    @pytest.mark.asyncio
    async def test_skips_no_change_recommendation(self):
        """Zone with demand_ratio ~1.0 produces no_change — apply skips it."""
        zone = _make_zone(multiplier=1.5)

        with patch(
            "app.services.surge_zone_autotune.list_zones", new=AsyncMock(return_value=[zone])
        ), patch(
            "app.services.surge_zone_autotune.get_demand_by_hour",
            new=AsyncMock(return_value=_make_demand_response()),
        ), patch(
            "app.services.surge_zone_autotune.update_zone", new=AsyncMock()
        ):
            result = await apply_auto_tune_recommendations(db=AsyncMock(), min_sample_size=1)

        assert result.applied == 0
        assert result.skipped == 1
        detail = result.details[0]
        assert detail.applied is False

    @pytest.mark.asyncio
    async def test_zone_id_filter_excludes_unspecified(self):
        """When zone_ids is provided, only those zones are applied."""
        zone_a = _make_zone(name="Zone A", multiplier=1.5, start_time=time(7, 0), end_time=time(9, 0))
        zone_b = _make_zone(name="Zone B", multiplier=1.5, start_time=time(7, 0), end_time=time(9, 0))

        rides = {h: 10 for h in range(24)}
        rides[7] = 60
        rides[8] = 60

        async def fake_update(db, z_id, **kwargs):
            updated = MagicMock()
            updated.id = z_id
            updated.multiplier = kwargs.get("multiplier", 1.5)
            return updated

        with patch(
            "app.services.surge_zone_autotune.list_zones",
            new=AsyncMock(return_value=[zone_a, zone_b]),
        ), patch(
            "app.services.surge_zone_autotune.get_demand_by_hour",
            new=AsyncMock(return_value=_make_demand_response(rides)),
        ), patch(
            "app.services.surge_zone_autotune.update_zone", new=fake_update
        ):
            # Only apply zone_a
            result = await apply_auto_tune_recommendations(
                db=AsyncMock(),
                zone_ids=[zone_a.id],
                min_sample_size=1,
            )

        assert result.applied == 1
        assert result.skipped == 1
        applied_names = {d.zone_name for d in result.details if d.applied}
        assert "Zone A" in applied_names
        assert "Zone B" not in applied_names

    @pytest.mark.asyncio
    async def test_zone_disappeared_at_apply_time(self):
        """If update_zone returns None, the detail shows applied=False."""
        zone = _make_zone(multiplier=1.5, start_time=time(7, 0), end_time=time(9, 0))

        rides = {h: 10 for h in range(24)}
        rides[7] = 60
        rides[8] = 60

        with patch(
            "app.services.surge_zone_autotune.list_zones", new=AsyncMock(return_value=[zone])
        ), patch(
            "app.services.surge_zone_autotune.get_demand_by_hour",
            new=AsyncMock(return_value=_make_demand_response(rides)),
        ), patch(
            "app.services.surge_zone_autotune.update_zone", new=AsyncMock(return_value=None)
        ):
            result = await apply_auto_tune_recommendations(db=AsyncMock(), min_sample_size=1)

        assert result.applied == 0
        assert result.skipped == 1
        detail = result.details[0]
        assert detail.applied is False
        assert "not found" in detail.skip_reason.lower()

    @pytest.mark.asyncio
    async def test_apply_response_has_generated_at(self):
        zone = _make_zone(multiplier=1.5)
        with patch(
            "app.services.surge_zone_autotune.list_zones", new=AsyncMock(return_value=[zone])
        ), patch(
            "app.services.surge_zone_autotune.get_demand_by_hour",
            new=AsyncMock(return_value=_make_demand_response()),
        ):
            result = await apply_auto_tune_recommendations(db=AsyncMock(), min_sample_size=1)

        assert isinstance(result.generated_at, datetime)


# ===========================================================================
# Schema tests
# ===========================================================================


class TestAutoTuneSchemas:
    def test_recommendation_schema(self):
        zone_id = uuid.uuid4()
        rec = SurgeZoneRecommendation(
            zone_id=zone_id,
            zone_name="Test",
            current_multiplier=1.5,
            recommended_multiplier=1.7,
            action=AutoTuneAction.increase,
            demand_ratio=2.1,
            zone_window_avg_rides=21.0,
            platform_avg_rides=10.0,
            recommendation_reason="Elevated demand.",
            data_points=42,
        )
        assert rec.zone_id == zone_id
        assert rec.action == AutoTuneAction.increase
        d = rec.model_dump()
        assert "zone_id" in d
        assert "recommended_multiplier" in d

    def test_preview_response_schema(self):
        resp = AutoTunePreviewResponse(
            recommendations=[],
            total_zones=0,
            zones_to_increase=0,
            zones_to_decrease=0,
            zones_no_change=0,
            zones_insufficient_data=0,
            generated_at=datetime.now(timezone.utc),
            lookback_days=30,
            min_sample_size=10,
        )
        assert resp.total_zones == 0
        assert resp.lookback_days == 30

    def test_apply_request_defaults(self):
        req = AutoTuneApplyRequest()
        assert req.zone_ids is None

    def test_apply_request_with_ids(self):
        ids = [uuid.uuid4(), uuid.uuid4()]
        req = AutoTuneApplyRequest(zone_ids=ids)
        assert len(req.zone_ids) == 2

    def test_apply_response_schema(self):
        resp = AutoTuneApplyResponse(
            applied=2,
            skipped=1,
            details=[
                AutoTuneApplyDetail(
                    zone_id=uuid.uuid4(),
                    zone_name="Z",
                    action=AutoTuneAction.increase,
                    old_multiplier=1.5,
                    new_multiplier=1.7,
                    applied=True,
                )
            ],
            generated_at=datetime.now(timezone.utc),
        )
        assert resp.applied == 2
        assert resp.skipped == 1
        assert len(resp.details) == 1

    def test_action_enum_values(self):
        assert AutoTuneAction.increase == "increase"
        assert AutoTuneAction.decrease == "decrease"
        assert AutoTuneAction.no_change == "no_change"
        assert AutoTuneAction.insufficient_data == "insufficient_data"

    def test_apply_detail_skip_reason_optional(self):
        detail = AutoTuneApplyDetail(
            zone_id=uuid.uuid4(),
            zone_name="Z",
            action=AutoTuneAction.increase,
            old_multiplier=1.5,
            new_multiplier=1.7,
            applied=True,
        )
        assert detail.skip_reason is None


# ===========================================================================
# Endpoint integration (mocked DB)
# ===========================================================================


class TestAutoTuneEndpoints:
    @pytest.mark.asyncio
    async def test_preview_endpoint_returns_preview_response(self):
        from app.api.v1.surge_zones import preview_auto_tune

        expected = AutoTunePreviewResponse(
            recommendations=[],
            total_zones=0,
            zones_to_increase=0,
            zones_to_decrease=0,
            zones_no_change=0,
            zones_insufficient_data=0,
            generated_at=datetime.now(timezone.utc),
            lookback_days=30,
            min_sample_size=10,
        )
        with patch(
            "app.api.v1.surge_zones.compute_auto_tune_recommendations",
            new=AsyncMock(return_value=expected),
        ):
            result = await preview_auto_tune(db=AsyncMock())

        assert result.total_zones == 0
        assert result.lookback_days == 30

    @pytest.mark.asyncio
    async def test_apply_endpoint_returns_apply_response(self):
        from app.api.v1.surge_zones import apply_auto_tune

        expected = AutoTuneApplyResponse(
            applied=1,
            skipped=0,
            details=[],
            generated_at=datetime.now(timezone.utc),
        )
        with patch(
            "app.api.v1.surge_zones.apply_auto_tune_recommendations",
            new=AsyncMock(return_value=expected),
        ):
            body = AutoTuneApplyRequest(zone_ids=None)
            result = await apply_auto_tune(body=body, db=AsyncMock())

        assert result.applied == 1

    @pytest.mark.asyncio
    async def test_preview_passes_lookback_and_sample_params(self):
        from app.api.v1.surge_zones import preview_auto_tune

        captured = {}

        async def fake_compute(db, lookback_days=30, min_sample_size=10):
            captured["lookback_days"] = lookback_days
            captured["min_sample_size"] = min_sample_size
            return AutoTunePreviewResponse(
                recommendations=[],
                total_zones=0,
                zones_to_increase=0,
                zones_to_decrease=0,
                zones_no_change=0,
                zones_insufficient_data=0,
                generated_at=datetime.now(timezone.utc),
                lookback_days=lookback_days,
                min_sample_size=min_sample_size,
            )

        with patch("app.api.v1.surge_zones.compute_auto_tune_recommendations", new=fake_compute):
            await preview_auto_tune(lookback_days=14, min_sample_size=5, db=AsyncMock())

        assert captured["lookback_days"] == 14
        assert captured["min_sample_size"] == 5

    @pytest.mark.asyncio
    async def test_apply_passes_zone_ids(self):
        from app.api.v1.surge_zones import apply_auto_tune

        zone_id = uuid.uuid4()
        captured = {}

        async def fake_apply(db, zone_ids=None, lookback_days=30, min_sample_size=10):
            captured["zone_ids"] = zone_ids
            return AutoTuneApplyResponse(
                applied=0, skipped=0, details=[], generated_at=datetime.now(timezone.utc)
            )

        with patch("app.api.v1.surge_zones.apply_auto_tune_recommendations", new=fake_apply):
            body = AutoTuneApplyRequest(zone_ids=[zone_id])
            await apply_auto_tune(body=body, db=AsyncMock())

        assert captured["zone_ids"] == [zone_id]
