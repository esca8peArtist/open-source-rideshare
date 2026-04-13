from datetime import datetime

from pydantic import BaseModel, field_validator


class CreatePromoCodeRequest(BaseModel):
    code: str
    description: str = ""
    promo_type: str  # "flat" or "percent"
    value: float
    max_discount: float | None = None
    minimum_fare: float = 0.0
    max_uses: int | None = None
    max_uses_per_user: int = 1
    first_ride_only: bool = False
    expires_at: datetime | None = None

    @field_validator("code")
    @classmethod
    def normalize_code(cls, v: str) -> str:
        return v.upper().strip()

    @field_validator("promo_type")
    @classmethod
    def validate_type(cls, v: str) -> str:
        if v not in ("flat", "percent"):
            raise ValueError("promo_type must be 'flat' or 'percent'")
        return v

    @field_validator("value")
    @classmethod
    def validate_value(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("value must be positive")
        return v


class UpdatePromoCodeRequest(BaseModel):
    description: str | None = None
    is_active: bool | None = None
    max_uses: int | None = None
    max_uses_per_user: int | None = None
    expires_at: datetime | None = None


class PromoCodeResponse(BaseModel):
    id: int
    code: str
    description: str
    promo_type: str
    value: float
    max_discount: float | None
    minimum_fare: float
    max_uses: int | None
    max_uses_per_user: int
    total_uses: int
    is_active: bool
    first_ride_only: bool
    is_referral: bool
    expires_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}


class ApplyPromoRequest(BaseModel):
    code: str

    @field_validator("code")
    @classmethod
    def normalize_code(cls, v: str) -> str:
        return v.upper().strip()


class ApplyPromoResponse(BaseModel):
    valid: bool
    reason: str
    discount: float = 0.0
    code: str = ""
    promo_type: str = ""
    value: float = 0.0


class PromoRedemptionResponse(BaseModel):
    id: int
    promo_code_id: int
    code: str
    user_id: int
    ride_id: int | None
    discount_amount: float
    redeemed_at: datetime
