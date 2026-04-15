"""Add corporate_expense_reports table.

Employees can submit rides (or manual expenses) for corporate reimbursement.
Admins review and approve or reject each report.

Tables created:
  corporate_expense_reports — employee-submitted expense reports

Revision ID: c3d4e5f6g7h8
Revises:     b2c3d4e5f6g7
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# ---------------------------------------------------------------------------
# Metadata
# ---------------------------------------------------------------------------

revision = "c3d4e5f6g7h8"
down_revision = "b2c3d4e5f6g7"
branch_labels = None
depends_on = None

# ---------------------------------------------------------------------------
# Upgrade
# ---------------------------------------------------------------------------


def upgrade() -> None:
    # Create the expensestatus enum type
    op.execute(
        "CREATE TYPE expensestatus AS ENUM "
        "('pending', 'approved', 'rejected', 'withdrawn')"
    )

    op.create_table(
        "corporate_expense_reports",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "account_id",
            sa.Integer(),
            sa.ForeignKey("corporate_accounts_v2.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "submitted_by_id",
            sa.Integer(),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column(
            "ride_id",
            sa.Integer(),
            sa.ForeignKey("rides.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("amount_usd", sa.Numeric(10, 2), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column(
            "cost_center_id",
            sa.Integer(),
            sa.ForeignKey("corporate_cost_centers.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "trip_purpose_id",
            sa.Integer(),
            sa.ForeignKey("corporate_trip_purposes.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("receipt_url", sa.String(500), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "pending",
                "approved",
                "rejected",
                "withdrawn",
                name="expensestatus",
                create_type=False,
            ),
            nullable=False,
            server_default="pending",
        ),
        sa.Column(
            "reviewed_by_id",
            sa.Integer(),
            sa.ForeignKey("users.id"),
            nullable=True,
        ),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("review_note", sa.Text(), nullable=True),
        sa.Column(
            "submitted_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    op.create_index(
        "ix_corporate_expense_reports_account_id",
        "corporate_expense_reports",
        ["account_id"],
    )
    op.create_index(
        "ix_corporate_expense_reports_submitted_by_id",
        "corporate_expense_reports",
        ["submitted_by_id"],
    )
    op.create_index(
        "ix_corporate_expense_reports_ride_id",
        "corporate_expense_reports",
        ["ride_id"],
    )


# ---------------------------------------------------------------------------
# Downgrade
# ---------------------------------------------------------------------------


def downgrade() -> None:
    op.drop_index(
        "ix_corporate_expense_reports_ride_id",
        table_name="corporate_expense_reports",
    )
    op.drop_index(
        "ix_corporate_expense_reports_submitted_by_id",
        table_name="corporate_expense_reports",
    )
    op.drop_index(
        "ix_corporate_expense_reports_account_id",
        table_name="corporate_expense_reports",
    )
    op.drop_table("corporate_expense_reports")
    op.execute("DROP TYPE expensestatus")
