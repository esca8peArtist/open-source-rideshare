"""Add corporate shuttle pass management tables.

Enterprise accounts define shuttle pass types (ride count, validity, price)
and issue pre-paid passes to individual employees.  Each ride redemption is
recorded in an append-only usage ledger.

Tables created:
  corporate_shuttle_pass_types   — admin-defined pass templates
  corporate_shuttle_passes       — issued passes for specific members
  corporate_shuttle_pass_usages  — append-only redemption ledger

Revision ID: i8j9k0l1m2n3
Revises:     h7i8j9k0l1m2
Create Date: 2026-04-16
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "i8j9k0l1m2n3"
down_revision = "h7i8j9k0l1m2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ---------------------------------------- corporate_shuttle_pass_types
    op.create_table(
        "corporate_shuttle_pass_types",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("ride_count", sa.Integer(), nullable=False),
        sa.Column("validity_days", sa.Integer(), nullable=True),
        sa.Column("price_usd", sa.Numeric(10, 2), nullable=True),
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
            "account_id",
            "name",
            name="uq_shuttle_pass_type_account_name",
        ),
    )
    op.create_index(
        "ix_shuttle_pass_type_account_id",
        "corporate_shuttle_pass_types",
        ["account_id"],
    )
    op.create_index(
        "ix_shuttle_pass_type_is_active",
        "corporate_shuttle_pass_types",
        ["is_active"],
    )
    op.create_index(
        "ix_shuttle_pass_type_created_at",
        "corporate_shuttle_pass_types",
        ["created_at"],
    )

    # ---------------------------------------- corporate_shuttle_passes
    op.create_table(
        "corporate_shuttle_passes",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("pass_type_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("member_id", sa.Integer(), nullable=True),
        sa.Column("rides_total", sa.Integer(), nullable=False),
        sa.Column("rides_used", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "issued_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("issued_by_id", sa.Integer(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
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
            ["pass_type_id"],
            ["corporate_shuttle_pass_types.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["corporate_accounts_v2.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["member_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["issued_by_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_shuttle_pass_pass_type_id",
        "corporate_shuttle_passes",
        ["pass_type_id"],
    )
    op.create_index(
        "ix_shuttle_pass_account_id",
        "corporate_shuttle_passes",
        ["account_id"],
    )
    op.create_index(
        "ix_shuttle_pass_member_id",
        "corporate_shuttle_passes",
        ["member_id"],
    )
    op.create_index(
        "ix_shuttle_pass_is_active",
        "corporate_shuttle_passes",
        ["is_active"],
    )

    # ---------------------------------------- corporate_shuttle_pass_usages
    op.create_table(
        "corporate_shuttle_pass_usages",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("pass_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("member_id", sa.Integer(), nullable=True),
        sa.Column(
            "booking_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column(
            "redeemed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("rides_remaining_after", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["pass_id"],
            ["corporate_shuttle_passes.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["corporate_accounts_v2.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["member_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["booking_id"],
            ["corporate_shuttle_bookings.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_shuttle_pass_usage_pass_id",
        "corporate_shuttle_pass_usages",
        ["pass_id"],
    )
    op.create_index(
        "ix_shuttle_pass_usage_account_id",
        "corporate_shuttle_pass_usages",
        ["account_id"],
    )
    op.create_index(
        "ix_shuttle_pass_usage_member_id",
        "corporate_shuttle_pass_usages",
        ["member_id"],
    )
    op.create_index(
        "ix_shuttle_pass_usage_redeemed_at",
        "corporate_shuttle_pass_usages",
        ["redeemed_at"],
    )


def downgrade() -> None:
    op.drop_table("corporate_shuttle_pass_usages")
    op.drop_table("corporate_shuttle_passes")
    op.drop_table("corporate_shuttle_pass_types")
