"""Add corporate_fleet_vehicles and corporate_fleet_assignments tables.

Enterprise corporate accounts can define a pool of company-owned or leased
vehicles and assign drivers to them.

Tables created:
  corporate_fleet_vehicles    — one record per vehicle in the fleet
  corporate_fleet_assignments — driver assignment history per vehicle

Revision ID: b1c2d3e4f5g6
Revises:     a0b1c2d3e4f5
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "b1c2d3e4f5g6"
down_revision = "a0b1c2d3e4f5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ---------------------------------------- corporate_fleet_vehicles
    op.create_table(
        "corporate_fleet_vehicles",
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
        sa.Column("vehicle_type", sa.String(50), nullable=True),
        sa.Column("make", sa.String(50), nullable=True),
        sa.Column("model_name", sa.String(50), nullable=True),
        sa.Column("year", sa.Integer(), nullable=True),
        sa.Column("license_plate", sa.String(20), nullable=True),
        sa.Column("color", sa.String(30), nullable=True),
        sa.Column(
            "capacity",
            sa.Integer(),
            nullable=False,
            server_default="4",
        ),
        sa.Column(
            "is_wav",
            sa.Boolean(),
            nullable=False,
            server_default="false",
        ),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default="true",
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
        sa.UniqueConstraint(
            "account_id", "name", name="uq_corp_fleet_vehicle_account_name"
        ),
    )
    op.create_index(
        "ix_corp_fleet_vehicle_account_id",
        "corporate_fleet_vehicles",
        ["account_id"],
    )
    op.create_index(
        "ix_corp_fleet_vehicle_is_active",
        "corporate_fleet_vehicles",
        ["is_active"],
    )

    # ---------------------------------------- corporate_fleet_assignments
    op.create_table(
        "corporate_fleet_assignments",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
        ),
        sa.Column(
            "fleet_vehicle_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("corporate_fleet_vehicles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "account_id",
            sa.Integer(),
            sa.ForeignKey("corporate_accounts_v2.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "driver_profile_id",
            sa.Integer(),
            sa.ForeignKey("driver_profiles.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "assigned_by_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default="true",
        ),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_corp_fleet_assignment_vehicle_id",
        "corporate_fleet_assignments",
        ["fleet_vehicle_id"],
    )
    op.create_index(
        "ix_corp_fleet_assignment_driver_id",
        "corporate_fleet_assignments",
        ["driver_profile_id"],
    )
    op.create_index(
        "ix_corp_fleet_assignment_is_active",
        "corporate_fleet_assignments",
        ["is_active"],
    )


def downgrade() -> None:
    op.drop_table("corporate_fleet_assignments")
    op.drop_table("corporate_fleet_vehicles")
