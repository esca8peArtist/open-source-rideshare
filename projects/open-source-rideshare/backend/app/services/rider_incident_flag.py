"""Rider incident flag service.

Automatically flags riders who accumulate INCIDENT_THRESHOLD driver safety
reports within INCIDENT_WINDOW_DAYS days.  A flag is raised (or refreshed) by
check_and_flag_rider(), which is called by driver_safety_report.create_report()
after each new report is persisted.

Only PENDING reports count toward the threshold — cleared/reviewed reports where
admin found no fault don't count, preventing spurious re-flags.  The window is
rolling (90 days back from now), not calendar-based.

Each rider has at most one flag record.  If the rider is already ACTIVE or
UNDER_REVIEW, the flag's report_count is updated in place.  A CLEARED flag is
re-raised as a new ACTIVE flag if the rider hits the threshold again.

Public API:
    check_and_flag_rider(db, rider_id, all_reports) -> dict | None
    get_flag(db, rider_id) -> dict | None
    admin_list_flags(db, status_filter, skip, limit) -> tuple[int, list[dict]]
    admin_review_flag(db, rider_id, admin_id, review_status, admin_notes) -> dict
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.rider_incident_flag import (
    INCIDENT_THRESHOLD,
    INCIDENT_WINDOW_DAYS,
    FlagStatus,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# In-memory store (keyed by rider_id)
# ---------------------------------------------------------------------------

_rider_incident_flags: dict[int, dict] = {}


def _utc_now() -> datetime:
    return datetime.now(tz=timezone.utc)


def _reset_store() -> None:
    """Clear all in-memory state.  For use in tests only."""
    _rider_incident_flags.clear()


# ---------------------------------------------------------------------------
# Internal helper
# ---------------------------------------------------------------------------


def _count_recent_reports(rider_id: int, all_reports: list[dict]) -> int:
    """Return the number of PENDING driver safety reports against rider_id
    filed within the rolling INCIDENT_WINDOW_DAYS window."""
    cutoff = _utc_now() - timedelta(days=INCIDENT_WINDOW_DAYS)
    return sum(
        1 for r in all_reports
        if (
            r["rider_id"] == rider_id
            and r["filed_at"] >= cutoff
            # Only pending reports count — reviewed/cleared ones don't fuel flags.
            and r["status"].value == "pending"
        )
    )


# ---------------------------------------------------------------------------
# Core flag logic
# ---------------------------------------------------------------------------


async def check_and_flag_rider(
    db: AsyncSession,
    rider_id: int,
    all_reports: list[dict],
) -> Optional[dict]:
    """Check whether rider_id has hit the incident threshold and raise/refresh
    a flag if so.

    Called after every new driver safety report is created.  Uses the
    caller-supplied report list to avoid a second store scan.

    Args:
        db:          Async DB session (unused — in-memory implementation).
        rider_id:    ID of the rider to check.
        all_reports: Full list of driver safety report dicts from the store.

    Returns:
        The flag dict if a flag was raised or refreshed, else None.
    """
    count = _count_recent_reports(rider_id, all_reports)
    if count < INCIDENT_THRESHOLD:
        return None

    now = _utc_now()
    existing = _rider_incident_flags.get(rider_id)

    if existing is None or existing["status"] == FlagStatus.CLEARED:
        # Raise a fresh flag (or re-raise after a previous clearance).
        flag = {
            "rider_id": rider_id,
            "report_count": count,
            "status": FlagStatus.ACTIVE,
            "flagged_at": now,
            "last_updated_at": now,
            "reviewed_by": None,
            "admin_notes": None,
        }
        _rider_incident_flags[rider_id] = flag
        logger.warning(
            "Rider incident flag RAISED — rider=%s report_count=%s", rider_id, count
        )
        return dict(flag)

    # Flag already ACTIVE or UNDER_REVIEW: refresh the count.
    existing["report_count"] = count
    existing["last_updated_at"] = now
    logger.info(
        "Rider incident flag REFRESHED — rider=%s report_count=%s status=%s",
        rider_id, count, existing["status"].value,
    )
    return dict(existing)


# ---------------------------------------------------------------------------
# Read operations
# ---------------------------------------------------------------------------


async def get_flag(
    db: AsyncSession,
    rider_id: int,
) -> Optional[dict]:
    """Return the current incident flag for rider_id, or None if no flag exists.

    Args:
        db:       Async DB session (unused).
        rider_id: ID of the rider.

    Returns:
        Flag dict, or None.
    """
    flag = _rider_incident_flags.get(rider_id)
    return dict(flag) if flag else None


async def admin_list_flags(
    db: AsyncSession,
    status_filter: Optional[str] = None,
    skip: int = 0,
    limit: int = 50,
) -> tuple[int, list[dict]]:
    """Return paginated rider incident flags for admin, newest-first.

    Args:
        db:            Async DB session (unused).
        status_filter: If set, only return flags with this status string.
        skip:          Pagination offset.
        limit:         Maximum records to return.

    Returns:
        (total, items) — filtered total and the requested page.
    """
    flags = list(_rider_incident_flags.values())

    if status_filter:
        flags = [f for f in flags if f["status"].value == status_filter]

    flags.sort(key=lambda f: f["flagged_at"], reverse=True)
    total = len(flags)
    page = flags[skip: skip + limit]
    return total, [dict(f) for f in page]


# ---------------------------------------------------------------------------
# Admin review
# ---------------------------------------------------------------------------


async def admin_review_flag(
    db: AsyncSession,
    rider_id: int,
    admin_id: int,
    review_status: FlagStatus,
    admin_notes: Optional[str] = None,
) -> dict:
    """Admin transitions an incident flag to UNDER_REVIEW or CLEARED.

    Args:
        db:            Async DB session (unused).
        rider_id:      ID of the rider whose flag is being reviewed.
        admin_id:      ID of the admin performing the review.
        review_status: New status — UNDER_REVIEW or CLEARED (not ACTIVE).
        admin_notes:   Optional notes on the review outcome.

    Returns:
        Updated flag dict.

    Raises:
        KeyError:   If no flag exists for this rider.
        ValueError: If review_status is ACTIVE (flags cannot be manually activated).
    """
    flag = _rider_incident_flags.get(rider_id)
    if flag is None:
        raise KeyError(f"No incident flag found for rider {rider_id}.")

    if review_status == FlagStatus.ACTIVE:
        raise ValueError(
            "Cannot manually set flag to 'active'. "
            "Flags are raised automatically when the threshold is exceeded."
        )

    now = _utc_now()
    flag["status"] = review_status
    flag["last_updated_at"] = now
    flag["reviewed_by"] = admin_id
    flag["admin_notes"] = admin_notes

    logger.info(
        "Admin %s reviewed rider incident flag — rider=%s new_status=%s",
        admin_id, rider_id, review_status.value,
    )
    return dict(flag)
