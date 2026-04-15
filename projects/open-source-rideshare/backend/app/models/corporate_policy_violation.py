"""Corporate Policy Violation model.

When an employee's ride booking violates their corporate account's ride policy,
a violation record is written here.  Violations are append-only (immutable once
created) and can be acknowledged by account admins once reviewed.

Violation types map to the checks in CorporateRidePolicy.check_ride_allowed:
  vehicle_type          — attempted vehicle category not in allowed list
  per_ride_cost_exceeded — estimated fare exceeds max_per_ride_usd
  business_hours        — booking attempted outside permitted hours
  missing_purpose       — require_purpose=True but no purpose provided
  unapproved_purpose    — purpose not in approved_purposes list
  spend_limit_exceeded  — employee's monthly spend cap reached
  ride_quota_exceeded   — employee's per-period ride quota reached
  blackout_period       — booking attempted during a configured blackout

Tables:
  corporate_policy_violations — one row per violation event; immutable.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


class CorporatePolicyViolation(Base):
    """An immutable record of a single ride-policy violation.

    Attributes:
        account_id:          FK to corporate_accounts_v2 (CASCADE delete).
        member_id:           FK to users — the employee whose booking violated
                             policy (CASCADE delete).
        ride_id:             FK to rides (SET NULL, nullable) — the ride that
                             triggered the check; NULL for pre-booking denials
                             where no ride row was created.
        violation_type:      Category of violation (see enum list above).
        violation_details:   JSONB context blob — e.g. attempted vehicle type,
                             policy limits, actual values at time of check.
        policy_snapshot:     JSONB copy of the policy that was in effect when
                             the violation was recorded; preserves the audit
                             trail even if the policy is later changed.
        is_acknowledged:     False until an admin reviews and marks acknowledged.
        acknowledged_by_id:  FK to users (SET NULL) — admin who acknowledged.
        acknowledged_at:     Timestamp of acknowledgement.
        acknowledgement_note: Optional note left by the acknowledging admin.
        created_at:          Immutable creation timestamp; no updated_at because
                             the violation body is never mutated.
    """

    __tablename__ = "corporate_policy_violations"
    __table_args__ = (
        Index("ix_corp_policy_violation_account_id", "account_id"),
        Index("ix_corp_policy_violation_member_id", "member_id"),
        Index(
            "ix_corp_policy_violation_account_created",
            "account_id",
            "created_at",
        ),
        Index(
            "ix_corp_policy_violation_unacked",
            "account_id",
            "is_acknowledged",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    account_id: Mapped[int] = mapped_column(
        ForeignKey("corporate_accounts_v2.id", ondelete="CASCADE"),
        nullable=False,
    )
    member_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    ride_id: Mapped[int | None] = mapped_column(
        ForeignKey("rides.id", ondelete="SET NULL"),
        nullable=True,
    )

    violation_type: Mapped[str] = mapped_column(String(50), nullable=False)
    violation_details: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    policy_snapshot: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    is_acknowledged: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    acknowledged_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    acknowledged_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    acknowledgement_note: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    # Relationships
    account = relationship("BusinessAccount", foreign_keys=[account_id])
    member = relationship("User", foreign_keys=[member_id])
    acknowledged_by = relationship("User", foreign_keys=[acknowledged_by_id])
