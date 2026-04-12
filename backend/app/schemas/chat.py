from datetime import datetime

from pydantic import BaseModel, field_validator


class ChatMessageSend(BaseModel):
    ride_id: int
    message: str

    @field_validator("message")
    @classmethod
    def validate_message(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Message cannot be empty")
        if len(v) > 2000:
            raise ValueError("Message cannot exceed 2000 characters")
        return v


class ChatMessageResponse(BaseModel):
    id: int
    ride_id: int
    sender_id: int
    recipient_id: int
    message: str
    is_read: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class ChatHistoryResponse(BaseModel):
    ride_id: int
    messages: list[ChatMessageResponse]
    total: int


class UnreadCountResponse(BaseModel):
    ride_id: int
    unread_count: int
