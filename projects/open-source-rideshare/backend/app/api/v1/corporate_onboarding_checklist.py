"""Corporate Account Onboarding Checklist endpoints.

Account-member endpoints (any active member):
  GET  /corporate/accounts/me/onboarding-checklist

Platform-admin endpoints:
  GET  /admin/corporate/accounts/{account_id}/onboarding-checklist
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, require_admin
from app.models.user import User
from app.schemas.corporate_onboarding_checklist import OnboardingChecklistResponse
from app.services.corporate_account_mgmt import get_user_account
from app.services.corporate_onboarding_checklist import get_onboarding_checklist

logger = logging.getLogger(__name__)

router = APIRouter(tags=["corporate-onboarding-checklist"])


# ---------------------------------------------------------------------------
# Internal helper
# ---------------------------------------------------------------------------


async def _resolve_account_id(db: AsyncSession, user_id: int) -> int:
    """Return the account_id for the authenticated user.

    Raises HTTP 404 when the user is not a member of any corporate account.
    """
    account = await get_user_account(db, user_id)
    if account is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="You are not a member of any corporate account.",
        )
    return account.id


# ---------------------------------------------------------------------------
# Member endpoint
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/accounts/me/onboarding-checklist",
    response_model=OnboardingChecklistResponse,
    summary="Get onboarding checklist for own corporate account",
)
async def get_my_onboarding_checklist(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return the setup checklist for the authenticated user's corporate account.

    Shows which onboarding steps (billing, employees, ride policy, cost centers,
    trip purposes, notifications, SSO, integrations) are complete and which
    remain to be configured.  Any active account member may call this endpoint.
    """
    account_id = await _resolve_account_id(db, user.id)
    return await get_onboarding_checklist(db, account_id)


# ---------------------------------------------------------------------------
# Platform admin endpoint
# ---------------------------------------------------------------------------


@router.get(
    "/admin/corporate/accounts/{account_id}/onboarding-checklist",
    response_model=OnboardingChecklistResponse,
    summary="Admin: get onboarding checklist for any corporate account",
)
async def admin_get_onboarding_checklist(
    account_id: int,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return the onboarding checklist for any corporate account (platform admin).

    Provides the same computed checklist as the member endpoint but does not
    require the admin to be a member of the target account.
    """
    return await get_onboarding_checklist(db, account_id)
