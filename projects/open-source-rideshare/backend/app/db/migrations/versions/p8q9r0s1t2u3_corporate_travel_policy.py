"""corporate_travel_policy

Versioned travel policy documents for corporate accounts with employee
acknowledgement tracking.  One policy may be active per account at a time.
Employees acknowledge the active policy; acknowledgements are append-only.

Tables:
  corporate_travel_policies        — versioned policy documents
  corporate_policy_acknowledgements — per-employee acknowledgement records

Revision ID: p8q9r0s1t2u3
Revises: o7p8q9r0s1t2
Create Date: 2026-04-16 00:00:00.000000

"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "p8q9r0s1t2u3"
down_revision = "o7p8q9r0s1t2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ---- corporate_travel_policies ----
    op.create_table(
        "corporate_travel_policies",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "account_id",
            sa.Integer(),
            sa.ForeignKey("corporate_accounts_v2.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("version_number", sa.String(50), nullable=False, server_default="1"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column(
            "requires_acknowledgement",
            sa.Boolean(),
            nullable=False,
            server_default="true",
        ),
        sa.Column("effective_date", sa.DateTime(timezone=True), nullable=True),
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
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_corp_travel_policy_account_id",
        "corporate_travel_policies",
        ["account_id"],
    )
    op.create_index(
        "ix_corp_travel_policy_is_active",
        "corporate_travel_policies",
        ["is_active"],
    )
    op.create_index(
        "ix_corp_travel_policy_created_at",
        "corporate_travel_policies",
        ["created_at"],
    )

    # ---- corporate_policy_acknowledgements ----
    op.create_table(
        "corporate_policy_acknowledgements",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "policy_id",
            sa.Integer(),
            sa.ForeignKey("corporate_travel_policies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "member_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "account_id",
            sa.Integer(),
            sa.ForeignKey("corporate_accounts_v2.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "acknowledged_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "policy_id",
            "member_id",
            name="uq_corp_policy_ack_policy_member",
        ),
    )
    op.create_index(
        "ix_corp_policy_ack_policy_id",
        "corporate_policy_acknowledgements",
        ["policy_id"],
    )
    op.create_index(
        "ix_corp_policy_ack_member_id",
        "corporate_policy_acknowledgements",
        ["member_id"],
    )
    op.create_index(
        "ix_corp_policy_ack_account_id",
        "corporate_policy_acknowledgements",
        ["account_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_corp_policy_ack_account_id",
        table_name="corporate_policy_acknowledgements",
    )
    op.drop_index(
        "ix_corp_policy_ack_member_id",
        table_name="corporate_policy_acknowledgements",
    )
    op.drop_index(
        "ix_corp_policy_ack_policy_id",
        table_name="corporate_policy_acknowledgements",
    )
    op.drop_table("corporate_policy_acknowledgements")

    op.drop_index(
        "ix_corp_travel_policy_created_at",
        table_name="corporate_travel_policies",
    )
    op.drop_index(
        "ix_corp_travel_policy_is_active",
        table_name="corporate_travel_policies",
    )
    op.drop_index(
        "ix_corp_travel_policy_account_id",
        table_name="corporate_travel_policies",
    )
    op.drop_table("corporate_travel_policies")
