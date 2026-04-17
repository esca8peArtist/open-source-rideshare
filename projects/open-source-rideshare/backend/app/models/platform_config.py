"""DB models for persistent platform configuration with full audit history."""
from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base


class ConfigValueType(str, enum.Enum):
    string = "string"
    integer = "integer"
    float_ = "float"
    boolean = "boolean"
    json = "json"

    # Make the enum value serialise as the plain string, not the member name
    @classmethod
    def _missing_(cls, value: object):
        for member in cls:
            if member.value == value:
                return member
        return None


class ConfigCategory(str, enum.Enum):
    pricing = "pricing"
    surge = "surge"
    safety = "safety"
    matching = "matching"
    features = "features"
    notifications = "notifications"
    compliance = "compliance"


class PlatformConfig(Base):
    __tablename__ = "platform_configs"

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    value: Mapped[str] = mapped_column(Text)
    value_type: Mapped[ConfigValueType] = mapped_column(Enum(ConfigValueType))
    category: Mapped[ConfigCategory] = mapped_column(Enum(ConfigCategory), index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    is_active: Mapped[bool] = mapped_column(default=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )


class PlatformConfigHistory(Base):
    __tablename__ = "platform_config_history"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Not a FK — preserved even if the config entry is later deleted
    config_key: Mapped[str] = mapped_column(String(100), index=True)
    old_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    new_value: Mapped[str] = mapped_column(Text)
    changed_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
