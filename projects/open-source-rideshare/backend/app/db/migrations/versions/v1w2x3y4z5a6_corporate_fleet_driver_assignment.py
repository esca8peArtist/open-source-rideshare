"""Corporate Fleet Driver Assignments.

Fleet admins assign corporate account members to fleet vehicles, tracking
who is the primary, secondary, pool, or temporary driver of each vehicle.

Tables created:
  corporate_fleet_driver_assignments — one record per driver-vehicle assignment

Revision ID: v1w2x3y4z5a6
Revises:     u0v1w2x3y4z5
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "v1w2x3y4z5a6"
down_revision: str = "u0v1w2x3y4z5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Driver assignment type enum
    op.execute(
        "CREATE TYPE fleetdriverassignmenttype AS ENUM ("
        "'primary', 'secondary', 'pool', 'temporary'"
        ")"
    )

    # Driver assignment status enum
    op.execute(
        "CREATE TYPE fleetdriverassignmentstatus AS ENUM ("
        "'active', 'inactive', 'pending', 'suspended'"
        ")"
    )

    # Driver assignments table
    op.create_table(
        "corporate_fleet_driver_assignments",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("vehicle_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column(
            "assignment_type",
            sa.Enum(
                "primary",
                "secondary",
                "pool",
                "temporary",
                name="fleetdriverassignmenttype",
            ),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum(
                "active",
                "inactive",
                "pending",
                "suspended",
                name="fleetdriverassignmentstatus",
            ),
            nullable=False,
            server_default="active",
        ),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("authorized_by_user_id", sa.Integer(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
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
        sa.ForeignKeyConstraint(
            ["vehicle_id"],
            ["corporate_fleet_vehicles.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["corporate_accounts_v2.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["authorized_by_user_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
    )
    op.create_index(
        "ix_fleet_driver_assignment_vehicle_id",
        "corporate_fleet_driver_assignments",
        ["vehicle_id"],
    )
    op.create_index(
        "ix_fleet_driver_assignment_account_id",
        "corporate_fleet_driver_assignments",
        ["account_id"],
    )
    op.create_index(
        "ix_fleet_driver_assignment_user_id",
        "corporate_fleet_driver_assignments",
        ["user_id"],
    )
    op.create_index(
        "ix_fleet_driver_assignment_status",
        "corporate_fleet_driver_assignments",
        ["status"],
    )
    op.create_index(
        "ix_fleet_driver_assignment_type",
        "corporate_fleet_driver_assignments",
        ["assignment_type"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_fleet_driver_assignment_type",
        table_name="corporate_fleet_driver_assignments",
    )
    op.drop_index(
        "ix_fleet_driver_assignment_status",
        table_name="corporate_fleet_driver_assignments",
    )
    op.drop_index(
        "ix_fleet_driver_assignment_user_id",
        table_name="corporate_fleet_driver_assignments",
    )
    op.drop_index(
        "ix_fleet_driver_assignment_account_id",
        table_name="corporate_fleet_driver_assignments",
    )
    op.drop_index(
        "ix_fleet_driver_assignment_vehicle_id",
        table_name="corporate_fleet_driver_assignments",
    )
    op.drop_table("corporate_fleet_driver_assignments")

    op.execute("DROP TYPE fleetdriverassignmentstatus")
    op.execute("DROP TYPE fleetdriverassignmenttype")
