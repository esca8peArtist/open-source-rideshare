"""Trip heatmap service.

Aggregates completed ride pickup and dropoff coordinates into geographic grid
cells for admin analytics. Useful for:
  - Identifying high-demand pickup/dropoff zones
  - Informing surge zone boundaries
  - Service area planning

Grid cells are formed by rounding coordinates to ``precision`` decimal places:
  - precision=1 → ~11 km cells
  - precision=2 → ~1.1 km cells  (default)
  - precision=3 → ~110 m cells
  - precision=4 → ~11 m cells

All functions are read-only; no data is mutated here.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.types import Numeric

from app.models.ride import Ride, RideStatus
from app.schemas.trip_heatmap import HeatmapCell, HeatmapFilters, HeatmapResponse


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _date_to_utc_start(d: date) -> datetime:
    return datetime(d.year, d.month, d.day, 0, 0, 0, tzinfo=timezone.utc)


def _date_to_utc_end(d: date) -> datetime:
    return datetime(d.year, d.month, d.day, 23, 59, 59, tzinfo=timezone.utc)


def _apply_date_and_status_filters(query, start_date, end_date, status_enum):
    """Apply common where clauses to a ride query."""
    if start_date is not None:
        query = query.where(Ride.requested_at >= _date_to_utc_start(start_date))
    if end_date is not None:
        query = query.where(Ride.requested_at <= _date_to_utc_end(end_date))
    if status_enum is not None:
        query = query.where(Ride.status == status_enum)
    return query


def _to_float(value) -> float | None:
    """Safely convert Decimal or float DB values to Python float."""
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    return float(value)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def get_trip_heatmap(
    db: AsyncSession,
    start_date: date | None = None,
    end_date: date | None = None,
    precision: int = 2,
    status: str | None = None,
    min_activity: int = 1,
) -> HeatmapResponse:
    """Compute a geographic heatmap of pickup and dropoff activity.

    Args:
        db: async database session
        start_date: inclusive start date filter on ride.requested_at
        end_date: inclusive end date filter on ride.requested_at
        precision: decimal places for coordinate rounding (1-4)
        status: optional RideStatus value string; defaults to "completed"
        min_activity: minimum total_activity to include a cell

    Returns:
        HeatmapResponse with cells sorted by total_activity descending.
    """
    # Resolve status filter
    if status is not None:
        try:
            status_enum = RideStatus(status)
        except ValueError:
            status_enum = None  # unknown status → no rides match → empty result
            # Mark as sentinel to skip queries
            _unknown_status = True
        else:
            _unknown_status = False
    else:
        status_enum = RideStatus.COMPLETED  # default: completed rides only
        _unknown_status = False

    cells: dict[tuple[float, float], dict] = {}

    if not _unknown_status:
        # ------------------------------------------------------------------
        # Query 1: pickup aggregation
        # ------------------------------------------------------------------
        from geoalchemy2.functions import ST_X, ST_Y  # noqa: PLC0415

        pickup_lat_col = func.round(
            cast(ST_Y(Ride.pickup_location), Numeric), precision
        ).label("cell_lat")
        pickup_lng_col = func.round(
            cast(ST_X(Ride.pickup_location), Numeric), precision
        ).label("cell_lng")
        pickup_count_col = func.count(Ride.id).label("pickup_count")
        avg_fare_col = func.avg(
            func.coalesce(Ride.actual_fare, Ride.estimated_fare)
        ).label("avg_fare")

        pickup_query = select(
            pickup_lat_col,
            pickup_lng_col,
            pickup_count_col,
            avg_fare_col,
        ).group_by(pickup_lat_col, pickup_lng_col)

        pickup_query = _apply_date_and_status_filters(
            pickup_query, start_date, end_date, status_enum
        )

        pickup_result = await db.execute(pickup_query)

        for row in pickup_result:
            lat = _to_float(row.cell_lat)
            lng = _to_float(row.cell_lng)
            if lat is None or lng is None:
                continue
            key = (lat, lng)
            cells[key] = {
                "lat": lat,
                "lng": lng,
                "pickup_count": int(row.pickup_count),
                "dropoff_count": 0,
                "avg_fare": _to_float(row.avg_fare),
            }

        # ------------------------------------------------------------------
        # Query 2: dropoff aggregation
        # ------------------------------------------------------------------
        dropoff_lat_col = func.round(
            cast(ST_Y(Ride.dropoff_location), Numeric), precision
        ).label("cell_lat")
        dropoff_lng_col = func.round(
            cast(ST_X(Ride.dropoff_location), Numeric), precision
        ).label("cell_lng")
        dropoff_count_col = func.count(Ride.id).label("dropoff_count")

        dropoff_query = select(
            dropoff_lat_col,
            dropoff_lng_col,
            dropoff_count_col,
        ).group_by(dropoff_lat_col, dropoff_lng_col)

        dropoff_query = _apply_date_and_status_filters(
            dropoff_query, start_date, end_date, status_enum
        )

        dropoff_result = await db.execute(dropoff_query)

        for row in dropoff_result:
            lat = _to_float(row.cell_lat)
            lng = _to_float(row.cell_lng)
            if lat is None or lng is None:
                continue
            key = (lat, lng)
            if key in cells:
                cells[key]["dropoff_count"] = int(row.dropoff_count)
            else:
                cells[key] = {
                    "lat": lat,
                    "lng": lng,
                    "pickup_count": 0,
                    "dropoff_count": int(row.dropoff_count),
                    "avg_fare": None,
                }

    # ------------------------------------------------------------------
    # Build response
    # ------------------------------------------------------------------
    heatmap_cells = []
    for cell_data in cells.values():
        total_activity = cell_data["pickup_count"] + cell_data["dropoff_count"]
        if total_activity < min_activity:
            continue
        heatmap_cells.append(
            HeatmapCell(
                lat=cell_data["lat"],
                lng=cell_data["lng"],
                pickup_count=cell_data["pickup_count"],
                dropoff_count=cell_data["dropoff_count"],
                total_activity=total_activity,
                avg_fare=round(cell_data["avg_fare"], 2)
                if cell_data["avg_fare"] is not None
                else None,
            )
        )

    # Sort by total_activity descending (hottest cells first)
    heatmap_cells.sort(key=lambda c: c.total_activity, reverse=True)

    filters = HeatmapFilters(
        start_date=start_date,
        end_date=end_date,
        status=status,
        precision=precision,
        min_activity=min_activity,
    )

    return HeatmapResponse(
        cells=heatmap_cells,
        total_cells=len(heatmap_cells),
        generated_at=datetime.now(timezone.utc),
        filters=filters,
    )
