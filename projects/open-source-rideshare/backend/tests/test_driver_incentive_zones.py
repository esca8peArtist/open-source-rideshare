"""Tests for the Driver Incentive Zone feature.

Geography helpers (pure):
  1.  _haversine_km — zero distance for identical points
  2.  _haversine_km — approximate distance between two real coordinates
  3.  _ray_cast_in_polygon — point inside a simple square
  4.  _ray_cast_in_polygon — point outside a simple square
  5.  check_ride_qualifies — inactive zone returns False
  6.  check_ride_qualifies — ride outside time window returns False
  7.  check_ride_qualifies — ride inside circle zone returns True
  8.  check_ride_qualifies — ride outside circle returns False
  9.  check_ride_qualifies — ride inside polygon zone returns True
  10. check_ride_qualifies — ride outside polygon returns False

Service layer (async, mocked DB):
  11. create_zone — inserts zone and returns it
  12. update_zone — applies partial update
  13. update_zone — raises 404 when zone not found
  14. deactivate_zone — sets is_active=False
  15. deactivate_zone — raises 404 when zone not found
  16. deactivate_zone — raises 409 when already inactive
  17. get_zone — returns None when not found
  18. get_zone — returns zone when found
  19. get_active_zones — returns list of active zones
  20. get_all_zones — returns paginated list
  21. record_zone_completion — creates new completion record
  22. record_zone_completion — idempotent on duplicate (zone_id, ride_id)
  23. record_zone_completion — raises 404 when zone not found
  24. record_zone_completion — raises 409 when total cap reached
  25. record_zone_completion — raises 409 when driver cap reached
  26. get_driver_completions — returns driver bonus history
  27. get_driver_zone_summary — zero totals for driver with no completions
  28. get_driver_zone_summary — aggregates bonus totals correctly
  29. get_zone_stats — raises 404 when zone not found
  30. get_zone_stats — returns correct stats with completions

Schema validation:
  31. CreateIncentiveZoneRequest — rejects missing geography
  32. CreateIncentiveZoneRequest — rejects ends_at before starts_at
  33. CreateIncentiveZoneRequest — rejects multiplier type without bonus_multiplier
  34. CreateIncentiveZoneRequest — rejects flat type without bonus_flat_cents
  35. CreateIncentiveZoneRequest — accepts valid circle geometry
  36. CreateIncentiveZoneRequest — accepts valid polygon geometry
  37. IncentiveZoneResponse.from_zone — sets bonus_summary for multiplier type
  38. IncentiveZoneResponse.from_zone — sets bonus_summary for flat type
  39. ZoneCompletionResponse.from_completion — computes bonus_amount_dollars

API layer (integration-style, skipped without live DB):
  40. GET /incentive-zones — 200 list of active zones
  41. GET /incentive-zones/{id} — 404 when zone not found
  42. GET /incentive-zones/my/completions — 200 driver bonus history
  43. GET /incentive-zones/my/summary — 200 driver summary
  44. POST /incentive-zones/admin — 201 creates zone (admin)
  45. POST /incentive-zones/admin — 403 for non-admin
  46. GET /incentive-zones/admin/all — 200 all zones (admin)
  47. PUT /incentive-zones/admin/{id} — 200 updates zone
  48. POST /incentive-zones/admin/{id}/deactivate — 200 deactivates zone
  49. POST /incentive-zones/admin/{id}/deactivate — 409 already inactive
  50. POST /incentive-zones/admin/completions — 201 records completion
  51. GET /incentive-zones/admin/{id}/stats — 200 zone stats
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.driver_incentive_zone import (
    DriverIncentiveZone,
    DriverZoneCompletion,
    IncentiveBonusType,
)
from app.schemas.driver_incentive_zone import (
    CreateIncentiveZoneRequest,
    DriverZoneEarningsSummary,
    IncentiveZoneResponse,
    ZoneCompletionResponse,
    ZoneStatsResponse,
)
from app.services.driver_incentive_zone import (
    IncentiveZoneError,
    _haversine_km,
    _ray_cast_in_polygon,
    check_ride_qualifies,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 4, 15, 12, 0, 0, tzinfo=timezone.utc)
_FUTURE = _NOW + timedelta(hours=2)
_PAST = _NOW - timedelta(hours=2)
_ZONE_ID = uuid.uuid4()

SQUARE_POLYGON = [
    {"lat": 40.0, "lon": -74.0},
    {"lat": 40.0, "lon": -73.0},
    {"lat": 41.0, "lon": -73.0},
    {"lat": 41.0, "lon": -74.0},
]


def _make_zone(**kwargs) -> DriverIncentiveZone:
    defaults = dict(
        id=_ZONE_ID,
        name="Test Zone",
        description="Test",
        reason="High demand from concert at 8pm",
        polygon=None,
        center_lat=40.5,
        center_lon=-73.5,
        radius_km=5.0,
        bonus_type=IncentiveBonusType.multiplier,
        bonus_multiplier=1.5,
        bonus_flat_cents=None,
        starts_at=_PAST,
        ends_at=_FUTURE,
        max_total_completions=None,
        max_completions_per_driver=None,
        min_driver_rating=None,
        is_active=True,
        created_at=_NOW,
        updated_at=_NOW,
    )
    defaults.update(kwargs)
    obj = MagicMock(spec=DriverIncentiveZone)
    for k, v in defaults.items():
        setattr(obj, k, v)
    return obj


def _make_completion(**kwargs) -> DriverZoneCompletion:
    defaults = dict(
        id=1,
        zone_id=_ZONE_ID,
        driver_profile_id=10,
        ride_id=42,
        bonus_amount_cents=300,
        bonus_type=IncentiveBonusType.multiplier,
        completed_at=_NOW,
    )
    defaults.update(kwargs)
    obj = MagicMock(spec=DriverZoneCompletion)
    for k, v in defaults.items():
        setattr(obj, k, v)
    return obj


# ---------------------------------------------------------------------------
# 1–4 _haversine_km and _ray_cast_in_polygon (pure)
# ---------------------------------------------------------------------------


def test_haversine_zero_distance():
    assert _haversine_km(40.0, -74.0, 40.0, -74.0) == pytest.approx(0.0, abs=0.001)


def test_haversine_known_distance():
    # NYC (40.7128, -74.0060) to Newark (40.7357, -74.1724) ≈ 14 km
    dist = _haversine_km(40.7128, -74.0060, 40.7357, -74.1724)
    assert 12.0 < dist < 17.0


def test_ray_cast_point_inside_square():
    assert _ray_cast_in_polygon(40.5, -73.5, SQUARE_POLYGON) is True


def test_ray_cast_point_outside_square():
    assert _ray_cast_in_polygon(42.0, -73.5, SQUARE_POLYGON) is False


# ---------------------------------------------------------------------------
# 5–10 check_ride_qualifies (pure)
# ---------------------------------------------------------------------------


def test_qualifies_inactive_zone_returns_false():
    zone = _make_zone(is_active=False)
    assert check_ride_qualifies(zone, 40.5, -73.5, _NOW) is False


def test_qualifies_outside_time_window_returns_false():
    # Ride completed before zone starts
    zone = _make_zone(starts_at=_NOW + timedelta(hours=1))
    assert check_ride_qualifies(zone, 40.5, -73.5, _NOW) is False


def test_qualifies_inside_circle_returns_true():
    zone = _make_zone(center_lat=40.5, center_lon=-73.5, radius_km=5.0, polygon=None)
    # Same coords as center — 0 km away — always qualifies
    assert check_ride_qualifies(zone, 40.5, -73.5, _NOW) is True


def test_qualifies_outside_circle_returns_false():
    zone = _make_zone(center_lat=40.5, center_lon=-73.5, radius_km=1.0, polygon=None)
    # Very far away
    assert check_ride_qualifies(zone, 51.5, 0.0, _NOW) is False


def test_qualifies_inside_polygon_returns_true():
    zone = _make_zone(polygon=SQUARE_POLYGON, center_lat=None, center_lon=None, radius_km=None)
    assert check_ride_qualifies(zone, 40.5, -73.5, _NOW) is True


def test_qualifies_outside_polygon_returns_false():
    zone = _make_zone(polygon=SQUARE_POLYGON, center_lat=None, center_lon=None, radius_km=None)
    assert check_ride_qualifies(zone, 42.0, -73.5, _NOW) is False


# ---------------------------------------------------------------------------
# 11–20 Service layer (async, mocked DB)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_zone_inserts_and_returns():
    db = AsyncMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()

    body = CreateIncentiveZoneRequest(
        name="Downtown Boost",
        reason="Pre-game surge demand at arena",
        center_lat=40.5,
        center_lon=-73.5,
        radius_km=3.0,
        bonus_type=IncentiveBonusType.multiplier,
        bonus_multiplier=1.5,
        starts_at=_NOW,
        ends_at=_FUTURE,
    )

    from app.services.driver_incentive_zone import create_zone

    await create_zone(db, body)

    db.add.assert_called_once()
    db.commit.assert_called_once()


@pytest.mark.asyncio
async def test_update_zone_applies_partial_update():
    from app.schemas.driver_incentive_zone import UpdateIncentiveZoneRequest
    from app.services.driver_incentive_zone import update_zone

    existing = _make_zone()
    db = AsyncMock()
    db.execute = AsyncMock(
        return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=existing))
    )
    db.commit = AsyncMock()
    db.refresh = AsyncMock()

    body = UpdateIncentiveZoneRequest(name="Updated Name")
    await update_zone(db, _ZONE_ID, body)

    assert existing.name == "Updated Name"
    db.commit.assert_called_once()


@pytest.mark.asyncio
async def test_update_zone_404_not_found():
    from app.schemas.driver_incentive_zone import UpdateIncentiveZoneRequest
    from app.services.driver_incentive_zone import update_zone

    db = AsyncMock()
    db.execute = AsyncMock(
        return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None))
    )

    with pytest.raises(IncentiveZoneError) as exc_info:
        await update_zone(db, _ZONE_ID, UpdateIncentiveZoneRequest(name="X"))
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_deactivate_zone_sets_inactive():
    from app.services.driver_incentive_zone import deactivate_zone

    zone = _make_zone(is_active=True)
    db = AsyncMock()
    db.execute = AsyncMock(
        return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=zone))
    )
    db.commit = AsyncMock()
    db.refresh = AsyncMock()

    await deactivate_zone(db, _ZONE_ID)
    assert zone.is_active is False


@pytest.mark.asyncio
async def test_deactivate_zone_404_not_found():
    from app.services.driver_incentive_zone import deactivate_zone

    db = AsyncMock()
    db.execute = AsyncMock(
        return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None))
    )

    with pytest.raises(IncentiveZoneError) as exc_info:
        await deactivate_zone(db, _ZONE_ID)
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_deactivate_zone_409_already_inactive():
    from app.services.driver_incentive_zone import deactivate_zone

    zone = _make_zone(is_active=False)
    db = AsyncMock()
    db.execute = AsyncMock(
        return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=zone))
    )

    with pytest.raises(IncentiveZoneError) as exc_info:
        await deactivate_zone(db, _ZONE_ID)
    assert exc_info.value.status_code == 409


@pytest.mark.asyncio
async def test_get_zone_returns_none():
    from app.services.driver_incentive_zone import get_zone

    db = AsyncMock()
    db.execute = AsyncMock(
        return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None))
    )
    result = await get_zone(db, _ZONE_ID)
    assert result is None


@pytest.mark.asyncio
async def test_get_zone_returns_zone():
    from app.services.driver_incentive_zone import get_zone

    zone = _make_zone()
    db = AsyncMock()
    db.execute = AsyncMock(
        return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=zone))
    )
    result = await get_zone(db, _ZONE_ID)
    assert result is zone


@pytest.mark.asyncio
async def test_get_active_zones_returns_list():
    from app.services.driver_incentive_zone import get_active_zones

    zone = _make_zone()
    mock_scalars = MagicMock()
    mock_scalars.all = MagicMock(return_value=[zone])
    db = AsyncMock()
    db.execute = AsyncMock(return_value=MagicMock(scalars=MagicMock(return_value=mock_scalars)))

    result = await get_active_zones(db)
    assert len(result) == 1
    assert result[0] is zone


@pytest.mark.asyncio
async def test_get_all_zones_returns_paginated():
    from app.services.driver_incentive_zone import get_all_zones

    zones = [_make_zone(), _make_zone()]
    mock_scalars = MagicMock()
    mock_scalars.all = MagicMock(return_value=zones)
    db = AsyncMock()
    db.execute = AsyncMock(return_value=MagicMock(scalars=MagicMock(return_value=mock_scalars)))

    result = await get_all_zones(db, skip=0, limit=10)
    assert len(result) == 2


# ---------------------------------------------------------------------------
# 21–25 record_zone_completion
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_record_zone_completion_creates_new():
    from app.services.driver_incentive_zone import record_zone_completion

    zone = _make_zone(max_total_completions=None, max_completions_per_driver=None)

    call_count = 0

    async def mock_execute(_):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            # zone lookup
            return MagicMock(scalar_one_or_none=MagicMock(return_value=zone))
        else:
            # idempotency check — no existing record
            return MagicMock(scalar_one_or_none=MagicMock(return_value=None))

    db = AsyncMock()
    db.execute = mock_execute
    db.commit = AsyncMock()
    db.refresh = AsyncMock()

    await record_zone_completion(db, _ZONE_ID, 10, 42, 300)
    db.add.assert_called_once()
    db.commit.assert_called_once()


@pytest.mark.asyncio
async def test_record_zone_completion_idempotent():
    from app.services.driver_incentive_zone import record_zone_completion

    zone = _make_zone()
    existing = _make_completion()

    call_count = 0

    async def mock_execute(_):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return MagicMock(scalar_one_or_none=MagicMock(return_value=zone))
        else:
            return MagicMock(scalar_one_or_none=MagicMock(return_value=existing))

    db = AsyncMock()
    db.execute = mock_execute

    result = await record_zone_completion(db, _ZONE_ID, 10, 42, 300)
    assert result is existing
    db.add.assert_not_called()


@pytest.mark.asyncio
async def test_record_zone_completion_404_zone_not_found():
    from app.services.driver_incentive_zone import record_zone_completion

    db = AsyncMock()
    db.execute = AsyncMock(
        return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None))
    )

    with pytest.raises(IncentiveZoneError) as exc_info:
        await record_zone_completion(db, _ZONE_ID, 10, 42, 300)
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_record_zone_completion_409_total_cap_reached():
    from app.services.driver_incentive_zone import record_zone_completion

    zone = _make_zone(max_total_completions=5, max_completions_per_driver=None)

    call_count = 0

    async def mock_execute(_):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            # zone lookup
            return MagicMock(scalar_one_or_none=MagicMock(return_value=zone))
        elif call_count == 2:
            # idempotency check — no existing
            return MagicMock(scalar_one_or_none=MagicMock(return_value=None))
        else:
            # total count — at cap
            return MagicMock(scalar_one=MagicMock(return_value=5))

    db = AsyncMock()
    db.execute = mock_execute

    with pytest.raises(IncentiveZoneError) as exc_info:
        await record_zone_completion(db, _ZONE_ID, 10, 42, 300)
    assert exc_info.value.status_code == 409


@pytest.mark.asyncio
async def test_record_zone_completion_409_driver_cap_reached():
    from app.services.driver_incentive_zone import record_zone_completion

    zone = _make_zone(max_total_completions=None, max_completions_per_driver=3)

    call_count = 0

    async def mock_execute(_):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            # zone lookup
            return MagicMock(scalar_one_or_none=MagicMock(return_value=zone))
        elif call_count == 2:
            # idempotency check — no existing
            return MagicMock(scalar_one_or_none=MagicMock(return_value=None))
        else:
            # driver count — at cap
            return MagicMock(scalar_one=MagicMock(return_value=3))

    db = AsyncMock()
    db.execute = mock_execute

    with pytest.raises(IncentiveZoneError) as exc_info:
        await record_zone_completion(db, _ZONE_ID, 10, 42, 300)
    assert exc_info.value.status_code == 409


# ---------------------------------------------------------------------------
# 26–28 Driver history and summary
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_driver_completions_returns_list():
    from app.services.driver_incentive_zone import get_driver_completions

    completions = [_make_completion(), _make_completion(id=2, ride_id=43)]
    mock_scalars = MagicMock()
    mock_scalars.all = MagicMock(return_value=completions)
    db = AsyncMock()
    db.execute = AsyncMock(return_value=MagicMock(scalars=MagicMock(return_value=mock_scalars)))

    result = await get_driver_completions(db, driver_profile_id=10)
    assert len(result) == 2


@pytest.mark.asyncio
async def test_get_driver_zone_summary_empty():
    from app.services.driver_incentive_zone import get_driver_zone_summary

    mock_scalars = MagicMock()
    mock_scalars.all = MagicMock(return_value=[])
    db = AsyncMock()
    db.execute = AsyncMock(return_value=MagicMock(scalars=MagicMock(return_value=mock_scalars)))

    summary = await get_driver_zone_summary(db, driver_profile_id=99)
    assert summary.total_completions == 0
    assert summary.total_bonus_cents == 0
    assert summary.total_bonus_dollars == 0.0
    assert summary.zones_participated == 0


@pytest.mark.asyncio
async def test_get_driver_zone_summary_aggregates():
    from app.services.driver_incentive_zone import get_driver_zone_summary

    zone_a = uuid.uuid4()
    zone_b = uuid.uuid4()
    completions = [
        _make_completion(zone_id=zone_a, bonus_amount_cents=300),
        _make_completion(id=2, ride_id=43, zone_id=zone_a, bonus_amount_cents=300),
        _make_completion(id=3, ride_id=44, zone_id=zone_b, bonus_amount_cents=500),
    ]
    mock_scalars = MagicMock()
    mock_scalars.all = MagicMock(return_value=completions)
    db = AsyncMock()
    db.execute = AsyncMock(return_value=MagicMock(scalars=MagicMock(return_value=mock_scalars)))

    summary = await get_driver_zone_summary(db, driver_profile_id=10)
    assert summary.total_completions == 3
    assert summary.total_bonus_cents == 1100
    assert summary.total_bonus_dollars == pytest.approx(11.0, abs=0.01)
    assert summary.zones_participated == 2


# ---------------------------------------------------------------------------
# 29–30 get_zone_stats
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_zone_stats_404_not_found():
    from app.services.driver_incentive_zone import get_zone_stats

    db = AsyncMock()
    db.execute = AsyncMock(
        return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None))
    )

    with pytest.raises(IncentiveZoneError) as exc_info:
        await get_zone_stats(db, _ZONE_ID)
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_get_zone_stats_returns_correct_stats():
    from app.services.driver_incentive_zone import get_zone_stats

    zone = _make_zone(max_total_completions=10)
    completions = [
        _make_completion(driver_profile_id=10, bonus_amount_cents=300),
        _make_completion(id=2, ride_id=43, driver_profile_id=11, bonus_amount_cents=500),
    ]

    call_count = 0

    async def mock_execute(_):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return MagicMock(scalar_one_or_none=MagicMock(return_value=zone))
        else:
            mock_s = MagicMock()
            mock_s.all = MagicMock(return_value=completions)
            return MagicMock(scalars=MagicMock(return_value=mock_s))

    db = AsyncMock()
    db.execute = mock_execute

    stats = await get_zone_stats(db, _ZONE_ID)
    assert stats.total_completions == 2
    assert stats.total_paid_cents == 800
    assert stats.total_paid_dollars == pytest.approx(8.0, abs=0.01)
    assert stats.unique_drivers == 2
    assert stats.remaining_budget == 8  # 10 - 2


# ---------------------------------------------------------------------------
# 31–39 Schema validation
# ---------------------------------------------------------------------------


def test_create_request_rejects_missing_geography():
    with pytest.raises(Exception):
        CreateIncentiveZoneRequest(
            name="Zone",
            reason="Test",
            bonus_type=IncentiveBonusType.multiplier,
            bonus_multiplier=1.5,
            starts_at=_NOW,
            ends_at=_FUTURE,
            # No polygon or circle
        )


def test_create_request_rejects_ends_before_starts():
    with pytest.raises(Exception):
        CreateIncentiveZoneRequest(
            name="Zone",
            reason="Test",
            center_lat=40.5,
            center_lon=-73.5,
            radius_km=2.0,
            bonus_type=IncentiveBonusType.multiplier,
            bonus_multiplier=1.5,
            starts_at=_FUTURE,
            ends_at=_NOW,  # before starts_at
        )


def test_create_request_rejects_multiplier_without_value():
    with pytest.raises(Exception):
        CreateIncentiveZoneRequest(
            name="Zone",
            reason="Test",
            center_lat=40.5,
            center_lon=-73.5,
            radius_km=2.0,
            bonus_type=IncentiveBonusType.multiplier,
            # bonus_multiplier missing
            starts_at=_NOW,
            ends_at=_FUTURE,
        )


def test_create_request_rejects_flat_without_cents():
    with pytest.raises(Exception):
        CreateIncentiveZoneRequest(
            name="Zone",
            reason="Test",
            center_lat=40.5,
            center_lon=-73.5,
            radius_km=2.0,
            bonus_type=IncentiveBonusType.flat,
            # bonus_flat_cents missing
            starts_at=_NOW,
            ends_at=_FUTURE,
        )


def test_create_request_accepts_valid_circle():
    req = CreateIncentiveZoneRequest(
        name="Circle Zone",
        reason="Test reason",
        center_lat=40.5,
        center_lon=-73.5,
        radius_km=3.0,
        bonus_type=IncentiveBonusType.multiplier,
        bonus_multiplier=1.5,
        starts_at=_NOW,
        ends_at=_FUTURE,
    )
    assert req.bonus_multiplier == 1.5


def test_create_request_accepts_valid_polygon():
    req = CreateIncentiveZoneRequest(
        name="Polygon Zone",
        reason="Test reason",
        polygon=SQUARE_POLYGON,
        bonus_type=IncentiveBonusType.flat,
        bonus_flat_cents=500,
        starts_at=_NOW,
        ends_at=_FUTURE,
    )
    assert req.bonus_flat_cents == 500


def test_incentive_zone_response_bonus_summary_multiplier():
    zone = _make_zone(bonus_type=IncentiveBonusType.multiplier, bonus_multiplier=1.5)
    resp = IncentiveZoneResponse.from_zone(zone)
    assert "1.50" in resp.bonus_summary
    assert "multiplier" in resp.bonus_summary


def test_incentive_zone_response_bonus_summary_flat():
    zone = _make_zone(
        bonus_type=IncentiveBonusType.flat, bonus_multiplier=None, bonus_flat_cents=500
    )
    resp = IncentiveZoneResponse.from_zone(zone)
    assert "$5.00" in resp.bonus_summary
    assert "flat bonus" in resp.bonus_summary


def test_zone_completion_response_dollar_conversion():
    completion = _make_completion(bonus_amount_cents=750)
    resp = ZoneCompletionResponse.from_completion(completion)
    assert resp.bonus_amount_dollars == pytest.approx(7.5, abs=0.01)


# ---------------------------------------------------------------------------
# 40–51 API layer (skipped without live DB)
# ---------------------------------------------------------------------------


@pytest.mark.skip(reason="requires live DB")
@pytest.mark.asyncio
async def test_api_list_active_zones_200(async_client, auth_headers):
    resp = await async_client.get("/api/v1/incentive-zones", headers=auth_headers)
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


@pytest.mark.skip(reason="requires live DB")
@pytest.mark.asyncio
async def test_api_get_zone_404(async_client, auth_headers):
    missing_id = str(uuid.uuid4())
    resp = await async_client.get(
        f"/api/v1/incentive-zones/{missing_id}", headers=auth_headers
    )
    assert resp.status_code == 404


@pytest.mark.skip(reason="requires live DB")
@pytest.mark.asyncio
async def test_api_get_my_completions_200(async_client, driver_headers):
    resp = await async_client.get(
        "/api/v1/incentive-zones/my/completions", headers=driver_headers
    )
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


@pytest.mark.skip(reason="requires live DB")
@pytest.mark.asyncio
async def test_api_get_my_summary_200(async_client, driver_headers):
    resp = await async_client.get(
        "/api/v1/incentive-zones/my/summary", headers=driver_headers
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "total_completions" in data
    assert "total_bonus_dollars" in data


@pytest.mark.skip(reason="requires live DB")
@pytest.mark.asyncio
async def test_api_admin_create_zone_201(async_client, admin_headers):
    payload = {
        "name": "Evening Boost",
        "reason": "Stadium event — expected 3× normal demand",
        "center_lat": 40.5,
        "center_lon": -73.5,
        "radius_km": 4.0,
        "bonus_type": "multiplier",
        "bonus_multiplier": 1.5,
        "starts_at": _NOW.isoformat(),
        "ends_at": _FUTURE.isoformat(),
    }
    resp = await async_client.post(
        "/api/v1/incentive-zones/admin", json=payload, headers=admin_headers
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "Evening Boost"
    assert "1.50" in data["bonus_summary"]


@pytest.mark.skip(reason="requires live DB")
@pytest.mark.asyncio
async def test_api_admin_create_zone_403_non_admin(async_client, rider_headers):
    payload = {
        "name": "Zone",
        "reason": "Test",
        "center_lat": 40.5,
        "center_lon": -73.5,
        "radius_km": 2.0,
        "bonus_type": "flat",
        "bonus_flat_cents": 300,
        "starts_at": _NOW.isoformat(),
        "ends_at": _FUTURE.isoformat(),
    }
    resp = await async_client.post(
        "/api/v1/incentive-zones/admin", json=payload, headers=rider_headers
    )
    assert resp.status_code == 403


@pytest.mark.skip(reason="requires live DB")
@pytest.mark.asyncio
async def test_api_admin_list_all_zones_200(async_client, admin_headers):
    resp = await async_client.get(
        "/api/v1/incentive-zones/admin/all", headers=admin_headers
    )
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


@pytest.mark.skip(reason="requires live DB")
@pytest.mark.asyncio
async def test_api_admin_update_zone_200(async_client, admin_headers, incentive_zone_id):
    resp = await async_client.put(
        f"/api/v1/incentive-zones/admin/{incentive_zone_id}",
        json={"name": "Renamed Zone"},
        headers=admin_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == "Renamed Zone"


@pytest.mark.skip(reason="requires live DB")
@pytest.mark.asyncio
async def test_api_admin_deactivate_zone_200(async_client, admin_headers, incentive_zone_id):
    resp = await async_client.post(
        f"/api/v1/incentive-zones/admin/{incentive_zone_id}/deactivate",
        headers=admin_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["is_active"] is False


@pytest.mark.skip(reason="requires live DB")
@pytest.mark.asyncio
async def test_api_admin_deactivate_zone_409_already_inactive(
    async_client, admin_headers, inactive_zone_id
):
    resp = await async_client.post(
        f"/api/v1/incentive-zones/admin/{inactive_zone_id}/deactivate",
        headers=admin_headers,
    )
    assert resp.status_code == 409


@pytest.mark.skip(reason="requires live DB")
@pytest.mark.asyncio
async def test_api_admin_record_completion_201(
    async_client, admin_headers, incentive_zone_id
):
    resp = await async_client.post(
        "/api/v1/incentive-zones/admin/completions",
        json={
            "zone_id": incentive_zone_id,
            "driver_profile_id": 1,
            "ride_id": 100,
            "bonus_amount_cents": 300,
        },
        headers=admin_headers,
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["bonus_amount_cents"] == 300
    assert data["bonus_amount_dollars"] == pytest.approx(3.0, abs=0.01)


@pytest.mark.skip(reason="requires live DB")
@pytest.mark.asyncio
async def test_api_admin_zone_stats_200(async_client, admin_headers, incentive_zone_id):
    resp = await async_client.get(
        f"/api/v1/incentive-zones/admin/{incentive_zone_id}/stats",
        headers=admin_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "total_completions" in data
    assert "total_paid_dollars" in data
    assert "unique_drivers" in data
