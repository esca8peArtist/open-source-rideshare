"""Corporate preferred driver pool.

Enterprise accounts curate a pool of preferred, vetted drivers.  The
matching engine surfaces pool members first when dispatching corporate
rides — giving companies continuity and quality assurance.

Tables created:
  corporate_driver_pool — one row per (account_id, driver_id) pair.

Revision ID: p7q8r9s0t1u2
Revises:     o6p7q8r9s0t1
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "p7q8r9s0t1u2"
down_revision: str = "o6p7q8r9s0t1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "corporate_driver_pool",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("driver_id", sa.Integer(), nullable=False),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column("notes", sa.String(500), nullable=True),
        sa.Column("added_by_id", sa.Integer(), nullable=False),
        sa.Column(
            "added_at",
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
            ["driver_id"],
            ["driver_profiles.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["added_by_id"],
            ["users.id"],
        ),
        sa.UniqueConstraint(
            "account_id",
            "driver_id",
            name="uq_corp_driver_pool_account_driver",
        ),
    )

    op.create_index(
        "ix_corp_driver_pool_account_id",
        "corporate_driver_pool",
        ["account_id"],
    )
    op.create_index(
        "ix_corp_driver_pool_driver_id",
        "corporate_driver_pool",
        ["driver_id"],
    )
    op.create_index(
        "ix_corp_driver_pool_active",
        "corporate_driver_pool",
        ["account_id", "is_active"],
        postgresql_where=sa.text("is_active = true"),
    )


def downgrade() -> None:
    op.drop_index("ix_corp_driver_pool_active", table_name="corporate_driver_pool")
    op.drop_index("ix_corp_driver_pool_driver_id", table_name="corporate_driver_pool")
    op.drop_index("ix_corp_driver_pool_account_id", table_name="corporate_driver_pool")
    op.drop_table("corporate_driver_pool")
