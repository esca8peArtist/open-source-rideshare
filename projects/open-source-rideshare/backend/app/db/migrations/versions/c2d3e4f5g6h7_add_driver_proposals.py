"""add cooperative governance: driver proposals and voting

Revision ID: c2d3e4f5g6h7
Revises: b1c2d3e4f5g6
Create Date: 2026-04-15

Creates two tables:
  driver_proposals — platform proposals submitted by drivers or admins
  driver_votes     — one vote per (driver, proposal) pair
"""

from alembic import op
import sqlalchemy as sa

revision = "c2d3e4f5g6h7"
down_revision = "b1c2d3e4f5g6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "driver_proposals",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("description", sa.Text, nullable=False),
        sa.Column(
            "proposal_type",
            sa.Enum(
                "fee_rate_change",
                "bonus_structure",
                "policy_change",
                "platform_feature",
                "general",
                name="proposaltype",
            ),
            nullable=False,
        ),
        sa.Column(
            "created_by_user_id",
            sa.Integer,
            sa.ForeignKey("users.id"),
            nullable=True,
        ),
        sa.Column(
            "created_by_admin",
            sa.Boolean,
            nullable=False,
            server_default="false",
        ),
        sa.Column(
            "status",
            sa.Enum(
                "draft",
                "open",
                "closed",
                "passed",
                "failed",
                "withdrawn",
                "implemented",
                name="proposalstatus",
            ),
            nullable=False,
            server_default="draft",
        ),
        sa.Column("voting_opens_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("voting_closes_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "min_lifetime_rides_to_vote",
            sa.Integer,
            nullable=False,
            server_default="50",
        ),
        sa.Column("votes_for", sa.Integer, nullable=False, server_default="0"),
        sa.Column("votes_against", sa.Integer, nullable=False, server_default="0"),
        sa.Column("votes_abstain", sa.Integer, nullable=False, server_default="0"),
        sa.Column(
            "result_threshold_pct",
            sa.Numeric(5, 4),
            nullable=False,
            server_default="0.5001",
        ),
        sa.Column("implementation_notes", sa.Text, nullable=True),
        sa.Column("implemented_at", sa.DateTime(timezone=True), nullable=True),
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
        "ix_driver_proposals_status",
        "driver_proposals",
        ["status"],
    )
    op.create_index(
        "ix_driver_proposals_created_by_user_id",
        "driver_proposals",
        ["created_by_user_id"],
    )
    op.create_index(
        "ix_driver_proposals_voting_closes_at",
        "driver_proposals",
        ["voting_closes_at"],
    )

    op.create_table(
        "driver_votes",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "proposal_id",
            sa.Integer,
            sa.ForeignKey("driver_proposals.id"),
            nullable=False,
        ),
        sa.Column(
            "driver_profile_id",
            sa.Integer,
            sa.ForeignKey("driver_profiles.id"),
            nullable=False,
        ),
        sa.Column(
            "vote",
            sa.Enum("yes", "no", "abstain", name="votechoice"),
            nullable=False,
        ),
        sa.Column(
            "voted_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "proposal_id",
            "driver_profile_id",
            name="uq_driver_vote_proposal_driver",
        ),
    )
    op.create_index(
        "ix_driver_votes_proposal_id",
        "driver_votes",
        ["proposal_id"],
    )
    op.create_index(
        "ix_driver_votes_driver_profile_id",
        "driver_votes",
        ["driver_profile_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_driver_votes_driver_profile_id", table_name="driver_votes")
    op.drop_index("ix_driver_votes_proposal_id", table_name="driver_votes")
    op.drop_table("driver_votes")

    op.drop_index("ix_driver_proposals_voting_closes_at", table_name="driver_proposals")
    op.drop_index("ix_driver_proposals_created_by_user_id", table_name="driver_proposals")
    op.drop_index("ix_driver_proposals_status", table_name="driver_proposals")
    op.drop_table("driver_proposals")

    op.execute("DROP TYPE IF EXISTS votechoice")
    op.execute("DROP TYPE IF EXISTS proposalstatus")
    op.execute("DROP TYPE IF EXISTS proposaltype")
