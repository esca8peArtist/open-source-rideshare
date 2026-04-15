"""Corporate Account Dashboard endpoints.

Returns a single aggregated health snapshot for a corporate account — one
call replaces ~10 separate API calls when rendering an admin overview page.

Admin endpoint:
  GET /corporate/{account_id}/dashboard
      — any authenticated user; returns the account dashboard

Platform-admin endpoint:
  GET /platform-admin/corporate/{account_id}/dashboard
      — admin access required; returns dashboard for any account
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, require_admin
from app.models.user import User
from app.schemas.corporate_account_dashboard import CorporateAccountDashboard
from app.services.corporate_account_dashboard import get_account_dashboard

logger = logging.getLogger(__name__)

router = APIRouter(tags=["corporate-account-dashboard"])


# ---------------------------------------------------------------------------
# Admin: account dashboard
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/{account_id}/dashboard",
    response_model=CorporateAccountDashboard,
    summary="Get the aggregated health dashboard for a corporate account",
)
async def get_corporate_account_dashboard(
    account_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return a consolidated snapshot of the corporate account's current state.

    Aggregates member counts, spend vs budget, credit balance, pending items,
    integration setup health, budget alerts, and active blackout periods into
    a single response.

    Raises 404 when *account_id* does not exist.
    """
    dashboard = await get_account_dashboard(db, account_id=account_id)
    return CorporateAccountDashboard(**dashboard)


# ---------------------------------------------------------------------------
# Platform-admin: account dashboard (any account)
# ---------------------------------------------------------------------------


@router.get(
    "/platform-admin/corporate/{account_id}/dashboard",
    response_model=CorporateAccountDashboard,
    summary="Platform admin: get dashboard for any corporate account",
)
async def platform_admin_get_corporate_dashboard(
    account_id: int,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return the aggregated dashboard for any corporate account.

    Raises 404 when *account_id* does not exist.
    """
    dashboard = await get_account_dashboard(db, account_id=account_id)
    return CorporateAccountDashboard(**dashboard)
