"""initial schema

Revision ID: d7cb1904c75e
Revises:
Create Date: 2026-04-11 17:47:43.327452

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import geoalchemy2


revision: str = 'd7cb1904c75e'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")

    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("phone", sa.String(20), nullable=False, unique=True, index=True),
        sa.Column("email", sa.String(255), nullable=True, unique=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("role", sa.Enum("rider", "driver", "admin", name="userrole"), nullable=False, server_default="rider"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("phone_verified", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "driver_profiles",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False, unique=True),
        sa.Column("vehicle_type", sa.String(50), nullable=False),
        sa.Column("vehicle_make", sa.String(100), nullable=False),
        sa.Column("vehicle_model", sa.String(100), nullable=False),
        sa.Column("vehicle_year", sa.Integer(), nullable=False),
        sa.Column("vehicle_color", sa.String(50), nullable=False),
        sa.Column("license_plate", sa.String(20), nullable=False),
        sa.Column("license_number", sa.String(50), nullable=False),
        sa.Column("insurance_policy", sa.String(100), nullable=True),
        sa.Column("background_check_status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("rating_avg", sa.Float(), nullable=False, server_default="5.0"),
        sa.Column("total_trips", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_online", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("is_approved", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("current_location", geoalchemy2.Geometry(geometry_type="POINT", srid=4326), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "rides",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("rider_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False, index=True),
        sa.Column("driver_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True, index=True),
        sa.Column(
            "status",
            sa.Enum("requested", "matched", "driver_en_route", "arrived", "in_progress", "completed", "cancelled", name="ridestatus"),
            nullable=False,
            server_default="requested",
        ),
        sa.Column("pickup_location", geoalchemy2.Geometry(geometry_type="POINT", srid=4326), nullable=False),
        sa.Column("dropoff_location", geoalchemy2.Geometry(geometry_type="POINT", srid=4326), nullable=False),
        sa.Column("pickup_address", sa.String(500), nullable=False),
        sa.Column("dropoff_address", sa.String(500), nullable=False),
        sa.Column("estimated_fare", sa.Float(), nullable=False),
        sa.Column("actual_fare", sa.Float(), nullable=True),
        sa.Column("distance_km", sa.Float(), nullable=True),
        sa.Column("duration_min", sa.Float(), nullable=True),
        sa.Column("tip_amount", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("requested_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("matched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rider_rating", sa.Integer(), nullable=True),
        sa.Column("driver_rating", sa.Integer(), nullable=True),
        sa.Column("cancellation_reason", sa.Text(), nullable=True),
    )

    op.create_table(
        "payments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("ride_id", sa.Integer(), sa.ForeignKey("rides.id"), nullable=False, unique=True),
        sa.Column("stripe_payment_intent_id", sa.String(255), nullable=True),
        sa.Column("amount", sa.Float(), nullable=False),
        sa.Column("platform_fee", sa.Float(), nullable=False),
        sa.Column("driver_payout", sa.Float(), nullable=False),
        sa.Column("status", sa.Enum("pending", "completed", "failed", "refunded", name="paymentstatus"), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("payments")
    op.drop_table("rides")
    op.drop_table("driver_profiles")
    op.drop_table("users")
    op.execute("DROP TYPE IF EXISTS paymentstatus")
    op.execute("DROP TYPE IF EXISTS ridestatus")
    op.execute("DROP TYPE IF EXISTS userrole")
