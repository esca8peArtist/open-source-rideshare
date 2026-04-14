"""Driver career tier service.

Public API
----------
calculate_tier(rides, rating, acceptance_rate) -> CareerTierLevel
get_tier_benefits(tier) -> TierBenefits
get_next_tier_progress(rides, rating, acceptance_rate, current_tier) -> NextTierProgress | None
get_driver_career_tier(db, driver_profile_id) -> DriverCareerTier
refresh_driver_tier(db, driver_profile_id) -> tuple[DriverCareerTier, bool]
get_tier_distribution(db) -> AdminTierDistributionResponse
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.driver import DriverProfile
from app.models.driver_performance import DriverPerformanceSnapshot
from app.models.driver_tier import CareerTierLevel, DriverCareerTier
from app.schemas.driver_tier import (
    AdminTierDistributionResponse,
    NextTierProgress,
    TierBenefits,
    TierCount,
)

# ---------------------------------------------------------------------------
# Tier threshold constants
# ---------------------------------------------------------------------------

# (min_rides, min_rating, min_acceptance_rate)
_THRESHOLDS: dict[CareerTierLevel, tuple[int, float, float]] = {
    CareerTierLevel.PLATINUM: (500, 4.8, 0.90),
    CareerTierLevel.GOLD: (200, 4.7, 0.85),
    CareerTierLevel.SILVER: (50, 4.5, 0.80),
    CareerTierLevel.BRONZE: (0, 0.0, 0.0),
}

_TIER_ORDER = [
    CareerTierLevel.BRONZE,
    CareerTierLevel.SILVER,
    CareerTierLevel.GOLD,
    CareerTierLevel.PLATINUM,
]

# ---------------------------------------------------------------------------
# Pure tier logic
# ---------------------------------------------------------------------------


def calculate_tier(
    rides: int,
    rating: float,
    acceptance_rate: float,
) -> CareerTierLevel:
    """Determine the highest tier the driver qualifies for.

    Evaluates PLATINUM → GOLD → SILVER → BRONZE in order and returns the
    first tier whose three criteria are all satisfied.

    Parameters
    ----------
    rides            Lifetime completed rides (DriverProfile.total_trips)
    rating           Average rider rating (DriverProfile.rating_avg)
    acceptance_rate  Most-recent-period acceptance rate (0.0–1.0)
    """
    for tier in reversed(_TIER_ORDER):  # PLATINUM → GOLD → SILVER → BRONZE
        min_rides, min_rating, min_acceptance = _THRESHOLDS[tier]
        if rides >= min_rides and rating >= min_rating and acceptance_rate >= min_acceptance:
            return tier
    return CareerTierLevel.BRONZE


def get_tier_benefits(tier: CareerTierLevel) -> TierBenefits:
    """Return the benefit package for a given tier level."""
    _benefits = {
        CareerTierLevel.BRONZE: TierBenefits(
            dispatch_priority=1,
            earnings_bonus_pct=0.0,
            badge=None,
            perks=["Standard dispatch priority"],
        ),
        CareerTierLevel.SILVER: TierBenefits(
            dispatch_priority=2,
            earnings_bonus_pct=2.0,
            badge="silver",
            perks=[
                "2% earnings bonus on every ride",
                "Priority dispatch over Bronze drivers",
                "Silver driver badge",
            ],
        ),
        CareerTierLevel.GOLD: TierBenefits(
            dispatch_priority=3,
            earnings_bonus_pct=5.0,
            badge="gold",
            perks=[
                "5% earnings bonus on every ride",
                "High-priority dispatch",
                "Gold driver badge",
                "Preferred ride matching",
            ],
        ),
        CareerTierLevel.PLATINUM: TierBenefits(
            dispatch_priority=4,
            earnings_bonus_pct=10.0,
            badge="platinum",
            perks=[
                "10% earnings bonus on every ride",
                "Top-priority dispatch",
                "Platinum driver badge",
                "Dedicated driver support line",
                "Airport queue priority",
            ],
        ),
    }
    return _benefits[tier]


def get_next_tier_progress(
    rides: int,
    rating: float,
    acceptance_rate: float,
    current_tier: CareerTierLevel,
) -> NextTierProgress | None:
    """Return progress toward the next tier, or None if already PLATINUM."""
    current_index = _TIER_ORDER.index(current_tier)
    if current_index >= len(_TIER_ORDER) - 1:
        return None  # Already PLATINUM

    next_tier = _TIER_ORDER[current_index + 1]
    min_rides, min_rating, min_acceptance = _THRESHOLDS[next_tier]

    return NextTierProgress(
        next_tier=next_tier,
        rides_needed=max(0, min_rides - rides),
        rides_required=min_rides,
        rating_needed=round(max(0.0, min_rating - rating), 2),
        rating_required=min_rating,
        acceptance_needed=round(max(0.0, min_acceptance - acceptance_rate), 3),
        acceptance_required=min_acceptance,
    )


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------


async def _fetch_acceptance_rate(db: AsyncSession, driver_user_id: int) -> float:
    """Fetch the acceptance rate from the most recent performance snapshot.

    Falls back to 1.0 (100%) if no snapshot exists yet (new driver).

    Note: DriverPerformanceSnapshot uses driver_id → users.id (not driver_profiles.id).
    """
    result = await db.execute(
        select(DriverPerformanceSnapshot)
        .where(DriverPerformanceSnapshot.driver_id == driver_user_id)
        .order_by(DriverPerformanceSnapshot.period_start.desc())
        .limit(1)
    )
    snapshot = result.scalar_one_or_none()
    if snapshot is None:
        return 1.0
    return snapshot.acceptance_rate


async def get_driver_career_tier(
    db: AsyncSession, driver_profile_id: int
) -> DriverCareerTier:
    """Return the career tier record for a driver, creating BRONZE if absent."""
    result = await db.execute(
        select(DriverCareerTier).where(
            DriverCareerTier.driver_id == driver_profile_id
        )
    )
    row = result.scalar_one_or_none()
    if row is None:
        row = DriverCareerTier(
            driver_id=driver_profile_id,
            current_tier=CareerTierLevel.BRONZE,
        )
        db.add(row)
        await db.flush()
    return row


async def refresh_driver_tier(
    db: AsyncSession, driver_profile_id: int
) -> tuple[DriverCareerTier, bool]:
    """Recalculate and persist the driver's career tier.

    Returns ``(tier_row, tier_changed)`` where ``tier_changed`` is True if the
    tier level changed as a result of this recalculation.

    Steps:
    1. Load DriverProfile for ride count and avg rating.
    2. Load most recent DriverPerformanceSnapshot for acceptance rate.
    3. Compute new tier via ``calculate_tier()``.
    4. Update the DriverCareerTier row in-place.
    """
    # Load profile
    prof_result = await db.execute(
        select(DriverProfile).where(DriverProfile.id == driver_profile_id)
    )
    profile = prof_result.scalar_one_or_none()
    if profile is None:
        raise ValueError(f"DriverProfile {driver_profile_id} not found")

    acceptance_rate = await _fetch_acceptance_rate(db, profile.user_id)

    rides = profile.total_trips
    rating = profile.rating_avg
    new_tier = calculate_tier(rides, rating, acceptance_rate)

    row = await get_driver_career_tier(db, driver_profile_id)
    tier_changed = row.current_tier != new_tier

    if tier_changed:
        row.previous_tier = row.current_tier.value
        row.current_tier = new_tier
        row.tier_since = datetime.now(tz=timezone.utc)

    row.evaluated_at = datetime.now(tz=timezone.utc)
    row.snapshot_rides = rides
    row.snapshot_rating = rating
    row.snapshot_acceptance_rate = acceptance_rate

    await db.flush()
    return row, tier_changed


# ---------------------------------------------------------------------------
# Admin aggregate
# ---------------------------------------------------------------------------


async def get_tier_distribution(db: AsyncSession) -> AdminTierDistributionResponse:
    """Return a count of drivers at each tier level."""
    result = await db.execute(
        select(DriverCareerTier.current_tier, func.count(DriverCareerTier.id))
        .group_by(DriverCareerTier.current_tier)
    )
    rows = result.all()
    counts: dict[CareerTierLevel, int] = {t: 0 for t in CareerTierLevel}
    for tier_val, cnt in rows:
        counts[tier_val] = cnt

    total = sum(counts.values())
    distribution = [TierCount(tier=t, count=counts[t]) for t in _TIER_ORDER]

    return AdminTierDistributionResponse(total_drivers=total, distribution=distribution)
