"""Corporate Custom Ride Field models.

Enterprise accounts often need to capture additional metadata on every ride — project
billing codes, client matter numbers, cost-allocation tags, or any other field that the
corporate back-office system requires.  Admins define the field schema; employees fill
in values when booking or after the ride completes.

Models
------
CorporateCustomField        — field definition (schema) per account
CorporateRideCustomFieldValue — individual value stored against a ride
"""

from __future__ import annotations

import enum
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


class CustomFieldType(str, enum.Enum):
    """Data type / widget for a custom field."""

    TEXT = "text"
    NUMBER = "number"
    DROPDOWN = "dropdown"
    CHECKBOX = "checkbox"


class CorporateCustomField(Base):
    """Schema definition for a custom field on rides within a corporate account.

    Attributes:
        account_id: FK to corporate_accounts_v2 (CASCADE delete).
        label: Human-readable label shown to employees (e.g. "Project Code").
        field_key: Slugified machine key unique per account (e.g. "project_code").
            Used as a stable identifier in exports and integrations.
        field_type: Data type/widget — text, number, dropdown, or checkbox.
        dropdown_options: Non-null only when field_type == "dropdown".  A JSON
            array of string options the employee may select from.
        is_required: When True, a value must be supplied on every corporate ride.
        max_length: Maximum character length enforced on text fields.  Null for
            non-text types.
        display_order: Ascending integer for UI ordering.  Defaults to 0.
        is_active: Soft-delete flag.  Inactive fields are hidden from employees
            but values already set are preserved.
        created_by_id: FK to users — the admin who created the field.
        created_at: Creation timestamp.
        updated_at: Last modification timestamp.
    """

    __tablename__ = "corporate_custom_fields"
    __table_args__ = (
        UniqueConstraint(
            "account_id", "field_key", name="uq_custom_field_account_key"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    account_id: Mapped[int] = mapped_column(
        ForeignKey("corporate_accounts_v2.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    label: Mapped[str] = mapped_column(String(200), nullable=False)
    field_key: Mapped[str] = mapped_column(String(100), nullable=False)

    field_type: Mapped[CustomFieldType] = mapped_column(
        Enum(CustomFieldType, name="custom_field_type"),
        nullable=False,
    )

    dropdown_options: Mapped[list[str] | None] = mapped_column(
        JSONB, nullable=True
    )

    is_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    max_length: Mapped[int | None] = mapped_column(Integer, nullable=True)
    display_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    created_by_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"),
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    account = relationship("BusinessAccount", foreign_keys=[account_id])
    created_by = relationship("User", foreign_keys=[created_by_id])
    values: Mapped[list[CorporateRideCustomFieldValue]] = relationship(
        "CorporateRideCustomFieldValue", back_populates="field", passive_deletes=True
    )


class CorporateRideCustomFieldValue(Base):
    """A single custom field value recorded against a specific ride.

    Attributes:
        field_id: FK to corporate_custom_fields (CASCADE delete).
        ride_id: FK to rides (CASCADE delete).
        value: Stored as text regardless of the field type; the service layer
            validates the value against the field schema before persisting.
        set_by_id: FK to users — the employee (or admin) who set the value.
        set_at: Timestamp of the most recent write.
    """

    __tablename__ = "corporate_ride_custom_field_values"
    __table_args__ = (
        UniqueConstraint("field_id", "ride_id", name="uq_ride_custom_field_value"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    field_id: Mapped[int] = mapped_column(
        ForeignKey("corporate_custom_fields.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    ride_id: Mapped[int] = mapped_column(
        ForeignKey("rides.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    value: Mapped[str] = mapped_column(Text, nullable=False)

    set_by_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"),
        nullable=False,
    )

    set_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    field: Mapped[CorporateCustomField] = relationship(
        "CorporateCustomField", back_populates="values"
    )
    set_by = relationship("User", foreign_keys=[set_by_id])
