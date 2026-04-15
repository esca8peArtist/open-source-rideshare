"""Pydantic schemas for driver bonus / quest programs."""

from datetime import datetime

from pydantic import BaseModel, Field

from app.models.driver_quest import QuestProgressStatus, QuestType


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------


class CreateQuestRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    quest_type: QuestType
    target_value: float = Field(..., gt=0)
    bonus_amount_cents: int = Field(..., gt=0)
    start_time: datetime
    end_time: datetime
    min_rating: float | None = Field(None, ge=0.0, le=5.0)
    zone_id: int | None = None


class UpdateQuestRequest(BaseModel):
    """Only title, description, and is_active may be changed after creation.

    target_value, bonus_amount_cents, and quest_type are intentionally excluded
    to prevent retroactive changes that would be unfair to drivers already
    working toward the original goal.
    """

    title: str | None = Field(None, min_length=1, max_length=255)
    description: str | None = None
    is_active: bool | None = None


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------


class QuestResponse(BaseModel):
    id: int
    title: str
    description: str | None
    quest_type: QuestType
    target_value: float
    bonus_amount_cents: int
    start_time: datetime
    end_time: datetime
    min_rating: float | None
    zone_id: int | None
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class QuestProgressResponse(BaseModel):
    """Quest detail combined with the driver's current progress."""

    quest_id: int
    quest_title: str
    quest_type: QuestType
    target_value: float
    bonus_amount_cents: int
    start_time: datetime
    end_time: datetime
    current_value: float
    status: QuestProgressStatus
    completed_at: datetime | None
    claimed_at: datetime | None
    progress_id: int

    model_config = {"from_attributes": True}


class ClaimQuestResponse(BaseModel):
    quest_id: int
    bonus_amount_cents: int
    claimed_at: datetime


class QuestStatsResponse(BaseModel):
    """Admin-level detail for a single quest including aggregate statistics."""

    quest: QuestResponse
    enrolled_count: int
    completed_count: int
    claimed_count: int
    total_bonus_paid_cents: int


class QuestLeaderboardEntry(BaseModel):
    rank: int
    driver_profile_id: int
    current_value: float
    status: QuestProgressStatus


class QuestLeaderboardResponse(BaseModel):
    quest_id: int
    entries: list[QuestLeaderboardEntry]
