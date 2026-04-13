"""add incentive_programs and driver_incentive_progress tables

Revision ID: e2f5a9c81d47
Revises: d9f4a7b62c38
Create Date: 2026-04-13 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'e2f5a9c81d47'
down_revision: Union[str, Sequence[str], None] = 'd9f4a7b62c38'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "incentive_programs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.String(1000), nullable=False, server_default=""),
        sa.Column("program_type", sa.String(50), nullable=False),
        sa.Column("bonus_amount", sa.Float(), nullable=False),
        sa.Column("trip_target", sa.Integer(), nullable=True),
        sa.Column("start_time", sa.Time(), nullable=True),
        sa.Column("end_time", sa.Time(), nullable=True),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("days_of_week", sa.String(20), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_incentive_programs_is_active", "incentive_programs", ["is_active"])
    op.create_index("ix_incentive_programs_start_date", "incentive_programs", ["start_date"])

    op.create_table(
        "driver_incentive_progress",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("driver_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False, index=True),
        sa.Column(
            "program_id",
            sa.Integer(),
            sa.ForeignKey("incentive_programs.id"),
            nullable=False,
            index=True,
        ),
        sa.Column("trips_completed", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("bonus_earned", sa.Float(), nullable=False, server_default=sa.text("0.0")),
        sa.Column("status", sa.String(50), nullable=False, server_default="active"),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("driver_id", "program_id", "period_start", name="uq_driver_program_period"),
    )
    op.create_index(
        "ix_driver_incentive_progress_status",
        "driver_incentive_progress",
        ["driver_id", "status"],
    )


def downgrade() -> None:
    op.drop_table("driver_incentive_progress")
    op.drop_table("incentive_programs")
