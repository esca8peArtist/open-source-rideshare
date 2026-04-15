"""Corporate SSO Configuration model.

Enterprise accounts can configure their identity provider (IdP) so employees
log in via SSO instead of username/password.  A single SSO config row is
allowed per corporate account.  Admins configure credentials, test the
connection, activate it, and optionally enforce SSO for all members.

Tables:
  corporate_sso_configs — one row per corporate account (UNIQUE on account_id).
"""

from __future__ import annotations

import enum
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
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


class SSOProvider(str, enum.Enum):
    """Identity provider type for SSO configuration."""

    saml = "saml"
    oidc = "oidc"
    google = "google"
    microsoft = "microsoft"
    okta = "okta"


class SSOStatus(str, enum.Enum):
    """Lifecycle status of an SSO configuration."""

    pending = "pending"      # Configured but not yet verified.
    active = "active"        # Verified and usable for authentication.
    disabled = "disabled"    # Explicitly disabled; SSO will not be attempted.


class CorporateSSOConfig(Base):
    """SSO configuration for a corporate account.

    One row per corporate account (enforced by UNIQUE constraint on
    ``account_id``).  Admins supply IdP credentials here; the platform
    uses them to redirect authentication to the company's identity provider.

    Attributes:
        account_id: FK to corporate_accounts_v2 (CASCADE delete).  UNIQUE —
            only one config per account.
        provider: Which IdP type is being configured.
        status: Lifecycle state; starts as ``pending`` after creation.
        enforce_sso: When True all members must authenticate via SSO; password
            login is blocked.  Can only be enabled when ``status == active``.
        saml_metadata_url: URL to the IdP SAML metadata XML.
        saml_entity_id: EntityID of the service provider registered with the IdP.
        saml_sso_url: IdP Single Sign-On URL.
        saml_slo_url: IdP Single Log-Out URL.
        saml_certificate: PEM-encoded X.509 certificate from the IdP.
        oidc_discovery_url: OIDC discovery document URL
            (``/.well-known/openid-configuration``).
        oidc_client_id: Client ID issued by the IdP.
        oidc_client_secret_hash: Hashed client secret — never stored or
            returned in plain text.
        oidc_scopes: Space-separated OIDC scope string; defaults to
            ``"openid email profile"``.
        attribute_mapping: JSONB — maps IdP attribute names to local field
            names, e.g. ``{"email": "mail", "name": "displayName"}``.
        allowed_domains: JSONB — list of email domain strings permitted to
            authenticate via this SSO config.
        last_tested_at: Timestamp of the last successful connection test.
        last_tested_by_id: FK to users — who ran the last test.
        created_at: Creation timestamp (UTC).
        updated_at: Last modification timestamp (UTC).
        created_by_id: FK to users — the admin who created the config.
    """

    __tablename__ = "corporate_sso_configs"
    __table_args__ = (
        UniqueConstraint("account_id", name="uq_corp_sso_account_id"),
        Index("ix_corp_sso_account_id", "account_id"),
        Index("ix_corp_sso_status", "status"),
        Index("ix_corp_sso_provider", "provider"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    account_id: Mapped[int] = mapped_column(
        ForeignKey("corporate_accounts_v2.id", ondelete="CASCADE"),
        nullable=False,
    )

    provider: Mapped[SSOProvider] = mapped_column(
        Enum(SSOProvider, name="ssoprovider"),
        nullable=False,
    )

    status: Mapped[SSOStatus] = mapped_column(
        Enum(SSOStatus, name="ssostatus"),
        nullable=False,
        default=SSOStatus.pending,
    )

    enforce_sso: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )

    # SAML fields
    saml_metadata_url: Mapped[str | None] = mapped_column(
        String(500), nullable=True
    )
    saml_entity_id: Mapped[str | None] = mapped_column(
        String(500), nullable=True
    )
    saml_sso_url: Mapped[str | None] = mapped_column(
        String(500), nullable=True
    )
    saml_slo_url: Mapped[str | None] = mapped_column(
        String(500), nullable=True
    )
    saml_certificate: Mapped[str | None] = mapped_column(Text, nullable=True)

    # OIDC fields
    oidc_discovery_url: Mapped[str | None] = mapped_column(
        String(500), nullable=True
    )
    oidc_client_id: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )
    oidc_client_secret_hash: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )
    oidc_scopes: Mapped[str | None] = mapped_column(
        String(500), nullable=True, default="openid email profile"
    )

    # Attribute / domain config
    attribute_mapping: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True
    )
    allowed_domains: Mapped[list[str] | None] = mapped_column(
        JSONB, nullable=True
    )

    # Test tracking
    last_tested_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_tested_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    created_by_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), nullable=False
    )

    account = relationship("BusinessAccount", foreign_keys=[account_id])
    created_by = relationship("User", foreign_keys=[created_by_id])
    last_tested_by = relationship("User", foreign_keys=[last_tested_by_id])
