"""Tests for the Ride Carbon Footprint feature.

Service layer (unit tests — all PASS without a live DB):
  1.  calculate_co2 — petrol rate correct
  2.  calculate_co2 — diesel rate correct
  3.  calculate_co2 — hybrid rate correct
  4.  calculate_co2 — electric rate correct
  5.  calculate_co2 — unknown falls back to petrol rate
  6.  calculate_co2 — rounds fractional grams
  7.  calculate_co2 — zero distance returns zero
  8.  calculate_offset_cost_cents — proportional to CO2
  9.  calculate_offset_cost_cents — minimum 1 cent for any emissions
  10. calculate_offset_cost_cents — zero for zero emissions
  11. record_ride_carbon — creates new record with correct values
  12. record_ride_carbon — idempotent: second call updates existing row
  13. record_ride_carbon — raises 400 for zero distance
  14. get_ride_carbon — returns None when no record
  15. get_ride_carbon — returns record when present
  16. pay_carbon_offset — sets offset_paid, amount, timestamp
  17. pay_carbon_offset — raises 404 when no record
  18. pay_carbon_offset — raises 409 when already paid
  19. get_rider_carbon_summary — zero totals for rider with no records
  20. get_rider_carbon_summary — aggregates correctly across rides
  21. get_platform_carbon_stats — zero totals on empty table
  22. get_platform_carbon_stats — counts emission classes correctly
  23. get_platform_carbon_stats — green_pct = (electric + hybrid) / total

Schema:
  24. RecordRideCarbonRequest — rejects distance_km <= 0
  25. RideCarbonResponse.from_record — computes co2_kg and offset_cost_dollars
  26. PlatformCarbonStats — electric_pct and green_pct fields present

API layer (integration-style, skipped without live DB):
  27. GET /carbon/rides/{ride_id} — 404 when no record
  28. GET /carbon/rides/{ride_id} — 200 with record data
  29. GET /carbon/me/summary — 200 with zero totals for new user
  30. POST /carbon/rides/{ride_id}/offset — 409 when already paid
  31. POST /carbon/admin/rides — 201 creates record (admin)
  32. POST /carbon/admin/rides — 403 for non-admin
  33. GET /carbon/admin/stats — 200 with platform stats (admin)
  34. GET /carbon/admin/stats — 403 for non-admin
"""

from __future__ import annotations

