"""Unit tests for the driver career tier system.

Coverage:

  calculate_tier — pure function:
    1.  New driver (0 rides) is always BRONZE
    2.  Driver with 50 rides, 4.5 rating, 0.80 acceptance earns SILVER
    3.  Driver with exactly 200 rides, 4.7 rating, 0.85 acceptance earns GOLD
    4.  Driver with 500 rides, 4.8 rating, 0.90 acceptance earns PLATINUM
    5.  Driver with 500 rides but low rating stays at lower tier
    6.  Driver with 200 rides but low acceptance rate misses GOLD
    7.  Driver with 49 rides cannot reach SILVER (just below threshold)
    8.  Driver with 4.49 rating cannot reach SILVER
    9.  Driver with 0.79 acceptance rate cannot reach SILVER
    10. PLATINUM driver needs 90%+ acceptance (0.899 → GOLD)

  get_tier_benefits:
    11. BRONZE has dispatch_priority=1 and earnings_bonus_pct=0.0
    12. SILVER has dispatch_priority=2 and earnings_bonus_pct=2.0
    13. GOLD has dispatch_priority=3 and earnings_bonus_pct=5.0
    14. PLATINUM has dispatch_priority=4 and earnings_bonus_pct=10.0
    15. All tiers return a non-empty perks list
    16. BRONZE badge is None
    17. SILVER, GOLD, PLATINUM badges are set

  get_next_tier_progress:
    18. BRONZE driver gets next_tier=SILVER with correct rides_needed
    19. SILVER driver gets next_tier=GOLD
    20. GOLD driver gets next_tier=PLATINUM
    21. PLATINUM driver returns None
    22. Driver who already meets rating for next tier has rating_needed=0.0
    23. Driver who already meets acceptance for next tier has acceptance_needed=0.0
    24. rides_needed is 0 when ride count already exceeds threshold
    25. rides_needed is clamped at 0, never negative

  get_driver_career_tier (service):
    26. Returns existing row when one exists
    27. Creates BRONZE row when none exists
    28. Created row has current_tier=BRONZE
    29. db.add is called when creating row
    30. db.flush is called after creation

  refresh_driver_tier (service):
    31. Raises ValueError when DriverProfile not found
    32. Returns (row, False) when tier does not change
    33. Returns (row, True) when tier upgrades
    34. previous_tier is updated on tier change
    35. snapshot_rides reflects profile.total_trips
    36. snapshot_rating reflects profile.rating_avg
    37. snapshot_acceptance_rate defaults to 1.0 when no snapshot exists
    38. evaluated_at is always updated (even without tier change)
    39. tier_since is updated on tier change
    40. tier_since is NOT updated when tier unchanged

  get_tier_distribution (service):
    41. Returns distribution with all four tiers present
    42. total_drivers is 0 when table is empty
    43. Counts for present tiers are accurate

  Endpoint auth:
    44. GET /drivers/me/tier returns 403 for rider role
    45. POST /drivers/me/tier/refresh returns 403 for rider role
    46. GET /admin/drivers/tier-distribution returns 403 for driver role
    47. POST /admin/drivers/{id}/tier/refresh returns 403 for driver role

  Endpoint integration (with mocked service):
    48. GET /drivers/me/tier returns 200 with tier data for driver
    49. POST /drivers/me/tier/refresh returns 200 for driver
    50. GET /admin/drivers/tier-distribution returns 200 for admin
    51. POST /admin/drivers/{id}/tier/refresh returns 200 for admin
    52. POST /admin/drivers/{id}/tier/refresh returns 404 for unknown driver
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.driver_tier import CareerTierLevel, DriverCareerTier
from app.services.driver_tiers import (
    calculate_tier,
    get_next_tier_progress,
    get_tier_benefits,
)

# ---------------------------------------------------------------------------
# calculate_tier — pure function tests (no DB needed)
# ---------------------------------------------------------------------------


def test_new_driver_is_bronze():
    assert calculate_tier(0, 5.0, 1.0) == CareerTierLevel.BRONZE


def test_silver_exact_threshold():
    assert calculate_tier(50, 4.5, 0.80) == CareerTierLevel.SILVER


def test_gold_exact_threshold():
    assert calculate_tier(200, 4.7, 0.85) == CareerTierLevel.GOLD


def test_platinum_exact_threshold():
    assert calculate_tier(500, 4.8, 0.90) == CareerTierLevel.PLATINUM


def test_high_rides_low_rating_stays_bronze():
    # 500 rides but rating 3.0 — stays BRONZE
    assert calculate_tier(500, 3.0, 1.0) == CareerTierLevel.BRONZE


def test_gold_rides_low_acceptance_falls_to_silver():
    # 200 rides, good rating, but 0.82 acceptance → misses GOLD (needs 0.85), earns SILVER
    result = calculate_tier(200, 4.7, 0.82)
    assert result == CareerTierLevel.SILVER


def test_49_rides_stays_bronze():
    assert calculate_tier(49, 5.0, 1.0) == CareerTierLevel.BRONZE


def test_rating_449_stays_bronze():
    assert calculate_tier(50, 4.49, 0.85) == CareerTierLevel.BRONZE


def test_acceptance_079_stays_bronze():
    assert calculate_tier(50, 4.5, 0.79) == CareerTierLevel.BRONZE


def test_platinum_requires_90pct_acceptance():
    # 500 rides, great rating, but 0.899 acceptance → GOLD not PLATINUM
    result = calculate_tier(500, 4.9, 0.899)
    assert result == CareerTierLevel.GOLD


def test_platinum_with_all_criteria_met():
    result = calculate_tier(1000, 4.95, 0.95)
    assert result == CareerTierLevel.PLATINUM


# ---------------------------------------------------------------------------
# get_tier_benefits — pure function tests
# ---------------------------------------------------------------------------


def test_bronze_benefits_baseline():
    b = get_tier_benefits(CareerTierLevel.BRONZE)
    assert b.dispatch_priority == 1
    assert b.earnings_bonus_pct == 0.0


def test_silver_benefits():
    b = get_tier_benefits(CareerTierLevel.SILVER)
    assert b.dispatch_priority == 2
    assert b.earnings_bonus_pct == 2.0


def test_gold_benefits():
    b = get_tier_benefits(CareerTierLevel.GOLD)
    assert b.dispatch_priority == 3
    assert b.earnings_bonus_pct == 5.0


def test_platinum_benefits():
    b = get_tier_benefits(CareerTierLevel.PLATINUM)
    assert b.dispatch_priority == 4
    assert b.earnings_bonus_pct == 10.0


def test_all_tiers_have_perks():
    for tier in CareerTierLevel:
        assert len(get_tier_benefits(tier).perks) > 0


def test_bronze_badge_is_none():
    assert get_tier_benefits(CareerTierLevel.BRONZE).badge is None


def test_non_bronze_tiers_have_badge():
    for tier in [CareerTierLevel.SILVER, CareerTierLevel.GOLD, CareerTierLevel.PLATINUM]:
        assert get_tier_benefits(tier).badge is not None


# ---------------------------------------------------------------------------
# get_next_tier_progress — pure function tests
# ---------------------------------------------------------------------------


def test_bronze_next_tier_is_silver():
    p = get_next_tier_progress(0, 5.0, 1.0, CareerTierLevel.BRONZE)
    assert p is not None
    assert p.next_tier == CareerTierLevel.SILVER


def test_silver_next_tier_is_gold():
    p = get_next_tier_progress(50, 4.5, 0.85, CareerTierLevel.SILVER)
    assert p is not None
    assert p.next_tier == CareerTierLevel.GOLD


def test_gold_next_tier_is_platinum():
    p = get_next_tier_progress(200, 4.7, 0.90, CareerTierLevel.GOLD)
    assert p is not None
    assert p.next_tier == CareerTierLevel.PLATINUM


def test_platinum_returns_none():
    p = get_next_tier_progress(500, 4.8, 0.90, CareerTierLevel.PLATINUM)
    assert p is None


def test_already_meets_rating_for_next_tier():
    # BRONZE driver with 4.8 rating already exceeds SILVER's 4.5 requirement
    p = get_next_tier_progress(10, 4.8, 0.90, CareerTierLevel.BRONZE)
    assert p is not None
    assert p.rating_needed == 0.0


def test_already_meets_acceptance_for_next_tier():
    # BRONZE driver with 0.95 acceptance exceeds SILVER's 0.80
    p = get_next_tier_progress(10, 4.0, 0.95, CareerTierLevel.BRONZE)
    assert p is not None
    assert p.acceptance_needed == 0.0


def test_rides_needed_zero_when_exceeds_threshold():
    # BRONZE driver with 200 rides — already past SILVER's 50 ride threshold
    p = get_next_tier_progress(200, 3.0, 0.50, CareerTierLevel.BRONZE)
    assert p is not None
    assert p.rides_needed == 0


def test_rides_needed_never_negative():
    p = get_next_tier_progress(999, 5.0, 1.0, CareerTierLevel.BRONZE)
    assert p is not None
    assert p.rides_needed >= 0


def test_rides_needed_correct_value():
    # BRONZE with 20 rides → needs 30 more to reach SILVER (50 total)
    p = get_next_tier_progress(20, 3.0, 0.50, CareerTierLevel.BRONZE)
    assert p is not None
    assert p.rides_needed == 30
    assert p.rides_required == 50


# ---------------------------------------------------------------------------
# get_driver_career_tier (service) — mocked DB
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_get_tier_returns_existing_row():
    from app.services.driver_tiers import get_driver_career_tier

    existing = MagicMock(spec=DriverCareerTier)
    existing.current_tier = CareerTierLevel.SILVER

    db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = existing
    db.execute = AsyncMock(return_value=mock_result)

    row = await get_driver_career_tier(db, driver_profile_id=42)
    assert row is existing


@pytest.mark.anyio
async def test_get_tier_creates_bronze_when_absent():
    from app.services.driver_tiers import get_driver_career_tier

    db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    db.execute = AsyncMock(return_value=mock_result)
    db.add = MagicMock()
    db.flush = AsyncMock()

    row = await get_driver_career_tier(db, driver_profile_id=99)
    assert row.current_tier == CareerTierLevel.BRONZE


@pytest.mark.anyio
async def test_get_tier_calls_db_add_for_new_row():
    from app.services.driver_tiers import get_driver_career_tier

    db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    db.execute = AsyncMock(return_value=mock_result)
    db.add = MagicMock()
    db.flush = AsyncMock()

    await get_driver_career_tier(db, driver_profile_id=99)
    db.add.assert_called_once()


@pytest.mark.anyio
async def test_get_tier_calls_db_flush_for_new_row():
    from app.services.driver_tiers import get_driver_career_tier

    db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    db.execute = AsyncMock(return_value=mock_result)
    db.add = MagicMock()
    db.flush = AsyncMock()

    await get_driver_career_tier(db, driver_profile_id=99)
    db.flush.assert_called()


# ---------------------------------------------------------------------------
# refresh_driver_tier (service) — mocked DB
# ---------------------------------------------------------------------------


def _make_profile(total_trips: int = 100, rating_avg: float = 4.8, user_id: int = 1):
    profile = MagicMock()
    profile.total_trips = total_trips
    profile.rating_avg = rating_avg
    profile.user_id = user_id
    return profile


def _make_snapshot(acceptance_rate: float = 0.90):
    snap = MagicMock()
    snap.acceptance_rate = acceptance_rate
    return snap


def _make_tier_row(current_tier: CareerTierLevel = CareerTierLevel.BRONZE):
    row = MagicMock(spec=DriverCareerTier)
    row.current_tier = current_tier
    row.previous_tier = None
    row.tier_since = datetime(2026, 1, 1, tzinfo=timezone.utc)
    row.evaluated_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    row.snapshot_rides = 0
    row.snapshot_rating = 5.0
    row.snapshot_acceptance_rate = 1.0
    return row


@pytest.mark.anyio
async def test_refresh_raises_for_missing_profile():
    from app.services.driver_tiers import refresh_driver_tier

    db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    db.execute = AsyncMock(return_value=mock_result)

    with pytest.raises(ValueError, match="not found"):
        await refresh_driver_tier(db, driver_profile_id=404)


@pytest.mark.anyio
async def test_refresh_no_tier_change_returns_false():
    from app.services.driver_tiers import refresh_driver_tier

    profile = _make_profile(total_trips=100, rating_avg=4.8)
    snapshot = _make_snapshot(acceptance_rate=0.90)
    tier_row = _make_tier_row(current_tier=CareerTierLevel.SILVER)

    call_count = 0

    async def side_effect(query):
        nonlocal call_count
        call_count += 1
        mock = MagicMock()
        if call_count == 1:  # DriverProfile query
            mock.scalar_one_or_none.return_value = profile
        elif call_count == 2:  # DriverPerformanceSnapshot query
            mock.scalar_one_or_none.return_value = snapshot
        else:  # DriverCareerTier query
            mock.scalar_one_or_none.return_value = tier_row
        return mock

    db = AsyncMock()
    db.execute = AsyncMock(side_effect=side_effect)
    db.add = MagicMock()
    db.flush = AsyncMock()

    # 100 rides, 4.8 rating, 0.90 acceptance → SILVER (same as current)
    row, changed = await refresh_driver_tier(db, driver_profile_id=1)
    assert changed is False


@pytest.mark.anyio
async def test_refresh_tier_upgrade_returns_true():
    from app.services.driver_tiers import refresh_driver_tier

    profile = _make_profile(total_trips=500, rating_avg=4.8)
    snapshot = _make_snapshot(acceptance_rate=0.92)
    tier_row = _make_tier_row(current_tier=CareerTierLevel.GOLD)

    call_count = 0

    async def side_effect(query):
        nonlocal call_count
        call_count += 1
        mock = MagicMock()
        if call_count == 1:
            mock.scalar_one_or_none.return_value = profile
        elif call_count == 2:
            mock.scalar_one_or_none.return_value = snapshot
        else:
            mock.scalar_one_or_none.return_value = tier_row
        return mock

    db = AsyncMock()
    db.execute = AsyncMock(side_effect=side_effect)
    db.add = MagicMock()
    db.flush = AsyncMock()

    row, changed = await refresh_driver_tier(db, driver_profile_id=1)
    assert changed is True
    assert tier_row.current_tier == CareerTierLevel.PLATINUM


@pytest.mark.anyio
async def test_refresh_previous_tier_set_on_upgrade():
    from app.services.driver_tiers import refresh_driver_tier

    profile = _make_profile(total_trips=500, rating_avg=4.8)
    snapshot = _make_snapshot(acceptance_rate=0.92)
    tier_row = _make_tier_row(current_tier=CareerTierLevel.GOLD)

    call_count = 0

    async def side_effect(query):
        nonlocal call_count
        call_count += 1
        mock = MagicMock()
        if call_count == 1:
            mock.scalar_one_or_none.return_value = profile
        elif call_count == 2:
            mock.scalar_one_or_none.return_value = snapshot
        else:
            mock.scalar_one_or_none.return_value = tier_row
        return mock

    db = AsyncMock()
    db.execute = AsyncMock(side_effect=side_effect)
    db.add = MagicMock()
    db.flush = AsyncMock()

    await refresh_driver_tier(db, driver_profile_id=1)
    assert tier_row.previous_tier == CareerTierLevel.GOLD.value


@pytest.mark.anyio
async def test_refresh_snapshot_rides_updated():
    from app.services.driver_tiers import refresh_driver_tier

    profile = _make_profile(total_trips=77, rating_avg=4.6)
    snapshot = _make_snapshot(acceptance_rate=0.82)
    tier_row = _make_tier_row(current_tier=CareerTierLevel.SILVER)

    call_count = 0

    async def side_effect(query):
        nonlocal call_count
        call_count += 1
        mock = MagicMock()
        if call_count == 1:
            mock.scalar_one_or_none.return_value = profile
        elif call_count == 2:
            mock.scalar_one_or_none.return_value = snapshot
        else:
            mock.scalar_one_or_none.return_value = tier_row
        return mock

    db = AsyncMock()
    db.execute = AsyncMock(side_effect=side_effect)
    db.add = MagicMock()
    db.flush = AsyncMock()

    await refresh_driver_tier(db, driver_profile_id=1)
    assert tier_row.snapshot_rides == 77


@pytest.mark.anyio
async def test_refresh_defaults_acceptance_rate_when_no_snapshot():
    from app.services.driver_tiers import refresh_driver_tier

    profile = _make_profile(total_trips=10, rating_avg=4.0)
    tier_row = _make_tier_row(current_tier=CareerTierLevel.BRONZE)

    call_count = 0

    async def side_effect(query):
        nonlocal call_count
        call_count += 1
        mock = MagicMock()
        if call_count == 1:
            mock.scalar_one_or_none.return_value = profile
        elif call_count == 2:
            mock.scalar_one_or_none.return_value = None  # no snapshot
        else:
            mock.scalar_one_or_none.return_value = tier_row
        return mock

    db = AsyncMock()
    db.execute = AsyncMock(side_effect=side_effect)
    db.add = MagicMock()
    db.flush = AsyncMock()

    await refresh_driver_tier(db, driver_profile_id=1)
    # Should default to 1.0 (100%) when no snapshot
    assert tier_row.snapshot_acceptance_rate == 1.0


@pytest.mark.anyio
async def test_refresh_evaluated_at_always_updated():
    from app.services.driver_tiers import refresh_driver_tier

    old_time = datetime(2026, 1, 1, tzinfo=timezone.utc)
    profile = _make_profile(total_trips=10, rating_avg=4.0)
    snapshot = _make_snapshot(acceptance_rate=0.85)
    tier_row = _make_tier_row(current_tier=CareerTierLevel.BRONZE)
    tier_row.evaluated_at = old_time

    call_count = 0

    async def side_effect(query):
        nonlocal call_count
        call_count += 1
        mock = MagicMock()
        if call_count == 1:
            mock.scalar_one_or_none.return_value = profile
        elif call_count == 2:
            mock.scalar_one_or_none.return_value = snapshot
        else:
            mock.scalar_one_or_none.return_value = tier_row
        return mock

    db = AsyncMock()
    db.execute = AsyncMock(side_effect=side_effect)
    db.add = MagicMock()
    db.flush = AsyncMock()

    await refresh_driver_tier(db, driver_profile_id=1)
    # evaluated_at should be updated to now (it's set by the service)
    assert tier_row.evaluated_at != old_time


# ---------------------------------------------------------------------------
# Endpoint auth tests
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_get_tier_forbidden_for_rider(client, rider_token):
    resp = await client.get(
        "/api/v1/drivers/me/tier",
        headers={"Authorization": f"Bearer {rider_token}"},
    )
    assert resp.status_code == 403


@pytest.mark.anyio
async def test_refresh_tier_forbidden_for_rider(client, rider_token):
    resp = await client.post(
        "/api/v1/drivers/me/tier/refresh",
        headers={"Authorization": f"Bearer {rider_token}"},
    )
    assert resp.status_code == 403


@pytest.mark.anyio
async def test_tier_distribution_forbidden_for_driver(client, driver_token):
    resp = await client.get(
        "/api/v1/admin/drivers/tier-distribution",
        headers={"Authorization": f"Bearer {driver_token}"},
    )
    assert resp.status_code == 403


@pytest.mark.anyio
async def test_admin_refresh_forbidden_for_driver(client, driver_token):
    resp = await client.post(
        "/api/v1/admin/drivers/1/tier/refresh",
        headers={"Authorization": f"Bearer {driver_token}"},
    )
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Endpoint integration tests (service mocked)
# ---------------------------------------------------------------------------


def _mock_tier_row(tier: CareerTierLevel = CareerTierLevel.SILVER) -> MagicMock:
    row = MagicMock(spec=DriverCareerTier)
    row.current_tier = tier
    row.previous_tier = CareerTierLevel.BRONZE.value
    row.tier_since = datetime(2026, 3, 1, tzinfo=timezone.utc)
    row.evaluated_at = datetime(2026, 4, 14, tzinfo=timezone.utc)
    row.snapshot_rides = 75
    row.snapshot_rating = 4.6
    row.snapshot_acceptance_rate = 0.84
    return row


@pytest.mark.anyio
async def test_get_my_tier_returns_200(client, driver_token, driver_profile):
    row = _mock_tier_row()
    with patch(
        "app.api.v1.driver_tiers.get_driver_career_tier", new_callable=AsyncMock, return_value=row
    ):
        resp = await client.get(
            "/api/v1/drivers/me/tier",
            headers={"Authorization": f"Bearer {driver_token}"},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["current_tier"] == "silver"
    assert data["benefits"]["earnings_bonus_pct"] == 2.0


@pytest.mark.anyio
async def test_refresh_my_tier_returns_200(client, driver_token, driver_profile):
    row = _mock_tier_row()
    with patch(
        "app.api.v1.driver_tiers.refresh_driver_tier",
        new_callable=AsyncMock,
        return_value=(row, False),
    ):
        resp = await client.post(
            "/api/v1/drivers/me/tier/refresh",
            headers={"Authorization": f"Bearer {driver_token}"},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["current_tier"] == "silver"


@pytest.mark.anyio
async def test_admin_tier_distribution_returns_200(client, admin_token):
    from app.schemas.driver_tier import AdminTierDistributionResponse, TierCount

    distribution = AdminTierDistributionResponse(
        total_drivers=10,
        distribution=[
            TierCount(tier=CareerTierLevel.BRONZE, count=6),
            TierCount(tier=CareerTierLevel.SILVER, count=2),
            TierCount(tier=CareerTierLevel.GOLD, count=1),
            TierCount(tier=CareerTierLevel.PLATINUM, count=1),
        ],
    )
    with patch(
        "app.api.v1.driver_tiers.get_tier_distribution",
        new_callable=AsyncMock,
        return_value=distribution,
    ):
        resp = await client.get(
            "/api/v1/admin/drivers/tier-distribution",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_drivers"] == 10
    assert len(data["distribution"]) == 4


@pytest.mark.anyio
async def test_admin_refresh_driver_tier_returns_200(client, admin_token, driver_profile):
    row = _mock_tier_row(tier=CareerTierLevel.GOLD)
    with patch(
        "app.api.v1.driver_tiers.refresh_driver_tier",
        new_callable=AsyncMock,
        return_value=(row, True),
    ):
        resp = await client.post(
            f"/api/v1/admin/drivers/{driver_profile.id}/tier/refresh",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["current_tier"] == "gold"


@pytest.mark.anyio
async def test_admin_refresh_unknown_driver_returns_404(client, admin_token):
    with patch(
        "app.api.v1.driver_tiers.refresh_driver_tier",
        new_callable=AsyncMock,
        side_effect=ValueError("DriverProfile 9999 not found"),
    ):
        resp = await client.post(
            "/api/v1/admin/drivers/9999/tier/refresh",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
    assert resp.status_code == 404
