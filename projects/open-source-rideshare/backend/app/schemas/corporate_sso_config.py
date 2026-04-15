"""Pydantic schemas for corporate SSO configuration.

Note: ``oidc_client_secret_hash`` is intentionally excluded from all response
schemas.  The hashed secret is write-only; it must never be returned to
callers.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field

from app.models.corporate_sso_config import SSOProvider, SSOStatus


class CorporateSSOConfigCreate(BaseModel):
    """Request body for creating an SSO configuration."""

    provider: SSOProvider

    # SAML fields — optional, provider-dependent
    saml_metadata_url: Optional[str] = Field(None, max_length=500)
    saml_entity_id: Optional[str] = Field(None, max_length=500)
    saml_sso_url: Optional[str] = Field(None, max_length=500)
    saml_slo_url: Optional[str] = Field(None, max_length=500)
    saml_certificate: Optional[str] = None

    # OIDC fields — optional, provider-dependent
    oidc_discovery_url: Optional[str] = Field(None, max_length=500)
    oidc_client_id: Optional[str] = Field(None, max_length=255)
    oidc_client_secret_hash: Optional[str] = Field(
        None,
        max_length=255,
        description="Store the hashed client secret, never the raw value.",
    )
    oidc_scopes: Optional[str] = Field(
        "openid email profile", max_length=500
    )

    attribute_mapping: Optional[dict[str, Any]] = None
    allowed_domains: Optional[list[str]] = None


class CorporateSSOConfigUpdate(BaseModel):
    """Request body for updating an SSO configuration.

    All fields are optional — only supplied fields are applied.
    """

    saml_metadata_url: Optional[str] = Field(None, max_length=500)
    saml_entity_id: Optional[str] = Field(None, max_length=500)
    saml_sso_url: Optional[str] = Field(None, max_length=500)
    saml_slo_url: Optional[str] = Field(None, max_length=500)
    saml_certificate: Optional[str] = None
    oidc_discovery_url: Optional[str] = Field(None, max_length=500)
    oidc_client_id: Optional[str] = Field(None, max_length=255)
    oidc_client_secret_hash: Optional[str] = Field(None, max_length=255)
    oidc_scopes: Optional[str] = Field(None, max_length=500)
    attribute_mapping: Optional[dict[str, Any]] = None
    allowed_domains: Optional[list[str]] = None


class CorporateSSOConfigResponse(BaseModel):
    """SSO configuration returned to callers.

    ``oidc_client_secret_hash`` is never included — secrets are write-only.
    """

    id: int
    account_id: int
    provider: SSOProvider
    status: SSOStatus
    enforce_sso: bool

    saml_metadata_url: Optional[str]
    saml_entity_id: Optional[str]
    saml_sso_url: Optional[str]
    saml_slo_url: Optional[str]
    saml_certificate: Optional[str]

    oidc_discovery_url: Optional[str]
    oidc_client_id: Optional[str]
    # oidc_client_secret_hash intentionally omitted
    oidc_scopes: Optional[str]

    attribute_mapping: Optional[dict[str, Any]]
    allowed_domains: Optional[list[str]]

    last_tested_at: Optional[datetime]
    last_tested_by_id: Optional[int]

    created_at: datetime
    updated_at: datetime
    created_by_id: int

    model_config = {"from_attributes": True}


class SSOEnforcementUpdate(BaseModel):
    """Request body for toggling SSO enforcement."""

    enforce: bool = Field(..., description="True to require SSO for all members.")
