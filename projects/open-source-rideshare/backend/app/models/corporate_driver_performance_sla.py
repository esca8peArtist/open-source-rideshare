"""Corporate Driver Performance SLA models.

Enterprise accounts track individual driver performance against KPI thresholds.
If a driver's metrics fall below the account's SLA thresholds, the account can
flag them for review or removal from their preferred driver pool.

Models:
  CorporateDriverPerformanceSLA
      — a named KPI-threshold policy belonging to a corporate account
  CorporateDriverSLARecord
      — a per-driver evaluation snapshot computed against an active policy

Tables:
  corporate_driver_performance_slas
  corporate_driver_sla_records
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


class CorporateDriverPerformanceSLA(Base):
    """A named driver-performance SLA policy belonging to a corporate account.

    Each policy defines thresholds for one or more KPI dimensions:
    on-time rate, average rating, cancellation rate, and acceptance rate.
    Only one policy may be active per account at a time; activating a new
    policy automatically deactivates any currently-active one.

    Attributes:
        id: UUID primary key.
        account_id: FK to corporate_accounts_v2 (CASCADE delete).
        name: Human-readable policy name (unique per account).
        description: Optional detailed description of the policy.
        min_on_time_rate_pct: Minimum on-time rate percentage (e.g. 85.0 = ≥85%).
        min_avg_rating: Minimum average driver rating (e.g. 4.5).
        max_cancellation_rate_pct: Maximum cancellation rate percentage (e.g. 5.0 = ≤5%).
        min_acceptance_rate_pct: Minimum acceptance rate percentage (e.g. 90.0 = ≥90%).
        evaluation_window_days: Rolling window in days for computing metrics (default 30).
        is_active: Only one active policy per account at a time.
        created_by_id: FK to users (SET NULL) — admin who created the record.
        created_at: UTC creation timestamp.
        updated_at: UTC last-modification timestamp.
    """

    __tablename__ = "corporate_driver_performance_slas"
    __table_args__ = (
        Index("ix_drv_perf_sla_account_id", "account_id"),
        Index("ix_drv_perf_sla_is_active", "is_active"),
        Index("ix_drv_perf_sla_created_at", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    account_id: Mapped[int] = mapped_column(
        ForeignKey("corporate_accounts_v2.id", ondelete="CASCADE"),
        nullable=False,
    )

    name: Mapped[str] = mapped_column(String(100), nullable=False)

    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    min_on_time_rate_pct: Mapped[float | None] = mapped_column(
        Numeric(5, 2), nullable=True
    )

    min_avg_rating: Mapped[float | None] = mapped_column(
        Numeric(3, 2), nullable=True
    )

    max_cancellation_rate_pct: Mapped[float | None] = mapped_column(
        Numeric(5, 2), nullable=True
    )

    min_acceptance_rate_pct: Mapped[float | None] = mapped_column(
        Numeric(5, 2), nullable=True
    )

    evaluation_window_days: Mapped[int] = mapped_column(
        Integer, nullable=False, default=30
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True
    )

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
    sla_records = relationship(
        "CorporateDriverSLARecord",
        back_populates="sla_policy",
        lazy="raise",
        cascade="all, delete-orphan",
    )


class CorporateDriverSLARecord(Base):
    """A per-driver SLA evaluation snapshot.

    Created once per evaluation run for a driver against an account's active
    SLA policy.  Captures metrics and pass/fail results for each KPI dimension
    so historical compliance data remains consistent even after policies are
    updated or deleted.

    ``account_id`` is denormalised for efficient platform-admin queries.

    Attributes:
        id: UUID primary key.
        account_id: Denormalised FK to corporate_accounts_v2 (CASCADE delete).
        sla_policy_id: FK to corporate_driver_performance_slas (SET NULL on delete).
        driver_profile_id: FK to driver_profiles (SET NULL on delete).
        evaluated_at: Timezone-aware timestamp when this record was computed.
        evaluation_window_days: Snapshot of the window used for evaluation.
        total_corporate_rides: Rides completed for this account within the window.
        on_time_rate_pct: Computed on-time rate, nullable.
        avg_rating: Computed average rating on corporate rides, nullable.
        cancellation_rate_pct: Computed cancellation rate, nullable.
        acceptance_rate_pct: Computed acceptance rate, nullable.
        on_time_met: Did the driver meet the on-time threshold? NULL if not set.
        rating_met: Did the driver meet the rating threshold? NULL if not set.
        cancellation_met: Did the driver meet the cancellation threshold? NULL if not set.
        acceptance_met: Did the driver meet the acceptance threshold? NULL if not set.
        overall_sla_met: True if all configured dimensions passed.
        flagged_for_review: True when an admin has flagged this record.
        flagged_by_id: FK to users (SET NULL) — admin who flagged the record.
        flagged_at: Timezone-aware timestamp when the record was flagged.
        flag_reason: Optional free-text reason for the flag.
    """

    __tablename__ = "corporate_driver_sla_records"
    __table_args__ = (
        Index("ix_drv_sla_record_account_id", "account_id"),
        Index("ix_drv_sla_record_driver_profile_id", "driver_profile_id"),
        Index("ix_drv_sla_record_evaluated_at", "evaluated_at"),
        Index("ix_drv_sla_record_overall_sla_met", "overall_sla_met"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    account_id: Mapped[int] = mapped_column(
        ForeignKey("corporate_accounts_v2.id", ondelete="CASCADE"),
        nullable=False,
    )

    sla_policy_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("corporate_driver_performance_slas.id", ondelete="SET NULL"),
        nullable=True,
    )

    driver_profile_id: Mapped[int | None] = mapped_column(
        ForeignKey("driver_profiles.id", ondelete="SET NULL"),
        nullable=True,
    )

    evaluated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    evaluation_window_days: Mapped[int] = mapped_column(
        Integer, nullable=False, default=30
    )

    total_corporate_rides: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )

    on_time_rate_pct: Mapped[float | None] = mapped_column(
        Numeric(5, 2), nullable=True
    )

    avg_rating: Mapped[float | None] = mapped_column(
        Numeric(3, 2), nullable=True
    )

    cancellation_rate_pct: Mapped[float | None] = mapped_column(
        Numeric(5, 2), nullable=True
    )

    acceptance_rate_pct: Mapped[float | None] = mapped_column(
        Numeric(5, 2), nullable=True
    )

    on_time_met: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    rating_met: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    cancellation_met: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    acceptance_met: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    overall_sla_met: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )

    flagged_for_review: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )

    flagged_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    flagged_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    flag_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    # ---- Relationships ----

    account = relationship(
        "BusinessAccount", foreign_keys=[account_id], lazy="raise"
    )
    sla_policy = relationship(
        "CorporateDriverPerformanceSLA",
        foreign_keys=[sla_policy_id],
        back_populates="sla_records",
        lazy="raise",
    )
    flagged_by = relationship(
        "User", foreign_keys=[flagged_by_id], lazy="raise"
    )
