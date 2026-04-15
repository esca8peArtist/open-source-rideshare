"""Corporate Admin Audit Log model.

Enterprise accounts need an immutable record of all significant admin actions
for compliance (SOX, SOC2, internal audit).  Every create/update/delete/approve
action taken by an admin within a corporate account is appended here.

CorporateAdminAuditLog — one row per auditable event; never updated or deleted.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


class CorporateAdminAuditLog(Base):
    """An immutable record of an admin action within a corporate account.

    Audit log entries are append-only — they are never modified or soft-deleted.
    The combination of ``action``, ``resource_type``, and ``resource_id`` fully
    describes what changed; the optional ``details`` JSONB carries before/after
    snapshots or any additional context the service layer chooses to record.

    Attributes:
        id: Auto-incrementing primary key.
        account_id: FK to corporate_accounts_v2 (CASCADE delete).
        actor_id: FK to users — the admin who performed the action.  Nullable
            to allow system-initiated entries (e.g. automated invoice generation).
        action: Short dot-namespaced string identifying the operation, e.g.
            ``"billing_contact.create"`` or ``"expense_report.approve"``.
        resource_type: The resource category, e.g. ``"billing_contact"`` or
            ``"department"``.  Matches the action prefix by convention.
        resource_id: Flexible string identifier for the affected resource (int
            PKs are stored as strings; UUIDs stored verbatim).
        details: Optional JSONB payload — before/after values, admin notes, etc.
        created_at: Timestamp of the event.  The only timestamp; no updated_at.
    """

    __tablename__ = "corporate_admin_audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    account_id: Mapped[int] = mapped_column(
        ForeignKey("corporate_accounts_v2.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    actor_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    action: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    resource_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    resource_id: Mapped[str] = mapped_column(String(200), nullable=False)

    details: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        index=True,
    )

    account = relationship("BusinessAccount", foreign_keys=[account_id])
    actor = relationship("User", foreign_keys=[actor_id])
