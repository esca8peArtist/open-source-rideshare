from datetime import datetime

from pydantic import BaseModel, Field


class ServiceAreaCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    description: str | None = None
    coordinates: list[list[float]] = Field(
        ...,
        min_length=3,
        description="List of [lng, lat] pairs forming the boundary polygon. "
        "Must have at least 3 points. Will be auto-closed if first != last.",
    )


class ServiceAreaUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=200)
    description: str | None = None
    coordinates: list[list[float]] | None = Field(
        None,
        min_length=3,
        description="Updated polygon boundary as [lng, lat] pairs.",
    )
    is_active: bool | None = None


class ServiceAreaResponse(BaseModel):
    id: int
    name: str
    description: str | None = None
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ServiceAreaListResponse(BaseModel):
    areas: list[ServiceAreaResponse]
    total: int


class ServiceAreaValidation(BaseModel):
    valid: bool
    pickup_covered: bool
    dropoff_covered: bool
    message: str | None = None
