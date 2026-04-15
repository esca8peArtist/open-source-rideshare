"""Corporate Fare Agreement model.

Enterprise accounts negotiate custom pricing with the platform.  A fare
agreement records the contracted rate type and value, the vehicle categories
it applies to, and an optional validity window.

Four rate types are supported:

  surge_cap          — maximum surge multiplier allowed for corporate rides
                       (e.g. value=1.5 → rides are never more than 1.5× base)
  flat_discount_pct  — flat percentage discount off the computed total fare
                       (e.g. value=10 → 10% off; must be 0–100)
  per_mile_rate_usd  — negotiated per-mile component in USD (informational
                       for the pricing engine; applied at ride billing time)
  per_minute_rate_usd — negotiated per-minute component in USD (informational)

Multiple agreements can be active simultaneously.  The compute service
applies surge_cap (takes the lowest cap) and flat_discount_pct (takes the
highest discount) when evaluating a hypothetical fare.  Per-mile/minute
rates are reference values surfaced to the billing layer.

CorporateFareAgreement — table corporate_fare_agreements
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


class FareAgreementRateType(str, enum.Enum):
    """The kind of pricing adjustment this agreement applies."""

    surge_cap = "surge_cap"
    flat_discount_pct = "flat_discount_pct"
    per_mile_rate_usd = "per_mile_rate_usd"
    per_minute_rate_usd = "per_minute_rate_usd"


class CorporateFareAgreement(Base):
    """A negotiated pricing contract between a corporate account and the platform.

    Attributes:
        id: UUID primary key.
        corporate_account_id: FK to corporate_accounts_v2.
        name: Human-friendly label (e.g. "Enterprise Surge Cap", "Q2 Discount").
        rate_type: What kind of pricing adjustment this is.
        value: The numeric value — interpreted per rate_type:
            surge_cap:           maximum multiplier (≥ 1.0)
            flat_discount_pct:   percentage off total fare (0–100)
            per_mile_rate_usd:   dollars per mile (> 0)
            per_minute_rate_usd: dollars per minute (> 0)
        applies_to_vehicle_types: JSONB list of vehicle categories this
            agreement covers; NULL = applies to all categories.
        valid_from: When the agreement takes effect; NULL = immediately.
        valid_until: When the agreement expires; NULL = no expiry.
        is_active: Soft-disable without deletion.
        notes: Optional free-text notes for internal use.
        created_by_id: FK to the admin who created this record.
        created_at / updated_at: Audit timestamps.
    """

    __tablename__ = "corporate_fare_agreements"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    corporate_account_id: Mapped[int] = mapped_column(
        ForeignKey("corporate_accounts_v2.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    name: Mapped[str] = mapped_column(String(200), nullable=False)

    rate_type: Mapped[FareAgreementRateType] = mapped_column(
        SAEnum(FareAgreementRateType),
        nullable=False,
    )

    # Numeric value — semantics depend on rate_type
    value: Mapped[Decimal] = mapped_column(Numeric(10, 4), nullable=False)

    # NULL → all vehicle categories; otherwise a list of strings
    applies_to_vehicle_types: Mapped[list[str] | None] = mapped_column(
        JSONB, nullable=True
    )

    # Validity window (NULL = open-ended on each side)
    valid_from: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    valid_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, index=True
    )

    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
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

    account = relationship("BusinessAccount", foreign_keys=[corporate_account_id])
    created_by = relationship("User", foreign_keys=[created_by_id])
