from datetime import date, datetime

from pydantic import BaseModel, Field


# ---- Bank Account ----

class ConnectAccountSetupRequest(BaseModel):
    """Driver initiates Stripe Connect onboarding."""
    return_url: str = Field(..., description="URL to redirect after Stripe onboarding")
    refresh_url: str = Field(..., description="URL if onboarding link expires")


class ConnectAccountSetupResponse(BaseModel):
    account_id: str
    onboarding_url: str


class BankAccountResponse(BaseModel):
    id: int
    driver_id: int
    stripe_connect_account_id: str
    account_status: str
    bank_last_four: str | None = None
    bank_name: str | None = None
    payout_frequency: str
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class UpdatePayoutFrequencyRequest(BaseModel):
    frequency: str = Field(..., pattern="^(weekly|biweekly|daily)$")


# ---- Payout ----

class PayoutSummary(BaseModel):
    id: int
    period_start: date
    period_end: date
    ride_earnings: float
    tip_earnings: float
    cancellation_fee_earnings: float
    bonus_amount: float
    deductions: float
    total_amount: float
    trip_count: int
    status: str
    created_at: datetime
    processed_at: datetime | None = None
    completed_at: datetime | None = None

    model_config = {"from_attributes": True}


class PayoutDetailResponse(BaseModel):
    id: int
    driver_id: int
    bank_account_id: int
    period_start: date
    period_end: date
    ride_earnings: float
    tip_earnings: float
    cancellation_fee_earnings: float
    bonus_amount: float
    deductions: float
    total_amount: float
    trip_count: int
    stripe_transfer_id: str | None = None
    status: str
    failure_reason: str | None = None
    notes: str | None = None
    created_at: datetime
    processed_at: datetime | None = None
    completed_at: datetime | None = None

    model_config = {"from_attributes": True}


class PayoutListResponse(BaseModel):
    payouts: list[PayoutSummary]
    total_paid: float
    total_pending: float


# ---- Admin ----

class AdminCreatePayoutRequest(BaseModel):
    """Admin triggers a payout for a specific driver and period."""
    driver_id: int
    period_start: date
    period_end: date
    bonus_amount: float = 0.0
    deductions: float = 0.0
    notes: str | None = None


class AdminProcessPayoutRequest(BaseModel):
    """Admin triggers Stripe transfer for a pending payout."""
    payout_id: int


class AdminPayoutOverview(BaseModel):
    total_drivers_with_accounts: int
    total_pending_payouts: int
    total_pending_amount: float
    total_completed_payouts: int
    total_completed_amount: float
    total_failed_payouts: int


class AdminBulkPayoutRequest(BaseModel):
    """Admin triggers settlements for all eligible drivers for a period."""
    period_start: date
    period_end: date
    bonus_amount: float = 0.0
    deductions: float = 0.0
    notes: str | None = None
