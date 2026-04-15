"""Add GDPR/CCPA privacy compliance tables.

GDPR (EU) and CCPA (California) require platforms to:
  - Record user consent for each policy type and version
  - Allow users to request a full export of their personal data
  - Honour right-to-erasure (deletion) requests within 30 days

Tables created:
  privacy_consent_records     — per-user consent audit trail
  data_export_requests        — lifecycle tracking for data export requests
  account_deletion_requests   — lifecycle tracking for deletion requests

Enum types created:
  policytype       — PRIVACY_POLICY / TERMS_OF_SERVICE / MARKETING / DATA_SHARING
  exportstatus     — PENDING / PROCESSING / READY / DOWNLOADED / EXPIRED / FAILED
  deletionstatus   — PENDING / CONFIRMED / CANCELLED / COMPLETED

Revision ID: i2j3k4l5m6n7
Revises: h1i2j3k4l5m6
Create Date: 2026-04-15
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic
revision: str = "i2j3k4l5m6n7"
down_revision: str = "h1i2j3k4l5m6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- Enum types -----------------------------------------------------------

    policytype = sa.Enum(
        "PRIVACY_POLICY",
        "TERMS_OF_SERVICE",
        "MARKETING",
        "DATA_SHARING",
        name="policytype",
    )
    policytype.create(op.get_bind(), checkfirst=True)

    exportstatus = sa.Enum(
        "PENDING",
        "PROCESSING",
        "READY",
        "DOWNLOADED",
        "EXPIRED",
        "FAILED",
        name="exportstatus",
    )
    exportstatus.create(op.get_bind(), checkfirst=True)

    deletionstatus = sa.Enum(
        "PENDING",
        "CONFIRMED",
        "CANCELLED",
        "COMPLETED",
        name="deletionstatus",
    )
    deletionstatus.create(op.get_bind(), checkfirst=True)

    # --- privacy_consent_records ----------------------------------------------

    op.create_table(
        "privacy_consent_records",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "policy_type",
            sa.Enum(
                "PRIVACY_POLICY",
                "TERMS_OF_SERVICE",
                "MARKETING",
                "DATA_SHARING",
                name="policytype",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("policy_version", sa.String(50), nullable=False),
        sa.Column(
            "consented",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("ip_address", sa.String(45), nullable=True),
        sa.Column("user_agent", sa.String(512), nullable=True),
        sa.Column(
            "consented_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )

    op.create_unique_constraint(
        "uq_consent_user_policy_version",
        "privacy_consent_records",
        ["user_id", "policy_type", "policy_version"],
    )
    op.create_index(
        "ix_privacy_consent_records_user_id",
        "privacy_consent_records",
        ["user_id"],
    )
    op.create_index(
        "ix_privacy_consent_records_policy_type",
        "privacy_consent_records",
        ["policy_type"],
    )

    # --- data_export_requests -------------------------------------------------

    op.create_table(
        "data_export_requests",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum(
                "PENDING",
                "PROCESSING",
                "READY",
                "DOWNLOADED",
                "EXPIRED",
                "FAILED",
                name="exportstatus",
                create_type=False,
            ),
            nullable=False,
            server_default="PENDING",
        ),
        sa.Column(
            "requested_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "download_count", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column("error_message", sa.String(1000), nullable=True),
    )

    op.create_index(
        "ix_data_export_requests_user_id",
        "data_export_requests",
        ["user_id"],
    )
    op.create_index(
        "ix_data_export_requests_status",
        "data_export_requests",
        ["status"],
    )

    # --- account_deletion_requests --------------------------------------------

    op.create_table(
        "account_deletion_requests",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum(
                "PENDING",
                "CONFIRMED",
                "CANCELLED",
                "COMPLETED",
                name="deletionstatus",
                create_type=False,
            ),
            nullable=False,
            server_default="PENDING",
        ),
        sa.Column("reason", sa.String(1000), nullable=True),
        sa.Column(
            "requested_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_index(
        "ix_account_deletion_requests_user_id",
        "account_deletion_requests",
        ["user_id"],
    )
    op.create_index(
        "ix_account_deletion_requests_status",
        "account_deletion_requests",
        ["status"],
    )
    op.create_index(
        "ix_account_deletion_requests_scheduled_for",
        "account_deletion_requests",
        ["scheduled_for"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_account_deletion_requests_scheduled_for",
        table_name="account_deletion_requests",
    )
    op.drop_index(
        "ix_account_deletion_requests_status",
        table_name="account_deletion_requests",
    )
    op.drop_index(
        "ix_account_deletion_requests_user_id",
        table_name="account_deletion_requests",
    )
    op.drop_table("account_deletion_requests")

    op.drop_index("ix_data_export_requests_status", table_name="data_export_requests")
    op.drop_index("ix_data_export_requests_user_id", table_name="data_export_requests")
    op.drop_table("data_export_requests")

    op.drop_index(
        "ix_privacy_consent_records_policy_type",
        table_name="privacy_consent_records",
    )
    op.drop_index(
        "ix_privacy_consent_records_user_id",
        table_name="privacy_consent_records",
    )
    op.drop_constraint(
        "uq_consent_user_policy_version",
        "privacy_consent_records",
        type_="unique",
    )
    op.drop_table("privacy_consent_records")

    sa.Enum(name="deletionstatus").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="exportstatus").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="policytype").drop(op.get_bind(), checkfirst=True)
