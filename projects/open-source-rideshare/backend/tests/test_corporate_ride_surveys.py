"""Tests for the Corporate Ride Satisfaction Surveys feature.

Service layer (async, mocked DB):
  1.  create_survey — creates active survey with defaults
  2.  create_survey — sets created_by_id from caller
  3.  create_survey — 409 on duplicate title within account
  4.  get_survey — returns survey when found
  5.  get_survey — 404 when not found
  6.  get_survey — 404 when survey belongs to different account
  7.  list_surveys — returns all surveys sorted by title
  8.  list_surveys — filter is_active=True returns only active
  9.  list_surveys — filter is_active=False returns only inactive
  10. update_survey — partial update writes only supplied fields
  11. update_survey — 404 when not found
  12. update_survey — 409 on title collision with different survey
  13. deactivate_survey — sets is_active=False
  14. deactivate_survey — 404 when not found
  15. deactivate_survey — 409 when already inactive
  16. reactivate_survey — sets is_active=True
  17. reactivate_survey — 404 when not found
  18. reactivate_survey — 409 when already active
  19. delete_survey — hard-deletes inactive survey
  20. delete_survey — 404 when not found
  21. delete_survey — 409 when active
  22. submit_response — creates response record
  23. submit_response — 404 when survey not found
  24. submit_response — 404 when survey is inactive
  25. submit_response — 409 when member already responded
  26. list_responses — returns responses for survey
  27. list_responses — 404 when survey not found
  28. get_survey_analytics — computes avg_rating for rating questions
  29. get_survey_analytics — collects text_responses for text questions
  30. get_survey_analytics — counts boolean_true/false for boolean questions
  31. get_survey_analytics — counts choices for multiple_choice questions
  32. get_survey_analytics — zero responses returns empty analytics
  33. list_all_platform — returns all surveys without filter
  34. list_all_platform — filters by account_id

Schema validation:
  35. RideSurveyCreate — valid data accepted
  36. RideSurveyCreate — blank title rejected
  37. RideSurveyCreate — empty questions list rejected
  38. RideSurveyUpdate — all fields optional
  39. RideSurveyUpdate — blank title rejected when supplied
  40. RideSurveyResponse — from_attributes construction
  41. SurveyResponseCreate — valid data accepted
  42. SurveyResponseCreate — empty responses list rejected
  43. SurveyResponseRecord — from_attributes construction
  44. QuestionAnalytics — rating fields populated correctly
  45. SurveyAnalyticsResponse — structure validated

API layer (service functions patched):
  46. GET list surveys (member) — 200 returns active surveys
  47. GET list surveys (member) — 404 when not in account
  48. GET {survey_id} (member) — 200 returns survey
  49. GET {survey_id} (member) — 404 when not found
  50. POST respond (member) — 201 submits response
  51. POST respond (member) — 409 when duplicate response
  52. GET my-responses (member) — 200 returns member's own responses
  53. POST create (admin) — 201 creates survey
  54. POST create (admin) — 403 non-admin cannot create
  55. POST create (admin) — 409 on duplicate title
  56. PUT update (admin) — 200 updates survey
  57. PUT update (admin) — 403 non-admin cannot update
  58. POST deactivate (admin) — 200 deactivates survey
  59. POST deactivate (admin) — 409 when already inactive
  60. POST reactivate (admin) — 200 reactivates survey
  61. DELETE survey (admin) — 204 deletes inactive survey
  62. DELETE survey (admin) — 409 when active
  63. GET responses (admin) — 200 returns response list
  64. GET analytics (admin) — 200 returns analytics
  65. GET platform all — 200 platform-admin lists all surveys
  66. GET platform for-account — 200 platform-admin lists for account
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.corporate_ride_survey import (
    CorporateRideSurvey,
    CorporateRideSurveyResponse,
)
from app.schemas.corporate_ride_survey import (
    QuestionAnalytics,
    QuestionItem,
    ResponseItem,
    RideSurveyCreate,
    RideSurveyListResponse,
    RideSurveyResponse,
    RideSurveyUpdate,
    SurveyAnalyticsResponse,
    SurveyResponseCreate,
    SurveyResponseListResponse,
    SurveyResponseRecord,
)
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


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

NOW = datetime(2026, 4, 16, 0, 0, 0, tzinfo=timezone.utc)

ACCOUNT_ID = 10
MEMBER_ID = 20
ADMIN_ID = 21
SURVEY_ID = uuid.uuid4()
RESPONSE_ID = uuid.uuid4()
OTHER_SURVEY_ID = uuid.uuid4()

QUESTIONS = [
    {"question_id": "q1", "text": "Overall rating?", "type": "rating", "options": None},
    {"question_id": "q2", "text": "Any comments?", "type": "text", "options": None},
]


def _make_survey(
    id: uuid.UUID = SURVEY_ID,
    account_id: int = ACCOUNT_ID,
    title: str = "Post-ride Survey",
    description: str | None = "Please rate your experience",
    questions: list | None = None,
    is_active: bool = True,
    valid_from: datetime | None = None,
    valid_until: datetime | None = None,
    created_by_id: int | None = ADMIN_ID,
) -> CorporateRideSurvey:
    s = CorporateRideSurvey()
    s.id = id
    s.account_id = account_id
    s.title = title
    s.description = description
    s.questions = questions if questions is not None else list(QUESTIONS)
    s.is_active = is_active
    s.valid_from = valid_from
    s.valid_until = valid_until
    s.created_by_id = created_by_id
    s.created_at = NOW
    s.updated_at = NOW
    return s


def _make_inactive_survey(**kwargs) -> CorporateRideSurvey:
    return _make_survey(is_active=False, **kwargs)


def _make_response_record(
    id: uuid.UUID = RESPONSE_ID,
    survey_id: uuid.UUID = SURVEY_ID,
    member_id: int | None = MEMBER_ID,
    account_id: int = ACCOUNT_ID,
    ride_id: int | None = None,
    responses: list | None = None,
) -> CorporateRideSurveyResponse:
    r = CorporateRideSurveyResponse()
    r.id = id
    r.survey_id = survey_id
    r.member_id = member_id
    r.account_id = account_id
    r.ride_id = ride_id
    r.responses = responses if responses is not None else [
        {"question_id": "q1", "answer": 5},
        {"question_id": "q2", "answer": "Great ride!"},
    ]
    r.submitted_at = NOW
    return r


def _make_survey_response_schema(survey: CorporateRideSurvey) -> RideSurveyResponse:
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


def _make_record_schema(r: CorporateRideSurveyResponse) -> SurveyResponseRecord:
    return SurveyResponseRecord(
        id=r.id,
        survey_id=r.survey_id,
        member_id=r.member_id,
        account_id=r.account_id,
        ride_id=r.ride_id,
        responses=r.responses,
        submitted_at=r.submitted_at,
    )


def _db_returning(row):
    db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = row
    db.execute.return_value = result
    return db


def _db_returning_all(rows):
    db = AsyncMock()
    result = MagicMock()
    scalar_result = MagicMock()
    scalar_result.all.return_value = rows
    result.scalars.return_value = scalar_result
    db.execute.return_value = result
    return db


def _db_multi(*responses):
    """Return a db mock that cycles through multiple execute() return values."""
    db = AsyncMock()
    results = []
    for r in responses:
        mock_result = MagicMock()
        if isinstance(r, list):
            scalar_res = MagicMock()
            scalar_res.all.return_value = r
            mock_result.scalars.return_value = scalar_res
        else:
            mock_result.scalar_one_or_none.return_value = r
        results.append(mock_result)
    db.execute.side_effect = results
    return db


# ---------------------------------------------------------------------------
# Service layer tests — create_survey
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_survey_creates_active_survey():
    """create_survey creates a new survey with is_active=True."""
    db = AsyncMock()
    db.add = MagicMock()

    async def _refresh(obj):
        obj.id = SURVEY_ID
        obj.created_at = NOW
        obj.updated_at = NOW

    db.refresh = AsyncMock(side_effect=_refresh)

    result_mock = MagicMock()
    result_mock.scalar_one_or_none.return_value = None
    db.execute.return_value = result_mock

    data = RideSurveyCreate(
        title="Post-ride Survey",
        questions=[QuestionItem(question_id="q1", text="Rate us", type="rating")],
    )
    result = await create_survey(db, ACCOUNT_ID, data, created_by_id=ADMIN_ID)

    db.add.assert_called_once()
    db.commit.assert_called_once()
    assert result.is_active is True


@pytest.mark.asyncio
async def test_create_survey_sets_created_by_id():
    """create_survey stores the created_by_id on the new record."""
    db = AsyncMock()
    captured = {}

    def _capture(obj):
        captured["survey"] = obj

    db.add = MagicMock(side_effect=_capture)

    async def _refresh(obj):
        obj.id = SURVEY_ID
        obj.created_at = NOW
        obj.updated_at = NOW

    db.refresh = AsyncMock(side_effect=_refresh)

    result_mock = MagicMock()
    result_mock.scalar_one_or_none.return_value = None
    db.execute.return_value = result_mock

    data = RideSurveyCreate(
        title="New Survey",
        questions=[QuestionItem(question_id="q1", text="Rate us", type="rating")],
    )
    await create_survey(db, ACCOUNT_ID, data, created_by_id=ADMIN_ID)
    assert captured["survey"].created_by_id == ADMIN_ID


@pytest.mark.asyncio
async def test_create_survey_409_on_duplicate_title():
    """create_survey raises 409 when a survey with the same title exists."""
    from fastapi import HTTPException

    existing = _make_survey()
    db = _db_returning(existing)

    data = RideSurveyCreate(
        title="Post-ride Survey",
        questions=[QuestionItem(question_id="q1", text="Rate us", type="rating")],
    )
    with pytest.raises(HTTPException) as exc:
        await create_survey(db, ACCOUNT_ID, data)
    assert exc.value.status_code == 409


# ---------------------------------------------------------------------------
# Service layer tests — get_survey
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_survey_returns_survey_when_found():
    """get_survey returns the survey response when found."""
    survey = _make_survey()
    db = _db_returning(survey)
    result = await get_survey(db, SURVEY_ID, ACCOUNT_ID)
    assert result.id == SURVEY_ID
    assert result.account_id == ACCOUNT_ID


@pytest.mark.asyncio
async def test_get_survey_404_when_not_found():
    """get_survey raises HTTP 404 when survey is not found."""
    from fastapi import HTTPException

    db = _db_returning(None)
    with pytest.raises(HTTPException) as exc:
        await get_survey(db, SURVEY_ID, ACCOUNT_ID)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_get_survey_404_for_different_account():
    """get_survey raises 404 when survey belongs to a different account."""
    from fastapi import HTTPException

    db = _db_returning(None)
    with pytest.raises(HTTPException) as exc:
        await get_survey(db, SURVEY_ID, account_id=999)
    assert exc.value.status_code == 404


# ---------------------------------------------------------------------------
# Service layer tests — list_surveys
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_surveys_returns_all():
    """list_surveys returns all surveys for the account."""
    surveys = [
        _make_survey(id=uuid.uuid4(), title="A Survey"),
        _make_survey(id=uuid.uuid4(), title="B Survey"),
    ]
    db = _db_returning_all(surveys)
    result = await list_surveys(db, ACCOUNT_ID)
    assert result.total == 2
    assert len(result.items) == 2


@pytest.mark.asyncio
async def test_list_surveys_filter_active():
    """list_surveys with is_active=True returns only active surveys."""
    active = _make_survey()
    db = _db_returning_all([active])
    result = await list_surveys(db, ACCOUNT_ID, is_active=True)
    assert result.total == 1
    assert result.items[0].is_active is True


@pytest.mark.asyncio
async def test_list_surveys_filter_inactive():
    """list_surveys with is_active=False returns only inactive surveys."""
    inactive = _make_inactive_survey()
    db = _db_returning_all([inactive])
    result = await list_surveys(db, ACCOUNT_ID, is_active=False)
    assert result.total == 1
    assert result.items[0].is_active is False


# ---------------------------------------------------------------------------
# Service layer tests — update_survey
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_survey_partial_update():
    """update_survey writes only supplied fields."""
    survey = _make_survey(title="Old Title")

    call_count = 0

    async def _side_effect(stmt):
        nonlocal call_count
        call_count += 1
        result = MagicMock()
        if call_count == 1:
            result.scalar_one_or_none.return_value = survey
        else:
            # Name collision check
            result.scalar_one_or_none.return_value = None
        return result

    db = AsyncMock()
    db.execute.side_effect = _side_effect

    data = RideSurveyUpdate(title="New Title")
    await update_survey(db, SURVEY_ID, ACCOUNT_ID, data)
    assert survey.title == "New Title"
    db.commit.assert_called_once()


@pytest.mark.asyncio
async def test_update_survey_404_when_not_found():
    """update_survey raises 404 when survey not found."""
    from fastapi import HTTPException

    db = _db_returning(None)
    data = RideSurveyUpdate(title="New Title")
    with pytest.raises(HTTPException) as exc:
        await update_survey(db, SURVEY_ID, ACCOUNT_ID, data)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_update_survey_409_on_title_collision():
    """update_survey raises 409 when new title collides with another survey."""
    from fastapi import HTTPException

    survey = _make_survey(title="Survey A")
    other = _make_survey(id=OTHER_SURVEY_ID, title="Survey B")

    call_count = 0

    async def _side_effect(stmt):
        nonlocal call_count
        call_count += 1
        result = MagicMock()
        if call_count == 1:
            result.scalar_one_or_none.return_value = survey
        else:
            result.scalar_one_or_none.return_value = other
        return result

    db = AsyncMock()
    db.execute.side_effect = _side_effect

    data = RideSurveyUpdate(title="Survey B")
    with pytest.raises(HTTPException) as exc:
        await update_survey(db, SURVEY_ID, ACCOUNT_ID, data)
    assert exc.value.status_code == 409


# ---------------------------------------------------------------------------
# Service layer tests — deactivate_survey
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_deactivate_survey_sets_inactive():
    """deactivate_survey sets is_active=False."""
    survey = _make_survey(is_active=True)
    db = _db_returning(survey)
    await deactivate_survey(db, SURVEY_ID, ACCOUNT_ID)
    assert survey.is_active is False
    db.commit.assert_called_once()


@pytest.mark.asyncio
async def test_deactivate_survey_404_when_not_found():
    """deactivate_survey raises 404 when survey not found."""
    from fastapi import HTTPException

    db = _db_returning(None)
    with pytest.raises(HTTPException) as exc:
        await deactivate_survey(db, SURVEY_ID, ACCOUNT_ID)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_deactivate_survey_409_when_already_inactive():
    """deactivate_survey raises 409 when survey is already inactive."""
    from fastapi import HTTPException

    survey = _make_inactive_survey()
    db = _db_returning(survey)
    with pytest.raises(HTTPException) as exc:
        await deactivate_survey(db, SURVEY_ID, ACCOUNT_ID)
    assert exc.value.status_code == 409


# ---------------------------------------------------------------------------
# Service layer tests — reactivate_survey
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reactivate_survey_sets_active():
    """reactivate_survey sets is_active=True."""
    survey = _make_inactive_survey()
    db = _db_returning(survey)
    await reactivate_survey(db, SURVEY_ID, ACCOUNT_ID)
    assert survey.is_active is True
    db.commit.assert_called_once()


@pytest.mark.asyncio
async def test_reactivate_survey_404_when_not_found():
    """reactivate_survey raises 404 when survey not found."""
    from fastapi import HTTPException

    db = _db_returning(None)
    with pytest.raises(HTTPException) as exc:
        await reactivate_survey(db, SURVEY_ID, ACCOUNT_ID)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_reactivate_survey_409_when_already_active():
    """reactivate_survey raises 409 when survey is already active."""
    from fastapi import HTTPException

    survey = _make_survey(is_active=True)
    db = _db_returning(survey)
    with pytest.raises(HTTPException) as exc:
        await reactivate_survey(db, SURVEY_ID, ACCOUNT_ID)
    assert exc.value.status_code == 409


# ---------------------------------------------------------------------------
# Service layer tests — delete_survey
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_survey_deletes_inactive():
    """delete_survey hard-deletes an inactive survey."""
    survey = _make_inactive_survey()
    db = _db_returning(survey)
    await delete_survey(db, SURVEY_ID, ACCOUNT_ID)
    db.delete.assert_called_once_with(survey)
    db.commit.assert_called_once()


@pytest.mark.asyncio
async def test_delete_survey_404_when_not_found():
    """delete_survey raises 404 when survey not found."""
    from fastapi import HTTPException

    db = _db_returning(None)
    with pytest.raises(HTTPException) as exc:
        await delete_survey(db, SURVEY_ID, ACCOUNT_ID)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_delete_survey_409_when_active():
    """delete_survey raises 409 when survey is active."""
    from fastapi import HTTPException

    survey = _make_survey(is_active=True)
    db = _db_returning(survey)
    with pytest.raises(HTTPException) as exc:
        await delete_survey(db, SURVEY_ID, ACCOUNT_ID)
    assert exc.value.status_code == 409


# ---------------------------------------------------------------------------
# Service layer tests — submit_response
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_submit_response_creates_record():
    """submit_response creates a new response record."""
    survey = _make_survey(is_active=True)
    record = _make_response_record()

    call_count = 0

    async def _side_effect(stmt):
        nonlocal call_count
        call_count += 1
        result = MagicMock()
        if call_count == 1:
            # get survey check
            result.scalar_one_or_none.return_value = survey
        else:
            # duplicate response check — none
            result.scalar_one_or_none.return_value = None
        return result

    db = AsyncMock()
    db.execute.side_effect = _side_effect
    db.add = MagicMock()

    async def _refresh(obj):
        obj.id = RESPONSE_ID
        obj.submitted_at = NOW

    db.refresh = AsyncMock(side_effect=_refresh)

    responses = [ResponseItem(question_id="q1", answer=5)]
    result = await submit_response(db, SURVEY_ID, ACCOUNT_ID, MEMBER_ID, None, responses)
    db.add.assert_called_once()
    db.commit.assert_called_once()


@pytest.mark.asyncio
async def test_submit_response_404_survey_not_found():
    """submit_response raises 404 when survey not found."""
    from fastapi import HTTPException

    db = _db_returning(None)
    responses = [ResponseItem(question_id="q1", answer=5)]
    with pytest.raises(HTTPException) as exc:
        await submit_response(db, SURVEY_ID, ACCOUNT_ID, MEMBER_ID, None, responses)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_submit_response_404_survey_inactive():
    """submit_response raises 404 when survey is inactive."""
    from fastapi import HTTPException

    inactive = _make_inactive_survey()
    db = _db_returning(inactive)
    responses = [ResponseItem(question_id="q1", answer=5)]
    with pytest.raises(HTTPException) as exc:
        await submit_response(db, SURVEY_ID, ACCOUNT_ID, MEMBER_ID, None, responses)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_submit_response_409_duplicate():
    """submit_response raises 409 when member already responded."""
    from fastapi import HTTPException

    survey = _make_survey(is_active=True)
    existing = _make_response_record()

    call_count = 0

    async def _side_effect(stmt):
        nonlocal call_count
        call_count += 1
        result = MagicMock()
        if call_count == 1:
            result.scalar_one_or_none.return_value = survey
        else:
            result.scalar_one_or_none.return_value = existing
        return result

    db = AsyncMock()
    db.execute.side_effect = _side_effect

    responses = [ResponseItem(question_id="q1", answer=5)]
    with pytest.raises(HTTPException) as exc:
        await submit_response(db, SURVEY_ID, ACCOUNT_ID, MEMBER_ID, None, responses)
    assert exc.value.status_code == 409


# ---------------------------------------------------------------------------
# Service layer tests — list_responses
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_responses_returns_responses():
    """list_responses returns all responses for the survey."""
    survey = _make_survey()
    records = [_make_response_record(), _make_response_record(id=uuid.uuid4(), member_id=22)]

    call_count = 0

    async def _side_effect(stmt):
        nonlocal call_count
        call_count += 1
        result = MagicMock()
        if call_count == 1:
            result.scalar_one_or_none.return_value = survey
        else:
            scalar_res = MagicMock()
            scalar_res.all.return_value = records
            result.scalars.return_value = scalar_res
        return result

    db = AsyncMock()
    db.execute.side_effect = _side_effect

    result = await list_responses(db, SURVEY_ID, ACCOUNT_ID)
    assert result.total == 2


@pytest.mark.asyncio
async def test_list_responses_404_when_survey_not_found():
    """list_responses raises 404 when survey not found."""
    from fastapi import HTTPException

    db = _db_returning(None)
    with pytest.raises(HTTPException) as exc:
        await list_responses(db, SURVEY_ID, ACCOUNT_ID)
    assert exc.value.status_code == 404


# ---------------------------------------------------------------------------
# Service layer tests — get_survey_analytics
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_analytics_avg_rating():
    """get_survey_analytics computes avg_rating for rating questions."""
    questions = [{"question_id": "q1", "text": "Rate us", "type": "rating", "options": None}]
    survey = _make_survey(questions=questions)
    resp1 = _make_response_record(
        id=uuid.uuid4(),
        responses=[{"question_id": "q1", "answer": 4}],
    )
    resp2 = _make_response_record(
        id=uuid.uuid4(),
        member_id=22,
        responses=[{"question_id": "q1", "answer": 2}],
    )

    call_count = 0

    async def _side_effect(stmt):
        nonlocal call_count
        call_count += 1
        result = MagicMock()
        if call_count == 1:
            result.scalar_one_or_none.return_value = survey
        else:
            scalar_res = MagicMock()
            scalar_res.all.return_value = [resp1, resp2]
            result.scalars.return_value = scalar_res
        return result

    db = AsyncMock()
    db.execute.side_effect = _side_effect

    analytics = await get_survey_analytics(db, SURVEY_ID, ACCOUNT_ID)
    assert analytics.total_responses == 2
    q = analytics.question_analytics[0]
    assert q.avg_rating == 3.0
    assert q.response_count == 2


@pytest.mark.asyncio
async def test_analytics_text_responses():
    """get_survey_analytics collects text_responses for text questions."""
    questions = [{"question_id": "q1", "text": "Comments?", "type": "text", "options": None}]
    survey = _make_survey(questions=questions)
    resp1 = _make_response_record(
        id=uuid.uuid4(),
        responses=[{"question_id": "q1", "answer": "Great!"}],
    )
    resp2 = _make_response_record(
        id=uuid.uuid4(),
        member_id=22,
        responses=[{"question_id": "q1", "answer": "OK ride"}],
    )

    call_count = 0

    async def _side_effect(stmt):
        nonlocal call_count
        call_count += 1
        result = MagicMock()
        if call_count == 1:
            result.scalar_one_or_none.return_value = survey
        else:
            scalar_res = MagicMock()
            scalar_res.all.return_value = [resp1, resp2]
            result.scalars.return_value = scalar_res
        return result

    db = AsyncMock()
    db.execute.side_effect = _side_effect

    analytics = await get_survey_analytics(db, SURVEY_ID, ACCOUNT_ID)
    q = analytics.question_analytics[0]
    assert "Great!" in q.text_responses
    assert "OK ride" in q.text_responses
    assert q.response_count == 2


@pytest.mark.asyncio
async def test_analytics_boolean_counts():
    """get_survey_analytics counts boolean_true/false for boolean questions."""
    questions = [{"question_id": "q1", "text": "On time?", "type": "boolean", "options": None}]
    survey = _make_survey(questions=questions)
    resp1 = _make_response_record(
        id=uuid.uuid4(),
        responses=[{"question_id": "q1", "answer": True}],
    )
    resp2 = _make_response_record(
        id=uuid.uuid4(),
        member_id=22,
        responses=[{"question_id": "q1", "answer": False}],
    )
    resp3 = _make_response_record(
        id=uuid.uuid4(),
        member_id=23,
        responses=[{"question_id": "q1", "answer": True}],
    )

    call_count = 0

    async def _side_effect(stmt):
        nonlocal call_count
        call_count += 1
        result = MagicMock()
        if call_count == 1:
            result.scalar_one_or_none.return_value = survey
        else:
            scalar_res = MagicMock()
            scalar_res.all.return_value = [resp1, resp2, resp3]
            result.scalars.return_value = scalar_res
        return result

    db = AsyncMock()
    db.execute.side_effect = _side_effect

    analytics = await get_survey_analytics(db, SURVEY_ID, ACCOUNT_ID)
    q = analytics.question_analytics[0]
    assert q.boolean_true_count == 2
    assert q.boolean_false_count == 1


@pytest.mark.asyncio
async def test_analytics_choice_counts():
    """get_survey_analytics counts choices for multiple_choice questions."""
    questions = [
        {
            "question_id": "q1",
            "text": "Vehicle type?",
            "type": "multiple_choice",
            "options": ["Sedan", "SUV"],
        }
    ]
    survey = _make_survey(questions=questions)
    resp1 = _make_response_record(
        id=uuid.uuid4(),
        responses=[{"question_id": "q1", "answer": "Sedan"}],
    )
    resp2 = _make_response_record(
        id=uuid.uuid4(),
        member_id=22,
        responses=[{"question_id": "q1", "answer": "Sedan"}],
    )
    resp3 = _make_response_record(
        id=uuid.uuid4(),
        member_id=23,
        responses=[{"question_id": "q1", "answer": "SUV"}],
    )

    call_count = 0

    async def _side_effect(stmt):
        nonlocal call_count
        call_count += 1
        result = MagicMock()
        if call_count == 1:
            result.scalar_one_or_none.return_value = survey
        else:
            scalar_res = MagicMock()
            scalar_res.all.return_value = [resp1, resp2, resp3]
            result.scalars.return_value = scalar_res
        return result

    db = AsyncMock()
    db.execute.side_effect = _side_effect

    analytics = await get_survey_analytics(db, SURVEY_ID, ACCOUNT_ID)
    q = analytics.question_analytics[0]
    assert q.choice_counts == {"Sedan": 2, "SUV": 1}


@pytest.mark.asyncio
async def test_analytics_zero_responses():
    """get_survey_analytics returns empty analytics when no responses exist."""
    questions = [{"question_id": "q1", "text": "Rate us", "type": "rating", "options": None}]
    survey = _make_survey(questions=questions)

    call_count = 0

    async def _side_effect(stmt):
        nonlocal call_count
        call_count += 1
        result = MagicMock()
        if call_count == 1:
            result.scalar_one_or_none.return_value = survey
        else:
            scalar_res = MagicMock()
            scalar_res.all.return_value = []
            result.scalars.return_value = scalar_res
        return result

    db = AsyncMock()
    db.execute.side_effect = _side_effect

    analytics = await get_survey_analytics(db, SURVEY_ID, ACCOUNT_ID)
    assert analytics.total_responses == 0
    q = analytics.question_analytics[0]
    assert q.response_count == 0
    assert q.avg_rating is None


# ---------------------------------------------------------------------------
# Service layer tests — list_all_platform
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_all_platform_returns_all():
    """list_all_platform returns all surveys without account filter."""
    surveys = [
        _make_survey(id=uuid.uuid4(), account_id=10),
        _make_survey(id=uuid.uuid4(), account_id=20),
    ]
    db = _db_returning_all(surveys)
    result = await list_all_platform(db)
    assert result.total == 2


@pytest.mark.asyncio
async def test_list_all_platform_filters_by_account():
    """list_all_platform with account_id filter returns only that account's surveys."""
    surveys = [_make_survey(account_id=10)]
    db = _db_returning_all(surveys)
    result = await list_all_platform(db, account_id=10)
    assert result.total == 1
    assert result.items[0].account_id == 10


