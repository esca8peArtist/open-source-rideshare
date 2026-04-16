"""Add corporate_office_locations and corporate_office_memberships tables.

Enterprise corporate accounts can define named office locations and assign
employees (account members) to them.  At most one location per account may
be designated headquarters; each member may have at most one primary office.

Tables created:
  corporate_office_locations  — named physical offices per corporate account
  corporate_office_memberships — member-to-office assignments (many-to-many)

Revision ID: q9r0s1t2u3v4
Revises:     z5a6b7c8d9e0
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


# ---------------------------------------------------------------------------
# Revision identifiers
# ---------------------------------------------------------------------------

revision = "q9r0s1t2u3v4"
down_revision = "z5a6b7c8d9e0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # 1. corporate_office_locations table
    # ------------------------------------------------------------------
    op.create_table(
        "corporate_office_locations",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "account_id",
            sa.Integer(),
            sa.ForeignKey("corporate_accounts_v2.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("address_line1", sa.String(255), nullable=False),
        sa.Column("address_line2", sa.String(255), nullable=True),
        sa.Column("city", sa.String(100), nullable=False),
        sa.Column("state", sa.String(100), nullable=False),
        sa.Column("postal_code", sa.String(20), nullable=False),
        sa.Column("country", sa.String(100), nullable=False, server_default="US"),
        sa.Column("latitude", sa.Numeric(9, 6), nullable=True),
        sa.Column("longitude", sa.Numeric(9, 6), nullable=True),
        sa.Column(
            "default_cost_center_id",
            sa.Integer(),
            sa.ForeignKey("corporate_cost_centers.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "is_headquarters", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column(
            "is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")
        ),
        sa.Column(
            "created_by_id",
            sa.Integer(),
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

    # Unique constraint: name must be unique within an account.
    op.create_unique_constraint(
        "uq_corp_office_location_account_name",
        "corporate_office_locations",
        ["account_id", "name"],
    )

    # Indexes on office locations.
    op.create_index(
        "ix_corp_office_loc_account_id",
        "corporate_office_locations",
        ["account_id"],
    )
    op.create_index(
        "ix_corp_office_loc_account_active",
        "corporate_office_locations",
        ["account_id", "is_active"],
    )
    op.create_index(
        "ix_corp_office_loc_account_hq",
        "corporate_office_locations",
        ["account_id", "is_headquarters"],
    )

    # ------------------------------------------------------------------
    # 2. corporate_office_memberships table
    # ------------------------------------------------------------------
    op.create_table(
        "corporate_office_memberships",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "office_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("corporate_office_locations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "member_id",
            sa.Integer(),
            sa.ForeignKey("corporate_account_members.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "account_id",
            sa.Integer(),
            sa.ForeignKey("corporate_accounts_v2.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "is_primary", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column(
            "assigned_by_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    # Unique constraint: one row per (office, member).
    op.create_unique_constraint(
        "uq_corp_office_membership_office_member",
        "corporate_office_memberships",
        ["office_id", "member_id"],
    )

    # Indexes on office memberships.
    op.create_index(
        "ix_corp_office_mem_office_id",
        "corporate_office_memberships",
        ["office_id"],
    )
    op.create_index(
        "ix_corp_office_mem_member_id",
        "corporate_office_memberships",
        ["member_id"],
    )
    op.create_index(
        "ix_corp_office_mem_account_id",
        "corporate_office_memberships",
        ["account_id"],
    )
    op.create_index(
        "ix_corp_office_mem_member_primary",
        "corporate_office_memberships",
        ["member_id", "is_primary"],
    )


def downgrade() -> None:
    # Drop memberships table first (has FK to locations).
    op.drop_index("ix_corp_office_mem_member_primary", table_name="corporate_office_memberships")
    op.drop_index("ix_corp_office_mem_account_id", table_name="corporate_office_memberships")
    op.drop_index("ix_corp_office_mem_member_id", table_name="corporate_office_memberships")
    op.drop_index("ix_corp_office_mem_office_id", table_name="corporate_office_memberships")
    op.drop_constraint(
        "uq_corp_office_membership_office_member",
        "corporate_office_memberships",
        type_="unique",
    )
    op.drop_table("corporate_office_memberships")

    # Drop locations table.
    op.drop_index("ix_corp_office_loc_account_hq", table_name="corporate_office_locations")
    op.drop_index("ix_corp_office_loc_account_active", table_name="corporate_office_locations")
    op.drop_index("ix_corp_office_loc_account_id", table_name="corporate_office_locations")
    op.drop_constraint(
        "uq_corp_office_location_account_name",
        "corporate_office_locations",
        type_="unique",
    )
    op.drop_table("corporate_office_locations")
