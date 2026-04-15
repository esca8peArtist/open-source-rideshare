"""Add cooperative board elections.

Democratic governance tooling for the cooperative: driver-owners elect
representatives to named board seats through a formal, transparent process.

Tables created:
  cooperative_board_seats   — named seats with term configuration
  board_elections           — per-seat elections with lifecycle stages
  board_candidacies         — driver self-nominations, admin-reviewed
  board_election_votes      — secret ballots (one per driver per election)

Enum types created:
  electionstatus            — draft / nominations_open / nominations_closed /
                              voting_open / tallied / certified / cancelled
  candidacystatus           — pending / approved / rejected / withdrawn

Revision ID: k3l4m5n6o7p8
Revises: j3k4l5m6n7o8
Create Date: 2026-04-15
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "k3l4m5n6o7p8"
down_revision: str = "j3k4l5m6n7o8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Enum types
    electionstatus = postgresql.ENUM(
        "draft",
        "nominations_open",
        "nominations_closed",
        "voting_open",
        "tallied",
        "certified",
        "cancelled",
        name="electionstatus",
        create_type=False,
    )
    electionstatus.create(op.get_bind(), checkfirst=True)

    candidacystatus = postgresql.ENUM(
        "pending",
        "approved",
        "rejected",
        "withdrawn",
        name="candidacystatus",
        create_type=False,
    )
    candidacystatus.create(op.get_bind(), checkfirst=True)

    # cooperative_board_seats
    op.create_table(
        "cooperative_board_seats",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False, unique=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("term_months", sa.Integer(), nullable=False, server_default="12"),
        sa.Column("max_consecutive_terms", sa.Integer(), nullable=True),
        sa.Column(
            "min_lifetime_rides_to_run",
            sa.Integer(),
            nullable=False,
            server_default="100",
        ),
        sa.Column(
            "current_holder_id",
            sa.Integer(),
            sa.ForeignKey("driver_profiles.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("holder_term_ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
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
        "ix_board_seats_current_holder", "cooperative_board_seats", ["current_holder_id"]
    )

    # board_elections
    op.create_table(
        "board_elections",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "seat_id",
            sa.Integer(),
            sa.ForeignKey("cooperative_board_seats.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "draft",
                "nominations_open",
                "nominations_closed",
                "voting_open",
                "tallied",
                "certified",
                "cancelled",
                name="electionstatus",
            ),
            nullable=False,
            server_default="draft",
        ),
        sa.Column("nominations_open_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("nominations_close_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("voting_opens_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("voting_closes_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "min_lifetime_rides_to_vote",
            sa.Integer(),
            nullable=False,
            server_default="50",
        ),
        sa.Column(
            "winner_id",
            sa.Integer(),
            sa.ForeignKey("driver_profiles.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("certified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("certification_notes", sa.Text(), nullable=True),
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
    op.create_index("ix_board_elections_seat_id", "board_elections", ["seat_id"])
    op.create_index("ix_board_elections_status", "board_elections", ["status"])

    # board_candidacies
    op.create_table(
        "board_candidacies",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "election_id",
            sa.Integer(),
            sa.ForeignKey("board_elections.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "driver_profile_id",
            sa.Integer(),
            sa.ForeignKey("driver_profiles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("statement", sa.Text(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "pending",
                "approved",
                "rejected",
                "withdrawn",
                name="candidacystatus",
            ),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("admin_notes", sa.Text(), nullable=True),
        sa.Column("vote_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "applied_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint(
            "election_id",
            "driver_profile_id",
            name="uq_board_candidacy_election_driver",
        ),
    )
    op.create_index(
        "ix_board_candidacies_election_id", "board_candidacies", ["election_id"]
    )
    op.create_index(
        "ix_board_candidacies_driver_id", "board_candidacies", ["driver_profile_id"]
    )
    op.create_index(
        "ix_board_candidacies_status", "board_candidacies", ["status"]
    )

    # board_election_votes
    op.create_table(
        "board_election_votes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "election_id",
            sa.Integer(),
            sa.ForeignKey("board_elections.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "candidacy_id",
            sa.Integer(),
            sa.ForeignKey("board_candidacies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "voter_driver_profile_id",
            sa.Integer(),
            sa.ForeignKey("driver_profiles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "voted_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "election_id",
            "voter_driver_profile_id",
            name="uq_board_vote_election_voter",
        ),
    )
    op.create_index(
        "ix_board_votes_election_id", "board_election_votes", ["election_id"]
    )
    op.create_index(
        "ix_board_votes_candidacy_id", "board_election_votes", ["candidacy_id"]
    )
    op.create_index(
        "ix_board_votes_voter_id",
        "board_election_votes",
        ["voter_driver_profile_id"],
    )


def downgrade() -> None:
    op.drop_table("board_election_votes")
    op.drop_table("board_candidacies")
    op.drop_table("board_elections")
    op.drop_table("cooperative_board_seats")
    op.execute("DROP TYPE IF EXISTS candidacystatus")
    op.execute("DROP TYPE IF EXISTS electionstatus")
