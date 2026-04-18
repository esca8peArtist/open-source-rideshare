"""add driver_earnings_goals table

Revision ID: p0q1r2s3t4u5
Revises: o9p0q1r2s3t4
Create Date: 2026-04-18
"""
from alembic import op
import sqlalchemy as sa

revision = "p0q1r2s3t4u5"
down_revision = "o9p0q1r2s3t4"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "driver_earnings_goals",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("driver_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column(
            "period_type",
            sa.Enum("DAILY", "WEEKLY", name="goalperiodtype"),
            nullable=False,
        ),
        sa.Column("target_amount", sa.Float(), nullable=False),
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
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("driver_id", name="uq_driver_earnings_goal_driver"),
    )
    op.create_index("ix_driver_earnings_goals_driver_id", "driver_earnings_goals", ["driver_id"])


def downgrade():
    op.drop_index("ix_driver_earnings_goals_driver_id", table_name="driver_earnings_goals")
    op.drop_table("driver_earnings_goals")
    op.execute("DROP TYPE IF EXISTS goalperiodtype")
