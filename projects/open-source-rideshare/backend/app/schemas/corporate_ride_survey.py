"""Pydantic schemas for Corporate Ride Satisfaction Surveys.

Schemas:
  QuestionItem              — a single survey question definition
  ResponseItem              — a single answer item within a response
  RideSurveyCreate          — admin POST body to create a new survey
  RideSurveyUpdate          — admin PUT body for partial updates
  RideSurveyResponse        — full survey representation
  RideSurveyListResponse    — list of surveys with total count
  SurveyResponseCreate      — employee POST body to submit a response
  SurveyResponseRecord      — full survey-response representation
  SurveyResponseListResponse — list of responses with total count
  QuestionAnalytics         — per-question aggregated analytics
  SurveyAnalyticsResponse   — full analytics for a survey
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, field_validator


# ---------------------------------------------------------------------------
# Question / response item primitives
# ---------------------------------------------------------------------------


class QuestionItem(BaseModel):
    """A single question in a survey."""

    question_id: str
    text: str
    type: Literal["rating", "text", "boolean", "multiple_choice"]
    options: Optional[list[str]] = None


class ResponseItem(BaseModel):
    """A single answer within a survey response."""

    question_id: str
    answer: Any


# ---------------------------------------------------------------------------
# Survey create / update schemas
# ---------------------------------------------------------------------------


class RideSurveyCreate(BaseModel):
    """Fields required to create a new corporate ride survey."""

    title: str
    description: Optional[str] = None
    questions: list[QuestionItem]
    valid_from: Optional[datetime] = None
    valid_until: Optional[datetime] = None

    @field_validator("title")
    @classmethod
    def title_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("title must not be blank")
        return v.strip()

    @field_validator("questions")
    @classmethod
    def questions_not_empty(cls, v: list[QuestionItem]) -> list[QuestionItem]:
        if not v:
            raise ValueError("questions must contain at least one item")
        return v


class RideSurveyUpdate(BaseModel):
    """Partial update schema — only supplied fields are written."""

    title: Optional[str] = None
    description: Optional[str] = None
    questions: Optional[list[QuestionItem]] = None
    is_active: Optional[bool] = None
    valid_from: Optional[datetime] = None
    valid_until: Optional[datetime] = None

    @field_validator("title")
    @classmethod
    def title_not_empty(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and not v.strip():
            raise ValueError("title must not be blank")
        return v.strip() if v is not None else v


# ---------------------------------------------------------------------------
# Survey response schemas
# ---------------------------------------------------------------------------


class RideSurveyResponse(BaseModel):
    """Full representation of a corporate ride survey."""

    model_config = {"from_attributes": True}

    id: uuid.UUID
    account_id: int
    title: str
    description: Optional[str]
    questions: list[Any]
    is_active: bool
    valid_from: Optional[datetime]
    valid_until: Optional[datetime]
    created_by_id: Optional[int]
    created_at: datetime
    updated_at: datetime


class RideSurveyListResponse(BaseModel):
    """List of surveys with total count."""

    items: list[RideSurveyResponse]
    total: int


# ---------------------------------------------------------------------------
# Survey response submission schemas
# ---------------------------------------------------------------------------


class SurveyResponseCreate(BaseModel):
    """Body for an employee to submit a survey response."""

    survey_id: uuid.UUID
    ride_id: Optional[int] = None
    responses: list[ResponseItem]

    @field_validator("responses")
    @classmethod
    def responses_not_empty(cls, v: list[ResponseItem]) -> list[ResponseItem]:
        if not v:
            raise ValueError("responses must contain at least one item")
        return v


class SurveyResponseRecord(BaseModel):
    """Full representation of a submitted survey response."""

    model_config = {"from_attributes": True}

    id: uuid.UUID
    survey_id: uuid.UUID
    member_id: Optional[int]
    account_id: int
    ride_id: Optional[int]
    responses: list[Any]
    submitted_at: datetime


class SurveyResponseListResponse(BaseModel):
    """List of survey responses with total count."""

    items: list[SurveyResponseRecord]
    total: int


# ---------------------------------------------------------------------------
# Analytics schemas
# ---------------------------------------------------------------------------


class QuestionAnalytics(BaseModel):
    """Aggregated analytics for a single survey question."""

    question_id: str
    text: str
    type: str
    response_count: int
    avg_rating: Optional[float] = None
    text_responses: list[str] = []
    boolean_true_count: Optional[int] = None
    boolean_false_count: Optional[int] = None
    choice_counts: Optional[dict[str, int]] = None


class SurveyAnalyticsResponse(BaseModel):
    """Full analytics for a corporate ride survey."""

    survey_id: uuid.UUID
    title: str
    total_responses: int
    question_analytics: list[QuestionAnalytics]
