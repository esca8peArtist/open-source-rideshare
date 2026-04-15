"""Corporate Trip Purpose Code model.

Corporate account admins define a list of valid purpose codes (e.g.
"CLIENT_MEETING", "CONFERENCE") that employees must use when tagging rides.
Analytics can then break down corporate spend by purpose code.

CorporateTripPurpose — table corporate_trip_purposes
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


class CorporateTripPurpose(Base):
    """Admin-defined purpose codes for tagging corporate rides.

    Attributes:
        id: Primary key.
        account_id: FK to corporate_accounts_v2.id (CASCADE delete).
        code: Short machine-readable identifier, e.g. "CLIENT_MEETING".
            Always stored in uppercase.  Must be unique within the account.
        label: Human-readable display label, e.g. "Client Meeting".
        is_active: Inactive purposes can no longer be assigned to new rides.
        requires_notes: When True, the employee must supply non-empty notes
            when tagging a ride with this purpose.
        created_at: Row creation timestamp.
        updated_at: Row last-modification timestamp.
    """

    __tablename__ = "corporate_trip_purposes"
    __table_args__ = (
        UniqueConstraint(
            "account_id", "code", name="uq_corp_trip_purpose_account_code"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    account_id: Mapped[int] = mapped_column(
        ForeignKey("corporate_accounts_v2.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    code: Mapped[str] = mapped_column(String(50), nullable=False)
    label: Mapped[str] = mapped_column(String(100), nullable=False)

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    requires_notes: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    account = relationship("BusinessAccount", foreign_keys=[account_id])
