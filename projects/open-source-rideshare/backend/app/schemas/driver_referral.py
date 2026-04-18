from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.models.driver_referral import DriverReferralStatus


class DriverReferralCodeResponse(BaseModel):
    """Referral code and summary stats for a driver."""

    referral_code: str | None
    total_referrals: int = Field(ge=0, description="Number of drivers who applied this code")
    pending_bonus: float = Field(ge=0.0, description="Sum of AWARDED bonuses not yet paid out")
    total_paid: float = Field(ge=0.0, description="Sum of all PAID bonuses")


class DriverReferralApplyRequest(BaseModel):
    code: str = Field(min_length=1, max_length=20)


class DriverReferralBonusEntry(BaseModel):
    id: int
    referee_driver_id: int
    milestone_rides: int
    bonus_amount: float
    status: DriverReferralStatus
    awarded_at: datetime | None
    paid_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}


class AdminDriverReferralEntry(BaseModel):
    id: int
    referrer_driver_id: int
    referee_driver_id: int
    milestone_rides: int
    bonus_amount: float
    status: DriverReferralStatus
    awarded_at: datetime | None
    paid_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}


class AdminDriverReferralListResponse(BaseModel):
    total: int
    referrals: list[AdminDriverReferralEntry]
