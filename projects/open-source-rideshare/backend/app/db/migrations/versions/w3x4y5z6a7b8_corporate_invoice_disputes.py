"""Add corporate_invoice_disputes table.

Corporate account members can formally dispute charges on their invoices.
This migration creates the disputetype and disputestatus enums and the
disputes table that tracks the full review lifecycle.

Tables created:
  corporate_invoice_disputes — one row per dispute event; status tracks the
                               lifecycle from submitted through resolution.

Revision ID: w3x4y5z6a7b8
Revises:     v2w3x4y5z6a7
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "w3x4y5z6a7b8"
down_revision: str = "v2w3x4y5z6a7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create the DisputeType enum
    dispute_type_enum = postgresql.ENUM(
        "incorrect_charge",
        "service_failure",
        "duplicate_charge",
        "policy_violation",
        "unauthorized_ride",
        "pricing_discrepancy",
        "other",
        name="disputetype",
    )
    dispute_type_enum.create(op.get_bind(), checkfirst=True)

    # Create the DisputeStatus enum
    dispute_status_enum = postgresql.ENUM(
        "submitted",
        "under_review",
        "resolved_upheld",
        "resolved_denied",
        "withdrawn",
        name="disputestatus",
    )
    dispute_status_enum.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "corporate_invoice_disputes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("invoice_id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("submitted_by_id", sa.Integer(), nullable=True),
        sa.Column(
            "dispute_type",
            sa.Enum(
                "incorrect_charge",
                "service_failure",
                "duplicate_charge",
                "policy_violation",
                "unauthorized_ride",
                "pricing_discrepancy",
                "other",
                name="disputetype",
            ),
            nullable=False,
        ),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("disputed_rides", sa.JSON(), nullable=True),
        sa.Column("disputed_amount_usd", sa.Numeric(10, 2), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "submitted",
                "under_review",
                "resolved_upheld",
                "resolved_denied",
                "withdrawn",
                name="disputestatus",
            ),
            nullable=False,
            server_default="submitted",
        ),
        sa.Column("resolution_note", sa.Text(), nullable=True),
        sa.Column("resolved_by_id", sa.Integer(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["corporate_accounts_v2.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["invoice_id"],
            ["corporate_invoices_v2.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["submitted_by_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["resolved_by_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index(
        "ix_corp_inv_disputes_invoice_id",
        "corporate_invoice_disputes",
        ["invoice_id"],
    )
    op.create_index(
        "ix_corp_inv_disputes_account_id",
        "corporate_invoice_disputes",
        ["account_id"],
    )
    op.create_index(
        "ix_corp_inv_disputes_status",
        "corporate_invoice_disputes",
        ["status"],
    )
    op.create_index(
        "ix_corp_inv_disputes_account_status",
        "corporate_invoice_disputes",
        ["account_id", "status"],
    )


def downgrade() -> None:
    op.drop_index("ix_corp_inv_disputes_account_status", table_name="corporate_invoice_disputes")
    op.drop_index("ix_corp_inv_disputes_status", table_name="corporate_invoice_disputes")
    op.drop_index("ix_corp_inv_disputes_account_id", table_name="corporate_invoice_disputes")
    op.drop_index("ix_corp_inv_disputes_invoice_id", table_name="corporate_invoice_disputes")
    op.drop_table("corporate_invoice_disputes")

    op.execute("DROP TYPE IF EXISTS disputestatus")
    op.execute("DROP TYPE IF EXISTS disputetype")
