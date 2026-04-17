"""Driver governance participation report API endpoint.

GET /drivers/me/governance-participation

Rationale:
    A cooperative rideshare platform is owned and governed by its driver-members.
    Drivers vote on fee rates, bonus structures, and platform policy changes; they
    elect board representatives in formal elections; their legislative proposals
    can become platform rules.  No Uber or Lyft equivalent of this endpoint exists
    because traditional gig platforms have no meaningful driver governance.

    This endpoint surfaces the full governance record for the authenticated driver:
    how many proposals they submitted and whether those proposals passed, how many
    eligible proposals they voted on, their vote breakdown, board elections they
    participated in or ran for, and what is currently open for their input.  A
    driver-owned cooperative owes its member-owners this visibility.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_driver
from app.db.database import get_db
from app.models.user import User
from app.schemas.driver_governance_participation import DriverGovernanceParticipation
from app.services.driver_governance_participation import (
    get_driver_governance_participation,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["driver-governance"])


@router.get(
    "/drivers/me/governance-participation",
    response_model=DriverGovernanceParticipation,
    summary="Driver governance participation report",
    description=(
        "Returns the authenticated driver's full cooperative governance participation "
        "record.  Includes:\n\n"
        "- **Proposals submitted**: total submitted and how many passed\n"
        "- **Votes cast**: total votes across all proposals with yes/no/abstain breakdown\n"
        "- **Participation rate**: votes cast vs. eligible proposals (driver's current "
        "ride count determines eligibility)\n"
        "- **Board elections**: elections participated in, ran for, and won\n"
        "- **Open proposals**: proposals currently accepting votes that the driver "
        "is eligible for but hasn't voted on yet\n"
        "- **Active elections**: board elections in nominations or voting phase\n"
        "- **Engagement tier**: 'active' (≥ 75%), 'engaged' (50–74%), 'occasional' "
        "(1–49%), 'new' (< 50 rides), or 'eligible_not_participating'\n"
        "- **Participation note**: plain-language summary of governance engagement\n\n"
        "This is a deliberate cooperative differentiator — member-owners have a right "
        "to know their own civic engagement record and what decisions are pending their "
        "input.  No Uber or Lyft equivalent exists."
    ),
)
async def get_governance_participation(
    driver: User = Depends(require_driver),
    db: AsyncSession = Depends(get_db),
) -> DriverGovernanceParticipation:
    """Return the governance participation report for the authenticated driver."""
    return await get_driver_governance_participation(db=db, user_id=driver.id)
