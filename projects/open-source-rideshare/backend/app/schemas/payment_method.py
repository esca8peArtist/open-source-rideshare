from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, field_validator


class SetupIntentResponse(BaseModel):
    setup_intent_id: str
    client_secret: str | None


class PaymentMethodCreate(BaseModel):
    stripe_payment_method_id: str = Field(min_length=1, max_length=255)
    card_brand: str = Field(min_length=1, max_length=50)
    card_last4: str = Field(min_length=4, max_length=4)
    card_exp_month: int = Field(ge=1, le=12)
    card_exp_year: int = Field(ge=2000, le=9999)

    @field_validator("card_last4")
    @classmethod
    def last4_must_be_digits(cls, v: str) -> str:
        if not v.isdigit():
            raise ValueError("card_last4 must be exactly 4 digits")
        return v


class PaymentMethodResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: int
    stripe_payment_method_id: str
    card_brand: str
    card_last4: str
    card_exp_month: int
    card_exp_year: int
    is_default: bool
    created_at: datetime


class PaymentMethodListResponse(BaseModel):
    items: list[PaymentMethodResponse]
    total: int
