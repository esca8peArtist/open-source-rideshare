"""Driver Mentorship Program endpoints.

Driver endpoints (authenticated, driver role):
  POST  /drivers/me/mentorship/request         — new driver requests mentorship
  GET   /drivers/me/mentorship                 — view own mentorship status (as mentee)
  GET   /drivers/me/mentees                    — list mentees (for mentors)
  GET   /drivers/me/mentorship/earnings        — commission earnings summary (for mentors)

Admin endpoints (ADMIN role):
  GET   /admin/mentorships                     — list all mentorships (filterable)
  POST  /admin/mentorships/{id}/assign         — assign a mentor
  POST  /admin/mentorships/{id}/cancel         — cancel a mentorship
  GET   /admin/mentorships/summary             — platform-wide stats
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_admin, require_driver
from app.models.driver_mentorship import MentorshipStatus
from app.models.user import User
from app.schemas.driver_mentorship import (
    AdminAssignMentorRequest,
    AdminCancelMentorshipRequest,
    AdminMentorshipSummary,
    MenteeListItem,
    MentorEarningSummary,
    MentorshipEarningResponse,
    MentorshipRequestCreate,
    MentorshipResponse,
)
from app.services import driver_mentorship as svc
from app.services.driver_mentorship import MentorshipError

logger = logging.getLogger(__name__)

router = APIRouter(tags=["driver-mentorship"])


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _http(exc: MentorshipError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.message)


# ---------------------------------------------------------------------------
# Driver self-service
# ---------------------------------------------------------------------------


@router.post(
    "/drivers/me/mentorship/request",
    response_model=MentorshipResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Request mentorship assignment",
)
async def request_mentorship(
    body: MentorshipRequestCreate,
    user: User = Depends(require_driver),
    db: AsyncSession = Depends(get_db),
):
    """Submit a request to be matched with a mentor.

    Only one pending or active mentorship is allowed at a time (409 if one
    already exists).
    """
    try:
        m = await svc.request_mentorship(db, user.id, note=body.note)
    except MentorshipError as exc:
        raise _http(exc)
    return MentorshipResponse.model_validate(m)


@router.get(
    "/drivers/me/mentorship",
    response_model=MentorshipResponse | None,
    summary="Get own mentorship status (as mentee)",
)
async def get_my_mentorship(
    user: User = Depends(require_driver),
    db: AsyncSession = Depends(get_db),
):
    """Return the most recent mentorship record for the authenticated driver
    (as mentee).  Returns null if no mentorship record exists.
    """
    m = await svc.get_mentee_mentorship(db, user.id)
    return MentorshipResponse.model_validate(m) if m else None


@router.get(
    "/drivers/me/mentees",
    response_model=list[MenteeListItem],
    summary="List mentees (for mentors)",
)
async def list_my_mentees(
    status_filter: MentorshipStatus | None = Query(default=None),
    user: User = Depends(require_driver),
    db: AsyncSession = Depends(get_db),
):
    """Return mentorships where the authenticated driver is the mentor."""
    mentorships = await svc.get_mentor_mentees(db, user.id, status_filter)
    items = []
    for m in mentorships:
        # Sum commission earned for this mentorship.
        total_commission = sum(e.commission_amount for e in (m.earnings or []))
        items.append(
            MenteeListItem(
                id=m.id,
                mentee_id=m.mentee_id,
                status=m.status,
                started_at=m.started_at,
                ends_at=m.ends_at,
                total_commission_earned=round(total_commission, 2),
            )
        )
    return items


@router.get(
    "/drivers/me/mentorship/earnings",
    response_model=MentorEarningSummary,
    summary="Commission earnings summary (for mentors)",
)
async def get_my_earnings_summary(
    user: User = Depends(require_driver),
    db: AsyncSession = Depends(get_db),
):
    """Return aggregated commission totals for the authenticated mentor."""
    summary = await svc.get_mentor_earning_summary(db, user.id)
    return MentorEarningSummary(**summary)


# ---------------------------------------------------------------------------
# Admin endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/admin/mentorships",
    response_model=list[MentorshipResponse],
    summary="List all mentorships (admin)",
)
async def admin_list_mentorships(
    status_filter: MentorshipStatus | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return all mentorship records, optionally filtered by status."""
    mentorships = await svc.list_mentorships(db, status_filter, limit, offset)
    return [MentorshipResponse.model_validate(m) for m in mentorships]


@router.get(
    "/admin/mentorships/summary",
    response_model=AdminMentorshipSummary,
    summary="Platform-wide mentorship statistics (admin)",
)
async def admin_mentorship_summary(
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return platform-wide counts and commission totals."""
    data = await svc.get_admin_summary(db)
    return AdminMentorshipSummary(**data)


@router.post(
    "/admin/mentorships/{mentorship_id}/assign",
    response_model=MentorshipResponse,
    summary="Assign a mentor to a pending mentorship (admin)",
)
async def admin_assign_mentor(
    mentorship_id: int,
    body: AdminAssignMentorRequest,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Activate a pending mentorship by assigning a mentor.

    Sets commission_rate and commission_days from the request (or defaults).
    Raises 409 if the mentorship is not pending.
    Raises 400 if mentor and mentee are the same person.
    """
    try:
        m = await svc.assign_mentor(
            db,
            mentorship_id=mentorship_id,
            mentor_user_id=body.mentor_id,
            commission_rate=body.commission_rate,
            commission_days=body.commission_days,
            admin_note=body.admin_note,
        )
    except MentorshipError as exc:
        raise _http(exc)
    return MentorshipResponse.model_validate(m)


@router.post(
    "/admin/mentorships/{mentorship_id}/cancel",
    response_model=MentorshipResponse,
    summary="Cancel a pending or active mentorship (admin)",
)
async def admin_cancel_mentorship(
    mentorship_id: int,
    body: AdminCancelMentorshipRequest,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Cancel a pending or active mentorship.

    Raises 409 if the mentorship is already completed or cancelled.
    """
    try:
        m = await svc.cancel_mentorship(
            db, mentorship_id, cancelled_by_id=user.id, reason=body.reason
        )
    except MentorshipError as exc:
        raise _http(exc)
    return MentorshipResponse.model_validate(m)
