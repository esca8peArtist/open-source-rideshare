"""Platform configuration model.

Database-backed key/value config store for runtime platform settings.
Replaces the in-memory `_platform_settings` dict in admin.py with a
persistent, auditable, categorised configuration table.
"""
from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


class ConfigCategory(str, enum.Enum):
    PRICING = "pricing"
    OPERATIONS = "operations"
    SAFETY = "safety"
    FEATURES = "features"
    NOTIFICATIONS = "notifications"
    MATCHING = "matching"


class ConfigValueType(str, enum.Enum):
    STRING = "string"
    FLOAT = "float"
    INT = "int"
    BOOL = "bool"
    JSON = "json"


class PlatformConfig(Base):
    """Runtime platform configuration entry.

    Each row is a single named setting.  Values are stored as text and
    interpreted according to `value_type`.  `updated_by_id` is null for
    system-seeded defaults and populated when an admin changes the value.
    """

    __tablename__ = "platform_config"

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(Text, unique=True, index=True, nullable=False)
    category: Mapped[ConfigCategory] = mapped_column(
        Enum(ConfigCategory), index=True, nullable=False,
    )
    value_type: Mapped[ConfigValueType] = mapped_column(
        Enum(ConfigValueType), nullable=False,
    )
    value: Mapped[str] = mapped_column(Text, nullable=False)
    label: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )
    updated_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True,
    )

    updated_by = relationship("User", foreign_keys=[updated_by_id])
