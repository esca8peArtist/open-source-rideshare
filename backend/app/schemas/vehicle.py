from datetime import datetime

from pydantic import BaseModel, field_validator


class VehicleCreate(BaseModel):
    vehicle_type: str
    make: str
    model: str
    year: int
    color: str
    license_plate: str
    capacity: int = 4
    is_wheelchair_accessible: bool = False

    @field_validator("year")
    @classmethod
    def validate_year(cls, v: int) -> int:
        if v < 1990 or v > 2030:
            raise ValueError("Vehicle year must be between 1990 and 2030")
        return v

    @field_validator("capacity")
    @classmethod
    def validate_capacity(cls, v: int) -> int:
        if v < 1 or v > 15:
            raise ValueError("Vehicle capacity must be between 1 and 15")
        return v


class VehicleUpdate(BaseModel):
    vehicle_type: str | None = None
    make: str | None = None
    model: str | None = None
    year: int | None = None
    color: str | None = None
    license_plate: str | None = None
    capacity: int | None = None
    is_wheelchair_accessible: bool | None = None

    @field_validator("year")
    @classmethod
    def validate_year(cls, v: int | None) -> int | None:
        if v is not None and (v < 1990 or v > 2030):
            raise ValueError("Vehicle year must be between 1990 and 2030")
        return v

    @field_validator("capacity")
    @classmethod
    def validate_capacity(cls, v: int | None) -> int | None:
        if v is not None and (v < 1 or v > 15):
            raise ValueError("Vehicle capacity must be between 1 and 15")
        return v


class VehicleResponse(BaseModel):
    id: int
    driver_profile_id: int
    vehicle_type: str
    make: str
    model: str
    year: int
    color: str
    license_plate: str
    capacity: int
    is_wheelchair_accessible: bool
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}