# ---------------------------------------------------------------------------
# Schema validation tests
# ---------------------------------------------------------------------------


def test_ride_survey_create_valid():
    """RideSurveyCreate accepts valid data."""
    data = RideSurveyCreate(
        title="Satisfaction Survey",
        questions=[
            QuestionItem(question_id="q1", text="Rate your ride", type="rating"),
            QuestionItem(question_id="q2", text="Comments", type="text"),
        ],
    )
    assert data.title == "Satisfaction Survey"
    assert len(data.questions) == 2


def test_ride_survey_create_blank_title_rejected():
    """RideSurveyCreate rejects a blank title."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        RideSurveyCreate(
            title="  ",
            questions=[QuestionItem(question_id="q1", text="Rate", type="rating")],
        )


def test_ride_survey_create_empty_questions_rejected():
    """RideSurveyCreate rejects an empty questions list."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        RideSurveyCreate(title="Survey", questions=[])


def test_ride_survey_update_all_fields_optional():
    """RideSurveyUpdate accepts empty update (all fields optional)."""
    data = RideSurveyUpdate()
    assert data.model_dump(exclude_unset=True) == {}


def test_ride_survey_update_blank_title_rejected():
    """RideSurveyUpdate rejects a blank title when supplied."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        RideSurveyUpdate(title="  ")


def test_ride_survey_response_from_attributes():
    """RideSurveyResponse can be constructed from ORM attributes."""
    survey = _make_survey()
    response = RideSurveyResponse.model_validate(survey)
    assert response.id == SURVEY_ID
    assert response.account_id == ACCOUNT_ID
    assert response.title == "Post-ride Survey"


def test_survey_response_create_valid():
    """SurveyResponseCreate accepts valid data."""
    data = SurveyResponseCreate(
        survey_id=SURVEY_ID,
        responses=[ResponseItem(question_id="q1", answer=5)],
    )
    assert data.survey_id == SURVEY_ID
    assert len(data.responses) == 1


def test_survey_response_create_empty_responses_rejected():
    """SurveyResponseCreate rejects empty responses list."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        SurveyResponseCreate(survey_id=SURVEY_ID, responses=[])


