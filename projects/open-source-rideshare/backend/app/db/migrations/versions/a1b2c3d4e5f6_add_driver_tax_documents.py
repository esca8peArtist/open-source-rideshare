"""add driver tax documents

Revision ID: a1b2c3d4e5f6
Revises: v1w2x3y4z5a6
Create Date: 2026-04-15

Creates two tables:
  driver_tax_profiles   — W-9 / taxpayer identification per driver (TIN last-4 only)
  driver_tax_documents  — annual 1099-NEC and earnings summary records
"""

from alembic import op
import sqlalchemy as sa

revision = "a1b2c3d4e5f6"
down_revision = "v1w2x3y4z5a6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "driver_tax_profiles",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "driver_profile_id",
            sa.Integer,
            sa.ForeignKey("driver_profiles.id"),
            unique=True,
            nullable=False,
        ),
        sa.Column(
            "tin_type",
            sa.Enum("ssn", "ein", name="tintype"),
            nullable=True,
        ),
        # Store ONLY the last 4 digits of the TIN — never the full number.
        sa.Column("tin_last4", sa.String(4), nullable=True),
        sa.Column("business_name", sa.String(255), nullable=True),
        sa.Column("has_w9", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("w9_received_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "is_backup_withholding_exempt",
            sa.Boolean,
            nullable=False,
            server_default="true",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_driver_tax_profiles_driver_profile_id",
        "driver_tax_profiles",
        ["driver_profile_id"],
    )

    op.create_table(
        "driver_tax_documents",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "driver_profile_id",
            sa.Integer,
            sa.ForeignKey("driver_profiles.id"),
            nullable=False,
        ),
        sa.Column("tax_year", sa.Integer, nullable=False),
        sa.Column(
            "document_type",
            sa.Enum("1099_nec", "earnings_summary", name="taxdocumenttype"),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum(
                "pending",
                "ready",
                "submitted_to_irs",
                "corrected",
                name="taxdocumentstatus",
            ),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("gross_earnings_cents", sa.Integer, nullable=False, server_default="0"),
        sa.Column(
            "nonemployee_compensation_cents",
            sa.Integer,
            nullable=False,
            server_default="0",
        ),
        sa.Column("rides_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("admin_notes", sa.String(1000), nullable=True),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "driver_profile_id",
            "tax_year",
            "document_type",
            name="uq_driver_tax_document_driver_year_type",
        ),
    )
    op.create_index(
        "ix_driver_tax_documents_driver_profile_id",
        "driver_tax_documents",
        ["driver_profile_id"],
    )
    op.create_index(
        "ix_driver_tax_documents_tax_year",
        "driver_tax_documents",
        ["tax_year"],
    )


def downgrade() -> None:
    op.drop_index("ix_driver_tax_documents_tax_year", table_name="driver_tax_documents")
    op.drop_index(
        "ix_driver_tax_documents_driver_profile_id", table_name="driver_tax_documents"
    )
    op.drop_table("driver_tax_documents")
    op.drop_index(
        "ix_driver_tax_profiles_driver_profile_id", table_name="driver_tax_profiles"
    )
    op.drop_table("driver_tax_profiles")
    op.execute("DROP TYPE IF EXISTS taxdocumentstatus")
    op.execute("DROP TYPE IF EXISTS taxdocumenttype")
    op.execute("DROP TYPE IF EXISTS tintype")
