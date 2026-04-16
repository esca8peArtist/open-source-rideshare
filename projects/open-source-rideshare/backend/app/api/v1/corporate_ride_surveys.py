"""Corporate Ride Satisfaction Survey endpoints.

Enterprise admins create named surveys that employees complete after rides.
Admins view aggregated per-question analytics.

Member endpoints (any active account member):
  GET  /corporate/ride-surveys              — list active surveys for my account
  GET  /corporate/ride-surveys/{survey_id}  — get a specific survey
  POST /corporate/ride-surveys/respond      — submit a response
  GET  /corporate/ride-surveys/my-responses — list my own responses

Admin endpoints (account admins only):
  POST   /corporate/ride-surveys                          — create survey (201)
  PUT    /corporate/ride-surveys/{survey_id}              — update survey
  POST   /corporate/ride-surveys/{survey_id}/deactivate   — deactivate
  POST   /corporate/ride-surveys/{survey_id}/reactivate   — reactivate
  DELETE /corporate/ride-surveys/{survey_id}              — delete (204)
  GET    /corporate/ride-surveys/{survey_id}/responses    — list responses
  GET    /corporate/ride-surveys/{survey_id}/analytics    — get analytics

Platform-admin endpoints:
  GET  /platform-admin/corporate/ride-surveys                          — all surveys
  GET  /platform-admin/corporate/ride-surveys/for-account/{account_id} — by account
"""

from __future__ import annotations

import logging
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, require_admin
from app.models.corporate_ride_survey import CorporateRideSurveyResponse as _RespModel
from app.models.user import User
from app.schemas.corporate_ride_survey import (
    RideSurveyCreate,
    RideSurveyListResponse,
    RideSurveyResponse,
    RideSurveyUpdate,
    SurveyAnalyticsResponse,
    SurveyResponseCreate,
    SurveyResponseListResponse,
    SurveyResponseRecord,
)
from app.services.corporate_account_mgmt import get_user_account
from app.services.corporate_ride_survey import (
    create_survey,
    deactivate_survey,
    delete_survey,
    get_survey,
    get_survey_analytics,
    list_all_platform,
    list_responses,
    list_surveys,
    reactivate_survey,
    submit_response,
    update_survey,
)
from app.services.corporate_trip_purpose import _require_account_admin

logger = logging.getLogger(__name__)

router = APIRouter(tags=["corporate-ride-surveys"])


# ---------------------------------------------------------------------------
# Internal helper
# ---------------------------------------------------------------------------


async def _resolve_account_id(db: AsyncSession, user_id: int) -> int:
    """Return the account_id for the authenticated user.

    Raises HTTP 404 if the user is not a member of any corporate account.
    """
    account = await get_user_account(db, user_id)
    if account is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="You are not a member of any corporate account.",
        )
    return account.id


