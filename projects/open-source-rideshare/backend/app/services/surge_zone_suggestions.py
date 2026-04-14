"""Surge zone boundary suggestion service.

Analyses the trip heatmap to identify high-demand geographic clusters and
proposes new surge zone boundaries that admins can review and apply.

Algorithm
---------
1. Fetch pickup+dropoff heatmap data for the requested date range.
2. Filter cells whose ``total_activity`` meets ``min_activity``.
3. Cluster remaining cells using a greedy BFS expansion:
   - Seed with the highest-activity unvisited cell.
   - Expand: add any unvisited cell whose centre is within
     ``cluster_radius_km`` of any cell already in the cluster.
   - Repeat until no more neighbours; then seed the next cluster.
4. Discard clusters with fewer than ``min_cells`` cells.
5. For each cluster compute:
   - Activity-weighted centroid (center_lat, center_lon).
   - Radius = max haversine distance from centroid to any cell +
     half-cell-size buffer (accounts for the cell's own footprint).
   - Total activity, activity-weighted avg_fare.
   - Confidence = cluster.total_activity / max_cluster.total_activity.
   - Suggested multiplier: 1.2 + confidence * 0.8 → [1.2, 2.0].
6. Check each centroid against active surge zones to flag overlaps.
7. Sort by total_activity descending; return top ``max_suggestions``.

All functions are read-only; no data is mutated here.
"""
from __future__ import annotations

import math
from collections import deque
from datetime import date, datetime, timezone

from app.schemas.surge_zone_suggestions import (
    ZoneSuggestion,
    ZoneSuggestionsFilters,
    ZoneSuggestionsResponse,
)
from app.services.surge_zones import list_zones
from app.services.trip_heatmap import get_trip_heatmap


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Multiplier range for suggestions
_MULT_MIN: float = 1.2
_MULT_MAX: float = 2.0

# Half-cell buffer added to cluster radius to cover cell footprint.
# At precision=2, one cell spans ~1.1 km → half ≈ 0.55 km.
# At precision=1 it's ~5.5 km, at precision=3 ~0.055 km.
# We compute this dynamically from the precision value.
_EARTH_RADIUS_KM: float = 6371.0


# ---------------------------------------------------------------------------
# Pure geo helpers
# ---------------------------------------------------------------------------