def test_survey_response_record_from_attributes():
    """SurveyResponseRecord can be constructed from ORM attributes."""
    record = _make_response_record()
    schema = SurveyResponseRecord.model_validate(record)
    assert schema.id == RESPONSE_ID
    assert schema.survey_id == SURVEY_ID
    assert schema.member_id == MEMBER_ID


def test_question_analytics_rating_fields():
    """QuestionAnalytics holds rating-specific fields."""
    qa = QuestionAnalytics(
        question_id="q1",
        text="Rate us",
        type="rating",
        response_count=3,
        avg_rating=4.2,
    )
    assert qa.avg_rating == 4.2
    assert qa.response_count == 3
    assert qa.text_responses == []


def test_survey_analytics_response_structure():
    """SurveyAnalyticsResponse holds survey-level and per-question data."""
    qa = QuestionAnalytics(
        question_id="q1",
        text="Rate us",
        type="rating",
        response_count=1,
        avg_rating=5.0,
    )
    analytics = SurveyAnalyticsResponse(
        survey_id=SURVEY_ID,
        title="Test Survey",
        total_responses=1,
        question_analytics=[qa],
    )
    assert analytics.total_responses == 1
    assert analytics.question_analytics[0].avg_rating == 5.0


# ---------------------------------------------------------------------------
# API layer tests
# ---------------------------------------------------------------------------

