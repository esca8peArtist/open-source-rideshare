"""Add corporate parking management tables.

Enterprise accounts define parking facilities, individual spots within those
facilities, and assign spots to employees.

Tables created:
  corporate_parking_facilities  — named parking facilities per account
  corporate_parking_spots       — individual spots within a facility
  corporate_parking_assignments — spot-to-member assignment records

Revision ID: f5g6h7i8j9k0
Revises:     e4f5g6h7i8j9
Create Date: 2026-04-16
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "f5g6h7i8j9k0"
down_revision = "e4f5g6h7i8j9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ---- enums ----
    facilitytype = postgresql.ENUM(
        "surface_lot",
        "parking_garage",
        "covered_structure",
        "underground",
        name="facilitytype",
        create_type=False,
    )
    facilitytype.create(op.get_bind(), checkfirst=True)

    spottype = postgresql.ENUM(
        "standard",
        "accessible",
        "ev_charging",
        "motorcycle",
        "oversized",
        "reserved",
        "visitor",
        name="spottype",
        create_type=False,
    )
    spottype.create(op.get_bind(), checkfirst=True)

    # ---------------------------------------- corporate_parking_facilities
    op.create_table(
        "corporate_parking_facilities",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(150), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("address_line1", sa.String(255), nullable=True),
        sa.Column("address_line2", sa.String(255), nullable=True),
        sa.Column("city", sa.String(100), nullable=True),
        sa.Column("state", sa.String(100), nullable=True),
        sa.Column("zip_code", sa.String(20), nullable=True),
        sa.Column("lat", sa.String(20), nullable=True),
        sa.Column("lng", sa.String(20), nullable=True),
        sa.Column(
            "facility_type",
            sa.Enum(
                "surface_lot",
                "parking_garage",
                "covered_structure",
                "underground",
                name="facilitytype",
            ),
            nullable=False,
        ),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_by_id", sa.Integer(), nullable=True),
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
            ["created_by_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "account_id", "name", name="uq_parking_facility_account_name"
        ),
    )
    op.create_index(
        "ix_parking_facility_account_id",
        "corporate_parking_facilities",
        ["account_id"],
    )
    op.create_index(
        "ix_parking_facility_is_active",
        "corporate_parking_facilities",
        ["is_active"],
    )
    op.create_index(
        "ix_parking_facility_created_at",
        "corporate_parking_facilities",
        ["created_at"],
    )

    # ---------------------------------------- corporate_parking_spots
    op.create_table(
        "corporate_parking_spots",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("facility_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("spot_identifier", sa.String(50), nullable=False),
        sa.Column(
            "spot_type",
            sa.Enum(
                "standard",
                "accessible",
                "ev_charging",
                "motorcycle",
                "oversized",
                "reserved",
                "visitor",
                name="spottype",
            ),
            nullable=False,
        ),
        sa.Column("floor_level", sa.String(20), nullable=True),
        sa.Column("is_assigned", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column(
            "created_at",
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
            ["facility_id"],
            ["corporate_parking_facilities.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "facility_id",
            "spot_identifier",
            name="uq_parking_spot_facility_identifier",
        ),
    )
    op.create_index(
        "ix_parking_spot_account_id",
        "corporate_parking_spots",
        ["account_id"],
    )
    op.create_index(
        "ix_parking_spot_facility_id",
        "corporate_parking_spots",
        ["facility_id"],
    )
    op.create_index(
        "ix_parking_spot_is_assigned",
        "corporate_parking_spots",
        ["is_assigned"],
    )
    op.create_index(
        "ix_parking_spot_spot_type",
        "corporate_parking_spots",
        ["spot_type"],
    )

    # ---------------------------------------- corporate_parking_assignments
    op.create_table(
        "corporate_parking_assignments",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("spot_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("member_id", sa.Integer(), nullable=True),
        sa.Column("assigned_by_id", sa.Integer(), nullable=True),
        sa.Column("permit_number", sa.String(100), nullable=True),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_by_id", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
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
            ["spot_id"],
            ["corporate_parking_spots.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["member_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["assigned_by_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["ended_by_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_parking_assignment_account_id",
        "corporate_parking_assignments",
        ["account_id"],
    )
    op.create_index(
        "ix_parking_assignment_spot_id",
        "corporate_parking_assignments",
        ["spot_id"],
    )
    op.create_index(
        "ix_parking_assignment_member_id",
        "corporate_parking_assignments",
        ["member_id"],
    )
    op.create_index(
        "ix_parking_assignment_is_active",
        "corporate_parking_assignments",
        ["is_active"],
    )


def downgrade() -> None:
    op.drop_table("corporate_parking_assignments")
    op.drop_table("corporate_parking_spots")
    op.drop_table("corporate_parking_facilities")

    op.execute("DROP TYPE IF EXISTS spottype")
    op.execute("DROP TYPE IF EXISTS facilitytype")
