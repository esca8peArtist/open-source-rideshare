"""Corporate Fleet Incident Reports.

Fleet admins and members log and track vehicle incidents including accidents,
breakdowns, traffic violations, theft, vandalism, weather damage, and other
events.

Tables created:
  corporate_fleet_incident_reports — one record per incident event

Revision ID: w2x3y4z5a6b7
Revises:     v1w2x3y4z5a6
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "w2x3y4z5a6b7"
down_revision: str = "v1w2x3y4z5a6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Incident type enum
    op.execute(
        "CREATE TYPE fleetincidenttype AS ENUM ("
        "'accident', 'breakdown', 'traffic_violation', 'theft', "
        "'vandalism', 'weather_damage', 'other'"
        ")"
    )

    # Incident severity enum
    op.execute(
        "CREATE TYPE fleetincidentseverity AS ENUM ("
        "'minor', 'moderate', 'major', 'total_loss'"
        ")"
    )

    # Incident status enum
    op.execute(
        "CREATE TYPE fleetincidentstatus AS ENUM ("
        "'reported', 'under_review', 'resolved', 'closed'"
        ")"
    )

    # Incident reports table
    op.create_table(
        "corporate_fleet_incident_reports",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("vehicle_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("reported_by_user_id", sa.Integer(), nullable=True),
        sa.Column(
            "incident_type",
            sa.Enum(
                "accident",
                "breakdown",
                "traffic_violation",
                "theft",
                "vandalism",
                "weather_damage",
                "other",
                name="fleetincidenttype",
            ),
            nullable=False,
        ),
        sa.Column(
            "severity",
            sa.Enum(
                "minor",
                "moderate",
                "major",
                "total_loss",
                name="fleetincidentseverity",
            ),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum(
                "reported",
                "under_review",
                "resolved",
                "closed",
                name="fleetincidentstatus",
            ),
            nullable=False,
            server_default="reported",
        ),
        sa.Column("incident_date", sa.Date(), nullable=False),
        sa.Column("incident_location", sa.String(500), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "damage_estimate",
            sa.Numeric(precision=10, scale=2),
            nullable=True,
        ),
        sa.Column("insurance_claim_number", sa.String(100), nullable=True),
        sa.Column("police_report_number", sa.String(100), nullable=True),
        sa.Column(
            "third_party_involved",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "injuries_reported",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolution_notes", sa.Text(), nullable=True),
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
            ["account_id"],
            ["corporate_accounts_v2.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["vehicle_id"],
            ["corporate_fleet_vehicles.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["reported_by_user_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
    )

    op.create_index(
        "ix_fleet_incident_account_id",
        "corporate_fleet_incident_reports",
        ["account_id"],
    )
    op.create_index(
        "ix_fleet_incident_vehicle_id",
        "corporate_fleet_incident_reports",
        ["vehicle_id"],
    )
    op.create_index(
        "ix_fleet_incident_status",
        "corporate_fleet_incident_reports",
        ["status"],
    )
    op.create_index(
        "ix_fleet_incident_account_date",
        "corporate_fleet_incident_reports",
        ["account_id", "incident_date"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_fleet_incident_account_date",
        table_name="corporate_fleet_incident_reports",
    )
    op.drop_index(
        "ix_fleet_incident_status",
        table_name="corporate_fleet_incident_reports",
    )
    op.drop_index(
        "ix_fleet_incident_vehicle_id",
        table_name="corporate_fleet_incident_reports",
    )
    op.drop_index(
        "ix_fleet_incident_account_id",
        table_name="corporate_fleet_incident_reports",
    )
    op.drop_table("corporate_fleet_incident_reports")

    op.execute("DROP TYPE fleetincidentstatus")
    op.execute("DROP TYPE fleetincidentseverity")
    op.execute("DROP TYPE fleetincidenttype")
