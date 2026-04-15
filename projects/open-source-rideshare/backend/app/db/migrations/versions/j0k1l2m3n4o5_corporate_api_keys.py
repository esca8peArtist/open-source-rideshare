"""Create corporate_api_keys table.

Enterprise admins generate named API keys with configurable permission scopes.
External systems use these keys to pull data from the corporate account via
the REST API.  Only the SHA-256 hash of the key is stored.

Tables created:
  corporate_api_keys — named programmatic access credentials.

Revision ID: j0k1l2m3n4o5
Revises:     i9j0k1l2m3n4
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "j0k1l2m3n4o5"
down_revision: str = "i9j0k1l2m3n4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "corporate_api_keys",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("key_prefix", sa.Text(), nullable=False),
        sa.Column("key_hash", sa.Text(), nullable=False),
        sa.Column("scopes", postgresql.JSONB(), nullable=False),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.UniqueConstraint("key_hash", name="uq_corporate_api_keys_key_hash"),
    )

    op.create_index(
        "ix_corporate_api_keys_account_id",
        "corporate_api_keys",
        ["account_id"],
    )
    op.create_index(
        "ix_corporate_api_keys_key_hash",
        "corporate_api_keys",
        ["key_hash"],
    )
    op.create_index(
        "ix_corporate_api_keys_is_active",
        "corporate_api_keys",
        ["is_active"],
    )
    op.create_index(
        "ix_corporate_api_keys_account_active",
        "corporate_api_keys",
        ["account_id", "is_active"],
    )


def downgrade() -> None:
    op.drop_index("ix_corporate_api_keys_account_active", table_name="corporate_api_keys")
    op.drop_index("ix_corporate_api_keys_is_active", table_name="corporate_api_keys")
    op.drop_index("ix_corporate_api_keys_key_hash", table_name="corporate_api_keys")
    op.drop_index("ix_corporate_api_keys_account_id", table_name="corporate_api_keys")
    op.drop_table("corporate_api_keys")
