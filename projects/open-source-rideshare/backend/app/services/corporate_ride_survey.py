"""Service layer for Corporate Ride Satisfaction Surveys.

Enterprise admins create named surveys with configurable questions.
Employees complete surveys after corporate rides.  Admins can view
per-question analytics across all responses.

Public surface
--------------
create_survey(db, account_id, data, created_by_id) -> RideSurveyResponse
get_survey(db, survey_id, account_id) -> RideSurveyResponse
list_surveys(db, account_id, is_active) -> RideSurveyListResponse
update_survey(db, survey_id, account_id, data) -> RideSurveyResponse
deactivate_survey(db, survey_id, account_id) -> RideSurveyResponse
reactivate_survey(db, survey_id, account_id) -> RideSurveyResponse
delete_survey(db, survey_id, account_id) -> None
submit_response(db, survey_id, account_id, member_id, ride_id, responses)
    -> SurveyResponseRecord
list_responses(db, survey_id, account_id) -> SurveyResponseListResponse
get_survey_analytics(db, survey_id, account_id) -> SurveyAnalyticsResponse
list_all_platform(db, account_id) -> RideSurveyListResponse
"""

from __future__ import annotations

import uuid
from typing import Any, Optional

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.corporate_ride_survey import (
    CorporateRideSurvey,
    CorporateRideSurveyResponse,
)
from app.schemas.corporate_ride_survey import (
    QuestionAnalytics,
    RideSurveyCreate,
    RideSurveyListResponse,
    RideSurveyResponse,
    RideSurveyUpdate,
    SurveyAnalyticsResponse,
    SurveyResponseCreate,
    SurveyResponseListResponse,
    SurveyResponseRecord,
)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _survey_to_response(survey: CorporateRideSurvey) -> RideSurveyResponse:
    """Convert a CorporateRideSurvey ORM instance to a response schema."""
    return RideSurveyResponse(
        id=survey.id,
        account_id=survey.account_id,
        title=survey.title,
        description=survey.description,
        questions=survey.questions,
        is_active=survey.is_active,
        valid_from=survey.valid_from,
        valid_until=survey.valid_until,
        created_by_id=survey.created_by_id,
        created_at=survey.created_at,
        updated_at=survey.updated_at,
    )


def _response_to_record(resp: CorporateRideSurveyResponse) -> SurveyResponseRecord:
    """Convert a CorporateRideSurveyResponse ORM instance to a record schema."""
    return SurveyResponseRecord(
        id=resp.id,
        survey_id=resp.survey_id,
        member_id=resp.member_id,
        account_id=resp.account_id,
        ride_id=resp.ride_id,
        responses=resp.responses,
        submitted_at=resp.submitted_at,
    )


async def _get_survey_row(
    db: AsyncSession,
    survey_id: uuid.UUID,
    account_id: int,
) -> CorporateRideSurvey | None:
    """Return the survey for this (account, id) pair or None."""
    result = await db.execute(
        select(CorporateRideSurvey).where(
            CorporateRideSurvey.id == survey_id,
            CorporateRideSurvey.account_id == account_id,
        )
    )
    return result.scalar_one_or_none()


async def _get_survey_or_404(
    db: AsyncSession,
    survey_id: uuid.UUID,
    account_id: int,
) -> CorporateRideSurvey:
    """Return the survey or raise HTTP 404."""
    survey = await _get_survey_row(db, survey_id, account_id)
    if survey is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Survey not found.",
        )
    return survey


# ---------------------------------------------------------------------------
# Public service functions — surveys
# ---------------------------------------------------------------------------


async def create_survey(
    db: AsyncSession,
    account_id: int,
    data: RideSurveyCreate,
    created_by_id: Optional[int] = None,
) -> RideSurveyResponse:
    """Create a new ride satisfaction survey for the account.

    Raises HTTP 409 if a survey with the same title already exists in the
    account.
    """
    existing = await db.execute(
        select(CorporateRideSurvey).where(
            CorporateRideSurvey.account_id == account_id,
            CorporateRideSurvey.title == data.title,
        )
    )
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A survey with this title already exists for the account.",
        )

    survey = CorporateRideSurvey(
        account_id=account_id,
        title=data.title,
        description=data.description,
        questions=[q.model_dump() for q in data.questions],
        is_active=True,
        valid_from=data.valid_from,
        valid_until=data.valid_until,
        created_by_id=created_by_id,
    )
    db.add(survey)
    await db.commit()
    await db.refresh(survey)
    return _survey_to_response(survey)


