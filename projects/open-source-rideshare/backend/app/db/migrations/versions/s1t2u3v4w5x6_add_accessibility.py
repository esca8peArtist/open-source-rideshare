"""add accessibility and WAV support

Revision ID: s1t2u3v4w5x6
Revises: r1s2t3u4v5w6
Create Date: 2026-04-15

Creates two tables:
  rider_accessibility_profiles  — rider self-reported accessibility needs
  driver_wav_certifications     — driver WAV capability with admin verification workflow
"""

from alembic import op
import sqlalchemy as sa

revision = "s1t2u3v4w5x6"
down_revision = "r1s2t3u4v5w6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    wav_status_enum = sa.Enum(
        "pending", "verified", "rejected", "expired",
        name="wavcertificationstatus",
    )

    op.create_table(
        "rider_accessibility_profiles",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("rider_id", sa.Integer(), nullable=False),
        sa.Column("needs_wav", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("has_mobility_device", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("visual_impairment", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("hearing_impairment", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("other_needs", sa.Text(), nullable=True),
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
    op.create_index(
        "ix_rider_accessibility_profiles_rider_id",
        "rider_accessibility_profiles",
        ["rider_id"],
    )

    op.create_table(
        "driver_wav_certifications",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("driver_id", sa.Integer(), nullable=False),
        sa.Column("status", wav_status_enum, nullable=False, server_default="pending"),
        sa.Column("vehicle_make", sa.String(100), nullable=True),
        sa.Column("vehicle_model", sa.String(100), nullable=True),
        sa.Column("vehicle_year", sa.Integer(), nullable=True),
        sa.Column("certification_document_url", sa.String(500), nullable=True),
        sa.Column("certification_number", sa.String(100), nullable=True),
        sa.Column(
            "submitted_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("verified_by_admin_id", sa.Integer(), nullable=True),
        sa.Column("admin_note", sa.Text(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["driver_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["verified_by_admin_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("driver_id"),
    )
    op.create_index(
        "ix_driver_wav_certifications_driver_id",
        "driver_wav_certifications",
        ["driver_id"],
    )
    op.create_index(
        "ix_driver_wav_certifications_status",
        "driver_wav_certifications",
        ["status"],
    )


def downgrade() -> None:
    op.drop_table("driver_wav_certifications")
    op.drop_table("rider_accessibility_profiles")
    op.execute("DROP TYPE IF EXISTS wavcertificationstatus")
