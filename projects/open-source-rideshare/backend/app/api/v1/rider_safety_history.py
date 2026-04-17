"""Rider safety incident history endpoint.

GET /riders/me/safety-incidents

Returns a paginated, filterable history of safety events the authenticated
rider has triggered (panic alerts).  Designed to be extensible as new
incident types are added.

Query parameters:
  - incident_type: "all" | "PANIC_ALERT"  (default "all")
  - status:        "all" | "active" | "resolved" | "false_alarm"  (default "all")
  - from_date:     YYYY-MM-DD — filter by triggered_at date ≥ this (inclusive)
  - to_date:       YYYY-MM-DD — filter by triggered_at date ≤ this (inclusive)
  - limit:         1–100, default 20
  - offset:        ≥0, default 0

Validation:
  - 422 when from_date > to_date
  - 422 when limit or offset out of range (FastAPI handles via Query constraints)

Business logic is entirely in the service layer.  This module handles HTTP
mapping only.
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.deps import get_current_user
from app.db.database import get_db
from app.models.user import User
from app.schemas.rider_safety_history import RiderSafetyHistory
from app.services.rider_safety_history import (
    DEFAULT_LIMIT,
    MAX_LIMIT,
    get_rider_safety_history,
)
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

router = APIRouter(tags=["rider-safety"])

_INCIDENT_TYPE_CHOICES = {"all", "PANIC_ALERT"}
_STATUS_CHOICES = {"all", "active", "resolved", "false_alarm"}


@router.get(
    "/riders/me/safety-incidents",
    response_model=RiderSafetyHistory,
    summary="Rider safety incident history",
    description=(
        "Return a paginated, filterable history of safety events triggered by "
        "the authenticated rider.  Includes an all-time summary (unaffected by "
        "filters) alongside the filtered, paginated incident list.\n\n"
        "**Filters**\n"
        "- `incident_type`: `all` (default) or `PANIC_ALERT`\n"
        "- `status`: `all` (default), `active`, `resolved`, `false_alarm`\n"
        "- `from_date` / `to_date`: YYYY-MM-DD, applied to trigger date in UTC (both inclusive)\n"
        "- `limit` / `offset`: pagination (limit 1–100, default 20)\n\n"
        "Returns 422 if `from_date` is after `to_date`."
    ),
)
async def get_safety_incidents(
    incident_type: str = Query(
        "all",
        description="Filter by incident type: 'all' or 'PANIC_ALERT'.",
    ),
    status: str = Query(
        "all",
        description="Filter by status: 'all', 'active', 'resolved', or 'false_alarm'.",
    ),
    from_date: Optional[date] = Query(
        None,
        description="Include only incidents on or after this date (YYYY-MM-DD, UTC, inclusive).",
    ),
    to_date: Optional[date] = Query(
        None,
        description="Include only incidents on or before this date (YYYY-MM-DD, UTC, inclusive).",
    ),
    limit: int = Query(
        DEFAULT_LIMIT,
        ge=1,
        le=MAX_LIMIT,
        description=f"Page size (1–{MAX_LIMIT}, default {DEFAULT_LIMIT}).",
    ),
    offset: int = Query(
        0,
        ge=0,
        description="Page offset (0-indexed).",
    ),
    rider: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> RiderSafetyHistory:
    """Return paginated safety incident history for the authenticated rider."""
    # Validate enum-like query params
    if incident_type not in _INCIDENT_TYPE_CHOICES:
        raise HTTPException(
            status_code=status_code_422(),
            detail=(
                f"Invalid incident_type '{incident_type}'. "
                f"Must be one of: {sorted(_INCIDENT_TYPE_CHOICES)}."
            ),
        )
    if status not in _STATUS_CHOICES:
        raise HTTPException(
            status_code=status_code_422(),
            detail=(
                f"Invalid status '{status}'. "
                f"Must be one of: {sorted(_STATUS_CHOICES)}."
            ),
        )

    # Validate date range
    if from_date is not None and to_date is not None and from_date > to_date:
        raise HTTPException(
            status_code=status_code_422(),
            detail="from_date must not be later than to_date.",
        )

    result = await get_rider_safety_history(
        db=db,
        rider_id=rider.id,
        incident_type=incident_type,
        status=status,
        from_date=from_date,
        to_date=to_date,
        limit=limit,
        offset=offset,
    )

    return RiderSafetyHistory(**result)


def status_code_422() -> int:
    """Return HTTP 422 status code (named to avoid shadowing the 'status' query param)."""
    return 422
