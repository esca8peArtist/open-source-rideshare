"""Corporate API Key model.

Enterprise admins generate named API keys with configurable permission scopes.
External systems (HRIS, ERP, analytics tools) use these keys to pull data from
the corporate account via the REST API.  Only the SHA-256 hash of the key is
stored — the plaintext is shown once at creation or rotation time.

Models
------
CorporateApiKey — a named programmatic access credential.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


class CorporateApiKey(Base):
    """A named API key granting programmatic read access to a corporate account.

    The raw key (format: ``rsk_<64 hex chars>``) is returned only when the key
    is created or rotated.  Only ``key_hash`` (SHA-256 hex) is persisted.
    ``key_prefix`` (the first 8 characters of the raw key) is stored so admins
    can identify which key is which in the listing without exposing the secret.

    Attributes:
        id: UUID primary key.
        account_id: FK to corporate_accounts_v2 (CASCADE delete).
        name: Human-readable label for this key (e.g. "HRIS integration").
        key_prefix: First 8 characters of the raw key — shown in list responses.
        key_hash: SHA-256 hex digest of the full raw key — used for verification.
        scopes: JSONB list of permission scope strings.
        is_active: When False the key is revoked and will not verify.
        expires_at: Optional expiry datetime; expired keys fail verification.
        last_used_at: Updated when the key successfully authenticates a request.
        created_by_id: FK to users — the admin who created the key.
        created_at: Creation timestamp.
        updated_at: Last modification timestamp.
    """

    __tablename__ = "corporate_api_keys"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    account_id: Mapped[int] = mapped_column(
        ForeignKey("corporate_accounts_v2.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    name: Mapped[str] = mapped_column(Text, nullable=False)

    # First 8 chars of the raw key — safe to display in listings
    key_prefix: Mapped[str] = mapped_column(Text, nullable=False)

    # SHA-256 hex of the raw key — never expose this
    key_hash: Mapped[str] = mapped_column(Text, nullable=False, unique=True)

    # e.g. ["rides:read", "invoices:read"]
    scopes: Mapped[list] = mapped_column(JSONB, nullable=False)

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    last_used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    created_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
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

    account = relationship("BusinessAccount", foreign_keys=[account_id])
    created_by = relationship("User", foreign_keys=[created_by_id])
