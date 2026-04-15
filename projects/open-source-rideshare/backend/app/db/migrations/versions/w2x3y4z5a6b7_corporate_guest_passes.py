"""Add corporate_guest_passes table and guest_pass_id column to rides.

Corporate employees can issue limited-use booking tokens (guest passes) to
non-employees such as clients, candidates, or visitors.  Guests use the
token to book a ride billed to the corporate account — no corporate login
is required on the guest side.

Tables created:
  corporate_guest_passes — per-account guest pass records with token, expiry,
                           usage limits, and optional budget/purpose/cost-center

Columns added to rides:
  guest_pass_id — nullable UUID FK to corporate_guest_passes.id

Revision ID: w2x3y4z5a6b7
Revises:     v2w3x4y5z6a7
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "w2x3y4z5a6b7"
down_revision: str = "v2w3x4y5z6a7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create the GuestPassStatus enum type
    guest_pass_status = postgresql.ENUM(
        "active", "exhausted", "expired", "revoked",
        name="guestpassstatus",
        create_type=True,
    )
    guest_pass_status.create(op.get_bind(), checkfirst=True)

    # corporate_guest_passes table
    op.create_table(
        "corporate_guest_passes",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("created_by_employee_id", sa.Integer(), nullable=False),
        sa.Column(
            "token",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("label", sa.String(200), nullable=False),
        sa.Column("max_uses", sa.Integer(), nullable=True),
        sa.Column("uses_remaining", sa.Integer(), nullable=True),
        sa.Column("max_ride_budget_usd", sa.Numeric(10, 2), nullable=True),
        sa.Column("trip_purpose_id", sa.Integer(), nullable=True),
        sa.Column("cost_center_id", sa.Integer(), nullable=True),
        sa.Column(
            "valid_from",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "active", "exhausted", "expired", "revoked",
                name="guestpassstatus",
                create_type=False,
            ),
            nullable=False,
            server_default="active",
        ),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_by_id", sa.Integer(), nullable=True),
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
        sa.ForeignKeyConstraint(["created_by_employee_id"], ["users.id"]),
        sa.ForeignKeyConstraint(
            ["trip_purpose_id"], ["corporate_trip_purposes.id"]
        ),
        sa.ForeignKeyConstraint(
            ["cost_center_id"], ["corporate_cost_centers.id"]
        ),
        sa.ForeignKeyConstraint(["revoked_by_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token", name="uq_corporate_guest_pass_token"),
    )

    op.create_index(
        "ix_corporate_guest_passes_account_id",
        "corporate_guest_passes",
        ["account_id"],
    )
    op.create_index(
        "ix_corporate_guest_passes_token",
        "corporate_guest_passes",
        ["token"],
    )

    # Add guest_pass_id column to rides
    op.add_column(
        "rides",
        sa.Column(
            "guest_pass_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("corporate_guest_passes.id"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_rides_guest_pass_id",
        "rides",
        ["guest_pass_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_rides_guest_pass_id", table_name="rides")
    op.drop_column("rides", "guest_pass_id")

    op.drop_index(
        "ix_corporate_guest_passes_token", table_name="corporate_guest_passes"
    )
    op.drop_index(
        "ix_corporate_guest_passes_account_id", table_name="corporate_guest_passes"
    )
    op.drop_table("corporate_guest_passes")

    # Drop the enum type
    op.execute("DROP TYPE IF EXISTS guestpassstatus")