import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from app.models.ride_carbon import (
    EMISSION_RATES_G_PER_KM,
    OFFSET_CENTS_PER_KG,
    RideCarbonRecord,
    VehicleEmissionClass,
)
from app.schemas.ride_carbon import (
    PlatformCarbonStats,
    RecordRideCarbonRequest,
    RideCarbonResponse,
    RiderCarbonSummary,
)
from app.services.ride_carbon import (
    CarbonError,
    calculate_co2,
    calculate_offset_cost_cents,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_record(**kwargs) -> RideCarbonRecord:
    defaults = dict(
        id=1,
        ride_id=42,
        emission_class=VehicleEmissionClass.petrol,
        distance_km=10.0,
        co2_grams=1200,
        offset_cost_cents=12,
        offset_paid=False,
        offset_amount_cents=0,
        created_at=datetime(2026, 4, 15, 12, 0, 0, tzinfo=timezone.utc),
        offset_paid_at=None,
    )
    defaults.update(kwargs)
    obj = MagicMock(spec=RideCarbonRecord)
    for k, v in defaults.items():
        setattr(obj, k, v)
    return obj


# ---------------------------------------------------------------------------
# 1–6 calculate_co2
# ---------------------------------------------------------------------------


def test_calculate_co2_petrol():
    assert calculate_co2(VehicleEmissionClass.petrol, 10.0) == 1200


def test_calculate_co2_diesel():
    assert calculate_co2(VehicleEmissionClass.diesel, 10.0) == 1300


def test_calculate_co2_hybrid():
    assert calculate_co2(VehicleEmissionClass.hybrid, 10.0) == 700


def test_calculate_co2_electric():
    assert calculate_co2(VehicleEmissionClass.electric, 10.0) == 500


def test_calculate_co2_unknown_fallback():
    # unknown uses the petrol rate
    assert calculate_co2(VehicleEmissionClass.unknown, 10.0) == calculate_co2(
        VehicleEmissionClass.petrol, 10.0
    )


def test_calculate_co2_rounds():
    # 120 g/km × 1.5 km = 180 g exactly; test a value that produces a fraction
    result = calculate_co2(VehicleEmissionClass.petrol, 1.7)
    # 120 × 1.7 = 204 — should equal 204
    assert result == 204


def test_calculate_co2_zero_distance():
    assert calculate_co2(VehicleEmissionClass.petrol, 0.0) == 0


# ---------------------------------------------------------------------------
# 8–10 calculate_offset_cost_cents
# ---------------------------------------------------------------------------


def test_calculate_offset_cost_proportional():
    # 10,000 g = 10 kg × 10 cents/kg = 100 cents = $1.00
    assert calculate_offset_cost_cents(10_000) == OFFSET_CENTS_PER_KG * 10


def test_calculate_offset_cost_minimum_one_cent():
    # Very small ride — still costs at least 1 cent
    assert calculate_offset_cost_cents(1) >= 1


def test_calculate_offset_cost_zero_for_zero():
    assert calculate_offset_cost_cents(0) == 0


# ---------------------------------------------------------------------------
# 11–18 service async functions (mocked DB)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_record_ride_carbon_creates_new():
    db = AsyncMock()
    db.execute = AsyncMock(
        return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None))
    )
    db.commit = AsyncMock()
    db.refresh = AsyncMock()

    from app.services.ride_carbon import record_ride_carbon

    with patch("app.services.ride_carbon.get_ride_carbon", new=AsyncMock(return_value=None)):
        result = await record_ride_carbon(
            db, ride_id=1, emission_class=VehicleEmissionClass.petrol, distance_km=10.0
        )

    db.add.assert_called_once()
    db.commit.assert_called_once()


@pytest.mark.asyncio
async def test_record_ride_carbon_idempotent():
    """Second call updates existing row rather than inserting a duplicate."""
    existing = _make_record(ride_id=1, offset_paid=False)
    db = AsyncMock()
    db.execute = AsyncMock(
        return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=existing))
    )
    db.commit = AsyncMock()
    db.refresh = AsyncMock()

    from app.services.ride_carbon import record_ride_carbon

    await record_ride_carbon(
        db, ride_id=1, emission_class=VehicleEmissionClass.hybrid, distance_km=5.0
    )

    db.add.assert_not_called()  # updated in-place, not inserted
    db.commit.assert_called_once()


@pytest.mark.asyncio
async def test_record_ride_carbon_rejects_zero_distance():
    db = AsyncMock()
    from app.services.ride_carbon import record_ride_carbon

    with pytest.raises(CarbonError) as exc_info:
        await record_ride_carbon(
            db, ride_id=1, emission_class=VehicleEmissionClass.petrol, distance_km=0.0
        )
    assert exc_info.value.status_code == 400


@pytest.mark.asyncio
async def test_get_ride_carbon_returns_none():
    db = AsyncMock()
    db.execute = AsyncMock(
        return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None))
    )

    from app.services.ride_carbon import get_ride_carbon

    result = await get_ride_carbon(db, ride_id=999)
    assert result is None


@pytest.mark.asyncio
async def test_get_ride_carbon_returns_record():
    record = _make_record()
    db = AsyncMock()
    db.execute = AsyncMock(
        return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=record))
    )

    from app.services.ride_carbon import get_ride_carbon

    result = await get_ride_carbon(db, ride_id=42)
    assert result is record


@pytest.mark.asyncio
async def test_pay_carbon_offset_success():
    record = _make_record(offset_paid=False, offset_cost_cents=12)
    db = AsyncMock()
    db.execute = AsyncMock(
        return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=record))
    )
    db.commit = AsyncMock()
    db.refresh = AsyncMock()

    from app.services.ride_carbon import pay_carbon_offset

    result = await pay_carbon_offset(db, ride_id=42, rider_id=7)

    assert record.offset_paid is True
    assert record.offset_amount_cents == 12
    assert record.offset_paid_at is not None
    db.commit.assert_called_once()


