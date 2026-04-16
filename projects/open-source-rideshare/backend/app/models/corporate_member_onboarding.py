"""Corporate Member Onboarding model.

Tracks the structured onboarding checklist for employees joining a corporate
account.  Ten setup steps are tracked in the ``steps_completed`` JSONB column.
Seven steps are auto-detectable from existing data (membership, transport
preferences, department, office, group, policy acknowledgement, manager, cost
centre, first ride); the final step requires manual admin confirmation.

Model:
  CorporateMemberOnboarding — one record per onboarding instance

Table:
  corporate_member_onboardings
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy import (
    Boolean,
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


class OnboardingStatus(str, enum.Enum):
    """Lifecycle states for a corporate member onboarding record."""

    pending = "pending"
    in_progress = "in_progress"
    completed = "completed"


# ---------------------------------------------------------------------------
# Canonical list of onboarding steps (in logical setup order)
# ---------------------------------------------------------------------------

ONBOARDING_STEPS: list[str] = [
    "membership_activated",
    "transport_preferences_set",
    "department_assigned",
    "office_assigned",
    "group_assigned",
    "policy_acknowledged",
    "manager_assigned",
    "cost_center_configured",
    "first_corporate_ride",
    "onboarding_complete_confirmed",
]

# Steps that can be auto-detected from existing data
AUTO_DETECTABLE_STEPS: set[str] = {
    "membership_activated",
    "transport_preferences_set",
    "department_assigned",
    "office_assigned",
    "group_assigned",
    "policy_acknowledged",
    "manager_assigned",
    "cost_center_configured",
    "first_corporate_ride",
}


def _empty_steps_completed() -> dict:
    """Return the initial ``steps_completed`` JSONB value with all steps incomplete."""
    return {
        step: {
            "completed": False,
            "completed_at": None,
            "completed_by_id": None,
            "notes": None,
            "auto_detected": False,
        }
        for step in ONBOARDING_STEPS
    }


class CorporateMemberOnboarding(Base):
    """Onboarding checklist for a new corporate account member.

    Attributes:
        id: UUID primary key.
        account_id: FK to corporate_accounts_v2.id (CASCADE delete).
        member_id: FK to users.id (SET NULL) — may be null if user is deleted.
        member_email: Email stored at creation for audit trail.
        member_name: Display name stored at creation for audit trail.
        invitation_id: Optional FK to corporate_employee_invitations (SET NULL).
        created_by_id: FK to users.id (SET NULL) — admin who created the tracker.
        status: Current lifecycle state (pending/in_progress/completed).
        steps_completed: JSONB tracking completion of each setup step.
        notes: Optional additional notes.
        completed_at: UTC timestamp when onboarding was marked complete.
        is_active: False once completed.
        created_at: UTC creation timestamp.
        updated_at: UTC last-modification timestamp.
    """

    __tablename__ = "corporate_member_onboardings"
    __table_args__ = (
        Index("ix_corp_onboarding_account_id", "account_id"),
        Index("ix_corp_onboarding_member_id", "member_id"),
        Index("ix_corp_onboarding_member_email", "member_email"),
        Index("ix_corp_onboarding_status", "status"),
        Index("ix_corp_onboarding_created_at", "created_at"),
        Index("ix_corp_onboarding_account_status", "account_id", "status"),
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

    invitation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("corporate_employee_invitations.id", ondelete="SET NULL"),
        nullable=True,
    )

    created_by_id: Mapped[int | None] = mapped_column(
        sa.Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    status: Mapped[OnboardingStatus] = mapped_column(
        sa.Enum(OnboardingStatus, name="onboardingstatus"),
        nullable=False,
        default=OnboardingStatus.pending,
    )

    steps_completed: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        default=_empty_steps_completed,
    )

    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
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
    created_by = relationship("User", foreign_keys=[created_by_id], lazy="raise")
    invitation = relationship(
        "CorporateEmployeeInvitation", foreign_keys=[invitation_id], lazy="raise"
    )
