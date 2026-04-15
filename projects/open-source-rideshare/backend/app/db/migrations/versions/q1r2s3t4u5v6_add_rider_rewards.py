"""add rider rewards

Revision ID: q1r2s3t4u5v6
Revises: p1q2r3s4t5u6
Create Date: 2026-04-15

Creates two tables for the rider loyalty rewards programme:
  rider_reward_accounts      — one row per rider; running balance + lifetime totals
  rider_reward_transactions  — immutable audit log of every points change
"""

from alembic import op
import sqlalchemy as sa

revision = "q1r2s3t4u5v6"
down_revision = "p1q2r3s4t5u6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # -- rider_reward_accounts --------------------------------------------------
    op.create_table(
        "rider_reward_accounts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("rider_id", sa.Integer(), nullable=False),
        sa.Column("points_balance", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("lifetime_earned", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("lifetime_redeemed", sa.Integer(), nullable=False, server_default="0"),
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
        sa.ForeignKeyConstraint(["rider_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("rider_id"),
    )
    op.create_index("ix_rider_reward_accounts_rider_id", "rider_reward_accounts", ["rider_id"])

    # -- rider_reward_transactions ----------------------------------------------
    reward_type_enum = sa.Enum(
        "earn", "redeem", "admin_adjust", "expiry",
        name="rewardtransactiontype",
    )
    op.create_table(
        "rider_reward_transactions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("rider_id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("ride_id", sa.Integer(), nullable=True),
        sa.Column("transaction_type", reward_type_enum, nullable=False),
        sa.Column("points_delta", sa.Integer(), nullable=False),
        sa.Column("balance_after", sa.Integer(), nullable=False),
        sa.Column("description", sa.String(255), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["rider_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["account_id"], ["rider_reward_accounts.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["ride_id"], ["rides.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_rider_reward_transactions_rider_id",
        "rider_reward_transactions",
        ["rider_id"],
    )
    op.create_index(
        "ix_rider_reward_transactions_account_id",
        "rider_reward_transactions",
        ["account_id"],
    )
    op.create_index(
        "ix_rider_reward_transactions_created_at",
        "rider_reward_transactions",
        ["created_at"],
    )


def downgrade() -> None:
    op.drop_table("rider_reward_transactions")
    op.drop_table("rider_reward_accounts")
    op.execute("DROP TYPE IF EXISTS rewardtransactiontype")
