"""Corporate Vehicle Incident Reports.

Fleet managers document incidents involving company vehicles and track them
through a resolution workflow with optional insurance claim linkage.

Tables created:
  corporate_vehicle_incident_reports — one record per fleet vehicle incident

Revision ID: p5q6r7s8t9u0
Revises:     o4p5q6r7s8t9
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "p5q6r7s8t9u0"
down_revision: str = "o4p5q6r7s8t9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TYPE incidenttype AS ENUM (
            'collision',
            'parking_damage',
            'vandalism',
            'theft',
            'mechanical_failure',
            'other'
        )
        """
    )

    op.execute(
        """
        CREATE TYPE incidentstatus AS ENUM (
            'draft',
            'reported',
            'under_review',
            'resolved',
            'closed'
        )
        """
    )

    op.create_table(
        "corporate_vehicle_incident_reports",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
        ),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column(
            "fleet_vehicle_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "incident_type",
            sa.Enum(
                "collision",
                "parking_damage",
                "vandalism",
                "theft",
                "mechanical_failure",
                "other",
                name="incidenttype",
            ),
            nullable=False,
        ),
        sa.Column(
            "incident_status",
            sa.Enum(
                "draft",
                "reported",
                "under_review",
                "resolved",
                "closed",
                name="incidentstatus",
            ),
            nullable=False,
            server_default="draft",
        ),
        sa.Column("incident_date", sa.Date(), nullable=False),
        sa.Column("incident_time", sa.Time(), nullable=True),
        sa.Column("incident_location", sa.String(500), nullable=True),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column(
            "estimated_damage_usd", sa.Numeric(precision=10, scale=2), nullable=True
        ),
        sa.Column("police_report_number", sa.String(100), nullable=True),
        sa.Column("driver_id", sa.Integer(), nullable=True),
        sa.Column(
            "insurance_policy_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column("insurance_claim_number", sa.String(100), nullable=True),
        sa.Column("witness_info", sa.Text(), nullable=True),
        sa.Column("reported_by_id", sa.Integer(), nullable=True),
        sa.Column("reviewed_by_id", sa.Integer(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
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
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["corporate_accounts_v2.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["fleet_vehicle_id"],
            ["corporate_fleet_vehicles.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["driver_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["insurance_policy_id"],
            ["corporate_fleet_insurance_policies.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["reported_by_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["reviewed_by_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
    )

    op.create_index(
        "ix_incident_account_id",
        "corporate_vehicle_incident_reports",
        ["account_id"],
    )
    op.create_index(
        "ix_incident_fleet_vehicle_id",
        "corporate_vehicle_incident_reports",
        ["fleet_vehicle_id"],
    )
    op.create_index(
        "ix_incident_status",
        "corporate_vehicle_incident_reports",
        ["incident_status"],
    )
    op.create_index(
        "ix_incident_date",
        "corporate_vehicle_incident_reports",
        ["incident_date"],
    )
    op.create_index(
        "ix_incident_insurance_policy_id",
        "corporate_vehicle_incident_reports",
        ["insurance_policy_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_incident_insurance_policy_id",
        table_name="corporate_vehicle_incident_reports",
    )
    op.drop_index(
        "ix_incident_date",
        table_name="corporate_vehicle_incident_reports",
    )
    op.drop_index(
        "ix_incident_status",
        table_name="corporate_vehicle_incident_reports",
    )
    op.drop_index(
        "ix_incident_fleet_vehicle_id",
        table_name="corporate_vehicle_incident_reports",
    )
    op.drop_index(
        "ix_incident_account_id",
        table_name="corporate_vehicle_incident_reports",
    )
    op.drop_table("corporate_vehicle_incident_reports")
    op.execute("DROP TYPE IF EXISTS incidentstatus")
    op.execute("DROP TYPE IF EXISTS incidenttype")
