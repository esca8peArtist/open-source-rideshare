"""Schemas for the driver referral program."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator


class ApplyReferralRequest(BaseModel):
    """Request body for a driver to apply a referral code at sign-up."""

    code: str = Field(..., min_length=1, max_length=16, description="Referral code from another driver")

    @field_validator("code")
    @classmethod
    def strip_and_upper(cls, v: str) -> str:
        return v.strip().upper()


class ApplyReferralResponse(BaseModel):
    """Response after applying a referral code."""

    success: bool
    message: str
    referrer_driver_profile_id: Optional[int] = None


class ReferralCodeResponse(BaseModel):
    """A driver's own referral code with a high-level summary."""

    code: str
    driver_profile_id: int
    total_referrals: int
    pending_count: int
    qualified_count: int
    bonus_paid_count: int
    total_bonus_earned: float = Field(description="Sum of all bonus_paid bonuses (USD)")
    created_at: datetime


class ReferralItem(BaseModel):
    """Summary of a single referral made by this driver."""

    referral_id: int
    referred_driver_profile_id: int
    status: str
    rides_completed: int
    rides_needed: int = Field(description="Total rides required to qualify")
    bonus_amount: float
    created_at: datetime
    qualified_at: Optional[datetime] = None


class ReferralListResponse(BaseModel):
    """Paginated list of drivers referred by the requesting driver."""

    code: str
    referrals: list[ReferralItem]
    total: int


class AdminReferralStats(BaseModel):
    """Platform-wide referral statistics for admins."""

    total_codes_issued: int
    total_referrals: int
    pending_count: int
    qualified_count: int
    bonus_paid_count: int
    total_bonus_paid_amount: float = Field(description="Sum of all paid bonuses (USD)")
