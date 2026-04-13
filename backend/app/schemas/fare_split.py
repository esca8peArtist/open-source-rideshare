from datetime import datetime

from pydantic import BaseModel, field_validator


class SplitParticipant(BaseModel):
    """A participant to split the fare with."""
    user_id: int | None = None
    phone: str | None = None
    email: str | None = None
    share_percentage: float | None = None  # If None, split equally

    @field_validator("share_percentage")
    @classmethod
    def validate_percentage(cls, v: float | None) -> float | None:
        if v is not None and (v <= 0 or v > 100):
            raise ValueError("share_percentage must be between 0 and 100")
        return v


class CreateFareSplitRequest(BaseModel):
    """Initiate a fare split for a ride."""
    participants: list[SplitParticipant]
    split_equally: bool = True

    @field_validator("participants")
    @classmethod
    def validate_participants(cls, v: list[SplitParticipant]) -> list[SplitParticipant]:
        if len(v) < 1:
            raise ValueError("Must have at least 1 participant to split with")
        if len(v) > 4:
            raise ValueError("Cannot split with more than 4 participants")
        for p in v:
            if not p.user_id and not p.phone and not p.email:
                raise ValueError("Each participant must have a user_id, phone, or email")
        return v


class FareSplitResponse(BaseModel):
    id: int
    ride_id: int
    user_id: int | None = None
    invite_phone: str | None = None
    invite_email: str | None = None
    is_initiator: bool
    status: str
    share_amount: float
    share_percentage: float
    created_at: datetime
    responded_at: datetime | None = None

    model_config = {"from_attributes": True}


class FareSplitDetailResponse(BaseModel):
    """Full split details for a ride."""
    ride_id: int
    total_fare: float
    split_count: int
    splits: list[FareSplitResponse]
    all_accepted: bool
    all_paid: bool


class RespondToSplitRequest(BaseModel):
    accept: bool


class SplitPaymentResponse(BaseModel):
    split_id: int
    share_amount: float
    client_secret: str | None = None
    payment_intent_id: str | None = None
    status: str
