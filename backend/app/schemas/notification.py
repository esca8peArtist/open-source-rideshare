from datetime import datetime

from pydantic import BaseModel, Field


class NotificationPreferenceResponse(BaseModel):
    push_enabled: bool
    sms_enabled: bool
    email_enabled: bool
    quiet_hours_start: int | None
    quiet_hours_end: int | None
    ride_updates: bool
    payment_updates: bool
    promo_updates: bool
    safety_alerts: bool

    model_config = {"from_attributes": True}


class UpdateNotificationPreference(BaseModel):
    push_enabled: bool | None = None
    sms_enabled: bool | None = None
    email_enabled: bool | None = None
    quiet_hours_start: int | None = Field(None, ge=0, le=23)
    quiet_hours_end: int | None = Field(None, ge=0, le=23)
    ride_updates: bool | None = None
    payment_updates: bool | None = None
    promo_updates: bool | None = None
    safety_alerts: bool | None = None


class NotificationLogResponse(BaseModel):
    id: int
    notification_type: str
    channel: str
    title: str
    body: str
    status: str
    ride_id: int | None
    is_read: bool
    created_at: datetime
    read_at: datetime | None

    model_config = {"from_attributes": True}


class NotificationListResponse(BaseModel):
    notifications: list[NotificationLogResponse]
    total: int
    unread_count: int


class UnreadNotificationCount(BaseModel):
    total_unread: int
