"""Corporate Shuttle Pass models.

Enterprise accounts can create shuttle pass types (e.g., "Monthly 20-Ride Pass")
and issue them to individual employees.  Each pass tracks rides used vs. total;
when an employee redeems a pass against a shuttle booking a usage record is
appended and the rides_used counter is incremented.

Models:
  CorporateShuttlePassType
      — admin-defined pass template (ride count, validity, price)
  CorporateShuttlePass
      — issued pass for a specific member
  CorporateShuttlePassUsage
      — append-only ledger of each ride redemption

Tables:
  corporate_shuttle_pass_types
  corporate_shuttle_passes
  corporate_shuttle_pass_usages
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


class CorporateShuttlePassType(Base):
    """An admin-defined shuttle pass template owned by a corporate account.

    Attributes:
        id: UUID primary key.
        account_id: FK to corporate_accounts_v2 (CASCADE delete).
        name: Human-readable pass type name (unique per account).
        description: Optional description.
        ride_count: Number of rides included in each issued pass.
        validity_days: Days from issue date until expiry (nullable = no expiry).
        price_usd: Nominal cost for accounting purposes (nullable).
        notes: Free-text notes (nullable).
        is_active: Soft-delete flag.
        created_by_id: FK to users (SET NULL) — admin who created the record.
        created_at: UTC creation timestamp.
        updated_at: UTC last-modification timestamp.
    """

    __tablename__ = "corporate_shuttle_pass_types"
    __table_args__ = (
        UniqueConstraint(
            "account_id", "name", name="uq_shuttle_pass_type_account_name"
        ),
        Index("ix_shuttle_pass_type_account_id", "account_id"),
        Index("ix_shuttle_pass_type_is_active", "is_active"),
        Index("ix_shuttle_pass_type_created_at", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    account_id: Mapped[int] = mapped_column(
        ForeignKey("corporate_accounts_v2.id", ondelete="CASCADE"),
        nullable=False,
    )

    name: Mapped[str] = mapped_column(String(200), nullable=False)

    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    ride_count: Mapped[int] = mapped_column(Integer, nullable=False)

    validity_days: Mapped[int | None] = mapped_column(Integer, nullable=True)

    price_usd: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 2), nullable=True
    )

    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    created_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
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

    # ---- Relationships ----

    account = relationship(
        "BusinessAccount", foreign_keys=[account_id], lazy="raise"
    )
    created_by = relationship("User", foreign_keys=[created_by_id], lazy="raise")
    passes = relationship(
        "CorporateShuttlePass",
        back_populates="pass_type",
        lazy="raise",
        cascade="all, delete-orphan",
    )


class CorporateShuttlePass(Base):
    """An issued shuttle pass for a specific corporate account member.

    rides_remaining is a computed view: ride_count - rides_used.  The service
    layer keeps rides_used accurate; do not update it outside the service.

    Attributes:
        id: UUID primary key.
        pass_type_id: FK to corporate_shuttle_pass_types (CASCADE delete).
        account_id: Denormalised FK to corporate_accounts_v2 (CASCADE delete).
        member_id: FK to users (SET NULL) — employee holding the pass.
        rides_total: Number of rides copied from the pass type at issuance.
        rides_used: Running count of redeemed rides.
        issued_at: UTC timestamp of issuance.
        expires_at: UTC expiry timestamp (nullable — None means no expiry).
        is_active: Soft-delete flag (admins can deactivate a pass early).
        issued_by_id: FK to users (SET NULL) — admin who issued the pass.
        notes: Free-text notes (nullable).
        created_at: UTC creation timestamp.
        updated_at: UTC last-modification timestamp.
    """

    __tablename__ = "corporate_shuttle_passes"
    __table_args__ = (
        Index("ix_shuttle_pass_pass_type_id", "pass_type_id"),
        Index("ix_shuttle_pass_account_id", "account_id"),
        Index("ix_shuttle_pass_member_id", "member_id"),
        Index("ix_shuttle_pass_is_active", "is_active"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    pass_type_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("corporate_shuttle_pass_types.id", ondelete="CASCADE"),
        nullable=False,
    )

    account_id: Mapped[int] = mapped_column(
        ForeignKey("corporate_accounts_v2.id", ondelete="CASCADE"),
        nullable=False,
    )

    member_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    rides_total: Mapped[int] = mapped_column(Integer, nullable=False)

    rides_used: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    issued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    issued_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    # ---- Relationships ----

    account = relationship(
        "BusinessAccount", foreign_keys=[account_id], lazy="raise"
    )
    pass_type = relationship(
        "CorporateShuttlePassType",
        foreign_keys=[pass_type_id],
        back_populates="passes",
        lazy="raise",
    )
    member = relationship("User", foreign_keys=[member_id], lazy="raise")
    issued_by = relationship("User", foreign_keys=[issued_by_id], lazy="raise")
    usages = relationship(
        "CorporateShuttlePassUsage",
        back_populates="pass_",
        lazy="raise",
        cascade="all, delete-orphan",
    )


class CorporateShuttlePassUsage(Base):
    """Append-only record of a shuttle pass ride redemption.

    Attributes:
        id: UUID primary key.
        pass_id: FK to corporate_shuttle_passes (CASCADE delete).
        account_id: Denormalised FK to corporate_accounts_v2 (CASCADE delete).
        member_id: Denormalised FK to users (SET NULL).
        booking_id: FK to corporate_shuttle_bookings (SET NULL, nullable) —
            the shuttle booking this redemption was applied to.
        redeemed_at: UTC timestamp of the redemption.
        rides_remaining_after: Snapshot of rides remaining after this
            redemption (rides_total - rides_used at the time of redemption).
        created_at: UTC creation timestamp.
    """

    __tablename__ = "corporate_shuttle_pass_usages"
    __table_args__ = (
        Index("ix_shuttle_pass_usage_pass_id", "pass_id"),
        Index("ix_shuttle_pass_usage_account_id", "account_id"),
        Index("ix_shuttle_pass_usage_member_id", "member_id"),
        Index("ix_shuttle_pass_usage_redeemed_at", "redeemed_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    pass_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("corporate_shuttle_passes.id", ondelete="CASCADE"),
        nullable=False,
    )

    account_id: Mapped[int] = mapped_column(
        ForeignKey("corporate_accounts_v2.id", ondelete="CASCADE"),
        nullable=False,
    )

    member_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    booking_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("corporate_shuttle_bookings.id", ondelete="SET NULL"),
        nullable=True,
    )

    redeemed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    rides_remaining_after: Mapped[int] = mapped_column(Integer, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # ---- Relationships ----

    account = relationship(
        "BusinessAccount", foreign_keys=[account_id], lazy="raise"
    )
    pass_ = relationship(
        "CorporateShuttlePass",
        foreign_keys=[pass_id],
        back_populates="usages",
        lazy="raise",
    )
    member = relationship("User", foreign_keys=[member_id], lazy="raise")
    booking = relationship(
        "CorporateShuttleBooking",
        foreign_keys=[booking_id],
        lazy="raise",
    )
