"""corporate_transport_preferences

Personal transport preference profiles for corporate account employees.
One row per (account, member): preferred vehicle type, accessibility needs,
home address + lat/lng, default cost centre + trip purpose, pickup note,
SMS notify number.

Revision ID: o7p8q9r0s1t2
Revises: n6o7p8q9r0s1
Create Date: 2026-04-16 00:00:00.000000

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "o7p8q9r0s1t2"
down_revision = "n6o7p8q9r0s1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "corporate_employee_transport_preferences",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("member_id", sa.Integer(), nullable=False),
        sa.Column("preferred_vehicle_type", sa.String(length=50), nullable=True),
        sa.Column(
            "accessibility_needs",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("home_address", sa.String(length=255), nullable=True),
        sa.Column(
            "home_latitude", sa.Numeric(precision=9, scale=6), nullable=True
        ),
        sa.Column(
            "home_longitude", sa.Numeric(precision=9, scale=6), nullable=True
        ),
        sa.Column("default_cost_center_id", sa.Integer(), nullable=True),
        sa.Column("default_trip_purpose_id", sa.Integer(), nullable=True),
        sa.Column("preferred_pickup_note", sa.Text(), nullable=True),
        sa.Column("notify_sms_number", sa.String(length=20), nullable=True),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
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
            ["member_id"],
            ["users.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["default_cost_center_id"],
            ["corporate_cost_centers.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["default_trip_purpose_id"],
            ["corporate_trip_purposes.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "account_id",
            "member_id",
            name="uq_corp_transport_pref_account_member",
        ),
    )

    op.create_index(
        "ix_corp_transport_pref_account_id",
        "corporate_employee_transport_preferences",
        ["account_id"],
    )
    op.create_index(
        "ix_corp_transport_pref_member_id",
        "corporate_employee_transport_preferences",
        ["member_id"],
    )
    op.create_index(
        "ix_corp_transport_pref_is_active",
        "corporate_employee_transport_preferences",
        ["is_active"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_corp_transport_pref_is_active",
        table_name="corporate_employee_transport_preferences",
    )
    op.drop_index(
        "ix_corp_transport_pref_member_id",
        table_name="corporate_employee_transport_preferences",
    )
    op.drop_index(
        "ix_corp_transport_pref_account_id",
        table_name="corporate_employee_transport_preferences",
    )
    op.drop_table("corporate_employee_transport_preferences")
