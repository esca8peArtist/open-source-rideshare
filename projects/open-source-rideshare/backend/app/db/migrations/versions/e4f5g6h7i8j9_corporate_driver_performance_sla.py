"""Add corporate_driver_performance_slas and corporate_driver_sla_records tables.

Enterprise accounts track individual driver performance against KPI thresholds.
Policies define the thresholds; records capture per-driver evaluation snapshots.

Tables created:
  corporate_driver_performance_slas — one record per named KPI policy
  corporate_driver_sla_records      — one record per driver evaluation

Revision ID: e4f5g6h7i8j9
Revises:     d3e4f5g6h7i8
Create Date: 2026-04-16
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "e4f5g6h7i8j9"
down_revision = "d3e4f5g6h7i8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ---------------------------------------- corporate_driver_performance_slas
    op.create_table(
        "corporate_driver_performance_slas",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
        ),
        sa.Column(
            "account_id",
            sa.Integer(),
            sa.ForeignKey("corporate_accounts_v2.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("min_on_time_rate_pct", sa.Numeric(5, 2), nullable=True),
        sa.Column("min_avg_rating", sa.Numeric(3, 2), nullable=True),
        sa.Column("max_cancellation_rate_pct", sa.Numeric(5, 2), nullable=True),
        sa.Column("min_acceptance_rate_pct", sa.Numeric(5, 2), nullable=True),
        sa.Column(
            "evaluation_window_days",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("30"),
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
        sa.Column(
            "created_by_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    op.create_index(
        "ix_drv_perf_sla_account_id",
        "corporate_driver_performance_slas",
        ["account_id"],
    )
    op.create_index(
        "ix_drv_perf_sla_is_active",
        "corporate_driver_performance_slas",
        ["is_active"],
    )
    op.create_index(
        "ix_drv_perf_sla_created_at",
        "corporate_driver_performance_slas",
        ["created_at"],
    )

    # ---------------------------------------- corporate_driver_sla_records
    op.create_table(
        "corporate_driver_sla_records",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
        ),
        sa.Column(
            "account_id",
            sa.Integer(),
            sa.ForeignKey("corporate_accounts_v2.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "sla_policy_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("corporate_driver_performance_slas.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "driver_profile_id",
            sa.Integer(),
            sa.ForeignKey("driver_profiles.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "evaluation_window_days",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("30"),
        ),
        sa.Column(
            "total_corporate_rides",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("on_time_rate_pct", sa.Numeric(5, 2), nullable=True),
        sa.Column("avg_rating", sa.Numeric(3, 2), nullable=True),
        sa.Column("cancellation_rate_pct", sa.Numeric(5, 2), nullable=True),
        sa.Column("acceptance_rate_pct", sa.Numeric(5, 2), nullable=True),
        sa.Column("on_time_met", sa.Boolean(), nullable=True),
        sa.Column("rating_met", sa.Boolean(), nullable=True),
        sa.Column("cancellation_met", sa.Boolean(), nullable=True),
        sa.Column("acceptance_met", sa.Boolean(), nullable=True),
        sa.Column(
            "overall_sla_met",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column(
            "flagged_for_review",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column(
            "flagged_by_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("flagged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("flag_reason", sa.Text(), nullable=True),
    )

    op.create_index(
        "ix_drv_sla_record_account_id",
        "corporate_driver_sla_records",
        ["account_id"],
    )
    op.create_index(
        "ix_drv_sla_record_driver_profile_id",
        "corporate_driver_sla_records",
        ["driver_profile_id"],
    )
    op.create_index(
        "ix_drv_sla_record_evaluated_at",
        "corporate_driver_sla_records",
        ["evaluated_at"],
    )
    op.create_index(
        "ix_drv_sla_record_overall_sla_met",
        "corporate_driver_sla_records",
        ["overall_sla_met"],
    )


def downgrade() -> None:
    op.drop_index("ix_drv_sla_record_overall_sla_met", "corporate_driver_sla_records")
    op.drop_index("ix_drv_sla_record_evaluated_at", "corporate_driver_sla_records")
    op.drop_index("ix_drv_sla_record_driver_profile_id", "corporate_driver_sla_records")
    op.drop_index("ix_drv_sla_record_account_id", "corporate_driver_sla_records")
    op.drop_table("corporate_driver_sla_records")

    op.drop_index("ix_drv_perf_sla_created_at", "corporate_driver_performance_slas")
    op.drop_index("ix_drv_perf_sla_is_active", "corporate_driver_performance_slas")
    op.drop_index("ix_drv_perf_sla_account_id", "corporate_driver_performance_slas")
    op.drop_table("corporate_driver_performance_slas")
