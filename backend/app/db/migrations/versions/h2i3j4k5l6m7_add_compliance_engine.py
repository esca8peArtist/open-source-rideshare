"""add compliance engine — jurisdictions table + driver_profiles compliance fields

Revision ID: h2i3j4k5l6m7
Revises: g1h2i3j4k5l6
Create Date: 2026-06-21 00:00:00.000000

This migration adds Sprint 1 compliance infrastructure:

1. ``jurisdictions`` table — immutable per-city TNC regulatory configuration.
   Seeded with Portland OR and Atlanta GA configs.

2. New columns on ``driver_profiles``:
   - ``membership_status`` (enum, default "active")
   - ``license_expiry`` (date, nullable)
   - ``background_check_expiry`` (date, nullable)
   - ``vehicle_inspection_expiry`` (date, nullable)
   - ``insurance_endorsement_expiry`` (date, nullable)
   - ``insurance_endorsement_verified_at`` (timestamp, nullable)
   - ``jurisdiction_id`` (foreign key → jurisdictions.id, nullable)

Existing driver records default to membership_status="active" and NULL expiry
dates.  Cooperatives should backfill expiry dates as part of their onboarding
review before enabling the compliance gate.

Rollback: removes all added columns and drops the jurisdictions table.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "h2i3j4k5l6m7"
down_revision: Union[str, Sequence[str], None] = "g1h2i3j4k5l6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── 1. Create jurisdictions table ────────────────────────────────────────
    op.create_table(
        "jurisdictions",
        sa.Column("id", sa.String(50), primary_key=True),
        sa.Column("name", sa.String(150), nullable=False),
        sa.Column(
            "background_check_type",
            sa.String(100),
            nullable=False,
            server_default="motor_vehicle_record + criminal",
        ),
        sa.Column("per_trip_surcharge", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column(
            "per_trip_surcharge_description", sa.String(200), nullable=False, server_default=""
        ),
        sa.Column("license_requirement", sa.Text(), nullable=False, server_default=""),
        sa.Column("insurance_requirement", sa.Text(), nullable=False, server_default=""),
        sa.Column("wav_mandate", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("wav_percentage", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("license_grace_days", sa.Integer(), nullable=False, server_default="14"),
        sa.Column(
            "background_check_grace_days", sa.Integer(), nullable=False, server_default="30"
        ),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
    )

    # ── 2. Seed jurisdiction configs ─────────────────────────────────────────
    op.bulk_insert(
        sa.table(
            "jurisdictions",
            sa.column("id", sa.String),
            sa.column("name", sa.String),
            sa.column("background_check_type", sa.String),
            sa.column("per_trip_surcharge", sa.Float),
            sa.column("per_trip_surcharge_description", sa.String),
            sa.column("license_requirement", sa.String),
            sa.column("insurance_requirement", sa.String),
            sa.column("wav_mandate", sa.Boolean),
            sa.column("wav_percentage", sa.Float),
            sa.column("license_grace_days", sa.Integer),
            sa.column("background_check_grace_days", sa.Integer),
            sa.column("is_active", sa.Boolean),
        ),
        [
            {
                "id": "portland_or",
                "name": "Portland, Oregon",
                "background_check_type": "motor_vehicle_record + criminal",
                "per_trip_surcharge": 0.50,
                "per_trip_surcharge_description": "Portland City Fee",
                "license_requirement": "Oregon commercial driver license",
                "insurance_requirement": "$1M commercial auto TNC endorsement",
                "wav_mandate": True,
                "wav_percentage": 0.05,
                "license_grace_days": 14,
                "background_check_grace_days": 30,
                "is_active": True,
            },
            {
                "id": "atlanta_ga",
                "name": "Atlanta, Georgia",
                "background_check_type": "motor_vehicle_record + criminal",
                "per_trip_surcharge": 0.00,
                "per_trip_surcharge_description": "",
                "license_requirement": "Georgia commercial driver license",
                "insurance_requirement": "$1M commercial auto TNC endorsement",
                "wav_mandate": False,
                "wav_percentage": 0.00,
                "license_grace_days": 14,
                "background_check_grace_days": 30,
                "is_active": True,
            },
        ],
    )

    # ── 3. Add membership_status enum + column to driver_profiles ────────────
    membershipstatus = sa.Enum(
        "active",
        "suspended",
        "probation",
        "compliance_hold",
        "terminated",
        name="membershipstatus",
    )
    membershipstatus.create(op.get_bind())

    op.add_column(
        "driver_profiles",
        sa.Column(
            "membership_status",
            sa.Enum(
                "active",
                "suspended",
                "probation",
                "compliance_hold",
                "terminated",
                name="membershipstatus",
                create_type=False,
            ),
            nullable=False,
            server_default="active",
        ),
    )
    op.create_index(
        "ix_driver_profiles_membership_status",
        "driver_profiles",
        ["membership_status"],
    )

    # ── 4. Add compliance document expiry columns ────────────────────────────
    op.add_column(
        "driver_profiles", sa.Column("license_expiry", sa.Date(), nullable=True)
    )
    op.create_index(
        "ix_driver_profiles_license_expiry", "driver_profiles", ["license_expiry"]
    )

    op.add_column(
        "driver_profiles",
        sa.Column("background_check_expiry", sa.Date(), nullable=True),
    )
    op.create_index(
        "ix_driver_profiles_background_check_expiry",
        "driver_profiles",
        ["background_check_expiry"],
    )

    op.add_column(
        "driver_profiles",
        sa.Column("vehicle_inspection_expiry", sa.Date(), nullable=True),
    )

    op.add_column(
        "driver_profiles",
        sa.Column("insurance_endorsement_expiry", sa.Date(), nullable=True),
    )

    op.add_column(
        "driver_profiles",
        sa.Column(
            "insurance_endorsement_verified_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )

    # ── 5. Add jurisdiction_id foreign key ───────────────────────────────────
    op.add_column(
        "driver_profiles",
        sa.Column("jurisdiction_id", sa.String(50), nullable=True),
    )
    op.create_foreign_key(
        "fk_driver_profiles_jurisdiction_id",
        "driver_profiles",
        "jurisdictions",
        ["jurisdiction_id"],
        ["id"],
    )
    op.create_index(
        "ix_driver_profiles_jurisdiction_id",
        "driver_profiles",
        ["jurisdiction_id"],
    )


def downgrade() -> None:
    # Remove driver_profiles additions in reverse order
    op.drop_index("ix_driver_profiles_jurisdiction_id", table_name="driver_profiles")
    op.drop_constraint(
        "fk_driver_profiles_jurisdiction_id", "driver_profiles", type_="foreignkey"
    )
    op.drop_column("driver_profiles", "jurisdiction_id")
    op.drop_column("driver_profiles", "insurance_endorsement_verified_at")
    op.drop_column("driver_profiles", "insurance_endorsement_expiry")
    op.drop_column("driver_profiles", "vehicle_inspection_expiry")
    op.drop_index(
        "ix_driver_profiles_background_check_expiry", table_name="driver_profiles"
    )
    op.drop_column("driver_profiles", "background_check_expiry")
    op.drop_index("ix_driver_profiles_license_expiry", table_name="driver_profiles")
    op.drop_column("driver_profiles", "license_expiry")
    op.drop_index(
        "ix_driver_profiles_membership_status", table_name="driver_profiles"
    )
    op.drop_column("driver_profiles", "membership_status")

    sa.Enum(name="membershipstatus").drop(op.get_bind())

    op.drop_table("jurisdictions")