async def get_survey(
    db: AsyncSession,
    survey_id: uuid.UUID,
    account_id: int,
) -> RideSurveyResponse:
    """Return a specific survey by ID.

    Raises HTTP 404 if not found or belongs to a different account.
    """
    survey = await _get_survey_or_404(db, survey_id, account_id)
    return _survey_to_response(survey)


async def list_surveys(
    db: AsyncSession,
    account_id: int,
    is_active: Optional[bool] = None,
) -> RideSurveyListResponse:
    """List all surveys for the account, sorted by title.

    Optional filter:
      - ``is_active``: True → active only; False → inactive only.
    """
    stmt = select(CorporateRideSurvey).where(
        CorporateRideSurvey.account_id == account_id
    )
    if is_active is not None:
        stmt = stmt.where(CorporateRideSurvey.is_active == is_active)
    stmt = stmt.order_by(CorporateRideSurvey.title)

    result = await db.execute(stmt)
    surveys = result.scalars().all()
    return RideSurveyListResponse(
        items=[_survey_to_response(s) for s in surveys],
        total=len(surveys),
    )


async def update_survey(
    db: AsyncSession,
    survey_id: uuid.UUID,
    account_id: int,
    data: RideSurveyUpdate,
) -> RideSurveyResponse:
    """Partially update a survey.

    Raises HTTP 404 if not found.
    Raises HTTP 409 on title collision with another survey in the same account.
    """
    survey = await _get_survey_or_404(db, survey_id, account_id)

    update_data = data.model_dump(exclude_unset=True)

    if "title" in update_data and update_data["title"] != survey.title:
        collision = await db.execute(
            select(CorporateRideSurvey).where(
                CorporateRideSurvey.account_id == account_id,
                CorporateRideSurvey.title == update_data["title"],
                CorporateRideSurvey.id != survey_id,
            )
        )
        if collision.scalar_one_or_none() is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A survey with this title already exists for the account.",
            )

    # Serialise questions if supplied as Pydantic objects.
    if "questions" in update_data and update_data["questions"] is not None:
        questions = update_data["questions"]
        if questions and hasattr(questions[0], "model_dump"):
            update_data["questions"] = [q.model_dump() for q in questions]

    for field, value in update_data.items():
        setattr(survey, field, value)

    await db.commit()
    await db.refresh(survey)
    return _survey_to_response(survey)


async def deactivate_survey(
    db: AsyncSession,
    survey_id: uuid.UUID,
    account_id: int,
) -> RideSurveyResponse:
    """Deactivate an active survey.

    Raises HTTP 404 if not found.
    Raises HTTP 409 if already inactive.
    """
    survey = await _get_survey_or_404(db, survey_id, account_id)
    if not survey.is_active:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Survey is already inactive.",
        )
    survey.is_active = False
    await db.commit()
    await db.refresh(survey)
    return _survey_to_response(survey)


async def reactivate_survey(
    db: AsyncSession,
    survey_id: uuid.UUID,
    account_id: int,
) -> RideSurveyResponse:
    """Reactivate an inactive survey.

    Raises HTTP 404 if not found.
    Raises HTTP 409 if already active.
    """
    survey = await _get_survey_or_404(db, survey_id, account_id)
    if survey.is_active:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Survey is already active.",
        )
    survey.is_active = True
    await db.commit()
    await db.refresh(survey)
    return _survey_to_response(survey)


async def delete_survey(
    db: AsyncSession,
    survey_id: uuid.UUID,
    account_id: int,
) -> None:
    """Hard-delete a survey.

    Raises HTTP 404 if not found.
    Raises HTTP 409 if the survey is still active — deactivate it first.
    """
    survey = await _get_survey_or_404(db, survey_id, account_id)
    if survey.is_active:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot delete an active survey. Deactivate it first.",
        )
    await db.delete(survey)
    await db.commit()


# ---------------------------------------------------------------------------
# Public service functions — responses
# ---------------------------------------------------------------------------


