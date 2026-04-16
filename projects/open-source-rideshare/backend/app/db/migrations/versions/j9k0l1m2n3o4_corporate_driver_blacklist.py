"""Corporate driver blacklist.

Enterprise accounts can block specific drivers from being dispatched on
their corporate rides.  This is the inverse of the preferred driver pool.

Tables created:
  corporate_driver_blacklist — one row per (account_id, driver_id) pair.

Revision ID: j9k0l1m2n3o4
Revises:     i8j9k0l1m2n3
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "j9k0l1m2n3o4"
down_revision: str = "i8j9k0l1m2n3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "corporate_driver_blacklist",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("driver_id", sa.Integer(), nullable=False),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column("reason", sa.String(500), nullable=True),
        sa.Column("blacklisted_by_id", sa.Integer(), nullable=True),
        sa.Column(
            "blacklisted_at",
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
            ["blacklisted_by_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint(
            "account_id",
            "driver_id",
            name="uq_corp_driver_blacklist_account_driver",
        ),
    )

    op.create_index(
        "ix_corp_driver_blacklist_account_id",
        "corporate_driver_blacklist",
        ["account_id"],
    )
    op.create_index(
        "ix_corp_driver_blacklist_driver_id",
        "corporate_driver_blacklist",
        ["driver_id"],
    )
    op.create_index(
        "ix_corp_driver_blacklist_active",
        "corporate_driver_blacklist",
        ["account_id", "is_active"],
        postgresql_where=sa.text("is_active = true"),
    )


def downgrade() -> None:
    op.drop_index(
        "ix_corp_driver_blacklist_active",
        table_name="corporate_driver_blacklist",
    )
    op.drop_index(
        "ix_corp_driver_blacklist_driver_id",
        table_name="corporate_driver_blacklist",
    )
    op.drop_index(
        "ix_corp_driver_blacklist_account_id",
        table_name="corporate_driver_blacklist",
    )
    op.drop_table("corporate_driver_blacklist")
