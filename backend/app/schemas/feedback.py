from datetime import datetime

from pydantic import BaseModel, field_validator


class FeedbackCreate(BaseModel):
    rating: int
    comment: str | None = None
    categories: list[str] | None = None
    tip_amount: float = 0.0

    @field_validator("rating")
    @classmethod
    def validate_rating(cls, v: int) -> int:
        if v < 1 or v > 5:
            raise ValueError("Rating must be between 1 and 5")
        return v

    @field_validator("categories")
    @classmethod
    def validate_categories(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return v
        valid = {
            "safety", "cleanliness", "navigation", "professionalism",
            "vehicle_condition", "communication", "pricing", "timeliness", "other",
        }
        for cat in v:
            if cat not in valid:
                raise ValueError(f"Invalid category: {cat}")
        return v


class FeedbackResponse(BaseModel):
    id: int
    ride_id: int
    user_id: int
    role: str
    rating: int
    comment: str | None = None
    categories: list[str] | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class DisputeCreate(BaseModel):
    dispute_type: str
    description: str

    @field_validator("dispute_type")
    @classmethod
    def validate_dispute_type(cls, v: str) -> str:
        valid = {
            "fare", "route", "driver_behavior", "rider_behavior",
            "safety_concern", "property_damage", "lost_item",
            "cancellation_fee", "other",
        }
        if v not in valid:
            raise ValueError(f"Invalid dispute type: {v}")
        return v

    @field_validator("description")
    @classmethod
    def validate_description(cls, v: str) -> str:
        if len(v.strip()) < 10:
            raise ValueError("Description must be at least 10 characters")
        if len(v) > 2000:
            raise ValueError("Description must be at most 2000 characters")
        return v.strip()


class DisputeResolve(BaseModel):
    status: str
    resolution_notes: str
    refund_amount: float | None = None

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: str) -> str:
        valid = {
            "resolved_rider_favor", "resolved_driver_favor",
            "resolved_partial", "dismissed",
        }
        if v not in valid:
            raise ValueError(f"Invalid resolution status: {v}")
        return v

    @field_validator("resolution_notes")
    @classmethod
    def validate_notes(cls, v: str) -> str:
        if len(v.strip()) < 5:
            raise ValueError("Resolution notes must be at least 5 characters")
        return v.strip()


class DisputeResponse(BaseModel):
    id: int
    ride_id: int
    filed_by: int
    dispute_type: str
    status: str
    description: str
    resolution_notes: str | None = None
    resolved_by: int | None = None
    refund_amount: float | None = None
    created_at: datetime
    updated_at: datetime
    resolved_at: datetime | None = None

    model_config = {"from_attributes": True}


class DisputeListResponse(BaseModel):
    disputes: list[DisputeResponse]
    total: int


class FeedbackListResponse(BaseModel):
    feedback: list[FeedbackResponse]
    total: int