def _haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Return the great-circle distance in km between two lat/lon points."""
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(dlon / 2) ** 2
    )
    return _EARTH_RADIUS_KM * 2 * math.asin(math.sqrt(a))


def _cell_half_size_km(precision: int) -> float:
    """Approximate half-width of a heatmap cell at the given precision.

    A cell at precision *p* spans roughly (111 km / 10**p) in both lat and
    lon directions (longitude is less, but we use lat as a conservative
    approximation).  Half that width is the buffer we add to the cluster
    radius so the outer ring of cells is fully covered.
    """
    cell_size_km = 111.0 / (10 ** precision)
    return cell_size_km / 2.0


# ---------------------------------------------------------------------------
# Clustering helpers
# ---------------------------------------------------------------------------


def _cluster_cells(
    cells: list,
    cluster_radius_km: float,
    min_cells: int,
) -> list[list]:
    """Partition ``cells`` into clusters using greedy BFS expansion.

    Each seed is the highest-activity unvisited cell. Cells are added to
    the growing cluster if their centre lies within ``cluster_radius_km``
    of any cell already in the cluster (neighbour search is O(n²) but
    heatmap cell counts are small enough that this is fine).

    Clusters with fewer than ``min_cells`` members are discarded.

    Args:
        cells: list of objects with .lat, .lng, .total_activity attributes,
               pre-sorted descending by total_activity.
        cluster_radius_km: maximum distance between any two neighbouring cells.
        min_cells: discard clusters smaller than this.

    Returns:
        List of clusters; each cluster is a list of cell objects.
    """
    unvisited: set[int] = set(range(len(cells)))
    clusters: list[list] = []

    while unvisited:
        # Seed: highest-activity unvisited cell (cells are pre-sorted)
        seed_idx = next(iter(unvisited))
        # Find true minimum index among unvisited to get highest-activity seed
        seed_idx = min(unvisited)  # smallest index = highest activity (pre-sorted)
        unvisited.discard(seed_idx)

        cluster = [cells[seed_idx]]
        queue: deque[int] = deque([seed_idx])

        while queue:
            current_idx = queue.popleft()
            current = cells[current_idx]
            to_add: list[int] = []
            for idx in list(unvisited):
                candidate = cells[idx]
                dist = _haversine(
                    current.lat, current.lng,
                    candidate.lat, candidate.lng,
                )
                if dist <= cluster_radius_km:
                    to_add.append(idx)

            for idx in to_add:
                unvisited.discard(idx)
                cluster.append(cells[idx])
                queue.append(idx)

        if len(cluster) >= min_cells:
            clusters.append(cluster)

    return clusters


def _compute_weighted_centroid(cluster: list) -> tuple[float, float]:
    """Return the activity-weighted centroid (lat, lon) of a cluster."""
    total_weight = sum(c.total_activity for c in cluster)
    if total_weight == 0:
        # Uniform fallback
        lat = sum(c.lat for c in cluster) / len(cluster)
        lon = sum(c.lng for c in cluster) / len(cluster)
        return lat, lon
    lat = sum(c.lat * c.total_activity for c in cluster) / total_weight
    lon = sum(c.lng * c.total_activity for c in cluster) / total_weight
    return lat, lon


def _compute_radius(
    center_lat: float,
    center_lon: float,
    cluster: list,
    precision: int,
) -> float:
    """Return the radius in km that covers all cells plus a half-cell buffer."""
    if not cluster:
        return _cell_half_size_km(precision)
    max_dist = max(
        _haversine(center_lat, center_lon, c.lat, c.lng)
        for c in cluster
    )
    return round(max_dist + _cell_half_size_km(precision), 3)


def _compute_avg_fare(cluster: list) -> float | None:
    """Activity-weighted average fare across cells that have fare data."""
    weighted_sum = 0.0
    weight_sum = 0.0
    for cell in cluster:
        if cell.avg_fare is not None:
            weighted_sum += cell.avg_fare * cell.total_activity
            weight_sum += cell.total_activity
    if weight_sum == 0:
        return None
    return round(weighted_sum / weight_sum, 2)


def _build_reason(
    cluster: list,
    total_activity: int,
    cell_count: int,
    confidence: float,
    overlaps: bool,
    overlapping_name: str | None,
) -> str:
    """Build a human-readable explanation for why this zone is suggested."""
    parts: list[str] = [
        f"{cell_count} high-demand grid cells with {total_activity} combined "
        f"pickup/dropoff events form a dense activity cluster."
    ]
    if confidence >= 0.8:
        parts.append("This is one of the busiest zones in the dataset.")
    elif confidence >= 0.5:
        parts.append("Demand is moderately elevated relative to the busiest cluster.")
    else:
        parts.append("Demand is lower than the busiest cluster but still above threshold.")

    if overlaps:
        parts.append(
            f"Note: centroid overlaps existing surge zone '{overlapping_name}' — "
            "consider adjusting the existing zone boundary instead of creating a new one."
        )
    return " ".join(parts)


def _suggest_multiplier(confidence: float) -> float:
    """Map a confidence score [0, 1] to a suggested multiplier [1.2, 2.0]."""
    raw = _MULT_MIN + confidence * (_MULT_MAX - _MULT_MIN)
    return round(max(_MULT_MIN, min(_MULT_MAX, raw)), 1)


# ---------------------------------------------------------------------------
# Overlap detection
# ---------------------------------------------------------------------------


def _check_overlaps(
    center_lat: float,
    center_lon: float,
    active_zones: list,
) -> tuple[bool, str | None]:
    """Return (overlaps, zone_name) for the first active zone whose boundary
    contains the centroid.

    Delegates to the existing point_in_zone logic from surge_zones.
    """
    from app.services.surge_zones import _point_in_zone  # noqa: PLC0415

    for zone in active_zones:
        if _point_in_zone(center_lat, center_lon, zone):
            return True, zone.name
    return False, None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def get_zone_boundary_suggestions(
    db,
    start_date: date | None = None,
    end_date: date | None = None,
    min_activity: int = 5,
    precision: int = 2,
    cluster_radius_km: float = 2.0,
    min_cells: int = 2,
    max_suggestions: int = 10,
) -> ZoneSuggestionsResponse:
    """Identify high-demand geographic clusters and propose surge zone boundaries.

    Args:
        db: async database session
        start_date: inclusive start date filter on ride requested_at
        end_date: inclusive end date filter on ride requested_at
        min_activity: minimum total_activity for a heatmap cell to be considered
        precision: heatmap grid precision (1–4 decimal places; default 2 ≈ 1.1 km cells)
        cluster_radius_km: max distance between neighbours in the same cluster
        min_cells: minimum cells a cluster must have to produce a suggestion
        max_suggestions: maximum number of suggestions to return

    Returns:
        ZoneSuggestionsResponse with up to ``max_suggestions`` suggestions.
    """
    # --- 1. Fetch heatmap data -----------------------------------------------
    heatmap = await get_trip_heatmap(
        db,
        start_date=start_date,
        end_date=end_date,
        precision=precision,
        min_activity=min_activity,
    )
    cells = heatmap.cells  # already sorted by total_activity descending

    # --- 2. Cluster cells ----------------------------------------------------
    if not cells:
        return ZoneSuggestionsResponse(
            suggestions=[],
            total_suggestions=0,
            filters=ZoneSuggestionsFilters(
                start_date=start_date,
                end_date=end_date,
                min_activity=min_activity,
                precision=precision,
                cluster_radius_km=cluster_radius_km,
                min_cells=min_cells,
                max_suggestions=max_suggestions,
            ),
            generated_at=datetime.now(timezone.utc),
        )

    clusters = _cluster_cells(cells, cluster_radius_km, min_cells)

    # --- 3. Sort clusters by total_activity descending -----------------------
    def _cluster_activity(cluster: list) -> int:
        return sum(c.total_activity for c in cluster)

    clusters.sort(key=_cluster_activity, reverse=True)

    max_activity = _cluster_activity(clusters[0]) if clusters else 1

    # --- 4. Fetch existing active zones for overlap detection ----------------
    active_zones = await list_zones(db, active_only=True)

    # --- 5. Build suggestions ------------------------------------------------
    suggestions: list[ZoneSuggestion] = []
    for idx, cluster in enumerate(clusters[:max_suggestions], start=1):
        total_activity = _cluster_activity(cluster)
        confidence = round(total_activity / max_activity, 3) if max_activity > 0 else 0.0
        center_lat, center_lon = _compute_weighted_centroid(cluster)
        center_lat = round(center_lat, 6)
        center_lon = round(center_lon, 6)
        radius_km = _compute_radius(center_lat, center_lon, cluster, precision)
        avg_fare = _compute_avg_fare(cluster)
        overlaps, overlapping_name = _check_overlaps(center_lat, center_lon, active_zones)
        reason = _build_reason(
            cluster,
            total_activity,
            len(cluster),
            confidence,
            overlaps,
            overlapping_name,
        )
        suggestions.append(
            ZoneSuggestion(
                suggestion_id=idx,
                center_lat=center_lat,
                center_lon=center_lon,
                radius_km=radius_km,
                suggested_multiplier=_suggest_multiplier(confidence),
                cell_count=len(cluster),
                total_activity=total_activity,
                avg_fare=avg_fare,
                confidence=confidence,
                reason=reason,
                overlaps_existing_zone=overlaps,
                overlapping_zone_name=overlapping_name,
            )
        )

    return ZoneSuggestionsResponse(
        suggestions=suggestions,
        total_suggestions=len(suggestions),
        filters=ZoneSuggestionsFilters(
            start_date=start_date,
            end_date=end_date,
            min_activity=min_activity,
            precision=precision,
            cluster_radius_km=cluster_radius_km,
            min_cells=min_cells,
            max_suggestions=max_suggestions,
        ),
        generated_at=datetime.now(timezone.utc),
    )
