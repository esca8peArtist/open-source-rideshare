"""add driver_onboarding table

Revision ID: d1e2f3a4b5c6
Revises: c5d6e7f8a901
Create Date: 2026-04-13 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd1e2f3a4b5c6'
down_revision: Union[str, Sequence[str], None] = 'c5d6e7f8a901'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "driver_onboarding",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "driver_profile_id",
            sa.Integer(),
            sa.ForeignKey("driver_profiles.id"),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "status",
            sa.Enum(
                "incomplete",
                "pending_review",
                "approved",
                "suspended",
                name="onboardingstatus",
            ),
            nullable=False,
            server_default="incomplete",
        ),
        sa.Column("suspension_reason", sa.Text(), nullable=True),
        sa.Column(
            "suspended_by",
            sa.Integer(),
            sa.ForeignKey("users.id"),
            nullable=True,
        ),
        sa.Column(
            "suspended_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "activated_by",
            sa.Integer(),
            sa.ForeignKey("users.id"),
            nullable=True,
        ),
        sa.Column(
            "activated_at",
            sa.DateTime(timezone=True),
            nullable=True,
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
        "ix_driver_onboarding_driver_profile_id",
        "driver_onboarding",
        ["driver_profile_id"],
        unique=True,
    )
    op.create_index(
        "ix_driver_onboarding_status",
        "driver_onboarding",
        ["status"],
    )


def downgrade() -> None:
    op.drop_index("ix_driver_onboarding_status", table_name="driver_onboarding")
    op.drop_index(
        "ix_driver_onboarding_driver_profile_id", table_name="driver_onboarding"
    )
    op.drop_table("driver_onboarding")
    op.execute("DROP TYPE IF EXISTS onboardingstatus")
