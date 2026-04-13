"""add vehicle_inspections and vehicle_inspection_alerts tables

Revision ID: b4c9d3e2f1a7
Revises: a3b8c2d1e4f5
Create Date: 2026-04-13 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b4c9d3e2f1a7'
down_revision: Union[str, Sequence[str], None] = 'a3b8c2d1e4f5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "vehicle_inspections",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "driver_id",
            sa.Integer(),
            sa.ForeignKey("users.id"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "inspection_type",
            sa.Enum(
                "annual",
                "semi_annual",
                "pre_trip",
                "post_trip",
                "repair_followup",
                name="inspectiontype",
            ),
            nullable=False,
        ),
        sa.Column("inspection_date", sa.Date(), nullable=False),
        sa.Column("expiry_date", sa.Date(), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "pending_review",
                "approved",
                "rejected",
                "expired",
                name="inspectionstatus",
            ),
            nullable=False,
            index=True,
        ),
        sa.Column("document_url", sa.String(500), nullable=True),
        sa.Column("odometer_reading", sa.Integer(), nullable=True),
        sa.Column("passed_items", sa.JSON(), nullable=True),
        sa.Column("failed_items", sa.JSON(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("rejection_reason", sa.String(500), nullable=True),
        sa.Column("reviewed_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
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
        "ix_vehicle_inspection_driver_status",
        "vehicle_inspections",
        ["driver_id", "status"],
    )
    op.create_index(
        "ix_vehicle_inspection_status_expiry",
        "vehicle_inspections",
        ["status", "expiry_date"],
    )

    op.create_table(
        "vehicle_inspection_alerts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "inspection_id",
            sa.Integer(),
            sa.ForeignKey("vehicle_inspections.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "alert_type",
            sa.Enum(
                "expiring_soon",
                "expired",
                "failed",
                name="inspectionalerttype",
            ),
            nullable=False,
        ),
        sa.Column("alert_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("acknowledged", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_table("vehicle_inspection_alerts")
    op.drop_index(
        "ix_vehicle_inspection_status_expiry",
        table_name="vehicle_inspections",
    )
    op.drop_index(
        "ix_vehicle_inspection_driver_status",
        table_name="vehicle_inspections",
    )
    op.drop_table("vehicle_inspections")
    op.execute("DROP TYPE IF EXISTS inspectionalerttype")
    op.execute("DROP TYPE IF EXISTS inspectionstatus")
    op.execute("DROP TYPE IF EXISTS inspectiontype")
