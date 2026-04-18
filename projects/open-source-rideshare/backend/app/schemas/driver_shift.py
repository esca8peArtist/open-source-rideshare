from datetime import datetime

from pydantic import BaseModel

from app.models.driver_shift import ShiftStatus


class DriverShiftResponse(BaseModel):
    id: int
    driver_id: int
    status: ShiftStatus
    started_at: datetime
    ended_at: datetime | None
    total_minutes: float | None
    rides_completed: int

    model_config = {"from_attributes": True}


class DriverShiftListResponse(BaseModel):
    items: list[DriverShiftResponse]
    total: int
    page: int
    page_size: int