async def submit_response(
    db: AsyncSession,
    survey_id: uuid.UUID,
    account_id: int,
    member_id: int,
    ride_id: Optional[int],
    responses: list[Any],
) -> SurveyResponseRecord:
    """Submit an employee's response to a survey.

    Raises HTTP 404 if the survey is not found or is inactive.
    Raises HTTP 409 if the member has already responded to this survey.
    """
    survey = await _get_survey_row(db, survey_id, account_id)
    if survey is None or not survey.is_active:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Survey not found or is not active.",
        )

    # Check for duplicate response.
    dup = await db.execute(
        select(CorporateRideSurveyResponse).where(
            CorporateRideSurveyResponse.survey_id == survey_id,
            CorporateRideSurveyResponse.member_id == member_id,
        )
    )
    if dup.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Member has already responded to this survey.",
        )

    serialised = [
        r.model_dump() if hasattr(r, "model_dump") else r for r in responses
    ]

    record = CorporateRideSurveyResponse(
        survey_id=survey_id,
        member_id=member_id,
        account_id=account_id,
        ride_id=ride_id,
        responses=serialised,
    )
    db.add(record)
    await db.commit()
    await db.refresh(record)
    return _response_to_record(record)


async def list_responses(
    db: AsyncSession,
    survey_id: uuid.UUID,
    account_id: int,
) -> SurveyResponseListResponse:
    """Return all responses for a survey.

    Raises HTTP 404 if the survey is not found.
    """
    await _get_survey_or_404(db, survey_id, account_id)

    result = await db.execute(
        select(CorporateRideSurveyResponse).where(
            CorporateRideSurveyResponse.survey_id == survey_id
        )
    )
    records = result.scalars().all()
    return SurveyResponseListResponse(
        items=[_response_to_record(r) for r in records],
        total=len(records),
    )


async def get_survey_analytics(
    db: AsyncSession,
    survey_id: uuid.UUID,
    account_id: int,
) -> SurveyAnalyticsResponse:
    """Compute per-question analytics across all responses for a survey.

    For each question:
      - rating:          avg_rating (float), response_count
      - text:            text_responses list
      - boolean:         boolean_true_count, boolean_false_count
      - multiple_choice: choice_counts dict

    Raises HTTP 404 if the survey is not found.
    """
    survey = await _get_survey_or_404(db, survey_id, account_id)

    result = await db.execute(
        select(CorporateRideSurveyResponse).where(
            CorporateRideSurveyResponse.survey_id == survey_id
        )
    )
    all_responses = result.scalars().all()

    # Build a lookup: question_id -> list of answers
    answer_map: dict[str, list[Any]] = {}
    for resp in all_responses:
        for item in resp.responses:
            qid = item.get("question_id") if isinstance(item, dict) else item.question_id
            ans = item.get("answer") if isinstance(item, dict) else item.answer
            answer_map.setdefault(qid, []).append(ans)

    question_analytics = []
    for q in survey.questions:
        qid = q.get("question_id") if isinstance(q, dict) else q.question_id
        qtext = q.get("text") if isinstance(q, dict) else q.text
        qtype = q.get("type") if isinstance(q, dict) else q.type
        answers = answer_map.get(qid, [])

        analytics = QuestionAnalytics(
            question_id=qid,
            text=qtext,
            type=qtype,
            response_count=len(answers),
        )

        if qtype == "rating":
            numeric = [float(a) for a in answers if a is not None]
            analytics.avg_rating = sum(numeric) / len(numeric) if numeric else None
        elif qtype == "text":
            analytics.text_responses = [str(a) for a in answers if a is not None]
        elif qtype == "boolean":
            analytics.boolean_true_count = sum(1 for a in answers if a is True)
            analytics.boolean_false_count = sum(1 for a in answers if a is False)
        elif qtype == "multiple_choice":
            counts: dict[str, int] = {}
            for a in answers:
                key = str(a)
                counts[key] = counts.get(key, 0) + 1
            analytics.choice_counts = counts

        question_analytics.append(analytics)

    return SurveyAnalyticsResponse(
        survey_id=survey.id,
        title=survey.title,
        total_responses=len(all_responses),
        question_analytics=question_analytics,
    )


async def list_all_platform(
    db: AsyncSession,
    account_id: Optional[int] = None,
) -> RideSurveyListResponse:
    """Platform-admin: list all surveys, optionally filtered by account."""
    stmt = select(CorporateRideSurvey)
    if account_id is not None:
        stmt = stmt.where(CorporateRideSurvey.account_id == account_id)
    stmt = stmt.order_by(
        CorporateRideSurvey.account_id,
        CorporateRideSurvey.title,
    )
    result = await db.execute(stmt)
    surveys = result.scalars().all()
    return RideSurveyListResponse(
        items=[_survey_to_response(s) for s in surveys],
        total=len(surveys),
    )
