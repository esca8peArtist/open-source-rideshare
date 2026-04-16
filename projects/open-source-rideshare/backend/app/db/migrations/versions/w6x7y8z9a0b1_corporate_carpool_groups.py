"""Add corporate_carpool_groups and corporate_carpool_members tables.

Corporate employees who share rides together for daily commutes can be
organised into carpool groups.  Each group can store an optional common
origin/destination, a departure time, and per-member pickup coordinates
with a sequencing order.

Tables created:
  corporate_carpool_groups   — named carpool groups within a corporate account
  corporate_carpool_members  — employees enrolled in a carpool group

Revision ID: w6x7y8z9a0b1
Revises:     v5w6x7y8z9a0
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "w6x7y8z9a0b1"
down_revision = "v5w6x7y8z9a0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ------------------------------------------------- corporate_carpool_groups
    op.create_table(
        "corporate_carpool_groups",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
        ),
        sa.Column(
            "account_id",
            sa.Integer,
            sa.ForeignKey("corporate_accounts_v2.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("max_members", sa.Integer, nullable=True),
        sa.Column("home_base_address", sa.String(500), nullable=True),
        sa.Column("home_base_lat", sa.Numeric(9, 6), nullable=True),
        sa.Column("home_base_lng", sa.Numeric(9, 6), nullable=True),
        sa.Column("destination_address", sa.String(500), nullable=True),
        sa.Column("destination_lat", sa.Numeric(9, 6), nullable=True),
        sa.Column("destination_lng", sa.Numeric(9, 6), nullable=True),
        sa.Column("departure_time", sa.String(5), nullable=True),
        sa.Column(
            "days_of_week",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("vehicle_type", sa.String(50), nullable=True),
        sa.Column(
            "cost_center_id",
            sa.Integer,
            sa.ForeignKey("corporate_cost_centers.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "trip_purpose_id",
            sa.Integer,
            sa.ForeignKey("corporate_trip_purposes.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "is_active",
            sa.Boolean,
            nullable=False,
            server_default=sa.true(),
        ),
        sa.Column(
            "created_by_id",
            sa.Integer,
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
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
        "ix_corp_carpool_group_account_id",
        "corporate_carpool_groups",
        ["account_id"],
    )
    op.create_index(
        "ix_corp_carpool_group_created_by",
        "corporate_carpool_groups",
        ["created_by_id"],
    )
    op.create_index(
        "ix_corp_carpool_group_account_active",
        "corporate_carpool_groups",
        ["account_id", "is_active"],
    )
    op.create_index(
        "ix_corp_carpool_group_account_name",
        "corporate_carpool_groups",
        ["account_id", "name"],
    )

    # ----------------------------------------------- corporate_carpool_members
    op.create_table(
        "corporate_carpool_members",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "carpool_group_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("corporate_carpool_groups.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "account_id",
            sa.Integer,
            sa.ForeignKey("corporate_accounts_v2.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "member_id",
            sa.Integer,
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("pickup_address", sa.String(500), nullable=True),
        sa.Column("pickup_lat", sa.Numeric(9, 6), nullable=True),
        sa.Column("pickup_lng", sa.Numeric(9, 6), nullable=True),
        sa.Column("pickup_sequence", sa.Integer, nullable=True),
        sa.Column(
            "is_active",
            sa.Boolean,
            nullable=False,
            server_default=sa.true(),
        ),
        sa.Column(
            "added_by_id",
            sa.Integer,
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column(
            "joined_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "carpool_group_id",
            "member_id",
            name="uq_carpool_group_member",
        ),
    )
    op.create_index(
        "ix_corp_carpool_member_group_id",
        "corporate_carpool_members",
        ["carpool_group_id"],
    )
    op.create_index(
        "ix_corp_carpool_member_account_id",
        "corporate_carpool_members",
        ["account_id"],
    )
    op.create_index(
        "ix_corp_carpool_member_member_id",
        "corporate_carpool_members",
        ["member_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_corp_carpool_member_member_id", table_name="corporate_carpool_members")
    op.drop_index("ix_corp_carpool_member_account_id", table_name="corporate_carpool_members")
    op.drop_index("ix_corp_carpool_member_group_id", table_name="corporate_carpool_members")
    op.drop_table("corporate_carpool_members")

    op.drop_index("ix_corp_carpool_group_account_name", table_name="corporate_carpool_groups")
    op.drop_index("ix_corp_carpool_group_account_active", table_name="corporate_carpool_groups")
    op.drop_index("ix_corp_carpool_group_created_by", table_name="corporate_carpool_groups")
    op.drop_index("ix_corp_carpool_group_account_id", table_name="corporate_carpool_groups")
    op.drop_table("corporate_carpool_groups")
