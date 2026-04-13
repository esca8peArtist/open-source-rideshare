from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from app.config import settings


@dataclass(frozen=True)
class FareBreakdown:
    base: float
    distance: float
    time: float
    multiplier: float
    multiplier_label: str | None
    demand_multiplier: float
    demand_label: str | None
    surge_multiplier: float
    surge_label: str | None
    subtotal: float
    platform_fee: float
    total: float


# Operator-configurable time-of-day multipliers.
# Keys are (start_hour, end_hour) tuples (24h, inclusive start, exclusive end).
# Values are (multiplier, label).
# Empty by default — cooperatives opt in to this; no algorithmic surge.
_time_multipliers: list[tuple[int, int, float, str]] = []


def set_time_multipliers(entries: list[dict]) -> None:
    """Replace the time-of-day multiplier schedule.

    Each entry: {"start_hour": 22, "end_hour": 6, "multiplier": 1.25, "label": "Late night"}
    Hours are 0-23. Ranges that cross midnight (start > end) are handled correctly.
    """
    _time_multipliers.clear()
    _time_multipliers.extend(
        (e["start_hour"], e["end_hour"], e["multiplier"], e["label"])
        for e in entries
    )


def get_time_multipliers() -> list[dict]:
    return [
        {"start_hour": s, "end_hour": e, "multiplier": m, "label": l}
        for s, e, m, l in _time_multipliers
    ]


# Runtime-overridable pricing parameters (set by admin API).
_pricing_overrides: dict[str, float] = {}


def set_pricing_overrides(overrides: dict[str, float]) -> None:
    """Allow admin to override base_fare, per_km_rate, per_minute_rate, minimum_fare, platform_fee_percent at runtime."""
    _pricing_overrides.update(overrides)


def get_pricing_params() -> dict[str, float]:
    return {
        "base_fare": _pricing_overrides.get("base_fare", settings.base_fare),
        "per_km_rate": _pricing_overrides.get("per_km_rate", settings.per_km_rate),
        "per_minute_rate": _pricing_overrides.get("per_minute_rate", settings.per_minute_rate),
        "minimum_fare": _pricing_overrides.get("minimum_fare", settings.minimum_fare),
        "platform_fee_percent": _pricing_overrides.get("platform_fee_percent", 0.0),
    }


def _resolve_time_multiplier(dt: datetime) -> tuple[float, str | None]:
    """Return the multiplier and label for the given time, or (1.0, None) if no rule matches."""
    hour = dt.hour
    for start, end, mult, label in _time_multipliers:
        if start <= end:
            # Same-day range, e.g. 6-9
            if start <= hour < end:
                return mult, label
        else:
            # Cross-midnight range, e.g. 22-6
            if hour >= start or hour < end:
                return mult, label
    return 1.0, None


def calculate_fare(distance_km: float, duration_min: float) -> float:
    """Backward-compatible fare calculation. Returns total fare as a float."""
    breakdown = calculate_fare_breakdown(distance_km, duration_min)
    return breakdown.total


def calculate_fare_breakdown(
    distance_km: float,
    duration_min: float,
    at_time: datetime | None = None,
    demand_multiplier: float = 1.0,
    demand_label: str | None = None,
    surge_multiplier: float = 1.0,
    surge_label: str | None = None,
) -> FareBreakdown:
    """Full fare calculation with breakdown.

    Args:
        distance_km: Trip distance in kilometers.
        duration_min: Estimated trip duration in minutes.
        at_time: Time to evaluate time-of-day multipliers against.
                 Defaults to current UTC time.
        demand_multiplier: Supply/demand-based multiplier (1.0 = no adjustment).
        demand_label: Human-readable explanation of demand pricing.
        surge_multiplier: Admin-defined geographic surge zone multiplier.
                          Displayed separately in the breakdown for transparency.
        surge_label: Human-readable label for the surge zone (e.g. "Downtown Core").
    """
    params = get_pricing_params()
    base = params["base_fare"]
    distance_component = distance_km * params["per_km_rate"]
    time_component = duration_min * params["per_minute_rate"]

    if at_time is None:
        at_time = datetime.now(timezone.utc)
    multiplier, multiplier_label = _resolve_time_multiplier(at_time)

    # All three multipliers stack: time-of-day * demand * surge zone
    combined_multiplier = multiplier * demand_multiplier * surge_multiplier
    subtotal = (base + distance_component + time_component) * combined_multiplier
    subtotal = max(subtotal, params["minimum_fare"])

    platform_fee = subtotal * (params["platform_fee_percent"] / 100.0)
    total = subtotal + platform_fee

    return FareBreakdown(
        base=round(base, 2),
        distance=round(distance_component, 2),
        time=round(time_component, 2),
        multiplier=multiplier,
        multiplier_label=multiplier_label,
        demand_multiplier=demand_multiplier,
        demand_label=demand_label,
        surge_multiplier=surge_multiplier,
        surge_label=surge_label,
        subtotal=round(subtotal, 2),
        platform_fee=round(platform_fee, 2),
        total=round(total, 2),
    )
