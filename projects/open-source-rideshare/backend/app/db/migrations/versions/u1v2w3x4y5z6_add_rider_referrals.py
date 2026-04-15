"""add rider referrals

Revision ID: u1v2w3x4y5z6
Revises: t1u2v3w4x5y6
Create Date: 2026-04-15

Creates two tables:
  rider_referral_codes  — one unique code per rider (generated on first request)
  rider_referrals       — each referral relationship (referrer → referred)
"""

from alembic import op
import sqlalchemy as sa

revision = "u1v2w3x4y5z6"
down_revision = "t1u2v3w4x5y6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    referral_status_enum = sa.Enum(
        "pending",
        "qualified",
        "rewarded",
        name="riderreferralstatus",
    )

    op.create_table(
        "rider_referral_codes",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("code", sa.String(16), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_rider_referral_codes_user_id", "rider_referral_codes", ["user_id"], unique=True)
    op.create_index("ix_rider_referral_codes_code", "rider_referral_codes", ["code"], unique=True)

    op.create_table(
        "rider_referrals",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("referrer_user_id", sa.Integer, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("referred_user_id", sa.Integer, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("code_used", sa.String(16), nullable=False),
        sa.Column(
            "status",
            referral_status_enum,
            nullable=False,
            server_default="pending",
        ),
        sa.Column("first_ride_id", sa.Integer, sa.ForeignKey("rides.id"), nullable=True),
        sa.Column("referrer_reward_amount", sa.Float, nullable=False, server_default="0"),
        sa.Column("referred_discount_amount", sa.Float, nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("qualified_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_rider_referrals_referrer_user_id", "rider_referrals", ["referrer_user_id"])
    op.create_index("ix_rider_referrals_referred_user_id", "rider_referrals", ["referred_user_id"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_rider_referrals_referred_user_id", table_name="rider_referrals")
    op.drop_index("ix_rider_referrals_referrer_user_id", table_name="rider_referrals")
    op.drop_table("rider_referrals")

    op.drop_index("ix_rider_referral_codes_code", table_name="rider_referral_codes")
    op.drop_index("ix_rider_referral_codes_user_id", table_name="rider_referral_codes")
    op.drop_table("rider_referral_codes")

    sa.Enum(name="riderreferralstatus").drop(op.get_bind())
