"""add rider_memberships table

Revision ID: k1l2m3n4o5p6
Revises: j1k2l3m4n5o6
Create Date: 2026-04-14 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'k1l2m3n4o5p6'
down_revision: Union[str, Sequence[str], None] = 'j1k2l3m4n5o6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "rider_memberships",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "rider_id",
            sa.Integer(),
            sa.ForeignKey("users.id"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "plan",
            sa.Enum("basic", "premium", name="membershipplan"),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum("active", "cancelled", "expired", name="membershipstatus"),
            nullable=False,
            server_default="active",
        ),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("monthly_price", sa.Float(), nullable=False),
        sa.Column("fare_discount_pct", sa.Float(), nullable=False),
        sa.Column("surge_cap_multiplier", sa.Float(), nullable=False),
        sa.Column("priority_matching", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("stripe_subscription_id", sa.String(255), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("rider_memberships")
    op.execute("DROP TYPE IF EXISTS membershipplan")
    op.execute("DROP TYPE IF EXISTS membershipstatus")