_ROUTER = "app.api.v1.corporate_ride_surveys"


# --- GET list surveys (member) ---


@pytest.mark.asyncio
async def test_api_list_surveys_200():
    """GET /corporate/ride-surveys returns the list of active surveys."""
    list_resp = RideSurveyListResponse(items=[], total=0)

    with (
        patch(f"{_ROUTER}._resolve_account_id", return_value=ACCOUNT_ID),
        patch(f"{_ROUTER}.list_surveys", return_value=list_resp),
    ):
        from app.api.v1.corporate_ride_surveys import list_member_surveys

        result = await list_member_surveys(
            user=MagicMock(id=MEMBER_ID), db=AsyncMock()
        )
    assert result.total == 0


@pytest.mark.asyncio
async def test_api_list_surveys_404_no_account():
    """GET /corporate/ride-surveys raises 404 when user has no account."""
    from fastapi import HTTPException

    with patch(
        f"{_ROUTER}._resolve_account_id",
        side_effect=HTTPException(status_code=404, detail="no account"),
    ):
        from app.api.v1.corporate_ride_surveys import list_member_surveys

        with pytest.raises(HTTPException) as exc:
            await list_member_surveys(
                user=MagicMock(id=MEMBER_ID), db=AsyncMock()
            )
    assert exc.value.status_code == 404


