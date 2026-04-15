"""Add rider cooperative membership, voting, and dividend tables.

Completes the multi-stakeholder cooperative model: riders can now join as
member-owners, vote on platform proposals, and receive quarterly surplus
distributions — the counterpart to the driver dividend system.

Tables created:
  rider_coop_memberships  — one row per rider; tracks status and lifetime metrics
  rider_coop_votes        — rider-member votes on cooperative proposals
  rider_dividend_shares   — per-rider allocation within a dividend period

Revision ID: c6d7e8f9a0b1
Revises: b5c6d7e8f9a0
Create Date: 2026-04-15
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "c6d7e8f9a0b1"
down_revision = "b5c6d7e8f9a0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- rider_coop_memberships -------------------------------------------
    op.create_table(
        "rider_coop_memberships",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("rider_id", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            sa.Enum("applicant", "member", "suspended", "resigned", name="ridermemberstatus"),
            nullable=False,
            server_default="applicant",
        ),
        sa.Column("lifetime_rides", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("voting_weight", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("reviewed_by_id", sa.Integer(), nullable=True),
        sa.Column("suspension_reason", sa.Text(), nullable=True),
        sa.Column(
            "applied_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("suspended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resigned_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["rider_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["reviewed_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("rider_id", name="uq_rider_coop_membership_rider"),
    )
    op.create_index(
        "ix_rider_coop_memberships_rider_id", "rider_coop_memberships", ["rider_id"]
    )
    op.create_index(
        "ix_rider_coop_memberships_status", "rider_coop_memberships", ["status"]
    )

    # --- rider_coop_votes -------------------------------------------------
    op.create_table(
        "rider_coop_votes",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("proposal_id", sa.Integer(), nullable=False),
        sa.Column("membership_id", sa.Integer(), nullable=False),
        sa.Column("rider_id", sa.Integer(), nullable=False),
        sa.Column(
            "choice",
            sa.Enum("yes", "no", "abstain", name="ridervotechoice"),
            nullable=False,
        ),
        sa.Column("voting_weight", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "voted_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["proposal_id"], ["driver_proposals.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["membership_id"], ["rider_coop_memberships.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["rider_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "proposal_id", "membership_id", name="uq_rider_vote_proposal"
        ),
    )
    op.create_index(
        "ix_rider_coop_votes_proposal_id", "rider_coop_votes", ["proposal_id"]
    )
    op.create_index(
        "ix_rider_coop_votes_membership_id", "rider_coop_votes", ["membership_id"]
    )
    op.create_index(
        "ix_rider_coop_votes_rider_id", "rider_coop_votes", ["rider_id"]
    )

    # --- rider_dividend_shares --------------------------------------------
    op.create_table(
        "rider_dividend_shares",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("dividend_id", sa.Integer(), nullable=False),
        sa.Column("membership_id", sa.Integer(), nullable=False),
        sa.Column("rider_id", sa.Integer(), nullable=False),
        sa.Column("qualifying_rides", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("share_pct", sa.Numeric(7, 4), nullable=False, server_default="0"),
        sa.Column("amount_usd", sa.Numeric(10, 2), nullable=False, server_default="0"),
        sa.Column(
            "status",
            sa.Enum("pending", "paid", "cancelled", name="riderdividendsharestatus"),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["dividend_id"], ["cooperative_dividends.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["membership_id"], ["rider_coop_memberships.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["rider_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "dividend_id", "membership_id", name="uq_rider_dividend_share"
        ),
    )
    op.create_index(
        "ix_rider_dividend_shares_dividend_id", "rider_dividend_shares", ["dividend_id"]
    )
    op.create_index(
        "ix_rider_dividend_shares_membership_id",
        "rider_dividend_shares",
        ["membership_id"],
    )
    op.create_index(
        "ix_rider_dividend_shares_rider_id", "rider_dividend_shares", ["rider_id"]
    )
    op.create_index(
        "ix_rider_dividend_shares_status", "rider_dividend_shares", ["status"]
    )


def downgrade() -> None:
    op.drop_index("ix_rider_dividend_shares_status", table_name="rider_dividend_shares")
    op.drop_index(
        "ix_rider_dividend_shares_rider_id", table_name="rider_dividend_shares"
    )
    op.drop_index(
        "ix_rider_dividend_shares_membership_id", table_name="rider_dividend_shares"
    )
    op.drop_index(
        "ix_rider_dividend_shares_dividend_id", table_name="rider_dividend_shares"
    )
    op.drop_table("rider_dividend_shares")

    op.drop_index("ix_rider_coop_votes_rider_id", table_name="rider_coop_votes")
    op.drop_index("ix_rider_coop_votes_membership_id", table_name="rider_coop_votes")
    op.drop_index("ix_rider_coop_votes_proposal_id", table_name="rider_coop_votes")
    op.drop_table("rider_coop_votes")

    op.drop_index("ix_rider_coop_memberships_status", table_name="rider_coop_memberships")
    op.drop_index(
        "ix_rider_coop_memberships_rider_id", table_name="rider_coop_memberships"
    )
    op.drop_table("rider_coop_memberships")

    op.execute("DROP TYPE IF EXISTS riderdividendsharestatus")
    op.execute("DROP TYPE IF EXISTS ridervotechoice")
    op.execute("DROP TYPE IF EXISTS ridermemberstatus")
