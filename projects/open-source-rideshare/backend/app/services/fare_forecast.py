"""Fare forecast service — future-window pricing transparency for riders.

Shows estimated fares at 6 evenly-spaced time slots (now through
now + lookahead_hours) so riders can pick the cheapest booking window.
This is a cooperative differentiator: Uber/Lyft show only current pricing.

Key functions:
  - demand_heuristic()    — pure: time-of-day demand estimate
  - build_recommendation() — pure: plain-English booking guidance
  - get_fare_forecast()   — async: full forecast for a route

All demand multipliers use a time-of-day heuristic (no Redis) and are
clearly labelled as estimates in the response. Surge zone data is queried
live from the database for each future slot using the existing
``is_zone_active_now`` mechanism, which supports future datetimes.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.fare_forecast import FareForecastResponse, ForecastSlot
from app.services.fare_preview import _estimate_duration_min, _haversine_km
from app.services.pricing import calculate_fare_breakdown
from app.services.surge_zones import _point_in_zone, is_zone_active_now, list_zones

# ---------------------------------------------------------------------------
# Pure helpers — no I/O, fully unit-testable
# ---------------------------------------------------------------------------

# (start_hour_inclusive, end_hour_exclusive, multiplier, label)
# Hours are UTC. Overnight windows use start > end convention (same as pricing.py).
_DEMAND_WINDOWS: list[tuple[int, int, float, str]] = [
    (7, 9, 1.3, "morning rush"),
    (17, 19, 1.3, "evening rush"),
    (23, 2, 1.2, "bar close"),   # overnight: 23:00–02:00 UTC
]


def demand_heuristic(dt: datetime) -> tuple[float, str]:
    """Return a (multiplier, label) demand estimate based on hour of day (UTC).

    This is a pure heuristic — it does not query Redis. The estimate is based
    on historical rideshare demand patterns:
      - 07:00–09:00 UTC: morning rush (×1.3)
      - 17:00–19:00 UTC: evening rush (×1.3)
      - 23:00–02:00 UTC: bar close   (×1.2)
      - all other hours: off-peak    (×1.0)

    Args:
        dt: A timezone-aware or naive UTC datetime.

    Returns:
        (multiplier, label) — multiplier is 1.0 and label is "off-peak" when
        no window matches.
    """
    hour = dt.hour
    for start, end, mult, label in _DEMAND_WINDOWS:
        if start <= end:
            # Same-day window, e.g. 07–09
            if start <= hour < end:
                return mult, label
        else:
            # Overnight window, e.g. 23–02
            if hour >= start or hour < end:
                return mult, label
    return 1.0, "off-peak"


def build_recommendation(slots: list[dict]) -> str:
    """Generate a plain-English booking recommendation from forecast slot data.

    Args:
        slots: List of dicts with at minimum keys:
               ``offset_minutes`` (int), ``estimated_fare`` (float),
               ``is_surge_active`` (bool), ``combined_multiplier`` (float).

    Returns:
        A plain-English string suitable for display in the rider app.
    """
    if not slots:
        return "No forecast data available."

    # Find cheapest slot (ties broken by earliest)
    cheapest = min(slots, key=lambda s: (s["estimated_fare"], s["offset_minutes"]))
    current = slots[0]  # offset = 0 (now)

    cheapest_offset = cheapest["offset_minutes"]
    cheapest_fare = cheapest["estimated_fare"]
    current_fare = current["estimated_fare"]

    # Case 1: No surge in any slot
    any_surge = any(s["is_surge_active"] for s in slots)
    if not any_surge:
        return "No surge predicted in any window — now is a good time to book."

    # Case 2: Cheapest slot is now (offset 0)
    if cheapest_offset == 0:
        # Now is cheapest despite some future slots having surge
        if any(s["is_surge_active"] for s in slots[1:]):
            return (
                "Fare is cheapest right now. Surge is expected later — "
                "book soon to lock in the best rate."
            )
        return "Standard pricing now. No significant fare changes predicted."

    # Case 3: A future slot is cheaper than now
    if current_fare > cheapest_fare:
        pct_higher = round((current_fare / cheapest_fare - 1.0) * 100)
        return (
            f"Cheapest fare in {cheapest_offset} minutes. "
            f"Current fare is {pct_higher}% higher than the best window."
        )

    # Case 4: Now is cheapest but there's surge active somewhere
    return (
        "Current pricing is competitive. Some surge may apply at other times — "
        "now is a reasonable time to book."
    )


# ---------------------------------------------------------------------------
# Main async entry point
# ---------------------------------------------------------------------------


async def get_fare_forecast(
    db: AsyncSession,
    origin_lat: float,
    origin_lon: float,
    dest_lat: float,
    dest_lon: float,
    lookahead_hours: int = 4,
    now: datetime | None = None,
) -> FareForecastResponse:
    """Build a fare forecast across 6 evenly-spaced future time slots.

    Slots are at now + 0%, 20%, 40%, 60%, 80%, 100% of the lookahead window.
    For the default lookahead_hours=4 this gives: +0m, +48m, +96m, +144m, +192m, +240m.

    Surge zone data is queried live from the database for each future slot.
    Demand multipliers are heuristic (time-of-day) and are clearly labelled.

    Args:
        db:              Async database session.
        origin_lat:      Pickup latitude.
        origin_lon:      Pickup longitude.
        dest_lat:        Dropoff latitude.
        dest_lon:        Dropoff longitude.
        lookahead_hours: How many hours ahead to forecast (1–12, default 4).
        now:             Explicit "now" for testability; defaults to current UTC.

    Returns:
        FareForecastResponse with 6 slots ordered by offset ascending.
    """
    if now is None:
        now = datetime.now(timezone.utc)

    # Route geometry — Haversine + 30 km/h estimate (no OSRM for forecasts)
    distance_km = _haversine_km(origin_lat, origin_lon, dest_lat, dest_lon)
    duration_min = _estimate_duration_min(distance_km)

    # Pre-fetch all active zones once — avoids N round-trips to DB
    try:
        all_zones = await list_zones(db, active_only=True)
    except Exception:
        all_zones = []

    # Build 6 evenly-spaced slots: 0%, 20%, 40%, 60%, 80%, 100% of window
    total_minutes = lookahead_hours * 60
    slot_offsets = [round(total_minutes * i / 5) for i in range(6)]

    raw_slots: list[dict] = []
    for offset_min in slot_offsets:
        slot_time = now + timedelta(minutes=offset_min)

        # Surge zone multiplier at this future time
        zone_mult = 1.0
        zone_name: str | None = None
        for zone in all_zones:
            if not is_zone_active_now(zone, now=slot_time):
                continue
            if _point_in_zone(origin_lat, origin_lon, zone):
                if zone.multiplier > zone_mult:
                    zone_mult = zone.multiplier
                    zone_name = zone.name

        # Demand multiplier — heuristic only
        demand_mult, demand_label = demand_heuristic(slot_time)

        # Combined multiplier
        combined = round(zone_mult * demand_mult, 3)

        # Fare breakdown
        breakdown = calculate_fare_breakdown(
            distance_km=distance_km,
            duration_min=duration_min,
            at_time=slot_time,
            demand_multiplier=demand_mult,
            demand_label=demand_label,
            surge_multiplier=zone_mult,
            surge_label=zone_name,
        )

        raw_slots.append(
            {
                "offset_minutes": offset_min,
                "estimated_departure": slot_time,
                "surge_multiplier": zone_mult,
                "surge_zone_name": zone_name,
                "demand_multiplier": demand_mult,
                "combined_multiplier": combined,
                "is_surge_active": combined > 1.0,
                "estimated_fare": breakdown.total,
                "is_cheapest": False,  # set below
            }
        )

    # Mark cheapest slot — earliest slot wins on tie
    min_fare = min(s["estimated_fare"] for s in raw_slots)
    cheapest_marked = False
    for slot in raw_slots:
        if not cheapest_marked and slot["estimated_fare"] == min_fare:
            slot["is_cheapest"] = True
            cheapest_marked = True

    recommendation = build_recommendation(raw_slots)

    forecast_slots = [ForecastSlot(**s) for s in raw_slots]

    return FareForecastResponse(
        origin_lat=origin_lat,
        origin_lon=origin_lon,
        dest_lat=dest_lat,
        dest_lon=dest_lon,
        distance_km=round(distance_km, 2),
        estimated_duration_min=round(duration_min, 1),
        demand_is_heuristic=True,
        forecast_generated_at=now,
        slots=forecast_slots,
        recommendation=recommendation,
    )
