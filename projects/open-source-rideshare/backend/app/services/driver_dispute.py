"""Driver dispute resolution service.

Provides due-process dispute resolution for cooperative driver-members.

On traditional gig platforms (Uber, Lyft), drivers have no meaningful
recourse: fares get silently adjusted, accounts deactivated without
explanation, false rider complaints accepted without review.  A cooperative
platform is legally and ethically obligated to provide its member-owners
with a formal dispute process — the right to file a grievance, have it
reviewed, appeal an unfavorable decision, and receive a timely resolution.

This service implements that process.  All storage is in-memory (same
pattern as other services in this codebase).  A production implementation
would replace the in-memory store with proper async DB calls via SQLAlchemy.

Public API:
    file_dispute(db, driver_id, dispute_type, description, ride_id, amount_disputed_usd) -> dict
    list_driver_disputes(db, driver_id, status_filter, skip, limit) -> tuple[int, list[dict]]
    get_dispute(db, driver_id, dispute_id) -> dict | None
    appeal_decision(db, driver_id, dispute_id, appeal_reason) -> dict
    withdraw_dispute(db, driver_id, dispute_id) -> dict
    admin_list_disputes(db, status_filter, dispute_type_filter, skip, limit) -> tuple[int, list[dict]]
    admin_resolve_dispute(db, dispute_id, resolution, admin_notes, admin_id) -> dict
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.driver_dispute import DisputeStatus, DisputeType

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# In-memory store (same pattern as other services in this codebase)
# ---------------------------------------------------------------------------

_disputes: dict[int, dict] = {}
_next_id: int = 1


def _utc_now() -> datetime:
    return datetime.now(tz=timezone.utc)


def _is_overdue(dispute: dict) -> bool:
    """Return True if filed > 14 days ago and still OPEN or UNDER_REVIEW."""
    overdue_statuses = {DisputeStatus.OPEN, DisputeStatus.UNDER_REVIEW}
    if dispute["status"] not in overdue_statuses:
        return False
    return _utc_now() - dispute["filed_at"] > timedelta(days=14)


def _enrich(dispute: dict) -> dict:
    """Return a copy of the dispute dict with is_overdue computed."""
    return {**dispute, "is_overdue": _is_overdue(dispute)}


# ---------------------------------------------------------------------------
# Driver-facing operations
# ---------------------------------------------------------------------------


async def file_dispute(
    db: AsyncSession,
    driver_id: int,
    dispute_type: DisputeType,
    description: str,
    ride_id: Optional[int],
    amount_disputed_usd: Optional[Decimal],
) -> dict:
    """File a new dispute on behalf of the driver.

    Args:
        db:                  Async database session (unused in mock implementation).
        driver_id:           Authenticated driver's user ID.
        dispute_type:        Category of the dispute.
        description:         Driver's account of the issue (20–2000 chars).
        ride_id:             Related ride ID, if applicable.
        amount_disputed_usd: Dollar amount disputed, if monetary.

    Returns:
        The newly created dispute as a dict (ready for DisputeResponse).
    """
    global _next_id
    now = _utc_now()
    dispute_id = _next_id
    _next_id += 1

    dispute = {
        "id": dispute_id,
        "driver_id": driver_id,
        "dispute_type": dispute_type,
        "status": DisputeStatus.OPEN,
        "description": description,
        "ride_id": ride_id,
        "amount_disputed_usd": amount_disputed_usd,
        "filed_at": now,
        "updated_at": now,
        "resolution_at": None,
        "admin_notes": None,
        "appeal_reason": None,
        "appeal_filed_at": None,
    }
    _disputes[dispute_id] = dispute
    logger.info("Driver %s filed dispute %s type=%s", driver_id, dispute_id, dispute_type)
    return _enrich(dispute)


async def list_driver_disputes(
    db: AsyncSession,
    driver_id: int,
    status_filter: Optional[DisputeStatus],
    skip: int,
    limit: int,
) -> tuple[int, list[dict]]:
    """Return paginated disputes belonging to the authenticated driver.

    Args:
        db:            Async database session (unused in mock implementation).
        driver_id:     Authenticated driver's user ID.
        status_filter: If provided, only return disputes with this status.
        skip:          Pagination offset.
        limit:         Maximum number of results to return.

    Returns:
        (total, items) — total count before pagination, and the page of disputes.
    """
    matches = [
        d for d in _disputes.values()
        if d["driver_id"] == driver_id
        and (status_filter is None or d["status"] == status_filter)
    ]
    # Sorted newest-first for predictable ordering
    matches.sort(key=lambda d: d["filed_at"], reverse=True)
    total = len(matches)
    page = matches[skip: skip + limit]
    return total, [_enrich(d) for d in page]


async def get_dispute(
    db: AsyncSession,
    driver_id: int,
    dispute_id: int,
) -> Optional[dict]:
    """Retrieve a single dispute that belongs to the authenticated driver.

    Args:
        db:         Async database session (unused in mock implementation).
        driver_id:  Authenticated driver's user ID.
        dispute_id: ID of the dispute to retrieve.

    Returns:
        The dispute dict if it exists and belongs to driver_id, else None.
        Callers should raise HTTP 404 when None is returned.
        The ownership check (driver_id match) is also the 403 guard — callers
        receive None whether the dispute does not exist or belongs to another
        driver, so the HTTP layer should return 404 rather than leaking
        existence to a different driver.
    """
    dispute = _disputes.get(dispute_id)
    if dispute is None or dispute["driver_id"] != driver_id:
        return None
    return _enrich(dispute)


async def appeal_decision(
    db: AsyncSession,
    driver_id: int,
    dispute_id: int,
    appeal_reason: str,
) -> dict:
    """Appeal a RESOLVED_AGAINST_DRIVER decision.

    Transitions the dispute from RESOLVED_AGAINST_DRIVER to PENDING_APPEAL.

    Args:
        db:           Async database session (unused in mock implementation).
        driver_id:    Authenticated driver's user ID.
        dispute_id:   ID of the dispute to appeal.
        appeal_reason: Driver's stated reason for the appeal (20–1000 chars).

    Returns:
        Updated dispute dict.

    Raises:
        PermissionError: If dispute_id does not exist or belongs to another driver.
        ValueError:      If the dispute is not in RESOLVED_AGAINST_DRIVER status.
    """
    dispute = _disputes.get(dispute_id)
    if dispute is None or dispute["driver_id"] != driver_id:
        raise PermissionError(f"Dispute {dispute_id} not found or not owned by driver {driver_id}")

    if dispute["status"] != DisputeStatus.RESOLVED_AGAINST_DRIVER:
        raise ValueError(
            f"Cannot appeal dispute in status '{dispute['status'].value}'. "
            "Only RESOLVED_AGAINST_DRIVER disputes can be appealed."
        )

    now = _utc_now()
    dispute["status"] = DisputeStatus.PENDING_APPEAL
    dispute["appeal_reason"] = appeal_reason
    dispute["appeal_filed_at"] = now
    dispute["updated_at"] = now
    logger.info("Driver %s filed appeal on dispute %s", driver_id, dispute_id)
    return _enrich(dispute)


async def withdraw_dispute(
    db: AsyncSession,
    driver_id: int,
    dispute_id: int,
) -> dict:
    """Withdraw an OPEN or UNDER_REVIEW dispute.

    Args:
        db:         Async database session (unused in mock implementation).
        driver_id:  Authenticated driver's user ID.
        dispute_id: ID of the dispute to withdraw.

    Returns:
        Updated dispute dict.

    Raises:
        PermissionError: If dispute_id does not exist or belongs to another driver.
        ValueError:      If the dispute is not in OPEN or UNDER_REVIEW status.
    """
    dispute = _disputes.get(dispute_id)
    if dispute is None or dispute["driver_id"] != driver_id:
        raise PermissionError(f"Dispute {dispute_id} not found or not owned by driver {driver_id}")

    withdrawable = {DisputeStatus.OPEN, DisputeStatus.UNDER_REVIEW}
    if dispute["status"] not in withdrawable:
        raise ValueError(
            f"Cannot withdraw dispute in status '{dispute['status'].value}'. "
            "Only OPEN or UNDER_REVIEW disputes can be withdrawn."
        )

    now = _utc_now()
    dispute["status"] = DisputeStatus.WITHDRAWN
    dispute["updated_at"] = now
    logger.info("Driver %s withdrew dispute %s", driver_id, dispute_id)
    return _enrich(dispute)


# ---------------------------------------------------------------------------
# Admin operations
# ---------------------------------------------------------------------------

# Resolution statuses that admins are allowed to set
_ADMIN_ALLOWED_RESOLUTIONS = {
    DisputeStatus.RESOLVED_IN_DRIVER_FAVOR,
    DisputeStatus.RESOLVED_AGAINST_DRIVER,
    DisputeStatus.DISMISSED,
}


async def admin_list_disputes(
    db: AsyncSession,
    status_filter: Optional[DisputeStatus],
    dispute_type_filter: Optional[DisputeType],
    skip: int,
    limit: int,
) -> tuple[int, list[dict]]:
    """List all disputes across all drivers (admin view).

    Args:
        db:                  Async database session (unused in mock implementation).
        status_filter:       If provided, filter by this status.
        dispute_type_filter: If provided, filter by this dispute type.
        skip:                Pagination offset.
        limit:               Maximum number of results.

    Returns:
        (total, items) — total count before pagination, and the page of disputes.
    """
    matches = [
        d for d in _disputes.values()
        if (status_filter is None or d["status"] == status_filter)
        and (dispute_type_filter is None or d["dispute_type"] == dispute_type_filter)
    ]
    matches.sort(key=lambda d: d["filed_at"], reverse=True)
    total = len(matches)
    page = matches[skip: skip + limit]
    return total, [_enrich(d) for d in page]


async def admin_resolve_dispute(
    db: AsyncSession,
    dispute_id: int,
    resolution: DisputeStatus,
    admin_notes: Optional[str],
    admin_id: int,
) -> dict:
    """Resolve a dispute (admin operation).

    Allowed resolutions: RESOLVED_IN_DRIVER_FAVOR, RESOLVED_AGAINST_DRIVER, DISMISSED.

    When resolving a PENDING_APPEAL dispute, RESOLVED_AGAINST_DRIVER is not
    permitted — that was the original decision.  Only RESOLVED_IN_DRIVER_FAVOR
    or DISMISSED are valid for appeals.

    Args:
        db:          Async database session (unused in mock implementation).
        dispute_id:  ID of the dispute to resolve.
        resolution:  New status (must be in _ADMIN_ALLOWED_RESOLUTIONS).
        admin_notes: Optional internal admin notes.
        admin_id:    ID of the admin performing the resolution (for audit trail).

    Returns:
        Updated dispute dict.

    Raises:
        KeyError:   If the dispute does not exist.
        ValueError: If the resolution status is not permitted.
    """
    dispute = _disputes.get(dispute_id)
    if dispute is None:
        raise KeyError(f"Dispute {dispute_id} not found")

    if resolution not in _ADMIN_ALLOWED_RESOLUTIONS:
        raise ValueError(
            f"'{resolution.value}' is not a valid resolution status.  "
            f"Allowed: {[r.value for r in _ADMIN_ALLOWED_RESOLUTIONS]}"
        )

    # When resolving an appeal, RESOLVED_AGAINST_DRIVER re-affirms the original
    # decision in a confusing way — the cooperative standard is to either
    # uphold the appeal (RESOLVED_IN_DRIVER_FAVOR) or dismiss it.
    if (
        dispute["status"] == DisputeStatus.PENDING_APPEAL
        and resolution == DisputeStatus.RESOLVED_AGAINST_DRIVER
    ):
        raise ValueError(
            "Cannot set RESOLVED_AGAINST_DRIVER on a PENDING_APPEAL dispute.  "
            "Use RESOLVED_IN_DRIVER_FAVOR to uphold the appeal, or DISMISSED to reject it."
        )

    now = _utc_now()
    dispute["status"] = resolution
    dispute["admin_notes"] = admin_notes
    dispute["resolution_at"] = now
    dispute["updated_at"] = now
    logger.info(
        "Admin %s resolved dispute %s as %s", admin_id, dispute_id, resolution.value
    )
    return _enrich(dispute)


# ---------------------------------------------------------------------------
# Test helper — allows tests to reset the in-memory store between runs
# ---------------------------------------------------------------------------


def _reset_store() -> None:
    """Clear all disputes and reset the ID counter.  For use in tests only."""
    global _next_id
    _disputes.clear()
    _next_id = 1
