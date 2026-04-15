"""Pydantic schemas for the rider referral program."""

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class RiderReferralCodeResponse(BaseModel):
    """Referrer's code plus aggregate stats."""

    code: str
    user_id: int
    total_referrals: int
    pending_count: int
    qualified_count: int
    rewarded_count: int
    total_reward_earned: float = Field(description="Total USD rewards credited to date")
    created_at: datetime

    model_config = {"from_attributes": True}


class RiderReferralItem(BaseModel):
    """Single referral in the paginated list."""

    referral_id: int
    referred_user_id: int
    status: str
    first_ride_id: Optional[int] = None
    referrer_reward_amount: float
    referred_discount_amount: float
    created_at: datetime
    qualified_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class RiderReferralListResponse(BaseModel):
    """Paginated referral list with the caller's code embedded."""

    code: str
    referrals: List[RiderReferralItem]
    total: int


class ApplyRiderReferralRequest(BaseModel):
    code: str = Field(min_length=1, max_length=16)


class ApplyRiderReferralResponse(BaseModel):
    success: bool
    message: str
    referrer_user_id: Optional[int] = None


class AdminRiderReferralStats(BaseModel):
    """Platform-wide aggregate referral statistics."""

    total_codes_issued: int
    total_referrals: int
    pending_count: int
    qualified_count: int
    rewarded_count: int
    total_reward_paid_amount: float = Field(description="Sum of referrer rewards with status=rewarded")