# --- GET {survey_id} (member) ---


@pytest.mark.asyncio
async def test_api_get_survey_200():
    """GET /corporate/ride-surveys/{survey_id} returns the survey."""
    survey_resp = _make_survey_response_schema(_make_survey())

    with (
        patch(f"{_ROUTER}._resolve_account_id", return_value=ACCOUNT_ID),
        patch(f"{_ROUTER}.get_survey", return_value=survey_resp),
    ):
        from app.api.v1.corporate_ride_surveys import get_survey_endpoint

        result = await get_survey_endpoint(
            survey_id=SURVEY_ID, user=MagicMock(id=MEMBER_ID), db=AsyncMock()
        )
    assert result.id == SURVEY_ID


@pytest.mark.asyncio
async def test_api_get_survey_404():
    """GET /corporate/ride-surveys/{survey_id} raises 404 when not found."""
    from fastapi import HTTPException

    with (
        patch(f"{_ROUTER}._resolve_account_id", return_value=ACCOUNT_ID),
        patch(
            f"{_ROUTER}.get_survey",
            side_effect=HTTPException(status_code=404, detail="not found"),
        ),
    ):
        from app.api.v1.corporate_ride_surveys import get_survey_endpoint

        with pytest.raises(HTTPException) as exc:
            await get_survey_endpoint(
                survey_id=SURVEY_ID, user=MagicMock(id=MEMBER_ID), db=AsyncMock()
            )
    assert exc.value.status_code == 404


