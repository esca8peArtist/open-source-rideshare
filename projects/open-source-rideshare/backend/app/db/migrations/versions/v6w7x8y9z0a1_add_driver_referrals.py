"""add driver_referrals table and driver_referral_code column

Revision ID: v6w7x8y9z0a1
Revises: u5v6w7x8y9z0
Create Date: 2026-04-18
"""
from alembic import op
import sqlalchemy as sa

revision = "v6w7x8y9z0a1"
down_revision = "u5v6w7x8y9z0"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "driver_profiles",
        sa.Column("driver_referral_code", sa.String(20), nullable=True),
    )
    op.create_index(
        "ix_driver_profiles_driver_referral_code",
        "driver_profiles",
        ["driver_referral_code"],
        unique=True,
    )

    op.create_table(
        "driver_referrals",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("referrer_driver_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("referee_driver_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("milestone_rides", sa.Integer(), nullable=False, server_default="10"),
        sa.Column("bonus_amount", sa.Float(), nullable=False, server_default="50.0"),
        sa.Column(
            "status",
            sa.Enum("pending", "awarded", "paid", name="driverreferralstatus"),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("awarded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("paid_on_payout_id", sa.Integer(), sa.ForeignKey("driver_payouts.id"), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("referrer_driver_id", "referee_driver_id", name="uq_driver_referral_pair"),
    )
    op.create_index("ix_driver_referrals_referrer", "driver_referrals", ["referrer_driver_id"])
    op.create_index("ix_driver_referrals_referee", "driver_referrals", ["referee_driver_id"])


def downgrade():
    op.drop_index("ix_driver_referrals_referee", table_name="driver_referrals")
    op.drop_index("ix_driver_referrals_referrer", table_name="driver_referrals")
    op.drop_table("driver_referrals")
    op.execute("DROP TYPE IF EXISTS driverreferralstatus")

    op.drop_index("ix_driver_profiles_driver_referral_code", table_name="driver_profiles")
    op.drop_column("driver_profiles", "driver_referral_code")
