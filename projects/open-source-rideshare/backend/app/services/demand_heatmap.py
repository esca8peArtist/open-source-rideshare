"""Trip demand heatmap service.

Aggregates ride pickup locations into geographic grid cells so drivers can
identify high-demand areas and admins can understand platform distribution.

Grid bucketing uses PostgreSQL's ``round(numeric, N)`` on the ST_Y/ST_X
coordinates of the pickup geometry — no extra geospatial libraries required.

Resolution options and their approximate cell sizes:
  low    — 0.1°  ≈ 11 km
  medium — 0.01° ≈  1.1 km  (default)
  high   — 0.001° ≈ 110 m

Public API
----------
    get_demand_heatmap(db, start_date, end_date, resolution, hour_start,
                       hour_end, day_of_week, limit, include_fare) -> dict

Pure helpers (no DB — easy to unit-test)
-----------------------------------------
    resolution_degrees(resolution: str) -> float
    resolution_decimal_places(resolution: str) -> int
    build_cell(row, include_fare: bool) -> dict
"""

from __future__ import annotations

import logging
from datetime import date, datetime, time, timezone
from typing import Any

from geoalchemy2.functions import ST_X, ST_Y
from sqlalchemy import Numeric, cast, extract, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ride import Ride, RideStatus

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Resolution constants
# ---------------------------------------------------------------------------

_RESOLUTION_DEGREES: dict[str, float] = {
    "low": 0.1,
    "medium": 0.01,
    "high": 0.001,
}

_RESOLUTION_DECIMAL_PLACES: dict[str, int] = {
    "low": 1,
    "medium": 2,
    "high": 3,
}

DEFAULT_RESOLUTION = "medium"
DEFAULT_LIMIT = 100
MAX_LIMIT_DRIVER = 200
MAX_LIMIT_ADMIN = 500


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def resolution_degrees(resolution: str) -> float:
    """Return the cell size in decimal degrees for the given resolution name.

    Falls back to medium (0.01°) for unknown values.
    """
    return _RESOLUTION_DEGREES.get(resolution, 0.01)


def resolution_decimal_places(resolution: str) -> int:
    """Return the number of decimal places used to round coordinates.

    Falls back to 2 (medium) for unknown values.
    """
    return _RESOLUTION_DECIMAL_PLACES.get(resolution, 2)


def build_cell(row: Any, include_fare: bool) -> dict:
    """Convert a SQLAlchemy result row to a heatmap cell dict.

    Args:
        row:          Row with columns: lat, lng, request_count,
                      completed_count, and optionally avg_fare / total_fare.
        include_fare: Whether fare columns are present in the row.

    Returns:
        Dict matching HeatmapCell or HeatmapCellWithFare schema.
    """
    cell: dict = {
        "lat": float(row.lat),
        "lng": float(row.lng),
        "request_count": int(row.request_count),
        "completed_count": int(row.completed_count),
    }
    if include_fare:
        avg = row.avg_fare
        total = row.total_fare
        cell["avg_fare"] = round(float(avg), 2) if avg is not None else None
        cell["total_fare"] = round(float(total), 2) if total is not None else 0.0
    return cell


# ---------------------------------------------------------------------------
# Service function
# ---------------------------------------------------------------------------


async def get_demand_heatmap(
    db: AsyncSession,
    start_date: date,
    end_date: date,
    resolution: str = DEFAULT_RESOLUTION,
    hour_start: int | None = None,
    hour_end: int | None = None,
    day_of_week: int | None = None,
    limit: int = DEFAULT_LIMIT,
    include_fare: bool = False,
) -> dict:
    """Return aggregated pickup demand bucketed into a geographic grid.

    Args:
        db:           Async DB session.
        start_date:   Inclusive start of the lookback window (UTC date).
        end_date:     Inclusive end of the lookback window (UTC date).
        resolution:   Grid cell size — "low", "medium", or "high".
        hour_start:   Restrict to rides requested at or after this UTC hour (0–23).
        hour_end:     Restrict to rides requested at or before this UTC hour (0–23).
        day_of_week:  ISO day of week filter: 1=Monday … 7=Sunday (PostgreSQL ISODOW).
                      The API layer maps 0=Monday … 6=Sunday → 1 … 7 before calling here.
        limit:        Maximum number of cells to return (sorted by demand desc).
        include_fare: If True, include avg_fare and total_fare in each cell.

    Returns:
        Dict matching AdminDemandHeatmapResponse or DriverDemandHeatmapResponse.
    """
    dec_places = resolution_decimal_places(resolution)
    res_deg = resolution_degrees(resolution)

    # Window boundaries in UTC
    window_start = datetime.combine(start_date, time.min).replace(tzinfo=timezone.utc)
    window_end = datetime.combine(end_date, time.max).replace(tzinfo=timezone.utc)

    # Grid cell expressions
    lat_cell = func.round(
        cast(ST_Y(Ride.pickup_location), Numeric(12, 8)), dec_places
    ).label("lat")
    lng_cell = func.round(
        cast(ST_X(Ride.pickup_location), Numeric(12, 8)), dec_places
    ).label("lng")

    # Aggregates
    request_count = func.count().label("request_count")
    completed_count = func.count().filter(
        Ride.status == RideStatus.COMPLETED
    ).label("completed_count")

    if include_fare:
        avg_fare = func.avg(Ride.actual_fare).filter(
            Ride.status == RideStatus.COMPLETED
        ).label("avg_fare")
        total_fare = func.coalesce(
            func.sum(Ride.actual_fare).filter(Ride.status == RideStatus.COMPLETED),
            0.0,
        ).label("total_fare")
        cols = [lat_cell, lng_cell, request_count, completed_count, avg_fare, total_fare]
    else:
        cols = [lat_cell, lng_cell, request_count, completed_count]

    stmt = select(*cols).where(
        Ride.requested_at >= window_start,
        Ride.requested_at <= window_end,
    )

    # Optional time-of-day filters
    if hour_start is not None:
        stmt = stmt.where(extract("hour", Ride.requested_at) >= hour_start)
    if hour_end is not None:
        stmt = stmt.where(extract("hour", Ride.requested_at) <= hour_end)

    # Optional ISO day-of-week filter (1=Monday … 7=Sunday)
    if day_of_week is not None:
        stmt = stmt.where(extract("isodow", Ride.requested_at) == day_of_week)

    stmt = (
        stmt.group_by(lat_cell, lng_cell)
        .order_by(request_count.desc())
        .limit(limit)
    )

    result = await db.execute(stmt)
    rows = result.fetchall()

    cells = [build_cell(row, include_fare=include_fare) for row in rows]
    total_requests = sum(c["request_count"] for c in cells)

    logger.debug(
        "Demand heatmap — resolution=%s window=%s→%s cells=%d total_requests=%d",
        resolution,
        start_date,
        end_date,
        len(cells),
        total_requests,
    )

    return {
        "period_start": start_date,
        "period_end": end_date,
        "resolution": resolution,
        "resolution_degrees": res_deg,
        "total_requests": total_requests,
        "total_cells": len(cells),
        "cells": cells,
    }