# --- POST respond (member) ---


@pytest.mark.asyncio
async def test_api_submit_response_201():
    """POST /corporate/ride-surveys/respond returns the created response record."""
    record_resp = _make_record_schema(_make_response_record())
    data = SurveyResponseCreate(
        survey_id=SURVEY_ID,
        responses=[ResponseItem(question_id="q1", answer=5)],
    )

    with (
        patch(f"{_ROUTER}._resolve_account_id", return_value=ACCOUNT_ID),
        patch(f"{_ROUTER}.submit_response", return_value=record_resp),
    ):
        from app.api.v1.corporate_ride_surveys import submit_survey_response

        result = await submit_survey_response(
            data=data, user=MagicMock(id=MEMBER_ID), db=AsyncMock()
        )
    assert result.survey_id == SURVEY_ID


@pytest.mark.asyncio
async def test_api_submit_response_409_duplicate():
    """POST /respond raises 409 when member already responded."""
    from fastapi import HTTPException

    data = SurveyResponseCreate(
        survey_id=SURVEY_ID,
        responses=[ResponseItem(question_id="q1", answer=5)],
    )

    with (
        patch(f"{_ROUTER}._resolve_account_id", return_value=ACCOUNT_ID),
        patch(
            f"{_ROUTER}.submit_response",
            side_effect=HTTPException(status_code=409, detail="Duplicate"),
        ),
    ):
        from app.api.v1.corporate_ride_surveys import submit_survey_response

        with pytest.raises(HTTPException) as exc:
            await submit_survey_response(
                data=data, user=MagicMock(id=MEMBER_ID), db=AsyncMock()
            )
    assert exc.value.status_code == 409


