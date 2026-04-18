"""add driver_shifts table

Revision ID: r2s3t4u5v6w7
Revises: q1r2s3t4u5v6
Create Date: 2026-04-18
"""
from alembic import op
import sqlalchemy as sa

revision = "r2s3t4u5v6w7"
down_revision = "q1r2s3t4u5v6"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "driver_shifts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("driver_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column(
            "status",
            sa.Enum("active", "completed", "auto_ended", name="shiftstatus"),
            nullable=False,
            server_default="active",
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("total_minutes", sa.Float(), nullable=True),
        sa.Column("rides_completed", sa.Integer(), nullable=False, server_default="0"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_driver_shifts_driver_id", "driver_shifts", ["driver_id"])
    op.create_index("ix_driver_shifts_started_at", "driver_shifts", ["started_at"])


def downgrade():
    op.drop_index("ix_driver_shifts_started_at", table_name="driver_shifts")
    op.drop_index("ix_driver_shifts_driver_id", table_name="driver_shifts")
    op.drop_table("driver_shifts")
    op.execute("DROP TYPE IF EXISTS shiftstatus")
