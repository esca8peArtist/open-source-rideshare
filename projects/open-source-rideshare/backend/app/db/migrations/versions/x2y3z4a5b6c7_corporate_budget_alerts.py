"""Add corporate_budget_alerts table.

Admins configure percentage-based alert thresholds on cost centers or the
overall corporate account.  When a billing cycle's actual spend crosses a
configured threshold the alert record transitions to 'triggered'.

Tables created:
  corporate_budget_alerts — per-account alert threshold records with scope,
                            cost center reference, threshold_pct, and
                            trigger/acknowledgement tracking.

Revision ID: x2y3z4a5b6c7
Revises:     w2x3y4z5a6b7
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "x2y3z4a5b6c7"
down_revision: str = "w2x3y4z5a6b7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create the BudgetAlertScope enum type
    budget_alert_scope = postgresql.ENUM(
        "cost_center", "account",
        name="budgetalertscope",
        create_type=True,
    )
    budget_alert_scope.create(op.get_bind(), checkfirst=True)

    # Create the BudgetAlertStatus enum type
    budget_alert_status = postgresql.ENUM(
        "active", "triggered", "acknowledged",
        name="budgetalertstatus",
        create_type=True,
    )
    budget_alert_status.create(op.get_bind(), checkfirst=True)

    # corporate_budget_alerts table
    op.create_table(
        "corporate_budget_alerts",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("corporate_account_id", sa.Integer(), nullable=False),
        sa.Column(
            "scope",
            sa.Enum(
                "cost_center", "account",
                name="budgetalertscope",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("cost_center_id", sa.Integer(), nullable=True),
        sa.Column("threshold_pct", sa.Integer(), nullable=False),
        sa.Column("label", sa.String(200), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "active", "triggered", "acknowledged",
                name="budgetalertstatus",
                create_type=False,
            ),
            nullable=False,
            server_default="active",
        ),
        sa.Column("triggered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("acknowledged_by_id", sa.Integer(), nullable=True),
        sa.Column("billing_month", sa.Date(), nullable=True),
        sa.Column("spend_at_trigger_usd", sa.Numeric(10, 2), nullable=True),
        sa.Column("budget_at_trigger_usd", sa.Numeric(10, 2), nullable=True),
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
            ["corporate_account_id"],
            ["corporate_accounts_v2.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["cost_center_id"],
            ["corporate_cost_centers.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["acknowledged_by_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "corporate_account_id",
            "scope",
            "cost_center_id",
            "threshold_pct",
            name="uq_budget_alert_account_scope_cc_pct",
        ),
    )

    op.create_index(
        "ix_corporate_budget_alerts_account_id",
        "corporate_budget_alerts",
        ["corporate_account_id"],
    )
    op.create_index(
        "ix_corporate_budget_alerts_cost_center_id",
        "corporate_budget_alerts",
        ["cost_center_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_corporate_budget_alerts_cost_center_id",
        table_name="corporate_budget_alerts",
    )
    op.drop_index(
        "ix_corporate_budget_alerts_account_id",
        table_name="corporate_budget_alerts",
    )
    op.drop_table("corporate_budget_alerts")

    op.execute("DROP TYPE IF EXISTS budgetalertstatus")
    op.execute("DROP TYPE IF EXISTS budgetalertscope")
