"""Corporate Employee Invitation model.

Admins issue invitation tokens to prospective employees by email.  The
recipient clicks a link (or submits the token) to accept the invitation and
become a member of the corporate account — no admin action required at
accept-time.

Two separate UUID columns are used so the public-facing token is never the
same as the row PK:

  id     — internal UUID primary key (not exposed in public endpoints)
  token  — shareable UUID delivered to the invitee (unique globally)

InvitationRole mirrors MemberRole but is self-contained to avoid cross-model
imports inside the models package.

CorporateEmployeeInvitation — table corporate_employee_invitations
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


class InvitationStatus(str, enum.Enum):
    """Lifecycle states for an employee invitation."""

    PENDING = "pending"
    ACCEPTED = "accepted"
    REVOKED = "revoked"
    EXPIRED = "expired"    # checked at validation time; never written by the service


class InvitationRole(str, enum.Enum):
    """Role the invitee will receive on acceptance."""

    ADMIN = "admin"
    MEMBER = "member"


class CorporateEmployeeInvitation(Base):
    """An email-based invitation for an employee to join a corporate account.

    Attributes:
        id: Internal UUID primary key.
        account_id: FK to corporate_accounts_v2.id (CASCADE delete).
        token: Shareable UUID delivered to the invitee.  Unique globally.
        email: Email address the invitation is addressed to.
        invited_by_id: FK to users.id — admin who sent the invitation.
        role: Role the invitee will receive on acceptance (admin/member).
        message: Optional personal note included in the invitation.
        expires_at: UTC datetime after which the invitation may no longer be
            accepted.  Defaults to 7 days from creation time.
        status: Current lifecycle state.
        accepted_at: Timestamp when the invitation was accepted.
        accepted_by_id: FK to users.id — user who accepted the invitation.
        revoked_at: Timestamp when the invitation was revoked.
        revoked_by_id: FK to users.id — admin who revoked the invitation.
        created_at: Row creation timestamp.
    """

    __tablename__ = "corporate_employee_invitations"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    account_id: Mapped[int] = mapped_column(
        ForeignKey("corporate_accounts_v2.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    token: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        unique=True,
        default=uuid.uuid4,
    )

    email: Mapped[str] = mapped_column(String(254), nullable=False, index=True)

    invited_by_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"),
        nullable=False,
        index=True,
    )

    role: Mapped[InvitationRole] = mapped_column(
        SAEnum(InvitationRole),
        nullable=False,
        default=InvitationRole.MEMBER,
    )

    message: Mapped[str | None] = mapped_column(Text, nullable=True)

    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    status: Mapped[InvitationStatus] = mapped_column(
        SAEnum(InvitationStatus),
        nullable=False,
        default=InvitationStatus.PENDING,
    )

    accepted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    accepted_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )

    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    revoked_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    account = relationship("BusinessAccount", foreign_keys=[account_id])
    invited_by = relationship("User", foreign_keys=[invited_by_id])
    accepted_by = relationship("User", foreign_keys=[accepted_by_id])
    revoked_by = relationship("User", foreign_keys=[revoked_by_id])
