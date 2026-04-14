"""add driver_subscriptions table

Revision ID: p1q2r3s4t5u6
Revises: o1p2q3r4s5t6
Create Date: 2026-04-15 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'p1q2r3s4t5u6'
down_revision: Union[str, Sequence[str], None] = 'o1p2q3r4s5t6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "driver_subscriptions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("driver_id", sa.Integer(), nullable=False),
        sa.Column(
            "plan",
            sa.Enum("weekly", "monthly", name="driversubscriptionplan"),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum("active", "cancelled", "expired", name="driversubscriptionstatus"),
            nullable=False,
            server_default="active",
        ),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("price", sa.Float(), nullable=False),
        sa.Column("commission_pct", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("auto_renew", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("stripe_subscription_id", sa.String(255), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["driver_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_driver_subscriptions_driver_id", "driver_subscriptions", ["driver_id"])
    op.create_index("ix_driver_subscriptions_status", "driver_subscriptions", ["status"])
    op.create_index("ix_driver_subscriptions_expires_at", "driver_subscriptions", ["expires_at"])


def downgrade() -> None:
    op.drop_index("ix_driver_subscriptions_expires_at", table_name="driver_subscriptions")
    op.drop_index("ix_driver_subscriptions_status", table_name="driver_subscriptions")
    op.drop_index("ix_driver_subscriptions_driver_id", table_name="driver_subscriptions")
    op.drop_table("driver_subscriptions")
    op.execute("DROP TYPE IF EXISTS driversubscriptionplan")
    op.execute("DROP TYPE IF EXISTS driversubscriptionstatus")
