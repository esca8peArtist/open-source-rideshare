"""add complaints table

Revision ID: d2e3f4a5b6c7
Revises: d9f4a7b62c38
Create Date: 2026-04-13 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd2e3f4a5b6c7'
down_revision: Union[str, Sequence[str], None] = 'd9f4a7b62c38'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "complaints",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "filed_by_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "against_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "ride_id",
            sa.Integer(),
            sa.ForeignKey("rides.id"),
            nullable=True,
            index=True,
        ),
        sa.Column(
            "category",
            sa.Enum(
                "unsafe_driving",
                "harassment",
                "discrimination",
                "vehicle_condition",
                "inappropriate_behavior",
                "fraud",
                "no_show",
                "wrong_route",
                "other",
                name="complaintcategory",
            ),
            nullable=False,
        ),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "pending",
                "reviewing",
                "resolved",
                "dismissed",
                name="complaintstatus",
            ),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("admin_notes", sa.Text(), nullable=True),
        sa.Column(
            "resolved_by_admin_id",
            sa.Integer(),
            sa.ForeignKey("users.id"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            index=True,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
    )


def downgrade() -> None:
    op.drop_table("complaints")
    op.execute("DROP TYPE IF EXISTS complaintcategory")
    op.execute("DROP TYPE IF EXISTS complaintstatus")
