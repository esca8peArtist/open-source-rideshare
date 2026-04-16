"""Corporate SLA Policy models.

Enterprise corporate accounts define Service Level Agreement (SLA) policies
that set contractual quality targets for rides.  Each ride is evaluated
against the currently-active policy and the result is stored as an immutable
snapshot so admins can generate compliance reports and breach lists.

Models:
  CorporateSLAPolicy
      — a named SLA policy belonging to a corporate account
  CorporateSLARideRecord
      — an immutable per-ride SLA evaluation snapshot

Table names:
  corporate_sla_policies
  corporate_sla_ride_records
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

import sqlalchemy as sa
from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
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


class CorporateSLAPolicy(Base):
    """A named SLA policy belonging to a corporate account.

    Each policy defines thresholds for one or more quality dimensions:
    wait time, driver rating, on-time arrival, and ride completion rate.
    Only one policy may be active per account at a time; activating a new
    policy automatically deactivates any currently-active one.

    Attributes:
        id: UUID primary key.
        account_id: FK to corporate_accounts_v2 (CASCADE delete).
        name: Human-readable policy name, unique among active policies.
        max_wait_time_minutes: Maximum acceptable wait in minutes.
        min_driver_rating: Minimum driver rating for compliance (e.g. 4.5).
        on_time_window_minutes: Tolerance window in minutes for scheduled rides.
        target_completion_rate_pct: Target ride completion percentage (0–100).
        is_active: Only one active policy per account at a time.
        effective_from: Optional date from which the policy applies.
        effective_until: Optional date until which the policy applies.
        created_by_id: FK to users (SET NULL) — admin who created the record.
        created_at: UTC creation timestamp.
        updated_at: UTC last-modification timestamp.
    """

    __tablename__ = "corporate_sla_policies"
    __table_args__ = (
        Index("ix_corp_sla_policy_account_id", "account_id"),
        Index("ix_corp_sla_policy_account_active", "account_id", "is_active"),
        Index("ix_corp_sla_policy_account_created", "account_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    account_id: Mapped[int] = mapped_column(
        ForeignKey("corporate_accounts_v2.id", ondelete="CASCADE"),
        nullable=False,
    )

    name: Mapped[str] = mapped_column(String(100), nullable=False)

    max_wait_time_minutes: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )

    min_driver_rating: Mapped[sa.Numeric | None] = mapped_column(
        Numeric(3, 2), nullable=True
    )

    on_time_window_minutes: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )

    target_completion_rate_pct: Mapped[sa.Numeric | None] = mapped_column(
        Numeric(5, 2), nullable=True
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )

    effective_from: Mapped[date | None] = mapped_column(Date, nullable=True)

    effective_until: Mapped[date | None] = mapped_column(Date, nullable=True)

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
    ride_records = relationship(
        "CorporateSLARideRecord",
        back_populates="policy",
        lazy="raise",
        cascade="all, delete-orphan",
    )


class CorporateSLARideRecord(Base):
    """An immutable per-ride SLA evaluation snapshot.

    Created once per corporate ride.  Captures the policy thresholds in
    effect at evaluation time so historical compliance data remains
    consistent even after policies are updated or deleted.

    ``account_id`` is denormalised for efficient platform-admin queries.

    Attributes:
        id: UUID primary key.
        account_id: Denormalised FK to corporate_accounts_v2 (CASCADE delete).
        policy_id: FK to corporate_sla_policies (SET NULL on policy delete).
        ride_id: FK to rides (SET NULL on ride delete).
        member_id: FK to corporate_account_members (SET NULL).
        wait_time_minutes: Actual wait time measured (minutes).
        driver_rating_at_time: Driver's rating at time of ride.
        was_scheduled_ride: Whether this was a pre-booked ride.
        scheduled_pickup_at: Original scheduled pickup time.
        actual_pickup_at: When the driver actually arrived at pickup.
        arrival_delta_minutes: actual_pickup_at - scheduled_pickup_at
            (negative = early, positive = late).
        wait_time_met: Whether the wait time threshold was satisfied.
            NULL when the threshold is not configured.
        driver_rating_met: Whether the driver rating threshold was satisfied.
            NULL when the threshold is not configured.
        on_time_met: Whether the on-time window threshold was satisfied.
            NULL when not applicable (non-scheduled ride or no threshold).
        overall_sla_met: True only if every configured dimension is met.
        evaluated_at: UTC timestamp of evaluation.
    """

    __tablename__ = "corporate_sla_ride_records"
    __table_args__ = (
        Index("ix_corp_sla_record_account_id", "account_id"),
        Index("ix_corp_sla_record_account_policy", "account_id", "policy_id"),
        Index("ix_corp_sla_record_account_met", "account_id", "overall_sla_met"),
        Index("ix_corp_sla_record_account_eval", "account_id", "evaluated_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    account_id: Mapped[int] = mapped_column(
        ForeignKey("corporate_accounts_v2.id", ondelete="CASCADE"),
        nullable=False,
    )

    policy_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("corporate_sla_policies.id", ondelete="SET NULL"),
        nullable=True,
    )

    ride_id: Mapped[int | None] = mapped_column(
        ForeignKey("rides.id", ondelete="SET NULL"),
        nullable=True,
    )

    member_id: Mapped[int | None] = mapped_column(
        ForeignKey("corporate_account_members.id", ondelete="SET NULL"),
        nullable=True,
    )

    wait_time_minutes: Mapped[sa.Numeric | None] = mapped_column(
        Numeric(8, 2), nullable=True
    )

    driver_rating_at_time: Mapped[sa.Numeric | None] = mapped_column(
        Numeric(3, 2), nullable=True
    )

    was_scheduled_ride: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )

    scheduled_pickup_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    actual_pickup_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    arrival_delta_minutes: Mapped[sa.Numeric | None] = mapped_column(
        Numeric(8, 2), nullable=True
    )

    wait_time_met: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    driver_rating_met: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    on_time_met: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    overall_sla_met: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )

    evaluated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # ---- Relationships ----

    account = relationship(
        "BusinessAccount", foreign_keys=[account_id], lazy="raise"
    )
    policy = relationship(
        "CorporateSLAPolicy",
        foreign_keys=[policy_id],
        back_populates="ride_records",
        lazy="raise",
    )
