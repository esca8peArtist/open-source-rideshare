"""Rider-facing busy hours service.

Wraps the admin demand-by-hour data and translates it into rider-friendly
demand levels. Strips internal metrics (fare breakdown, completion rates)
and adds current-hour awareness.

Demand level thresholds (relative to peak hour):
  peak   — >= 75 % of peak-hour volume
  high   — >= 40 % of peak-hour volume
  medium — >= 15 % of peak-hour volume
  low    — anything below 15 % (or no data at all)
"""
from __future__ import annotations

from datetime import datetime, timezone

from app.schemas.busy_hours import BusyHourSlot, BusyHoursResponse, DemandLevel
from app.services.demand_heatmap import get_demand_by_hour


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _classify_demand(total_rides: int, max_rides: int) -> DemandLevel:
    """Map a raw ride count onto a DemandLevel relative to the busiest hour."""
    if max_rides == 0:
        return DemandLevel.low
    ratio = total_rides / max_rides
    if ratio >= 0.75:
        return DemandLevel.peak
    if ratio >= 0.40:
        return DemandLevel.high
    if ratio >= 0.15:
        return DemandLevel.medium
    return DemandLevel.low


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def get_busy_hours(
    db,
    day_of_week: int | None = None,
) -> BusyHoursResponse:
    """Return rider-friendly busy-hours data derived from historical demand.

    Args:
        db: async database session
        day_of_week: optional PostgreSQL DOW filter (0=Sunday … 6=Saturday)

    Returns:
        BusyHoursResponse with 24 slots, each carrying a DemandLevel and
        typical wait time. Admin-only fields (fare, completion breakdown) are
        not included.
    """
    demand = await get_demand_by_hour(db, day_of_week=day_of_week)

    now = datetime.now(timezone.utc)
    current_hour = now.hour

    max_rides = max((s.total_rides for s in demand.slots), default=0)

    slots: list[BusyHourSlot] = []
    for s in demand.slots:
        level = _classify_demand(s.total_rides, max_rides)
        slots.append(
            BusyHourSlot(
                hour=s.hour,
                hour_label=s.hour_label,
                demand_level=level,
                typical_wait_minutes=s.avg_wait_minutes,
                is_current_hour=(s.hour == current_hour),
            )
        )

    current_slot = slots[current_hour]

    return BusyHoursResponse(
        slots=slots,
        peak_hour=demand.peak_hour,
        current_hour=current_hour,
        current_demand_level=current_slot.demand_level,
        day_of_week=day_of_week,
        generated_at=now,
    )
