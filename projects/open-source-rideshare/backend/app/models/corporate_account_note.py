"""Corporate Account Note model.

Platform admins annotate corporate accounts with CRM-style freeform notes —
support call summaries, sales context, billing exceptions, compliance findings.
Notes carry a type label, a pin flag (pinned notes surface first), and an
internal flag that controls whether account members can see the note.

Tables:
  corporate_account_notes — one row per note; pinned notes sort first,
                            then newest-first within unpinned.
"""

from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


class NoteType(str, enum.Enum):
    """Categorises the subject matter of a corporate account note.

    Values:
        general    — misc / uncategorised notes
        billing    — payment issues, invoice questions, credit adjustments
        support    — help-desk interactions, bug reports, escalations
        compliance — regulatory findings, policy violations, audit items
        sales      — deal context, renewal conversations, upsell notes
        technical  — integration issues, API/SSO/webhook configuration
    """

    general = "general"
    billing = "billing"
    support = "support"
    compliance = "compliance"
    sales = "sales"
    technical = "technical"


class CorporateAccountNote(Base):
    """A freeform annotation left by a platform admin on a corporate account.

    Attributes:
        account_id:   FK to corporate_accounts_v2 (CASCADE delete).
        author_id:    FK to users (SET NULL when author is deleted).
        note_type:    Category label (see NoteType enum).
        content:      Freeform text body of the note (min 10 chars).
        is_pinned:    When True, the note is surfaced before unpinned notes.
        is_internal:  When True, only platform admins can see the note.
                      When False, account admins/members can also view it.
        created_at:   Immutable creation timestamp.
        updated_at:   Last-edit timestamp; updated automatically.
    """

    __tablename__ = "corporate_account_notes"
    __table_args__ = (
        Index("ix_corp_note_account_id", "account_id"),
        Index("ix_corp_note_author_id", "author_id"),
        Index("ix_corp_note_account_pinned", "account_id", "is_pinned"),
        Index("ix_corp_note_created_at", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    account_id: Mapped[int] = mapped_column(
        ForeignKey("corporate_accounts_v2.id", ondelete="CASCADE"),
        nullable=False,
    )
    author_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    note_type: Mapped[NoteType] = mapped_column(
        Enum(NoteType, name="notetype"),
        nullable=False,
        default=NoteType.general,
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)

    is_pinned: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_internal: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    # Relationships
    account = relationship("BusinessAccount", foreign_keys=[account_id])
    author = relationship("User", foreign_keys=[author_id])