# --- GET my-responses (member) ---


@pytest.mark.asyncio
async def test_api_my_responses_200():
    """GET /corporate/ride-surveys/my-responses returns member's own responses."""
    record = _make_response_record()
    scalar_res = MagicMock()
    scalar_res.all.return_value = [record]
    execute_result = MagicMock()
    execute_result.scalars.return_value = scalar_res
    db = AsyncMock()
    db.execute.return_value = execute_result

    with patch(f"{_ROUTER}._resolve_account_id", return_value=ACCOUNT_ID):
        from app.api.v1.corporate_ride_surveys import list_my_responses

        result = await list_my_responses(
            user=MagicMock(id=MEMBER_ID), db=db
        )
    assert result.total == 1


# --- POST create (admin) ---


@pytest.mark.asyncio
async def test_api_create_survey_201():
    """POST /corporate/ride-surveys returns created survey."""
    survey_resp = _make_survey_response_schema(_make_survey())
    data = RideSurveyCreate(
        title="Post-ride Survey",
        questions=[QuestionItem(question_id="q1", text="Rate us", type="rating")],
    )

    with (
        patch(f"{_ROUTER}._resolve_account_id", return_value=ACCOUNT_ID),
        patch(f"{_ROUTER}._require_account_admin"),
        patch(f"{_ROUTER}.create_survey", return_value=survey_resp),
    ):
        from app.api.v1.corporate_ride_surveys import create_survey_endpoint

        result = await create_survey_endpoint(
            data=data, user=MagicMock(id=ADMIN_ID), db=AsyncMock()
        )
    assert result.is_active is True


@pytest.mark.asyncio
async def test_api_create_survey_403_non_admin():
    """POST /corporate/ride-surveys raises 403 for non-admin."""
    from fastapi import HTTPException

    data = RideSurveyCreate(
        title="Survey",
        questions=[QuestionItem(question_id="q1", text="Rate us", type="rating")],
    )

    with (
        patch(f"{_ROUTER}._resolve_account_id", return_value=ACCOUNT_ID),
        patch(
            f"{_ROUTER}._require_account_admin",
            side_effect=HTTPException(status_code=403, detail="Forbidden"),
        ),
    ):
        from app.api.v1.corporate_ride_surveys import create_survey_endpoint

        with pytest.raises(HTTPException) as exc:
            await create_survey_endpoint(
                data=data, user=MagicMock(id=MEMBER_ID), db=AsyncMock()
            )
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_api_create_survey_409_duplicate_title():
    """POST /corporate/ride-surveys raises 409 on duplicate title."""
    from fastapi import HTTPException

    data = RideSurveyCreate(
        title="Post-ride Survey",
        questions=[QuestionItem(question_id="q1", text="Rate us", type="rating")],
    )

    with (
        patch(f"{_ROUTER}._resolve_account_id", return_value=ACCOUNT_ID),
        patch(f"{_ROUTER}._require_account_admin"),
        patch(
            f"{_ROUTER}.create_survey",
            side_effect=HTTPException(status_code=409, detail="Duplicate"),
        ),
    ):
        from app.api.v1.corporate_ride_surveys import create_survey_endpoint

        with pytest.raises(HTTPException) as exc:
            await create_survey_endpoint(
                data=data, user=MagicMock(id=ADMIN_ID), db=AsyncMock()
            )
    assert exc.value.status_code == 409


# --- PUT update (admin) ---


@pytest.mark.asyncio
async def test_api_update_survey_200():
    """PUT /corporate/ride-surveys/{survey_id} returns updated survey."""
    survey_resp = _make_survey_response_schema(_make_survey(title="Updated"))
    data = RideSurveyUpdate(title="Updated")

    with (
        patch(f"{_ROUTER}._resolve_account_id", return_value=ACCOUNT_ID),
        patch(f"{_ROUTER}._require_account_admin"),
        patch(f"{_ROUTER}.update_survey", return_value=survey_resp),
    ):
        from app.api.v1.corporate_ride_surveys import update_survey_endpoint

        result = await update_survey_endpoint(
            survey_id=SURVEY_ID,
            data=data,
            user=MagicMock(id=ADMIN_ID),
            db=AsyncMock(),
        )
    assert result.title == "Updated"


@pytest.mark.asyncio
async def test_api_update_survey_403_non_admin():
    """PUT /corporate/ride-surveys/{survey_id} raises 403 for non-admin."""
    from fastapi import HTTPException

    data = RideSurveyUpdate(title="Updated")

    with (
        patch(f"{_ROUTER}._resolve_account_id", return_value=ACCOUNT_ID),
        patch(
            f"{_ROUTER}._require_account_admin",
            side_effect=HTTPException(status_code=403, detail="Forbidden"),
        ),
    ):
        from app.api.v1.corporate_ride_surveys import update_survey_endpoint

        with pytest.raises(HTTPException) as exc:
            await update_survey_endpoint(
                survey_id=SURVEY_ID,
                data=data,
                user=MagicMock(id=MEMBER_ID),
                db=AsyncMock(),
            )
    assert exc.value.status_code == 403


# --- POST deactivate (admin) ---


@pytest.mark.asyncio
async def test_api_deactivate_survey_200():
    """POST deactivate returns deactivated survey."""
    survey_resp = _make_survey_response_schema(_make_inactive_survey())

    with (
        patch(f"{_ROUTER}._resolve_account_id", return_value=ACCOUNT_ID),
        patch(f"{_ROUTER}._require_account_admin"),
        patch(f"{_ROUTER}.deactivate_survey", return_value=survey_resp),
    ):
        from app.api.v1.corporate_ride_surveys import deactivate_survey_endpoint

        result = await deactivate_survey_endpoint(
            survey_id=SURVEY_ID, user=MagicMock(id=ADMIN_ID), db=AsyncMock()
        )
    assert result.is_active is False


