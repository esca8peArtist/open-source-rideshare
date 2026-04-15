"""Add corporate approval chain tables.

Adds four tables supporting configurable multi-step approval workflows for
corporate rides.  Completely separate from the simpler CorporateRideApproval
feature.

Tables created:
  corporate_approval_chains              — named chain definition per account.
  corporate_approval_chain_steps         — ordered steps within a chain.
  corporate_approval_chain_requests      — running multi-step approval requests.
  corporate_approval_chain_step_decisions — per-step decisions by approvers.

Revision ID: c3d4e5f6a7b8
Revises:     b2c3d4e5f6a7
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from alembic import op


# ---------------------------------------------------------------------------
# Revision identifiers
# ---------------------------------------------------------------------------

revision = "c3d4e5f6a7b8"
down_revision = "b2c3d4e5f6a7"
branch_labels = None
depends_on = None


# ---------------------------------------------------------------------------
# Migration
# ---------------------------------------------------------------------------


def upgrade() -> None:
    # -----------------------------------------------------------------------
    # corporate_approval_chains
    # -----------------------------------------------------------------------
    op.create_table(
        "corporate_approval_chains",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("created_by_id", sa.Integer(), nullable=True),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("description", sa.String(length=300), nullable=True),
        sa.Column("min_cost_usd", sa.Numeric(10, 2), nullable=True),
        sa.Column(
            "applies_to_all_cost_centers",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "cost_center_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
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
            ["created_by_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index(
        "ix_corp_approval_chain_account_id",
        "corporate_approval_chains",
        ["account_id"],
    )
    op.create_index(
        "ix_corp_approval_chain_account_active",
        "corporate_approval_chains",
        ["account_id", "is_active"],
    )

    # -----------------------------------------------------------------------
    # corporate_approval_chain_steps
    # -----------------------------------------------------------------------
    op.create_table(
        "corporate_approval_chain_steps",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("chain_id", sa.Integer(), nullable=False),
        sa.Column("approver_user_id", sa.Integer(), nullable=True),
        sa.Column("step_order", sa.Integer(), nullable=False),
        sa.Column("approver_type", sa.String(length=20), nullable=False),
        sa.Column("timeout_hours", sa.Integer(), nullable=True),
        sa.Column(
            "escalation_action",
            sa.String(length=10),
            nullable=False,
            server_default=sa.text("'deny'"),
        ),
        sa.Column("description", sa.String(length=200), nullable=True),
        sa.ForeignKeyConstraint(
            ["chain_id"],
            ["corporate_approval_chains.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["approver_user_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "chain_id",
            "step_order",
            name="uq_corp_approval_chain_step_order",
        ),
    )

    op.create_index(
        "ix_corp_approval_chain_step_chain_id",
        "corporate_approval_chain_steps",
        ["chain_id"],
    )

    # -----------------------------------------------------------------------
    # corporate_approval_chain_requests
    # -----------------------------------------------------------------------
    op.create_table(
        "corporate_approval_chain_requests",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("chain_id", sa.Integer(), nullable=True),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("requester_id", sa.Integer(), nullable=True),
        sa.Column("cost_center_id", sa.Integer(), nullable=True),
        sa.Column("final_decision_by_id", sa.Integer(), nullable=True),
        sa.Column(
            "current_step_order",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("1"),
        ),
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default=sa.text("'pending'"),
        ),
        sa.Column("estimated_cost_usd", sa.Numeric(10, 2), nullable=True),
        sa.Column("purpose", sa.String(length=200), nullable=True),
        sa.Column("destination_description", sa.String(length=300), nullable=True),
        sa.Column(
            "final_decision_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["chain_id"],
            ["corporate_approval_chains.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["corporate_accounts_v2.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["requester_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["cost_center_id"],
            ["corporate_cost_centers.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["final_decision_by_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index(
        "ix_corp_approval_chain_req_account_id",
        "corporate_approval_chain_requests",
        ["account_id"],
    )
    op.create_index(
        "ix_corp_approval_chain_req_requester_id",
        "corporate_approval_chain_requests",
        ["requester_id"],
    )
    op.create_index(
        "ix_corp_approval_chain_req_account_status",
        "corporate_approval_chain_requests",
        ["account_id", "status"],
    )

    # -----------------------------------------------------------------------
    # corporate_approval_chain_step_decisions
    # -----------------------------------------------------------------------
    op.create_table(
        "corporate_approval_chain_step_decisions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("request_id", sa.Integer(), nullable=False),
        sa.Column("approver_id", sa.Integer(), nullable=True),
        sa.Column("step_order", sa.Integer(), nullable=False),
        sa.Column("decision", sa.String(length=10), nullable=False),
        sa.Column("note", sa.String(length=500), nullable=True),
        sa.Column(
            "decided_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["request_id"],
            ["corporate_approval_chain_requests.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["approver_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "request_id",
            "step_order",
            name="uq_corp_approval_step_decision",
        ),
    )

    op.create_index(
        "ix_corp_approval_step_decision_request_id",
        "corporate_approval_chain_step_decisions",
        ["request_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_corp_approval_step_decision_request_id",
        table_name="corporate_approval_chain_step_decisions",
    )
    op.drop_table("corporate_approval_chain_step_decisions")

    op.drop_index(
        "ix_corp_approval_chain_req_account_status",
        table_name="corporate_approval_chain_requests",
    )
    op.drop_index(
        "ix_corp_approval_chain_req_requester_id",
        table_name="corporate_approval_chain_requests",
    )
    op.drop_index(
        "ix_corp_approval_chain_req_account_id",
        table_name="corporate_approval_chain_requests",
    )
    op.drop_table("corporate_approval_chain_requests")

    op.drop_index(
        "ix_corp_approval_chain_step_chain_id",
        table_name="corporate_approval_chain_steps",
    )
    op.drop_table("corporate_approval_chain_steps")

    op.drop_index(
        "ix_corp_approval_chain_account_active",
        table_name="corporate_approval_chains",
    )
    op.drop_index(
        "ix_corp_approval_chain_account_id",
        table_name="corporate_approval_chains",
    )
    op.drop_table("corporate_approval_chains")