# ---------------------------------------------------------------------------
# Member: list active surveys
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/ride-surveys",
    response_model=RideSurveyListResponse,
    summary="List active surveys for my corporate account",
)
async def list_member_surveys(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return all active ride surveys for the authenticated user's account.

    Any active corporate account member may call this endpoint.
    """
    account_id = await _resolve_account_id(db, user.id)
    return await list_surveys(db, account_id, is_active=True)


# ---------------------------------------------------------------------------
# Member: submit a response — must come before /{survey_id}
# ---------------------------------------------------------------------------


@router.post(
    "/corporate/ride-surveys/respond",
    response_model=SurveyResponseRecord,
    status_code=status.HTTP_201_CREATED,
    summary="Submit a ride satisfaction survey response",
)
async def submit_survey_response(
    data: SurveyResponseCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Submit the authenticated member's response to a survey.

    Returns 404 if the survey does not exist or is inactive.
    Returns 409 if the member has already responded to this survey.
    Any active corporate account member may call this endpoint.
    """
    account_id = await _resolve_account_id(db, user.id)
    return await submit_response(
        db,
        survey_id=data.survey_id,
        account_id=account_id,
        member_id=user.id,
        ride_id=data.ride_id,
        responses=data.responses,
    )


# ---------------------------------------------------------------------------
# Member: list my own responses — must come before /{survey_id}
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/ride-surveys/my-responses",
    response_model=SurveyResponseListResponse,
    summary="List my own survey responses",
)
async def list_my_responses(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return all survey responses submitted by the authenticated member.

    Any active corporate account member may call this endpoint.
    """
    account_id = await _resolve_account_id(db, user.id)
    result = await db.execute(
        select(_RespModel).where(
            _RespModel.account_id == account_id,
            _RespModel.member_id == user.id,
        )
    )
    records = result.scalars().all()
    from app.services.corporate_ride_survey import _response_to_record

    return SurveyResponseListResponse(
        items=[_response_to_record(r) for r in records],
        total=len(records),
    )


# ---------------------------------------------------------------------------
# Member: get a specific survey
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/ride-surveys/{survey_id}",
    response_model=RideSurveyResponse,
    summary="Get a specific ride survey",
)
async def get_survey_endpoint(
    survey_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return a specific ride survey by ID.

    Any active corporate account member may call this endpoint.
    """
    account_id = await _resolve_account_id(db, user.id)
    return await get_survey(db, survey_id, account_id)


# ---------------------------------------------------------------------------
# Admin: create survey
# ---------------------------------------------------------------------------


@router.post(
    "/corporate/ride-surveys",
    response_model=RideSurveyResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new ride satisfaction survey (admin only)",
)
async def create_survey_endpoint(
    data: RideSurveyCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new ride satisfaction survey for the account.

    Returns 409 if a survey with the same title already exists.
    Only account admins may call this endpoint.
    """
    account_id = await _resolve_account_id(db, user.id)
    await _require_account_admin(db, account_id, user.id)
    return await create_survey(db, account_id, data, created_by_id=user.id)


# ---------------------------------------------------------------------------
# Admin: update survey
# ---------------------------------------------------------------------------


@router.put(
    "/corporate/ride-surveys/{survey_id}",
    response_model=RideSurveyResponse,
    summary="Update a ride satisfaction survey (admin only)",
)
async def update_survey_endpoint(
    survey_id: uuid.UUID,
    data: RideSurveyUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Partially update a ride survey.

    Returns 409 on duplicate title.  Only account admins may call this endpoint.
    """
    account_id = await _resolve_account_id(db, user.id)
    await _require_account_admin(db, account_id, user.id)
    return await update_survey(db, survey_id, account_id, data)


# ---------------------------------------------------------------------------
# Admin: deactivate survey
# ---------------------------------------------------------------------------


@router.post(
    "/corporate/ride-surveys/{survey_id}/deactivate",
    response_model=RideSurveyResponse,
    summary="Deactivate a ride survey (admin only)",
)
async def deactivate_survey_endpoint(
    survey_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Deactivate an active ride survey.

    Returns 409 if already inactive.  Only account admins may call this endpoint.
    """
    account_id = await _resolve_account_id(db, user.id)
    await _require_account_admin(db, account_id, user.id)
    return await deactivate_survey(db, survey_id, account_id)


# ---------------------------------------------------------------------------
# Admin: reactivate survey
# ---------------------------------------------------------------------------


@router.post(
    "/corporate/ride-surveys/{survey_id}/reactivate",
    response_model=RideSurveyResponse,
    summary="Reactivate a ride survey (admin only)",
)
async def reactivate_survey_endpoint(
    survey_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Reactivate an inactive ride survey.

    Returns 409 if already active.  Only account admins may call this endpoint.
    """
    account_id = await _resolve_account_id(db, user.id)
    await _require_account_admin(db, account_id, user.id)
    return await reactivate_survey(db, survey_id, account_id)


# ---------------------------------------------------------------------------
# Admin: delete survey
# ---------------------------------------------------------------------------


@router.delete(
    "/corporate/ride-surveys/{survey_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a ride survey (admin only)",
)
async def delete_survey_endpoint(
    survey_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Hard-delete a ride survey.

    Returns 409 if the survey is active — deactivate it first.
    Only account admins may call this endpoint.
    """
    account_id = await _resolve_account_id(db, user.id)
    await _require_account_admin(db, account_id, user.id)
    await delete_survey(db, survey_id, account_id)


# ---------------------------------------------------------------------------
# Admin: list responses
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/ride-surveys/{survey_id}/responses",
    response_model=SurveyResponseListResponse,
    summary="List all responses for a survey (admin only)",
)
async def list_survey_responses_endpoint(
    survey_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return all employee responses for a specific survey.

    Only account admins may call this endpoint.
    """
    account_id = await _resolve_account_id(db, user.id)
    await _require_account_admin(db, account_id, user.id)
    return await list_responses(db, survey_id, account_id)


# ---------------------------------------------------------------------------
# Admin: analytics
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/ride-surveys/{survey_id}/analytics",
    response_model=SurveyAnalyticsResponse,
    summary="Get per-question analytics for a survey (admin only)",
)
async def get_analytics_endpoint(
    survey_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return aggregated per-question analytics for a ride survey.

    Only account admins may call this endpoint.
    """
    account_id = await _resolve_account_id(db, user.id)
    await _require_account_admin(db, account_id, user.id)
    return await get_survey_analytics(db, survey_id, account_id)


# ---------------------------------------------------------------------------
# Platform-admin: list all surveys
# ---------------------------------------------------------------------------


@router.get(
    "/platform-admin/corporate/ride-surveys",
    response_model=RideSurveyListResponse,
    summary="Platform admin: list all ride surveys",
)
async def admin_list_all_surveys(
    account_id: Optional[int] = Query(None, description="Filter by account ID"),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return all ride surveys across all corporate accounts.

    Optionally filter by ``account_id``.  Platform admin only.
    """
    return await list_all_platform(db, account_id=account_id)


# ---------------------------------------------------------------------------
# Platform-admin: list surveys for a specific account
# ---------------------------------------------------------------------------


@router.get(
    "/platform-admin/corporate/ride-surveys/for-account/{account_id}",
    response_model=RideSurveyListResponse,
    summary="Platform admin: list ride surveys for a specific account",
)
async def admin_list_surveys_for_account(
    account_id: int,
    is_active: Optional[bool] = Query(None),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return all ride surveys for any corporate account.

    Platform admin only.
    """
    return await list_surveys(db, account_id, is_active=is_active)
