"""Add cancellation_policies and cancellation_records tables.

Tables created:
  cancellation_policies  — platform-level fee configuration (singleton, admin-managed).
  cancellation_records   — one row per cancelled ride with fee details.

Indexes added on is_active, ride_id, cancelled_by, fee_charged_to, and fee_status
for efficient querying on the most common filter patterns.

Revision ID: a2b3c4d5e6f7
Revises: y1z2a3b4c5d6
Create Date: 2026-04-15
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "a2b3c4d5e6f7"
down_revision = "y1z2a3b4c5d6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # Enum types
    # ------------------------------------------------------------------
    cancelled_by_enum = sa.Enum(
        "rider", "driver", "admin", "system",
        name="cancelledby",
    )
    cancelled_by_enum.create(op.get_bind(), checkfirst=True)

    fee_charged_to_enum = sa.Enum(
        "rider", "driver", "none",
        name="feechrgedto",
    )
    fee_charged_to_enum.create(op.get_bind(), checkfirst=True)

    fee_status_enum = sa.Enum(
        "pending", "charged", "waived", "refunded",
        name="feestatus",
    )
    fee_status_enum.create(op.get_bind(), checkfirst=True)

    # ------------------------------------------------------------------
    # cancellation_policies
    # ------------------------------------------------------------------
    op.create_table(
        "cancellation_policies",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("rider_grace_period_seconds", sa.Integer(), nullable=False, server_default="120"),
        sa.Column("rider_fee_flat", sa.Numeric(10, 2), nullable=False, server_default="5.00"),
        sa.Column("rider_fee_percent", sa.Numeric(5, 4), nullable=False, server_default="0.0000"),
        sa.Column("driver_free_cancels_per_day", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("driver_cancel_penalty", sa.Numeric(10, 2), nullable=False, server_default="2.00"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
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
    )

    op.create_index(
        "ix_cancellation_policies_is_active",
        "cancellation_policies",
        ["is_active"],
    )

    # ------------------------------------------------------------------
    # cancellation_records
    # ------------------------------------------------------------------
    op.create_table(
        "cancellation_records",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("ride_id", sa.Integer(), nullable=False),
        sa.Column("cancelled_by", cancelled_by_enum, nullable=False),
        sa.Column("cancellation_reason", sa.Text(), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("grace_period_expired", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("fee_applied", sa.Numeric(10, 2), nullable=False, server_default="0.00"),
        sa.Column("fee_charged_to", fee_charged_to_enum, nullable=False, server_default="none"),
        sa.Column("fee_status", fee_status_enum, nullable=False, server_default="pending"),
        sa.Column("waived_by_admin_id", sa.Integer(), nullable=True),
        sa.Column("waive_reason", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["ride_id"], ["rides.id"]),
        sa.ForeignKeyConstraint(["waived_by_admin_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("ride_id", name="uq_cancellation_records_ride_id"),
    )

    op.create_index(
        "ix_cancellation_records_ride_id",
        "cancellation_records",
        ["ride_id"],
        unique=True,
    )
    op.create_index(
        "ix_cancellation_records_cancelled_by",
        "cancellation_records",
        ["cancelled_by"],
    )
    op.create_index(
        "ix_cancellation_records_fee_charged_to",
        "cancellation_records",
        ["fee_charged_to"],
    )
    op.create_index(
        "ix_cancellation_records_fee_status",
        "cancellation_records",
        ["fee_status"],
    )


def downgrade() -> None:
    op.drop_index("ix_cancellation_records_fee_status", "cancellation_records")
    op.drop_index("ix_cancellation_records_fee_charged_to", "cancellation_records")
    op.drop_index("ix_cancellation_records_cancelled_by", "cancellation_records")
    op.drop_index("ix_cancellation_records_ride_id", "cancellation_records")
    op.drop_table("cancellation_records")

    op.drop_index("ix_cancellation_policies_is_active", "cancellation_policies")
    op.drop_table("cancellation_policies")

    sa.Enum(name="feestatus").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="feechrgedto").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="cancelledby").drop(op.get_bind(), checkfirst=True)
