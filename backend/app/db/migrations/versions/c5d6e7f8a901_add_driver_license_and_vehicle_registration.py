"""add driver_licenses, driver_license_alerts, vehicle_registrations, and vehicle_registration_alerts tables

Revision ID: c5d6e7f8a901
Revises: b4c9d3e2f1a7
Create Date: 2026-04-13 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c5d6e7f8a901'
down_revision: Union[str, Sequence[str], None] = 'b4c9d3e2f1a7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- driver_licenses --------------------------------------------------------
    op.create_table(
        "driver_licenses",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "driver_id",
            sa.Integer(),
            sa.ForeignKey("users.id"),
            nullable=False,
            index=True,
        ),
        sa.Column("license_number", sa.String(100), nullable=False),
        sa.Column("state_issued", sa.String(50), nullable=False),
        sa.Column(
            "license_class",
            sa.Enum("A", "B", "C", "CDL", name="licenseclass"),
            nullable=False,
        ),
        sa.Column("expiry_date", sa.Date(), nullable=False),
        sa.Column("document_url", sa.String(500), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "pending_upload",
                "pending_review",
                "approved",
                "rejected",
                "expired",
                name="licensedocumentstatus",
            ),
            nullable=False,
            index=True,
        ),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("rejection_reason", sa.Text(), nullable=True),
        sa.Column(
            "reviewed_by",
            sa.Integer(),
            sa.ForeignKey("users.id"),
            nullable=True,
        ),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), nullable=True),
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
        "ix_driver_license_driver_status",
        "driver_licenses",
        ["driver_id", "status"],
    )
    op.create_index(
        "ix_driver_license_status_expiry",
        "driver_licenses",
        ["status", "expiry_date"],
    )

    # --- driver_license_alerts --------------------------------------------------
    op.create_table(
        "driver_license_alerts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "driver_id",
            sa.Integer(),
            sa.ForeignKey("users.id"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "license_id",
            sa.Integer(),
            sa.ForeignKey("driver_licenses.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "alert_type",
            sa.Enum("30_day", "7_day", "1_day", "expired", name="licensealerttype"),
            nullable=False,
        ),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    # --- vehicle_registrations --------------------------------------------------
    op.create_table(
        "vehicle_registrations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "driver_id",
            sa.Integer(),
            sa.ForeignKey("users.id"),
            nullable=False,
            index=True,
        ),
        sa.Column("vehicle_id", sa.String(100), nullable=True),
        sa.Column("plate_number", sa.String(20), nullable=False),
        sa.Column("state", sa.String(50), nullable=False),
        sa.Column("expiry_date", sa.Date(), nullable=False),
        sa.Column("document_url", sa.String(500), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "pending_upload",
                "pending_review",
                "approved",
                "rejected",
                "expired",
                name="registrationdocumentstatus",
            ),
            nullable=False,
            index=True,
        ),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("rejection_reason", sa.Text(), nullable=True),
        sa.Column(
            "reviewed_by",
            sa.Integer(),
            sa.ForeignKey("users.id"),
            nullable=True,
        ),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), nullable=True),
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
        "ix_vehicle_registration_driver_status",
        "vehicle_registrations",
        ["driver_id", "status"],
    )
    op.create_index(
        "ix_vehicle_registration_status_expiry",
        "vehicle_registrations",
        ["status", "expiry_date"],
    )

    # --- vehicle_registration_alerts --------------------------------------------
    op.create_table(
        "vehicle_registration_alerts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "driver_id",
            sa.Integer(),
            sa.ForeignKey("users.id"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "registration_id",
            sa.Integer(),
            sa.ForeignKey("vehicle_registrations.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "alert_type",
            sa.Enum("30_day", "7_day", "1_day", "expired", name="registrationalerttype"),
            nullable=False,
        ),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_table("vehicle_registration_alerts")
    op.drop_index(
        "ix_vehicle_registration_status_expiry",
        table_name="vehicle_registrations",
    )
    op.drop_index(
        "ix_vehicle_registration_driver_status",
        table_name="vehicle_registrations",
    )
    op.drop_table("vehicle_registrations")

    op.drop_table("driver_license_alerts")
    op.drop_index(
        "ix_driver_license_status_expiry",
        table_name="driver_licenses",
    )
    op.drop_index(
        "ix_driver_license_driver_status",
        table_name="driver_licenses",
    )
    op.drop_table("driver_licenses")

    op.execute("DROP TYPE IF EXISTS registrationalerttype")
    op.execute("DROP TYPE IF EXISTS registrationdocumentstatus")
    op.execute("DROP TYPE IF EXISTS licensealerttype")
    op.execute("DROP TYPE IF EXISTS licensedocumentstatus")
    op.execute("DROP TYPE IF EXISTS licenseclass")