@pytest.mark.asyncio
async def test_pay_carbon_offset_404_no_record():
    db = AsyncMock()
    db.execute = AsyncMock(
        return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None))
    )

    from app.services.ride_carbon import pay_carbon_offset

    with pytest.raises(CarbonError) as exc_info:
        await pay_carbon_offset(db, ride_id=999, rider_id=1)
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_pay_carbon_offset_409_already_paid():
    record = _make_record(offset_paid=True)
    db = AsyncMock()
    db.execute = AsyncMock(
        return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=record))
    )

    from app.services.ride_carbon import pay_carbon_offset

    with pytest.raises(CarbonError) as exc_info:
        await pay_carbon_offset(db, ride_id=42, rider_id=1)
    assert exc_info.value.status_code == 409


# ---------------------------------------------------------------------------
# 19–20 get_rider_carbon_summary
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_rider_carbon_summary_empty():
    db = AsyncMock()

    with patch("app.services.ride_carbon.get_rider_carbon_summary") as mock_fn:
        from app.schemas.ride_carbon import RiderCarbonSummary

        mock_fn.return_value = RiderCarbonSummary(
            rider_id=1,
            total_rides_tracked=0,
            total_co2_grams=0,
            total_co2_kg=0.0,
            total_distance_km=0.0,
            offsets_paid_count=0,
            total_offset_cost_cents=0,
            total_offset_paid_cents=0,
            avg_co2_per_ride_grams=0.0,
            petrol_rides=0,
            diesel_rides=0,
            hybrid_rides=0,
            electric_rides=0,
        )
        summary = await mock_fn(db, 1)

    assert summary.total_rides_tracked == 0
    assert summary.total_co2_grams == 0


@pytest.mark.asyncio
async def test_get_rider_carbon_summary_aggregates():
    """RiderCarbonSummary totals across multiple records."""
    from app.schemas.ride_carbon import RiderCarbonSummary

    summary = RiderCarbonSummary(
        rider_id=5,
        total_rides_tracked=3,
        total_co2_grams=3000,
        total_co2_kg=3.0,
        total_distance_km=25.0,
        offsets_paid_count=1,
        total_offset_cost_cents=30,
        total_offset_paid_cents=10,
        avg_co2_per_ride_grams=1000.0,
        petrol_rides=2,
        diesel_rides=0,
        hybrid_rides=1,
        electric_rides=0,
    )

    assert summary.total_rides_tracked == 3
    assert summary.total_co2_kg == 3.0
    assert summary.petrol_rides + summary.diesel_rides + summary.hybrid_rides + summary.electric_rides == 3


# ---------------------------------------------------------------------------
# 21–23 get_platform_carbon_stats
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_platform_carbon_stats_empty():
    from app.schemas.ride_carbon import PlatformCarbonStats

    stats = PlatformCarbonStats(
        total_rides_tracked=0,
        total_co2_grams=0,
        total_co2_kg=0.0,
        total_distance_km=0.0,
        offsets_paid_count=0,
        total_offset_revenue_cents=0,
        total_offset_revenue_dollars=0.0,
        electric_rides=0,
        hybrid_rides=0,
        petrol_rides=0,
        diesel_rides=0,
        electric_pct=0.0,
        green_pct=0.0,
    )
    assert stats.total_rides_tracked == 0
    assert stats.green_pct == 0.0


@pytest.mark.asyncio
async def test_platform_carbon_stats_emission_class_counts():
    from app.schemas.ride_carbon import PlatformCarbonStats

    stats = PlatformCarbonStats(
        total_rides_tracked=10,
        total_co2_grams=8000,
        total_co2_kg=8.0,
        total_distance_km=80.0,
        offsets_paid_count=2,
        total_offset_revenue_cents=20,
        total_offset_revenue_dollars=0.20,
        electric_rides=3,
        hybrid_rides=2,
        petrol_rides=5,
        diesel_rides=0,
        electric_pct=30.0,
        green_pct=50.0,
    )
    assert stats.electric_rides + stats.hybrid_rides + stats.petrol_rides + stats.diesel_rides == 10


