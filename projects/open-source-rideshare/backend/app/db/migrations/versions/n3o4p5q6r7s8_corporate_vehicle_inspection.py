"""Corporate Vehicle Inspection Checklists.

Fleet managers define reusable inspection templates for company vehicles.
Drivers or fleet managers submit completed checklists (pre-trip, post-trip,
scheduled, or incident) before/after each vehicle use.  Defects found during
an inspection are flagged for maintenance tracking.

Tables created:
  corporate_vehicle_inspection_templates — reusable checklist templates
  corporate_vehicle_inspections          — completed/pending inspection records

Revision ID: n3o4p5q6r7s8
Revises:     m2n3o4p5q6r7
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "n3o4p5q6r7s8"
down_revision: str = "m2n3o4p5q6r7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TYPE inspectiontype AS ENUM (
            'pre_trip',
            'post_trip',
            'scheduled',
            'incident'
        )
        """
    )

    op.execute(
        """
        CREATE TYPE inspectionstatus AS ENUM (
            'pending',
            'passed',
            'failed',
            'requires_attention'
        )
        """
    )

    op.create_table(
        "corporate_vehicle_inspection_templates",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
        ),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("description", sa.String(500), nullable=True),
        sa.Column(
            "inspection_items",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column("created_by_id", sa.Integer(), nullable=True),
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
            ["created_by_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint(
            "account_id",
            "name",
            name="uq_corp_veh_insp_template_account_name",
        ),
    )

    op.create_index(
        "ix_corp_veh_insp_tmpl_account_id",
        "corporate_vehicle_inspection_templates",
        ["account_id"],
    )
    op.create_index(
        "ix_corp_veh_insp_tmpl_is_active",
        "corporate_vehicle_inspection_templates",
        ["account_id", "is_active"],
    )

    op.create_table(
        "corporate_vehicle_inspections",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
        ),
        sa.Column(
            "template_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column(
            "fleet_vehicle_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column(
            "reservation_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column(
            "inspection_type",
            sa.Enum(
                "pre_trip",
                "post_trip",
                "scheduled",
                "incident",
                name="inspectiontype",
            ),
            nullable=False,
        ),
        sa.Column(
            "inspection_status",
            sa.Enum(
                "pending",
                "passed",
                "failed",
                "requires_attention",
                name="inspectionstatus",
            ),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("inspected_by_id", sa.Integer(), nullable=True),
        sa.Column("inspected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("odometer_miles", sa.Integer(), nullable=True),
        sa.Column("fuel_level_pct", sa.Integer(), nullable=True),
        sa.Column(
            "items_checked",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("defects_noted", postgresql.JSONB(), nullable=True),
        sa.Column("overall_notes", sa.String(1000), nullable=True),
        sa.Column(
            "maintenance_log_id",
            postgresql.UUID(as_uuid=True),
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
        sa.ForeignKeyConstraint(
            ["template_id"],
            ["corporate_vehicle_inspection_templates.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["fleet_vehicle_id"],
            ["corporate_fleet_vehicles.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["corporate_accounts_v2.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["reservation_id"],
            ["corporate_vehicle_reservations.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["inspected_by_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["maintenance_log_id"],
            ["corporate_vehicle_maintenance_logs.id"],
            ondelete="SET NULL",
        ),
    )

    op.create_index(
        "ix_corp_veh_insp_account_id",
        "corporate_vehicle_inspections",
        ["account_id"],
    )
    op.create_index(
        "ix_corp_veh_insp_fleet_vehicle_id",
        "corporate_vehicle_inspections",
        ["fleet_vehicle_id"],
    )
    op.create_index(
        "ix_corp_veh_insp_type",
        "corporate_vehicle_inspections",
        ["inspection_type"],
    )
    op.create_index(
        "ix_corp_veh_insp_status",
        "corporate_vehicle_inspections",
        ["inspection_status"],
    )
    op.create_index(
        "ix_corp_veh_insp_inspected_at",
        "corporate_vehicle_inspections",
        ["inspected_at"],
    )
    op.create_index(
        "ix_corp_veh_insp_template_id",
        "corporate_vehicle_inspections",
        ["template_id"],
    )
    op.create_index(
        "ix_corp_veh_insp_reservation_id",
        "corporate_vehicle_inspections",
        ["reservation_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_corp_veh_insp_reservation_id",
        table_name="corporate_vehicle_inspections",
    )
    op.drop_index(
        "ix_corp_veh_insp_template_id",
        table_name="corporate_vehicle_inspections",
    )
    op.drop_index(
        "ix_corp_veh_insp_inspected_at",
        table_name="corporate_vehicle_inspections",
    )
    op.drop_index(
        "ix_corp_veh_insp_status",
        table_name="corporate_vehicle_inspections",
    )
    op.drop_index(
        "ix_corp_veh_insp_type",
        table_name="corporate_vehicle_inspections",
    )
    op.drop_index(
        "ix_corp_veh_insp_fleet_vehicle_id",
        table_name="corporate_vehicle_inspections",
    )
    op.drop_index(
        "ix_corp_veh_insp_account_id",
        table_name="corporate_vehicle_inspections",
    )
    op.drop_table("corporate_vehicle_inspections")

    op.drop_index(
        "ix_corp_veh_insp_tmpl_is_active",
        table_name="corporate_vehicle_inspection_templates",
    )
    op.drop_index(
        "ix_corp_veh_insp_tmpl_account_id",
        table_name="corporate_vehicle_inspection_templates",
    )
    op.drop_table("corporate_vehicle_inspection_templates")

    op.execute("DROP TYPE IF EXISTS inspectionstatus")
    op.execute("DROP TYPE IF EXISTS inspectiontype")
