"""Corporate Member Offboarding model.

Tracks the structured offboarding workflow for employees leaving a corporate
account.  The workflow covers ten cleanup steps (membership deactivation,
pending approval closure, invitation revocation, recurring ride deactivation,
carpool group removal, shift assignment removal, delegation revocation, expense
report withdrawal, approval chain flagging, and data export generation).

Progress for each step is stored in the ``steps_completed`` JSONB column as a
dict keyed by step name.

Model:
  CorporateMemberOffboarding — one record per offboarding instance

Table:
  corporate_member_offboardings
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


class OffboardingStatus(str, enum.Enum):
    """Lifecycle states for a corporate member offboarding record."""

    pending = "pending"
    in_progress = "in_progress"
    completed = "completed"
    cancelled = "cancelled"


# ---------------------------------------------------------------------------
# Canonical list of offboarding steps (in logical execution order)
# ---------------------------------------------------------------------------

OFFBOARDING_STEPS: list[str] = [
    "deactivate_membership",
    "close_pending_approvals",
    "cancel_pending_invitations",
    "deactivate_recurring_rides",
    "remove_from_carpool_groups",
    "remove_from_shifts",
    "revoke_delegations",
    "remove_expense_reports",
    "transfer_approval_chain_steps",
    "data_export_generated",
]


def _empty_steps_completed() -> dict:
    """Return the initial ``steps_completed`` JSONB value with all steps incomplete."""
    return {
        step: {
            "completed": False,
            "completed_at": None,
            "completed_by_id": None,
            "notes": None,
            "count": 0,
        }
        for step in OFFBOARDING_STEPS
    }


class CorporateMemberOffboarding(Base):
    """Offboarding workflow record for a corporate account member.

    Attributes:
        id: UUID primary key.
        account_id: FK to corporate_accounts_v2.id (CASCADE delete).
        member_id: FK to users.id (SET NULL) — may be null if user is deleted.
        member_email: Email stored at creation for audit trail.
        member_name: Display name stored at creation for audit trail.
        initiated_by_id: FK to users.id (SET NULL) — admin who started offboarding.
        status: Current lifecycle state (pending/in_progress/completed/cancelled).
        reason: Why the employee is leaving (optional free text).
        last_day: Employee's last working day (optional).
        steps_completed: JSONB tracking completion of each cleanup step.
        notes: Optional additional notes.
        completed_at: UTC timestamp when offboarding was marked complete.
        cancelled_at: UTC timestamp when offboarding was cancelled.
        cancelled_by_id: FK to users.id (SET NULL) — who cancelled.
        is_active: False once completed or cancelled.
        created_at: UTC creation timestamp.
        updated_at: UTC last-modification timestamp.
    """

    __tablename__ = "corporate_member_offboardings"
    __table_args__ = (
        Index("ix_corp_offboarding_account_id", "account_id"),
        Index("ix_corp_offboarding_member_id", "member_id"),
        Index("ix_corp_offboarding_member_email", "member_email"),
        Index("ix_corp_offboarding_status", "status"),
        Index("ix_corp_offboarding_created_at", "created_at"),
        Index("ix_corp_offboarding_account_status", "account_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    account_id: Mapped[int] = mapped_column(
        sa.Integer,
        ForeignKey("corporate_accounts_v2.id", ondelete="CASCADE"),
        nullable=False,
    )

    member_id: Mapped[int | None] = mapped_column(
        sa.Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    member_email: Mapped[str] = mapped_column(String(255), nullable=False)

    member_name: Mapped[str] = mapped_column(String(255), nullable=False)

    initiated_by_id: Mapped[int | None] = mapped_column(
        sa.Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    status: Mapped[OffboardingStatus] = mapped_column(
        sa.Enum(OffboardingStatus, name="offboardingstatus"),
        nullable=False,
        default=OffboardingStatus.pending,
    )

    reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    last_day: Mapped[datetime | None] = mapped_column(Date, nullable=True)

    steps_completed: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        default=_empty_steps_completed,
    )

    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    cancelled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    cancelled_by_id: Mapped[int | None] = mapped_column(
        sa.Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

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

    account = relationship("BusinessAccount", foreign_keys=[account_id], lazy="raise")
    member = relationship("User", foreign_keys=[member_id], lazy="raise")
    initiated_by = relationship("User", foreign_keys=[initiated_by_id], lazy="raise")
    cancelled_by = relationship("User", foreign_keys=[cancelled_by_id], lazy="raise")
