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
