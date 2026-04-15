"""Add corporate_custom_fields and corporate_ride_custom_field_values tables.

Enterprise accounts can define custom metadata fields (project codes, client billing
codes, etc.) that employees fill in on corporate rides.

Tables created:
  corporate_custom_fields               — field schema definitions per account
  corporate_ride_custom_field_values    — per-ride values for each custom field

Revision ID: f6g7h8i9j0k1
Revises:     e5f6g7h8i9j0
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# ---------------------------------------------------------------------------
# Metadata
# ---------------------------------------------------------------------------

revision = "f6g7h8i9j0k1"
down_revision = "e5f6g7h8i9j0"
branch_labels = None
depends_on = None


# ---------------------------------------------------------------------------
# Upgrade
# ---------------------------------------------------------------------------


def upgrade() -> None:
    # Enum type for field data types
    custom_field_type = postgresql.ENUM(
        "text", "number", "dropdown", "checkbox",
        name="custom_field_type",
        create_type=True,
    )
    custom_field_type.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "corporate_custom_fields",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "account_id",
            sa.Integer(),
            sa.ForeignKey("corporate_accounts_v2.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("label", sa.String(200), nullable=False),
        sa.Column("field_key", sa.String(100), nullable=False),
        sa.Column(
            "field_type",
            sa.Enum(
                "text", "number", "dropdown", "checkbox",
                name="custom_field_type",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("dropdown_options", postgresql.JSONB(), nullable=True),
        sa.Column("is_required", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("max_length", sa.Integer(), nullable=True),
        sa.Column("display_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column(
            "created_by_id",
            sa.Integer(),
            sa.ForeignKey("users.id"),
            nullable=False,
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
        sa.UniqueConstraint("account_id", "field_key", name="uq_custom_field_account_key"),
    )
    op.create_index(
        "ix_corporate_custom_fields_account_id",
        "corporate_custom_fields",
        ["account_id"],
    )
    op.create_index(
        "ix_corporate_custom_fields_is_active",
        "corporate_custom_fields",
        ["is_active"],
    )
    op.create_index(
        "ix_corporate_custom_fields_display_order",
        "corporate_custom_fields",
        ["display_order"],
    )

    op.create_table(
        "corporate_ride_custom_field_values",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "field_id",
            sa.Integer(),
            sa.ForeignKey("corporate_custom_fields.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "ride_id",
            sa.Integer(),
            sa.ForeignKey("rides.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column(
            "set_by_id",
            sa.Integer(),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column(
            "set_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("field_id", "ride_id", name="uq_ride_custom_field_value"),
    )
    op.create_index(
        "ix_corp_ride_custom_field_values_field_id",
        "corporate_ride_custom_field_values",
        ["field_id"],
    )
    op.create_index(
        "ix_corp_ride_custom_field_values_ride_id",
        "corporate_ride_custom_field_values",
        ["ride_id"],
    )


# ---------------------------------------------------------------------------
# Downgrade
# ---------------------------------------------------------------------------


def downgrade() -> None:
    op.drop_index(
        "ix_corp_ride_custom_field_values_ride_id",
        table_name="corporate_ride_custom_field_values",
    )
    op.drop_index(
        "ix_corp_ride_custom_field_values_field_id",
        table_name="corporate_ride_custom_field_values",
    )
    op.drop_table("corporate_ride_custom_field_values")

    op.drop_index(
        "ix_corporate_custom_fields_display_order",
        table_name="corporate_custom_fields",
    )
    op.drop_index(
        "ix_corporate_custom_fields_is_active",
        table_name="corporate_custom_fields",
    )
    op.drop_index(
        "ix_corporate_custom_fields_account_id",
        table_name="corporate_custom_fields",
    )
    op.drop_table("corporate_custom_fields")

    sa.Enum(name="custom_field_type").drop(op.get_bind(), checkfirst=True)
