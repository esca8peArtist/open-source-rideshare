"""Corporate Member Fine-Grained Permissions model.

Enterprise accounts can grant specific named permission scopes to individual
members beyond the binary admin/member role.  This allows organisations to
have department-specific or function-specific admins without elevating a
member to full account-admin.

Examples
--------
* A finance employee is granted ``billing_admin`` — they can manage invoices
  and payment methods without seeing HR data.
* An IT lead is granted ``sso_admin`` — they can configure SSO without billing
  access.
* A travel coordinator is granted ``booking_approver`` — they can approve ride
  requests without full admin rights.

Models
------
CorporateMemberPermission  — table corporate_member_permissions
"""

from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


class PermissionScope(str, enum.Enum):
    """Named permission scopes available for corporate members.

    Each scope corresponds to a cluster of related features.  The
    platform can check ``has_permission(scope)`` at service-call time to
    gate access beyond the basic admin/member split.
    """

    BILLING_ADMIN = "billing_admin"
    """Manage invoices, billing settings, and payment methods."""

    HR_ADMIN = "hr_admin"
    """Manage employee invitations, offboarding, departments, and groups."""

    FLEET_MANAGER = "fleet_manager"
    """Manage fleet vehicles, reservations, and maintenance logs."""

    REPORT_VIEWER = "report_viewer"
    """View analytics, scheduled reports, and data exports."""

    BOOKING_APPROVER = "booking_approver"
    """Approve or reject employee ride-booking requests."""

    DATA_EXPORTER = "data_exporter"
    """Initiate and download data exports."""

    SSO_ADMIN = "sso_admin"
    """Configure and test SSO settings for the account."""


class CorporateMemberPermission(Base):
    """A fine-grained permission scope granted to a corporate member.

    One row per (account_id, member_id, permission_scope) triple.  Only
    one active grant can exist per triple — re-granting a scope that was
    previously revoked reactivates the existing row (upsert semantics).

    Attributes:
        id: Integer primary key.
        account_id: FK to corporate_accounts_v2 (CASCADE delete).
        member_id: FK to users — the employee who holds this permission.
        permission_scope: The named scope being granted.
        granted_by_id: FK to users — admin who granted the permission
            (SET NULL if the granting user is deleted).
        granted_at: UTC timestamp of the most-recent grant.
        expires_at: Optional expiry — if set, the permission is considered
            inactive after this timestamp even if is_active is True.
        is_active: Soft-delete flag — False when the permission is revoked.
        notes: Optional admin note explaining why the permission was granted.
    """

    __tablename__ = "corporate_member_permissions"
    __table_args__ = (
        UniqueConstraint(
            "account_id",
            "member_id",
            "permission_scope",
            name="uq_corp_member_permission_account_member_scope",
        ),
        Index("ix_corp_member_permission_account_id", "account_id"),
        Index("ix_corp_member_permission_member_id", "member_id"),
        Index(
            "ix_corp_member_permission_active",
            "account_id",
            "is_active",
            postgresql_where="is_active = true",
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

    permission_scope: Mapped[PermissionScope] = mapped_column(
        SAEnum(PermissionScope),
        nullable=False,
    )

    granted_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    granted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
    )

    notes: Mapped[str | None] = mapped_column(String(500), nullable=True)

    account = relationship("BusinessAccount", foreign_keys=[account_id])
    member = relationship("User", foreign_keys=[member_id])
    granted_by = relationship("User", foreign_keys=[granted_by_id])
