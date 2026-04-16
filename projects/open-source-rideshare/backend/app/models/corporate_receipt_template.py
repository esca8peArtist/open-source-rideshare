"""Corporate Receipt Template model.

Finance feature: corporate accounts define a custom receipt template applied
to all ride receipts for their employees.  Finance and admin teams can brand
receipts with company name/logo, add a custom reference prefix, include footer
notes, and toggle driver details or route map visibility.

Extra custom line items (e.g. project codes or cost centre tags) are stored as
a JSONB list so the schema stays flexible without additional migrations.

Tables:
  corporate_receipt_templates — one row per corporate account; upsert-on-read.
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
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


class CorporateReceiptTemplate(Base):
    """Custom receipt template configuration for a corporate account.

    One row per account (unique constraint on ``account_id``).  Created lazily
    via upsert-on-read — the first GET returns a default template so callers
    always receive a well-formed response.

    Attributes:
        account_id: FK to corporate_accounts_v2 (CASCADE delete).  UNIQUE —
            one template per account.
        company_name: Display name shown at the top of the receipt.  If null,
            the account's own name is used by the receipt generator.
        logo_url: URL of the company logo to embed.  Must be a URL-like string
            when provided; the service layer validates format.
        header_message: Optional introductory text printed below the company name.
        footer_message: Optional footer note, e.g. expense submission instructions.
        reference_prefix: Short string prepended to receipt reference numbers,
            e.g. "ACME" → "ACME-2026-001".  Max 20 characters.
        show_driver_details: When True, driver name and photo are included on
            the receipt.  Defaults to True.
        show_route_map: When True, a route map image is included on the receipt.
            Defaults to True.
        custom_line_items: JSONB list of ``{"label": str, "value": str}`` objects
            appended to the receipt, e.g. project codes or cost-centre tags.
        is_active: When False the template is not applied to new receipts.
        created_by_id: FK to users — admin who created the template (SET NULL
            on user deletion).
        updated_by_id: FK to users — last admin to modify the template (SET NULL
            on user deletion).
        created_at: UTC creation timestamp.
        updated_at: UTC last-modification timestamp.
    """

    __tablename__ = "corporate_receipt_templates"
    __table_args__ = (
        UniqueConstraint(
            "account_id",
            name="uq_corp_receipt_template_account_id",
        ),
        Index("ix_corp_receipt_template_account_id", "account_id"),
        Index("ix_corp_receipt_template_is_active", "account_id", "is_active"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    account_id: Mapped[int] = mapped_column(
        ForeignKey("corporate_accounts_v2.id", ondelete="CASCADE"),
        nullable=False,
    )

    company_name: Mapped[str | None] = mapped_column(String(200), nullable=True)

    logo_url: Mapped[str | None] = mapped_column(String(500), nullable=True)

    header_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    footer_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Max 20 chars — short enough to keep reference numbers readable
    reference_prefix: Mapped[str | None] = mapped_column(String(20), nullable=True)

    show_driver_details: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True
    )

    show_route_map: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True
    )

    # List of {"label": str, "value": str} objects
    custom_line_items: Mapped[list[dict[str, Any]] | None] = mapped_column(
        JSONB, nullable=True
    )

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    created_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    updated_by_id: Mapped[int | None] = mapped_column(
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

    # Relationships
    account = relationship(
        "BusinessAccount", foreign_keys=[account_id], lazy="raise"
    )
    created_by = relationship("User", foreign_keys=[created_by_id], lazy="raise")
    updated_by = relationship("User", foreign_keys=[updated_by_id], lazy="raise")
