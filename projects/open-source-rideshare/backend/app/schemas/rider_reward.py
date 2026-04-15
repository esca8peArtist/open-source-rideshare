"""Pydantic schemas for the rider loyalty rewards feature."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.models.rider_reward import RewardTransactionType


# ---------------------------------------------------------------------------
# Account
# ---------------------------------------------------------------------------


class RewardAccountResponse(BaseModel):
    """Current reward account summary returned to riders."""

    points_balance: int
    lifetime_earned: int
    lifetime_redeemed: int
    # Convenience: dollar value of current balance (balance × POINT_VALUE_CENTS / 100)
    balance_value_usd: float
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Transactions
# ---------------------------------------------------------------------------


class RewardTransactionResponse(BaseModel):
    id: int
    transaction_type: RewardTransactionType
    points_delta: int
    balance_after: int
    description: str | None
    ride_id: int | None
    created_at: datetime

    model_config = {"from_attributes": True}


class RewardTransactionPage(BaseModel):
    items: list[RewardTransactionResponse]
    total: int
    offset: int
    limit: int


# ---------------------------------------------------------------------------
# Redemption
# ---------------------------------------------------------------------------


class RedeemPointsRequest(BaseModel):
    """Request body for POST /riders/me/rewards/redeem."""

    points: int = Field(..., ge=1, description="Number of points to redeem")
    # Optional: rider can pre-declare which ride they intend to apply the
    # discount to.  Not enforced server-side — included for client UX.
    ride_id: int | None = Field(None, description="Ride the discount will be applied to")


class RedeemPointsResponse(BaseModel):
    """Response after a successful redemption."""

    points_redeemed: int
    discount_value_usd: float       # dollar value of the points redeemed
    new_balance: int
    transaction_id: int


# ---------------------------------------------------------------------------
# Admin adjustments
# ---------------------------------------------------------------------------


class AdminAdjustPointsRequest(BaseModel):
    """Admin manually credits or debits a rider's points balance."""

    rider_id: int
    points_delta: int = Field(..., description="Positive = credit, negative = debit")
    description: str | None = Field(
        None, max_length=255, description="Reason for adjustment (shown in history)"
    )


# ---------------------------------------------------------------------------
# Admin stats
# ---------------------------------------------------------------------------


class RewardPlatformStats(BaseModel):
    """Platform-wide rewards summary for admin dashboard."""

    total_accounts: int
    total_outstanding_points: int          # sum of all current balances
    outstanding_liability_usd: float       # dollar value of outstanding points
    total_lifetime_earned: int
    total_lifetime_redeemed: int
    total_lifetime_earned_usd: float       # dollar value ever earned
    total_lifetime_redeemed_usd: float     # dollar value ever redeemed
