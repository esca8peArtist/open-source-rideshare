"""Rider safety incident history service.

Aggregates a rider's safety events (panic alerts) into a paginated,
filterable history.  Uses the same in-memory store as rider_safety.py —
no separate state is maintained.

Public API:
    get_rider_safety_history(
        db, rider_id, incident_type, status, from_date, to_date, limit, offset
    ) -> dict

The returned dict matches the RiderSafetyHistory schema:
    {
        "total_count": int,            # filtered count (before pagination)
        "incidents": list[dict],       # page of records, newest-first
        "summary": {                   # all-time counts, unaffected by filters
            "total_all_time": int,
            "active_count": int,
            "resolved_count": int,
            "false_alarm_count": int,
        },
        "filters_applied": {
            "incident_type": str,
            "status": str,
            "from_date": date | None,
            "to_date": date | None,
            "limit": int,
            "offset": int,
        },
    }
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.rider_safety import PanicAlertStatus
from app.schemas.rider_safety_history import (
    SafetyIncidentStatusFilter,
    SafetyIncidentType,
)
from app.services.rider_safety import list_rider_panic_alerts

logger = logging.getLogger(__name__)

# Default and boundary constants
DEFAULT_LIMIT = 20
MAX_LIMIT = 100


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _parse_status(status_str: str) -> Optional[PanicAlertStatus]:
    """Map a SafetyIncidentStatusFilter string to a PanicAlertStatus, or None for 'all'."""
    mapping = {
        SafetyIncidentStatusFilter.ACTIVE: PanicAlertStatus.ACTIVE,
        SafetyIncidentStatusFilter.RESOLVED: PanicAlertStatus.RESOLVED,
        SafetyIncidentStatusFilter.FALSE_ALARM: PanicAlertStatus.FALSE_ALARM,
    }
    return mapping.get(SafetyIncidentStatusFilter(status_str))


def _apply_filters(
    alerts: list[dict],
    incident_type: str,
    status: str,
    from_date: Optional[date],
    to_date: Optional[date],
) -> list[dict]:
    """Filter a list of alert dicts by type, status, and date range.

    Args:
        alerts:        All alerts for the rider (any status), newest-first.
        incident_type: "all" or "PANIC_ALERT".
        status:        "all", "active", "resolved", or "false_alarm".
        from_date:     Include only incidents triggered on or after this date.
        to_date:       Include only incidents triggered on or before this date.

    Returns:
        Filtered list, preserving newest-first ordering.
    """
    result = alerts

    # incident_type filter — currently only PANIC_ALERT exists, but guard for future types
    if incident_type != "all":
        try:
            expected_type = SafetyIncidentType(incident_type)
        except ValueError:
            # Unknown type — no records can match
            return []
        # All records in _panic_alerts are PANIC_ALERTs; a different type would return nothing
        if expected_type != SafetyIncidentType.PANIC_ALERT:
            return []
        # If PANIC_ALERT, no further filtering needed — all records qualify

    # status filter
    status_enum = _parse_status(status)
    if status_enum is not None:
        result = [a for a in result if a["status"] == status_enum]

    # date range filter — apply to triggered_at (convert to date in UTC)
    if from_date is not None:
        result = [a for a in result if _to_utc_date(a["triggered_at"]) >= from_date]
    if to_date is not None:
        result = [a for a in result if _to_utc_date(a["triggered_at"]) <= to_date]

    return result


def _to_utc_date(dt: datetime) -> date:
    """Return the UTC calendar date for a datetime (timezone-aware or naive treated as UTC)."""
    if dt.tzinfo is None:
        return dt.date()
    return dt.astimezone(timezone.utc).date()


def _build_summary(all_alerts: list[dict]) -> dict:
    """Compute all-time counts from the rider's unfiltered alert list.

    Args:
        all_alerts: All panic alerts for the rider (any status).

    Returns:
        Summary dict matching SafetyIncidentSummary schema.
    """
    active = sum(1 for a in all_alerts if a["status"] == PanicAlertStatus.ACTIVE)
    resolved = sum(1 for a in all_alerts if a["status"] == PanicAlertStatus.RESOLVED)
    false_alarm = sum(1 for a in all_alerts if a["status"] == PanicAlertStatus.FALSE_ALARM)
    return {
        "total_all_time": len(all_alerts),
        "active_count": active,
        "resolved_count": resolved,
        "false_alarm_count": false_alarm,
    }


def _alert_to_incident(alert: dict) -> dict:
    """Convert a panic alert dict to a SafetyIncidentRecord dict.

    Args:
        alert: A panic alert dict from the rider_safety store.

    Returns:
        Incident record dict matching SafetyIncidentRecord schema.
    """
    status = alert["status"]
    status_str = status.value if hasattr(status, "value") else str(status)
    return {
        "id": alert["id"],
        "incident_type": SafetyIncidentType.PANIC_ALERT,
        "ride_id": alert["ride_id"],
        "driver_id": alert["driver_id"],
        "status": status_str,
        "location_lat": alert.get("location_lat"),
        "location_lng": alert.get("location_lng"),
        "triggered_at": alert["triggered_at"],
        "resolved_at": alert.get("resolved_at"),
        "resolution_notes": alert.get("resolution_notes"),
    }


# ---------------------------------------------------------------------------
# Public service function
# ---------------------------------------------------------------------------


async def get_rider_safety_history(
    db: AsyncSession,
    rider_id: int,
    incident_type: str = "all",
    status: str = "all",
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
    limit: int = DEFAULT_LIMIT,
    offset: int = 0,
) -> dict:
    """Return paginated, filtered safety incident history for a rider.

    Fetches all panic alerts for the rider, builds the all-time summary
    from the unfiltered set, then applies filters and pagination.

    Args:
        db:            Async database session (unused in this implementation).
        rider_id:      ID of the authenticated rider.
        incident_type: "all" or "PANIC_ALERT" (default "all").
        status:        "all", "active", "resolved", or "false_alarm" (default "all").
        from_date:     Inclusive lower bound on triggered_at date (UTC, optional).
        to_date:       Inclusive upper bound on triggered_at date (UTC, optional).
        limit:         Page size (1–100, default 20).
        offset:        Page offset (≥0, default 0).

    Returns:
        Dict matching the RiderSafetyHistory schema.
    """
    # Fetch all alerts for this rider (newest-first)
    all_alerts = await list_rider_panic_alerts(db=db, rider_id=rider_id)

    # Summary is built from the full unfiltered set
    summary = _build_summary(all_alerts)

    # Apply filters
    filtered = _apply_filters(
        alerts=all_alerts,
        incident_type=incident_type,
        status=status,
        from_date=from_date,
        to_date=to_date,
    )

    total_count = len(filtered)

    # Paginate
    page = filtered[offset: offset + limit]

    incidents = [_alert_to_incident(a) for a in page]

    logger.debug(
        "Safety history — rider=%s total=%d filtered=%d page=%d offset=%d",
        rider_id, len(all_alerts), total_count, len(page), offset,
    )

    return {
        "total_count": total_count,
        "incidents": incidents,
        "summary": summary,
        "filters_applied": {
            "incident_type": incident_type,
            "status": status,
            "from_date": from_date,
            "to_date": to_date,
            "limit": limit,
            "offset": offset,
        },
    }