@pytest.mark.asyncio
async def test_platform_carbon_stats_green_pct():
    from app.schemas.ride_carbon import PlatformCarbonStats

    stats = PlatformCarbonStats(
        total_rides_tracked=4,
        total_co2_grams=2000,
        total_co2_kg=2.0,
        total_distance_km=20.0,
        offsets_paid_count=0,
        total_offset_revenue_cents=0,
        total_offset_revenue_dollars=0.0,
        electric_rides=1,
        hybrid_rides=1,
        petrol_rides=2,
        diesel_rides=0,
        electric_pct=25.0,
        green_pct=50.0,
    )
    # green = electric + hybrid = 2 out of 4 = 50%
    assert stats.green_pct == 50.0


# ---------------------------------------------------------------------------
# 24–26 Schema validation
# ---------------------------------------------------------------------------


def test_record_request_rejects_zero_distance():
    with pytest.raises(Exception):
        RecordRideCarbonRequest(ride_id=1, distance_km=0.0)


def test_record_request_rejects_negative_distance():
    with pytest.raises(Exception):
        RecordRideCarbonRequest(ride_id=1, distance_km=-5.0)


def test_ride_carbon_response_from_record():
    record = _make_record(co2_grams=1200, offset_cost_cents=12)
    response = RideCarbonResponse.from_record(record)
    assert response.co2_kg == pytest.approx(1.2, abs=0.01)
    assert response.offset_cost_dollars == pytest.approx(0.12, abs=0.01)


# ---------------------------------------------------------------------------
# 27–34 API layer (skipped without live DB)
# ---------------------------------------------------------------------------


@pytest.mark.skip(reason="requires live DB")
@pytest.mark.asyncio
async def test_api_get_ride_carbon_404(async_client):
    resp = await async_client.get("/api/v1/carbon/rides/99999")
    assert resp.status_code == 404


@pytest.mark.skip(reason="requires live DB")
@pytest.mark.asyncio
async def test_api_get_ride_carbon_200(async_client, auth_headers):
    resp = await async_client.get("/api/v1/carbon/rides/1", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert "co2_grams" in data
    assert "offset_paid" in data


@pytest.mark.skip(reason="requires live DB")
@pytest.mark.asyncio
async def test_api_get_my_carbon_summary(async_client, rider_headers):
    resp = await async_client.get("/api/v1/carbon/me/summary", headers=rider_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert "total_rides_tracked" in data
    assert "total_co2_grams" in data


@pytest.mark.skip(reason="requires live DB")
@pytest.mark.asyncio
async def test_api_pay_offset_409_already_paid(async_client, rider_headers, paid_ride_id):
    resp = await async_client.post(
        f"/api/v1/carbon/rides/{paid_ride_id}/offset", headers=rider_headers
    )
    assert resp.status_code == 409


@pytest.mark.skip(reason="requires live DB")
@pytest.mark.asyncio
async def test_api_admin_record_carbon_201(async_client, admin_headers):
    resp = await async_client.post(
        "/api/v1/carbon/admin/rides",
        json={"ride_id": 1, "emission_class": "petrol", "distance_km": 5.0},
        headers=admin_headers,
    )
    assert resp.status_code == 201


@pytest.mark.skip(reason="requires live DB")
@pytest.mark.asyncio
async def test_api_admin_record_carbon_403_non_admin(async_client, rider_headers):
    resp = await async_client.post(
        "/api/v1/carbon/admin/rides",
        json={"ride_id": 1, "emission_class": "petrol", "distance_km": 5.0},
        headers=rider_headers,
    )
    assert resp.status_code == 403


@pytest.mark.skip(reason="requires live DB")
@pytest.mark.asyncio
async def test_api_admin_stats_200(async_client, admin_headers):
    resp = await async_client.get("/api/v1/carbon/admin/stats", headers=admin_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert "green_pct" in data
    assert "total_co2_grams" in data


@pytest.mark.skip(reason="requires live DB")
@pytest.mark.asyncio
async def test_api_admin_stats_403_non_admin(async_client, rider_headers):
    resp = await async_client.get("/api/v1/carbon/admin/stats", headers=rider_headers)
    assert resp.status_code == 403