@pytest.mark.asyncio
async def test_api_deactivate_survey_409_already_inactive():
    """POST deactivate raises 409 when already inactive."""
    from fastapi import HTTPException

    with (
        patch(f"{_ROUTER}._resolve_account_id", return_value=ACCOUNT_ID),
        patch(f"{_ROUTER}._require_account_admin"),
        patch(
            f"{_ROUTER}.deactivate_survey",
            side_effect=HTTPException(status_code=409, detail="Already inactive"),
        ),
    ):
        from app.api.v1.corporate_ride_surveys import deactivate_survey_endpoint

        with pytest.raises(HTTPException) as exc:
            await deactivate_survey_endpoint(
                survey_id=SURVEY_ID, user=MagicMock(id=ADMIN_ID), db=AsyncMock()
            )
    assert exc.value.status_code == 409


# --- POST reactivate (admin) ---


@pytest.mark.asyncio
async def test_api_reactivate_survey_200():
    """POST reactivate returns reactivated survey."""
    survey_resp = _make_survey_response_schema(_make_survey(is_active=True))

    with (
        patch(f"{_ROUTER}._resolve_account_id", return_value=ACCOUNT_ID),
        patch(f"{_ROUTER}._require_account_admin"),
        patch(f"{_ROUTER}.reactivate_survey", return_value=survey_resp),
    ):
        from app.api.v1.corporate_ride_surveys import reactivate_survey_endpoint

        result = await reactivate_survey_endpoint(
            survey_id=SURVEY_ID, user=MagicMock(id=ADMIN_ID), db=AsyncMock()
        )
    assert result.is_active is True


# --- DELETE survey (admin) ---


@pytest.mark.asyncio
async def test_api_delete_survey_204():
    """DELETE /corporate/ride-surveys/{survey_id} completes without raising."""
    with (
        patch(f"{_ROUTER}._resolve_account_id", return_value=ACCOUNT_ID),
        patch(f"{_ROUTER}._require_account_admin"),
        patch(f"{_ROUTER}.delete_survey", return_value=None),
    ):
        from app.api.v1.corporate_ride_surveys import delete_survey_endpoint

        await delete_survey_endpoint(
            survey_id=SURVEY_ID, user=MagicMock(id=ADMIN_ID), db=AsyncMock()
        )


@pytest.mark.asyncio
async def test_api_delete_survey_409_when_active():
    """DELETE survey raises 409 when survey is active."""
    from fastapi import HTTPException

    with (
        patch(f"{_ROUTER}._resolve_account_id", return_value=ACCOUNT_ID),
        patch(f"{_ROUTER}._require_account_admin"),
        patch(
            f"{_ROUTER}.delete_survey",
            side_effect=HTTPException(status_code=409, detail="Active"),
        ),
    ):
        from app.api.v1.corporate_ride_surveys import delete_survey_endpoint

        with pytest.raises(HTTPException) as exc:
            await delete_survey_endpoint(
                survey_id=SURVEY_ID, user=MagicMock(id=ADMIN_ID), db=AsyncMock()
            )
    assert exc.value.status_code == 409


# --- GET responses (admin) ---


@pytest.mark.asyncio
async def test_api_list_responses_200():
    """GET /responses returns the response list."""
    list_resp = SurveyResponseListResponse(items=[], total=0)

    with (
        patch(f"{_ROUTER}._resolve_account_id", return_value=ACCOUNT_ID),
        patch(f"{_ROUTER}._require_account_admin"),
        patch(f"{_ROUTER}.list_responses", return_value=list_resp),
    ):
        from app.api.v1.corporate_ride_surveys import list_survey_responses_endpoint

        result = await list_survey_responses_endpoint(
            survey_id=SURVEY_ID, user=MagicMock(id=ADMIN_ID), db=AsyncMock()
        )
    assert result.total == 0


# --- GET analytics (admin) ---


@pytest.mark.asyncio
async def test_api_get_analytics_200():
    """GET /analytics returns survey analytics."""
    qa = QuestionAnalytics(
        question_id="q1",
        text="Rate us",
        type="rating",
        response_count=1,
        avg_rating=4.0,
    )
    analytics_resp = SurveyAnalyticsResponse(
        survey_id=SURVEY_ID,
        title="Post-ride Survey",
        total_responses=1,
        question_analytics=[qa],
    )

    with (
        patch(f"{_ROUTER}._resolve_account_id", return_value=ACCOUNT_ID),
        patch(f"{_ROUTER}._require_account_admin"),
        patch(f"{_ROUTER}.get_survey_analytics", return_value=analytics_resp),
    ):
        from app.api.v1.corporate_ride_surveys import get_analytics_endpoint

        result = await get_analytics_endpoint(
            survey_id=SURVEY_ID, user=MagicMock(id=ADMIN_ID), db=AsyncMock()
        )
    assert result.total_responses == 1
    assert result.question_analytics[0].avg_rating == 4.0


# --- Platform-admin ---


@pytest.mark.asyncio
async def test_api_platform_list_all_surveys_200():
    """Platform-admin list-all returns all surveys."""
    list_resp = RideSurveyListResponse(items=[], total=0)

    with patch(f"{_ROUTER}.list_all_platform", return_value=list_resp):
        from app.api.v1.corporate_ride_surveys import admin_list_all_surveys

        result = await admin_list_all_surveys(
            account_id=None, _admin=MagicMock(), db=AsyncMock()
        )
    assert result.total == 0


@pytest.mark.asyncio
async def test_api_platform_list_surveys_for_account_200():
    """Platform-admin list-for-account returns surveys for a specific account."""
    list_resp = RideSurveyListResponse(items=[], total=0)

    with patch(f"{_ROUTER}.list_surveys", return_value=list_resp):
        from app.api.v1.corporate_ride_surveys import admin_list_surveys_for_account

        result = await admin_list_surveys_for_account(
            account_id=ACCOUNT_ID,
            is_active=None,
            _admin=MagicMock(),
            db=AsyncMock(),
        )
    assert result.total == 0
