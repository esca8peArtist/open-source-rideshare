"""Admin surge analytics service.

Queries the surge_pricing_events log to give operators insight into when and
where surge pricing fired, at what multipliers, and under what supply/demand
conditions. All queries are time-bounded to keep response times predictable.

Main functions:
  record_surge_event()     — called fire-and-forget from fare_preview
  get_surge_summary()      — platform-level summary for a time window
  get_zone_breakdown()     — per-zone event counts and average multipliers
  get_demand_heatmap()     — geohash cells ranked by surge frequency
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ride import CancellationCategory, Ride, RideStatus
from app.models.surge_event import SurgeEventType, SurgePricingEvent

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Write path — called fire-and-forget from fare_preview
# ---------------------------------------------------------------------------


async def record_surge_event(
    db: AsyncSession,
    *,
    lat: float,
    lon: float,
    geohash: str,
    surge_zone_id: str | None,
    surge_zone_name: str | None,
    zone_multiplier: float,
    demand_multiplier: float,
    demand_count: int,
    supply_count: int,
    combined_multiplier: float,
) -> None:
    """Persist one surge event. Callers must catch and swallow all exceptions."""
    has_zone = zone_multiplier > 1.0
    has_demand = demand_multiplier > 1.0

    if has_zone and has_demand:
        event_type = SurgeEventType.COMBINED
    elif has_zone:
        event_type = SurgeEventType.ZONE_ONLY
    else:
        event_type = SurgeEventType.DEMAND_ONLY

    event = SurgePricingEvent(
        event_type=event_type,
        lat=lat,
        lon=lon,
        geohash=geohash,
        surge_zone_id=str(surge_zone_id) if surge_zone_id else None,
        surge_zone_name=surge_zone_name,
        zone_multiplier=zone_multiplier,
        demand_multiplier=demand_multiplier,
        demand_count=demand_count,
        supply_count=supply_count,
        combined_multiplier=combined_multiplier,
    )
    db.add(event)
    await db.flush()


# ---------------------------------------------------------------------------
# Analytics dataclasses
# ---------------------------------------------------------------------------


@dataclass
class SurgeSummary:
    period_days: int
    total_surge_events: int
    zone_surge_events: int
    demand_surge_events: int
    combined_surge_events: int
    avg_combined_multiplier: float
    peak_hour: int | None
    top_zone_name: str | None
    top_zone_event_count: int


@dataclass
class ZoneAnalytics:
    zone_id: str | None
    zone_name: str
    event_count: int
    avg_multiplier: float
    avg_demand_count: float
    avg_supply_count: float


@dataclass
class DemandHeatmapCell:
    geohash: str
    event_count: int
    avg_combined_multiplier: float


@dataclass
class DailyPriceSensitivity:
    date: str  # YYYY-MM-DD
    total_cancellations: int
    price_cancellations: int
    surge_events: int
    price_cancellation_rate: float


@dataclass
class PriceSensitivityReport:
    period_days: int
    total_cancellations: int
    price_cancellations: int
    price_cancellation_rate: float
    total_surge_events: int
    daily_breakdown: list[DailyPriceSensitivity]


# ---------------------------------------------------------------------------
# Read path — analytics queries
# ---------------------------------------------------------------------------


def _since(days: int) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=days)


async def get_surge_summary(db: AsyncSession, days: int = 7) -> SurgeSummary:
    """Return platform-level surge statistics for the last `days` days."""
    since = _since(days)

    # Total counts by event type
    counts_q = await db.execute(
        select(
            SurgePricingEvent.event_type,
            func.count().label("cnt"),
        )
        .where(SurgePricingEvent.recorded_at >= since)
        .group_by(SurgePricingEvent.event_type)
    )
    counts_by_type: dict[str, int] = {row.event_type: row.cnt for row in counts_q}

    total = sum(counts_by_type.values())
    zone_only = counts_by_type.get(SurgeEventType.ZONE_ONLY, 0)
    demand_only = counts_by_type.get(SurgeEventType.DEMAND_ONLY, 0)
    combined = counts_by_type.get(SurgeEventType.COMBINED, 0)
    zone_total = zone_only + combined
    demand_total = demand_only + combined

    # Average combined multiplier
    avg_q = await db.execute(
        select(func.avg(SurgePricingEvent.combined_multiplier))
        .where(SurgePricingEvent.recorded_at >= since)
    )
    avg_multiplier = float(avg_q.scalar() or 1.0)

    # Peak hour (UTC hour of day with most events)
    peak_hour: int | None = None
    if total > 0:
        hour_q = await db.execute(
            select(
                func.extract("hour", SurgePricingEvent.recorded_at).label("hr"),
                func.count().label("cnt"),
            )
            .where(SurgePricingEvent.recorded_at >= since)
            .group_by(text("hr"))
            .order_by(text("cnt DESC"))
            .limit(1)
        )
        row = hour_q.one_or_none()
        if row:
            peak_hour = int(row.hr)

    # Top zone by event count
    top_zone_name: str | None = None
    top_zone_count = 0
    if zone_total > 0:
        zone_q = await db.execute(
            select(
                SurgePricingEvent.surge_zone_name,
                func.count().label("cnt"),
            )
            .where(
                SurgePricingEvent.recorded_at >= since,
                SurgePricingEvent.surge_zone_name.isnot(None),
            )
            .group_by(SurgePricingEvent.surge_zone_name)
            .order_by(text("cnt DESC"))
            .limit(1)
        )
        row = zone_q.one_or_none()
        if row:
            top_zone_name = row.surge_zone_name
            top_zone_count = int(row.cnt)

    return SurgeSummary(
        period_days=days,
        total_surge_events=total,
        zone_surge_events=zone_total,
        demand_surge_events=demand_total,
        combined_surge_events=combined,
        avg_combined_multiplier=round(avg_multiplier, 3),
        peak_hour=peak_hour,
        top_zone_name=top_zone_name,
        top_zone_event_count=top_zone_count,
    )


async def get_zone_breakdown(db: AsyncSession, days: int = 30) -> list[ZoneAnalytics]:
    """Per-zone analytics: event count, average multiplier, demand/supply stats."""
    since = _since(days)

    result = await db.execute(
        select(
            SurgePricingEvent.surge_zone_id,
            SurgePricingEvent.surge_zone_name,
            func.count().label("event_count"),
            func.avg(SurgePricingEvent.zone_multiplier).label("avg_multiplier"),
            func.avg(SurgePricingEvent.demand_count).label("avg_demand"),
            func.avg(SurgePricingEvent.supply_count).label("avg_supply"),
        )
        .where(
            SurgePricingEvent.recorded_at >= since,
            SurgePricingEvent.surge_zone_name.isnot(None),
        )
        .group_by(SurgePricingEvent.surge_zone_id, SurgePricingEvent.surge_zone_name)
        .order_by(text("event_count DESC"))
    )

    return [
        ZoneAnalytics(
            zone_id=row.surge_zone_id,
            zone_name=row.surge_zone_name,
            event_count=int(row.event_count),
            avg_multiplier=round(float(row.avg_multiplier or 1.0), 3),
            avg_demand_count=round(float(row.avg_demand or 0), 1),
            avg_supply_count=round(float(row.avg_supply or 0), 1),
        )
        for row in result
    ]


async def get_demand_heatmap(
    db: AsyncSession, days: int = 7, limit: int = 50
) -> list[DemandHeatmapCell]:
    """Geohash cells ranked by surge event frequency."""
    since = _since(days)

    result = await db.execute(
        select(
            SurgePricingEvent.geohash,
            func.count().label("event_count"),
            func.avg(SurgePricingEvent.combined_multiplier).label("avg_multiplier"),
        )
        .where(SurgePricingEvent.recorded_at >= since)
        .group_by(SurgePricingEvent.geohash)
        .order_by(text("event_count DESC"))
        .limit(limit)
    )

    return [
        DemandHeatmapCell(
            geohash=row.geohash,
            event_count=int(row.event_count),
            avg_combined_multiplier=round(float(row.avg_multiplier or 1.0), 3),
        )
        for row in result
    ]

async def get_price_sensitivity_report(
    db: AsyncSession,
    days: int = 30,
) -> PriceSensitivityReport:
    """Return price sensitivity analytics for the last *days* days.

    Answers: how many riders are abandoning due to pricing, and how does that
    rate compare to the overall cancellation rate?

    Per-day breakdown includes surge event counts so operators can visually
    correlate high-surge days with elevated price abandonment — the basis for
    tuning multiplier caps or transparency features.

    Uses ``Ride.cancelled_at`` as the time key for cancellations.  Rides
    without ``cancelled_at`` (status != CANCELLED) are excluded.
    """
    since = _since(days)

    # 1. Total cancellations in window
    total_q = await db.execute(
        select(func.count()).where(
            Ride.status == RideStatus.CANCELLED,
            Ride.cancelled_at >= since,
        )
    )
    total_cancellations: int = int(total_q.scalar() or 0)

    # 2. PRICE_TOO_HIGH cancellations in window
    price_q = await db.execute(
        select(func.count()).where(
            Ride.cancellation_category == CancellationCategory.PRICE_TOO_HIGH,
            Ride.cancelled_at >= since,
        )
    )
    price_cancellations: int = int(price_q.scalar() or 0)

    price_cancellation_rate = (
        round(price_cancellations / total_cancellations, 4) if total_cancellations > 0 else 0.0
    )

    # 3. Total surge events in window
    surge_q = await db.execute(
        select(func.count()).where(SurgePricingEvent.recorded_at >= since)
    )
    total_surge_events: int = int(surge_q.scalar() or 0)

    # 4. Per-day breakdown — daily cancellation counts + surge event counts.
    #    Two separate queries, merged in Python to avoid a cross-table GROUP BY.

    # 4a. Daily cancellation counts (total and PRICE_TOO_HIGH)
    daily_cancel_q = await db.execute(
        select(
            func.date_trunc("day", Ride.cancelled_at).label("day"),
            func.count().label("total_cancels"),
            func.count(Ride.id).filter(
                Ride.cancellation_category == CancellationCategory.PRICE_TOO_HIGH
            ).label("price_cancels"),
        )
        .where(
            Ride.status == RideStatus.CANCELLED,
            Ride.cancelled_at >= since,
        )
        .group_by(text("day"))
        .order_by(text("day"))
    )
    cancels_by_day: dict[str, tuple[int, int]] = {}
    for row in daily_cancel_q:
        day_str = row.day.strftime("%Y-%m-%d") if row.day else "unknown"
        cancels_by_day[day_str] = (int(row.total_cancels), int(row.price_cancels))

    # 4b. Daily surge event counts
    daily_surge_q = await db.execute(
        select(
            func.date_trunc("day", SurgePricingEvent.recorded_at).label("day"),
            func.count().label("surge_cnt"),
        )
        .where(SurgePricingEvent.recorded_at >= since)
        .group_by(text("day"))
    )
    surge_by_day: dict[str, int] = {}
    for row in daily_surge_q:
        day_str = row.day.strftime("%Y-%m-%d") if row.day else "unknown"
        surge_by_day[day_str] = int(row.surge_cnt)

    # Merge by day
    all_days = sorted(set(cancels_by_day.keys()) | set(surge_by_day.keys()))
    daily_breakdown = []
    for day_str in all_days:
        total_c, price_c = cancels_by_day.get(day_str, (0, 0))
        surge_c = surge_by_day.get(day_str, 0)
        rate = round(price_c / total_c, 4) if total_c > 0 else 0.0
        daily_breakdown.append(
            DailyPriceSensitivity(
                date=day_str,
                total_cancellations=total_c,
                price_cancellations=price_c,
                surge_events=surge_c,
                price_cancellation_rate=rate,
            )
        )

    return PriceSensitivityReport(
        period_days=days,
        total_cancellations=total_cancellations,
        price_cancellations=price_cancellations,
        price_cancellation_rate=price_cancellation_rate,
        total_surge_events=total_surge_events,
        daily_breakdown=daily_breakdown,
    )
