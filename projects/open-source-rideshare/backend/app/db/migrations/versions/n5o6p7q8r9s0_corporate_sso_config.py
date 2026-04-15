"""Corporate SSO configuration.

Enterprise accounts can configure their identity provider (IdP) so employees
log in via SSO instead of username/password.

Tables created:
  corporate_sso_configs — one row per corporate account (UNIQUE on account_id).

Enums created:
  ssoprovider — saml / oidc / google / microsoft / okta
  ssostatus   — pending / active / disabled

Revision ID: n5o6p7q8r9s0
Revises:     m4n5o6p7q8r9
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "n5o6p7q8r9s0"
down_revision: str = "m4n5o6p7q8r9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Enums
    ssoprovider = postgresql.ENUM(
        "saml",
        "oidc",
        "google",
        "microsoft",
        "okta",
        name="ssoprovider",
    )
    ssoprovider.create(op.get_bind(), checkfirst=True)

    ssostatus = postgresql.ENUM(
        "pending",
        "active",
        "disabled",
        name="ssostatus",
    )
    ssostatus.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "corporate_sso_configs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column(
            "provider",
            sa.Enum(
                "saml",
                "oidc",
                "google",
                "microsoft",
                "okta",
                name="ssoprovider",
            ),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum(
                "pending",
                "active",
                "disabled",
                name="ssostatus",
            ),
            nullable=False,
            server_default="pending",
        ),
        sa.Column(
            "enforce_sso",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        # SAML fields
        sa.Column("saml_metadata_url", sa.String(500), nullable=True),
        sa.Column("saml_entity_id", sa.String(500), nullable=True),
        sa.Column("saml_sso_url", sa.String(500), nullable=True),
        sa.Column("saml_slo_url", sa.String(500), nullable=True),
        sa.Column("saml_certificate", sa.Text(), nullable=True),
        # OIDC fields
        sa.Column("oidc_discovery_url", sa.String(500), nullable=True),
        sa.Column("oidc_client_id", sa.String(255), nullable=True),
        sa.Column("oidc_client_secret_hash", sa.String(255), nullable=True),
        sa.Column(
            "oidc_scopes",
            sa.String(500),
            nullable=True,
            server_default="openid email profile",
        ),
        # Attribute / domain config
        sa.Column(
            "attribute_mapping",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "allowed_domains",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        # Test tracking
        sa.Column(
            "last_tested_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column("last_tested_by_id", sa.Integer(), nullable=True),
        # Timestamps
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("created_by_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["corporate_accounts_v2.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["users.id"],
        ),
        sa.ForeignKeyConstraint(
            ["last_tested_by_id"],
            ["users.id"],
        ),
        sa.UniqueConstraint("account_id", name="uq_corp_sso_account_id"),
    )

    op.create_index(
        "ix_corp_sso_account_id",
        "corporate_sso_configs",
        ["account_id"],
    )
    op.create_index(
        "ix_corp_sso_status",
        "corporate_sso_configs",
        ["status"],
    )
    op.create_index(
        "ix_corp_sso_provider",
        "corporate_sso_configs",
        ["provider"],
    )


def downgrade() -> None:
    op.drop_index("ix_corp_sso_provider", table_name="corporate_sso_configs")
    op.drop_index("ix_corp_sso_status", table_name="corporate_sso_configs")
    op.drop_index("ix_corp_sso_account_id", table_name="corporate_sso_configs")
    op.drop_table("corporate_sso_configs")
    sa.Enum(name="ssostatus").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="ssoprovider").drop(op.get_bind(), checkfirst=True)
