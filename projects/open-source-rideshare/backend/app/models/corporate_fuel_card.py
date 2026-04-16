"""Corporate Fuel Card models.

Enterprise fleet managers assign company fuel cards to fleet vehicles and/or
drivers to cover fuel costs.  Admins configure per-card spending limits and
record fuel transactions against each card.

Models
------
CorporateFuelCard            — table corporate_fuel_cards
CorporateFuelCardTransaction — table corporate_fuel_card_transactions
"""

from __future__ import annotations

import enum
import uuid
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


class CardNetwork(str, enum.Enum):
    """Fuel card issuer / network type."""

    VISA = "visa"
    MASTERCARD = "mastercard"
    FLEET_CARD = "fleet_card"
    WEX = "wex"
    VOYAGER = "voyager"
    OTHER = "other"


class FuelType(str, enum.Enum):
    """Type of fuel dispensed."""

    REGULAR = "regular"
    PREMIUM = "premium"
    DIESEL = "diesel"
    ELECTRIC = "electric"
    OTHER = "other"


class CorporateFuelCard(Base):
    """A company fuel card assigned to a fleet vehicle and/or driver.

    Attributes:
        id: Integer primary key.
        account_id: FK to corporate_accounts_v2 (CASCADE delete).
        card_last_four: Last four digits of the card number (display only).
        card_network: Issuer/network type enum.
        nickname: Friendly human-readable label, e.g. "Van 2 WEX Card".
            Unique within an account.
        assigned_vehicle_id: Optional FK to corporate_fleet_vehicles (UUID;
            SET NULL on delete).  A card can be attached to one vehicle.
        assigned_driver_id: Optional FK to users (SET NULL on delete).  A
            card can also be associated with a named driver.
        monthly_limit_usd: Optional per-card monthly spending cap.  None
            means no limit enforced.
        is_active: Whether the card is currently usable.
        issued_by_id: FK to users — admin who registered the card (SET NULL).
        notes: Free-text notes for fleet managers.
        created_at: UTC creation timestamp.
        updated_at: UTC last-update timestamp.
    """

    __tablename__ = "corporate_fuel_cards"
    __table_args__ = (
        Index("ix_corp_fuel_card_account_id", "account_id"),
        Index("ix_corp_fuel_card_is_active", "account_id", "is_active"),
        Index("ix_corp_fuel_card_vehicle_id", "assigned_vehicle_id"),
        Index("ix_corp_fuel_card_driver_id", "assigned_driver_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    account_id: Mapped[int] = mapped_column(
        ForeignKey("corporate_accounts_v2.id", ondelete="CASCADE"),
        nullable=False,
    )

    card_last_four: Mapped[str] = mapped_column(String(4), nullable=False)

    card_network: Mapped[CardNetwork] = mapped_column(
        SAEnum(CardNetwork),
        nullable=False,
        default=CardNetwork.OTHER,
        server_default=CardNetwork.OTHER.value,
    )

    nickname: Mapped[str] = mapped_column(String(100), nullable=False)

    assigned_vehicle_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("corporate_fleet_vehicles.id", ondelete="SET NULL"),
        nullable=True,
    )

    assigned_driver_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    monthly_limit_usd: Mapped[float | None] = mapped_column(
        Numeric(10, 2), nullable=True
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )

    issued_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    notes: Mapped[str | None] = mapped_column(String(500), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    account = relationship("BusinessAccount", foreign_keys=[account_id])
    assigned_vehicle = relationship(
        "CorporateFleetVehicle", foreign_keys=[assigned_vehicle_id]
    )
    assigned_driver = relationship("User", foreign_keys=[assigned_driver_id])
    issued_by = relationship("User", foreign_keys=[issued_by_id])
    transactions: Mapped[list[CorporateFuelCardTransaction]] = relationship(
        "CorporateFuelCardTransaction",
        back_populates="card",
        cascade="all, delete-orphan",
    )


class CorporateFuelCardTransaction(Base):
    """A single fuel transaction recorded against a company fuel card.

    Attributes:
        id: Integer primary key.
        fuel_card_id: FK to corporate_fuel_cards (CASCADE delete).
        account_id: FK to corporate_accounts_v2 (CASCADE delete).
        transaction_date: Date of the fuel purchase.
        merchant_name: Name of the fuel station or charging provider.
        fuel_type: Type of fuel dispensed.
        gallons: Volume dispensed in gallons (nullable — e.g. unknown or EV).
        amount_usd: Total transaction amount in USD.
        odometer_miles: Vehicle odometer reading at time of purchase (nullable).
        notes: Optional free-text notes.
        recorded_by_id: FK to users — the person who logged the transaction
            (SET NULL on delete).
        created_at: UTC creation timestamp.
    """

    __tablename__ = "corporate_fuel_card_transactions"
    __table_args__ = (
        Index("ix_corp_fuel_txn_account_id", "account_id"),
        Index("ix_corp_fuel_txn_card_id", "fuel_card_id"),
        Index("ix_corp_fuel_txn_date", "fuel_card_id", "transaction_date"),
        Index("ix_corp_fuel_txn_acct_date", "account_id", "transaction_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    fuel_card_id: Mapped[int] = mapped_column(
        ForeignKey("corporate_fuel_cards.id", ondelete="CASCADE"),
        nullable=False,
    )

    account_id: Mapped[int] = mapped_column(
        ForeignKey("corporate_accounts_v2.id", ondelete="CASCADE"),
        nullable=False,
    )

    transaction_date: Mapped[date] = mapped_column(Date, nullable=False)

    merchant_name: Mapped[str] = mapped_column(String(200), nullable=False)

    fuel_type: Mapped[FuelType] = mapped_column(
        SAEnum(FuelType),
        nullable=False,
        default=FuelType.OTHER,
        server_default=FuelType.OTHER.value,
    )

    gallons: Mapped[float | None] = mapped_column(Numeric(8, 3), nullable=True)

    amount_usd: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)

    odometer_miles: Mapped[int | None] = mapped_column(Integer, nullable=True)

    notes: Mapped[str | None] = mapped_column(String(500), nullable=True)

    recorded_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    card = relationship("CorporateFuelCard", back_populates="transactions")
    account = relationship("BusinessAccount", foreign_keys=[account_id])
    recorded_by = relationship("User", foreign_keys=[recorded_by_id])
