import enum
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


class AuditCategory(str, enum.Enum):
    RIDE = "ride"
    DRIVER = "driver"
    PAYMENT = "payment"
    SAFETY = "safety"
    DISPUTE = "dispute"
    VERIFICATION = "verification"
    ACCOUNT = "account"
    ADMIN = "admin"
    PAYOUT = "payout"


class AuditSeverity(str, enum.Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class AuditLog(Base):
    """Immutable audit trail for regulatory compliance and TNC audits.

    Every significant platform event is logged here — ride state changes,
    driver approvals, payment transfers, dispute resolutions, SOS incidents,
    and admin actions.  Entries are append-only; no update or delete.
    """

    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True,
    )
    category: Mapped[AuditCategory] = mapped_column(
        Enum(AuditCategory), index=True,
    )
    severity: Mapped[AuditSeverity] = mapped_column(
        Enum(AuditSeverity), default=AuditSeverity.INFO,
    )
    event_type: Mapped[str] = mapped_column(String(100), index=True)
    description: Mapped[str] = mapped_column(Text)

    # Who performed the action (null for system-triggered events)
    actor_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True, index=True,
    )
    actor_role: Mapped[str | None] = mapped_column(String(20), nullable=True)

    # What entity was affected
    target_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    target_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)

    # Optional linked entities for cross-referencing
    ride_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True, index=True,
    )

    # Structured metadata (JSON-serialised string for portability)
    metadata_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    # IP / request context (for admin actions)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)

    actor = relationship("User", foreign_keys=[actor_id], backref="audit_actions")
    target_user = relationship("User", foreign_keys=[user_id])
