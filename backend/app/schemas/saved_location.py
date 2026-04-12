from datetime import datetime

from pydantic import BaseModel, field_validator


class SavedLocationCreate(BaseModel):
    label: str = "custom"  # home, work, custom
    name: str
    address: str
    lat: float
    lng: float
    place_id: str | None = None
    icon: str | None = None

    @field_validator("label")
    @classmethod
    def validate_label(cls, v: str) -> str:
        allowed = {"home", "work", "custom"}
        if v not in allowed:
            raise ValueError(f"Label must be one of: {', '.join(sorted(allowed))}")
        return v

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        v = v.strip()
        if not v or len(v) > 100:
            raise ValueError("Name must be 1-100 characters")
        return v

    @field_validator("lat")
    @classmethod
    def validate_lat(cls, v: float) -> float:
        if v < -90 or v > 90:
            raise ValueError("Latitude must be between -90 and 90")
        return v

    @field_validator("lng")
    @classmethod
    def validate_lng(cls, v: float) -> float:
        if v < -180 or v > 180:
            raise ValueError("Longitude must be between -180 and 180")
        return v


class SavedLocationUpdate(BaseModel):
    label: str | None = None
    name: str | None = None
    address: str | None = None
    lat: float | None = None
    lng: float | None = None
    place_id: str | None = None
    icon: str | None = None

    @field_validator("label")
    @classmethod
    def validate_label(cls, v: str | None) -> str | None:
        if v is not None:
            allowed = {"home", "work", "custom"}
            if v not in allowed:
                raise ValueError(f"Label must be one of: {', '.join(sorted(allowed))}")
        return v

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str | None) -> str | None:
        if v is not None:
            v = v.strip()
            if not v or len(v) > 100:
                raise ValueError("Name must be 1-100 characters")
        return v

    @field_validator("lat")
    @classmethod
    def validate_lat(cls, v: float | None) -> float | None:
        if v is not None and (v < -90 or v > 90):
            raise ValueError("Latitude must be between -90 and 90")
        return v

    @field_validator("lng")
    @classmethod
    def validate_lng(cls, v: float | None) -> float | None:
        if v is not None and (v < -180 or v > 180):
            raise ValueError("Longitude must be between -180 and 180")
        return v


class SavedLocationResponse(BaseModel):
    id: int
    user_id: int
    label: str
    name: str
    address: str
    lat: float
    lng: float
    place_id: str | None = None
    icon: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
