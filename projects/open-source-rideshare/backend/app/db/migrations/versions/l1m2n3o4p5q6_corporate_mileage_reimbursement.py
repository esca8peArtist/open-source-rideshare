"""Corporate mileage reimbursement.

Employees submit personal-vehicle mileage claims; admins configure per-mile
rates and approval thresholds; full claim lifecycle (draft → submitted →
approved/rejected → paid).

Tables created:
  corporate_mileage_policies — one row per account (unique on account_id)
  corporate_mileage_claims   — one row per claim

Revision ID: l1m2n3o4p5q6
Revises:     k0l1m2n3o4p5
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "l1m2n3o4p5q6"
down_revision: str = "k0l1m2n3o4p5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TYPE claimstatus AS ENUM (
            'draft',
            'submitted',
            'approved',
            'rejected',
            'paid'
        )
        """
    )

    op.create_table(
        "corporate_mileage_policies",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column(
            "rate_per_mile",
            sa.Numeric(6, 4),
            nullable=False,
            server_default="0.6700",
        ),
        sa.Column("max_miles_per_claim", sa.Integer(), nullable=True),
        sa.Column("requires_approval_above_usd", sa.Numeric(8, 2), nullable=True),
        sa.Column("requires_approval_above_miles", sa.Integer(), nullable=True),
        sa.Column(
            "require_trip_purpose",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column("created_by_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["corporate_accounts_v2.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint("account_id", name="uq_corp_mileage_policy_account_id"),
    )

    op.create_index(
        "ix_corp_mileage_policy_account_id",
        "corporate_mileage_policies",
        ["account_id"],
    )

    op.create_table(
        "corporate_mileage_claims",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("member_id", sa.Integer(), nullable=True),
        sa.Column("trip_date", sa.Date(), nullable=False),
        sa.Column("miles", sa.Numeric(8, 2), nullable=False),
        sa.Column("rate_used_usd", sa.Numeric(6, 4), nullable=False),
        sa.Column("amount_usd", sa.Numeric(10, 2), nullable=False),
        sa.Column("description", sa.String(500), nullable=False),
        sa.Column("trip_purpose_id", sa.Integer(), nullable=True),
        sa.Column("cost_center_id", sa.Integer(), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "draft",
                "submitted",
                "approved",
                "rejected",
                "paid",
                name="claimstatus",
            ),
            nullable=False,
            server_default="draft",
        ),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reviewed_by_id", sa.Integer(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("review_note", sa.String(500), nullable=True),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["corporate_accounts_v2.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["member_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["trip_purpose_id"],
            ["corporate_trip_purposes.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["cost_center_id"],
            ["corporate_cost_centers.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["reviewed_by_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
    )

    op.create_index(
        "ix_corp_mileage_claim_account_id",
        "corporate_mileage_claims",
        ["account_id"],
    )
    op.create_index(
        "ix_corp_mileage_claim_member_id",
        "corporate_mileage_claims",
        ["member_id"],
    )
    op.create_index(
        "ix_corp_mileage_claim_status",
        "corporate_mileage_claims",
        ["account_id", "status"],
    )
    op.create_index(
        "ix_corp_mileage_claim_trip_date",
        "corporate_mileage_claims",
        ["account_id", "trip_date"],
    )


def downgrade() -> None:
    op.drop_index("ix_corp_mileage_claim_trip_date", table_name="corporate_mileage_claims")
    op.drop_index("ix_corp_mileage_claim_status", table_name="corporate_mileage_claims")
    op.drop_index("ix_corp_mileage_claim_member_id", table_name="corporate_mileage_claims")
    op.drop_index("ix_corp_mileage_claim_account_id", table_name="corporate_mileage_claims")
    op.drop_table("corporate_mileage_claims")

    op.drop_index("ix_corp_mileage_policy_account_id", table_name="corporate_mileage_policies")
    op.drop_table("corporate_mileage_policies")

    op.execute("DROP TYPE IF EXISTS claimstatus")
