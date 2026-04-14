"""Surge zone auto-tuning service.

Analyses historical demand data (hourly ride volume from get_demand_by_hour)
to generate multiplier adjustment recommendations for each active surge zone.

Algorithm
---------
1. Fetch demand_by_hour for the lookback window (default: last 30 days).
2. Compute platform_avg: total rides across all 24 hours / 24.
3. For each active zone, identify which hour slots fall within its active
   time window (start_time / end_time). If the zone has no time window,
   all 24 hours are used.
4. Compute zone_window_avg: total rides in those hour slots / len(active_hours).
5. Compute demand_ratio = zone_window_avg / platform_avg.
6. Map demand_ratio to a multiplier adjustment:
     ratio >= 2.0  → increase by 0.20  (very high demand window)
     ratio >= 1.5  → increase by 0.10  (elevated demand window)
     ratio <= 0.50 → decrease by 0.10  (low demand window)
     otherwise     → no_change
7. Clamp recommended multiplier to [1.0, 10.0].
8. If the zone has fewer than min_sample_size rides in the window, mark as
   insufficient_data and leave the current multiplier unchanged.

Apply
-----
compute_auto_tune_recommendations() is read-only.
apply_auto_tune_recommendations() reads the preview and writes updates to DB.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, time, timedelta, timezone
from typing import Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.surge_zone_autotune import (
    AutoTuneAction,
    AutoTuneApplyDetail,
    AutoTuneApplyResponse,
    AutoTunePreviewResponse,
    SurgeZoneRecommendation,
)
from app.services.demand_heatmap import get_demand_by_hour
from app.services.surge_zones import list_zones, update_zone

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_SURGE_MIN: float = 1.0
_SURGE_MAX: float = 10.0

# Demand thresholds for recommendation actions
_RATIO_VERY_HIGH: float = 2.0   # zone avg >= 2× platform avg → increase
_RATIO_HIGH: float = 1.5        # zone avg >= 1.5× platform avg → increase (smaller nudge)
_RATIO_LOW: float = 0.5         # zone avg <= 0.5× platform avg → decrease

# Multiplier nudge amounts (conservative)
_NUDGE_LARGE: float = 0.20
_NUDGE_SMALL: float = 0.10


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _get_active_hours(start: time, end: time) -> list[int]:
    """Return the list of hour-of-day integers covered by [start, end).

    Handles same-day and overnight windows correctly.

    Examples:
        08:00 – 10:00 → [8, 9]
        22:00 – 06:00 → [22, 23, 0, 1, 2, 3, 4, 5]
        00:00 – 00:00 → [] (degenerate — no hours; caller uses all 24)
    """
    start_h = start.hour
    end_h = end.hour

    if start_h == end_h:
        # Degenerate — treat as empty; the caller will fall back to all 24
        return []

    hours: list[int] = []
    if start_h < end_h:
        hours = list(range(start_h, end_h))
    else:
        # Overnight: start → midnight, then midnight → end
        hours = list(range(start_h, 24)) + list(range(0, end_h))
    return hours


def _clamp_multiplier(value: float) -> float:
    return round(max(_SURGE_MIN, min(_SURGE_MAX, value)), 2)


def _recommend_multiplier(current: float, demand_ratio: float) -> tuple[float, AutoTuneAction]:
    """Return (recommended_multiplier, action) based on the demand ratio."""
    if demand_ratio >= _RATIO_VERY_HIGH:
        new = _clamp_multiplier(current + _NUDGE_LARGE)
        action = AutoTuneAction.increase if new > current else AutoTuneAction.no_change
    elif demand_ratio >= _RATIO_HIGH:
        new = _clamp_multiplier(current + _NUDGE_SMALL)
        action = AutoTuneAction.increase if new > current else AutoTuneAction.no_change
    elif demand_ratio <= _RATIO_LOW:
        new = _clamp_multiplier(current - _NUDGE_SMALL)
        action = AutoTuneAction.decrease if new < current else AutoTuneAction.no_change
    else:
        new = _clamp_multiplier(current)
        action = AutoTuneAction.no_change
    return new, action


def _build_reason(
    action: AutoTuneAction,
    demand_ratio: float | None,
    zone_avg: float | None,
    platform_avg: float,
    data_points: int,
    min_sample_size: int,
) -> str:
    if action == AutoTuneAction.insufficient_data:
        return (
            f"Insufficient data: {data_points} rides in window "
            f"(minimum required: {min_sample_size})."
        )
    if demand_ratio is None or platform_avg == 0:
        return "No platform ride data available for this lookback period."
    pct = round((demand_ratio - 1.0) * 100, 1)
    direction = "above" if pct >= 0 else "below"
    abs_pct = abs(pct)
    base = (
        f"Demand during zone window averages {zone_avg:.1f} rides/hr "
        f"({abs_pct:.1f}% {direction} platform average of {platform_avg:.1f} rides/hr)."
    )
    if action == AutoTuneAction.increase:
        return base + " Multiplier increased to capture elevated demand."
    elif action == AutoTuneAction.decrease:
        return base + " Multiplier reduced to match lower demand window."
    else:
        return base + " Demand is within normal range — no change recommended."


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def compute_auto_tune_recommendations(
    db: AsyncSession,
    lookback_days: int = 30,
    min_sample_size: int = 10,
) -> AutoTunePreviewResponse:
    """Compute multiplier recommendations for all active surge zones.

    Read-only — does not modify any zone. Call apply_auto_tune_recommendations
    to persist changes.

    Args:
        db: async database session
        lookback_days: number of historical days to analyse (default 30)
        min_sample_size: minimum rides required in a zone's window to make a
            recommendation; zones below this threshold get insufficient_data

    Returns:
        AutoTunePreviewResponse with one recommendation per active zone.
    """
    end_date = date.today()
    start_date = end_date - timedelta(days=lookback_days)

    # Platform-wide hourly demand for the lookback window
    demand_response = await get_demand_by_hour(db, start_date=start_date, end_date=end_date)
    slots_by_hour = {s.hour: s for s in demand_response.slots}
    platform_avg: float = (
        demand_response.total_rides / 24.0 if demand_response.total_rides > 0 else 0.0
    )

    zones = await list_zones(db, active_only=True)

    recommendations: list[SurgeZoneRecommendation] = []

    for zone in zones:
        # Determine which hours are in this zone's active window
        if zone.start_time is not None and zone.end_time is not None:
            active_hours = _get_active_hours(zone.start_time, zone.end_time)
            if not active_hours:
                # Degenerate window — fall back to all 24
                active_hours = list(range(24))
        else:
            active_hours = list(range(24))

        # Aggregate demand for those hours
        zone_total = sum(slots_by_hour[h].total_rides for h in active_hours if h in slots_by_hour)
        zone_avg: float = zone_total / len(active_hours) if active_hours else 0.0
        data_points = zone_total

        if data_points < min_sample_size:
            rec = SurgeZoneRecommendation(
                zone_id=zone.id,
                zone_name=zone.name,
                current_multiplier=zone.multiplier,
                recommended_multiplier=_clamp_multiplier(zone.multiplier),
                action=AutoTuneAction.insufficient_data,
                demand_ratio=None,
                zone_window_avg_rides=zone_avg if platform_avg > 0 else None,
                platform_avg_rides=platform_avg,
                recommendation_reason=_build_reason(
                    AutoTuneAction.insufficient_data,
                    None,
                    None,
                    platform_avg,
                    data_points,
                    min_sample_size,
                ),
                data_points=data_points,
            )
        elif platform_avg == 0.0:
            rec = SurgeZoneRecommendation(
                zone_id=zone.id,
                zone_name=zone.name,
                current_multiplier=zone.multiplier,
                recommended_multiplier=_clamp_multiplier(zone.multiplier),
                action=AutoTuneAction.no_change,
                demand_ratio=None,
                zone_window_avg_rides=None,
                platform_avg_rides=0.0,
                recommendation_reason=_build_reason(
                    AutoTuneAction.no_change, None, None, 0.0, data_points, min_sample_size
                ),
                data_points=data_points,
            )
        else:
            demand_ratio = zone_avg / platform_avg
            new_mult, action = _recommend_multiplier(zone.multiplier, demand_ratio)
            rec = SurgeZoneRecommendation(
                zone_id=zone.id,
                zone_name=zone.name,
                current_multiplier=zone.multiplier,
                recommended_multiplier=new_mult,
                action=action,
                demand_ratio=round(demand_ratio, 3),
                zone_window_avg_rides=round(zone_avg, 2),
                platform_avg_rides=round(platform_avg, 2),
                recommendation_reason=_build_reason(
                    action, demand_ratio, zone_avg, platform_avg, data_points, min_sample_size
                ),
                data_points=data_points,
            )

        recommendations.append(rec)

    return AutoTunePreviewResponse(
        recommendations=recommendations,
        total_zones=len(recommendations),
        zones_to_increase=sum(1 for r in recommendations if r.action == AutoTuneAction.increase),
        zones_to_decrease=sum(1 for r in recommendations if r.action == AutoTuneAction.decrease),
        zones_no_change=sum(1 for r in recommendations if r.action == AutoTuneAction.no_change),
        zones_insufficient_data=sum(
            1 for r in recommendations if r.action == AutoTuneAction.insufficient_data
        ),
        generated_at=datetime.now(timezone.utc),
        lookback_days=lookback_days,
        min_sample_size=min_sample_size,
    )


async def apply_auto_tune_recommendations(
    db: AsyncSession,
    zone_ids: list[uuid.UUID] | None = None,
    lookback_days: int = 30,
    min_sample_size: int = 10,
) -> AutoTuneApplyResponse:
    """Compute recommendations and apply the actionable ones to the database.

    Args:
        db: async database session
        zone_ids: if provided, only apply recommendations for these zone IDs.
            None means apply all actionable (increase / decrease) recommendations.
        lookback_days: passed through to compute_auto_tune_recommendations
        min_sample_size: passed through to compute_auto_tune_recommendations

    Returns:
        AutoTuneApplyResponse with per-zone apply / skip details.
    """
    preview = await compute_auto_tune_recommendations(
        db, lookback_days=lookback_days, min_sample_size=min_sample_size
    )

    actionable = {AutoTuneAction.increase, AutoTuneAction.decrease}
    details: list[AutoTuneApplyDetail] = []
    applied = 0
    skipped = 0

    for rec in preview.recommendations:
        # Honour zone_ids filter if provided
        if zone_ids is not None and rec.zone_id not in zone_ids:
            details.append(
                AutoTuneApplyDetail(
                    zone_id=rec.zone_id,
                    zone_name=rec.zone_name,
                    action=rec.action,
                    old_multiplier=rec.current_multiplier,
                    new_multiplier=rec.current_multiplier,
                    applied=False,
                    skip_reason="Not included in requested zone_ids.",
                )
            )
            skipped += 1
            continue

        if rec.action not in actionable:
            details.append(
                AutoTuneApplyDetail(
                    zone_id=rec.zone_id,
                    zone_name=rec.zone_name,
                    action=rec.action,
                    old_multiplier=rec.current_multiplier,
                    new_multiplier=rec.current_multiplier,
                    applied=False,
                    skip_reason=(
                        "No change recommended."
                        if rec.action == AutoTuneAction.no_change
                        else rec.recommendation_reason
                    ),
                )
            )
            skipped += 1
            continue

        # Apply the recommendation
        updated = await update_zone(db, rec.zone_id, multiplier=rec.recommended_multiplier)
        if updated is not None:
            details.append(
                AutoTuneApplyDetail(
                    zone_id=rec.zone_id,
                    zone_name=rec.zone_name,
                    action=rec.action,
                    old_multiplier=rec.current_multiplier,
                    new_multiplier=rec.recommended_multiplier,
                    applied=True,
                )
            )
            applied += 1
        else:
            # Zone disappeared between preview and apply (race condition)
            details.append(
                AutoTuneApplyDetail(
                    zone_id=rec.zone_id,
                    zone_name=rec.zone_name,
                    action=rec.action,
                    old_multiplier=rec.current_multiplier,
                    new_multiplier=rec.current_multiplier,
                    applied=False,
                    skip_reason="Zone not found at apply time (may have been deleted).",
                )
            )
            skipped += 1

    return AutoTuneApplyResponse(
        applied=applied,
        skipped=skipped,
        details=details,
        generated_at=datetime.now(timezone.utc),
    )
