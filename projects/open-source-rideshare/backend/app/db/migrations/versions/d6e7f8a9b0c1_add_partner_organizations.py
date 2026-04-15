"""Add community partner organizations, credit grants, and credit usages.

Tables created:
  partner_organizations  — community org accounts (hospitals, NGOs, social services, etc.)
  partner_credit_grants  — per-rider credit allocations issued by an org
  partner_credit_usages  — records of grant funds applied to completed rides

Enum types created:
  partnerorgtype    — healthcare / social_services / education / transit_authority /
                      nonprofit / government / other
  partnerorgstatus  — pending / active / suspended / terminated
  partnercreditstatus — active / exhausted / expired / revoked

Revision ID: d6e7f8a9b0c1
Revises: c6d7e8f9a0b1
Create Date: 2026-04-15
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "d6e7f8a9b0c1"
down_revision = "c6d7e8f9a0b1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # Enum types
    # ------------------------------------------------------------------
    partnerorgtype_enum = sa.Enum(
        "healthcare", "social_services", "education",
        "transit_authority", "nonprofit", "government", "other",
        name="partnerorgtype",
    )
    partnerorgtype_enum.create(op.get_bind(), checkfirst=True)

    partnerorgstatus_enum = sa.Enum(
        "pending", "active", "suspended", "terminated",
        name="partnerorgstatus",
    )
    partnerorgstatus_enum.create(op.get_bind(), checkfirst=True)

    partnercreditstatus_enum = sa.Enum(
        "active", "exhausted", "expired", "revoked",
        name="partnercreditstatus",
    )
    partnercreditstatus_enum.create(op.get_bind(), checkfirst=True)

    # ------------------------------------------------------------------
    # partner_organizations
    # ------------------------------------------------------------------
    op.create_table(
        "partner_organizations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("org_type", partnerorgtype_enum, nullable=False),
        sa.Column("status", partnerorgstatus_enum, nullable=False, server_default="pending"),
        sa.Column("contact_name", sa.String(255), nullable=False),
        sa.Column("contact_email", sa.String(255), nullable=False),
        sa.Column("contact_phone", sa.String(50), nullable=True),
        sa.Column("partner_admin_user_id", sa.Integer(), nullable=True),
        sa.Column("monthly_credit_limit_usd", sa.Numeric(12, 2), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("admin_note", sa.Text(), nullable=True),
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
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("suspended_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["partner_admin_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_partner_organizations_status", "partner_organizations", ["status"])
    op.create_index("ix_partner_organizations_org_type", "partner_organizations", ["org_type"])
    op.create_index(
        "ix_partner_organizations_partner_admin_user_id",
        "partner_organizations",
        ["partner_admin_user_id"],
    )

    # ------------------------------------------------------------------
    # partner_credit_grants
    # ------------------------------------------------------------------
    op.create_table(
        "partner_credit_grants",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("organization_id", sa.Integer(), nullable=False),
        sa.Column("rider_id", sa.Integer(), nullable=False),
        sa.Column("issued_by_admin_id", sa.Integer(), nullable=True),
        sa.Column("status", partnercreditstatus_enum, nullable=False, server_default="active"),
        sa.Column("amount_usd", sa.Numeric(10, 2), nullable=False),
        sa.Column("amount_used_usd", sa.Numeric(10, 2), nullable=False, server_default="0.00"),
        sa.Column("per_ride_cap_usd", sa.Numeric(10, 2), nullable=True),
        sa.Column("purpose", sa.String(500), nullable=True),
        sa.Column("expiry_date", sa.Date(), nullable=True),
        sa.Column("revoked_by_admin_id", sa.Integer(), nullable=True),
        sa.Column("revoke_reason", sa.Text(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
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
            ["organization_id"], ["partner_organizations.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["rider_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["issued_by_admin_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["revoked_by_admin_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_partner_credit_grants_organization_id",
        "partner_credit_grants",
        ["organization_id"],
    )
    op.create_index("ix_partner_credit_grants_rider_id", "partner_credit_grants", ["rider_id"])
    op.create_index("ix_partner_credit_grants_status", "partner_credit_grants", ["status"])
    op.create_index(
        "ix_partner_credit_grants_expiry_date", "partner_credit_grants", ["expiry_date"]
    )

    # ------------------------------------------------------------------
    # partner_credit_usages
    # ------------------------------------------------------------------
    op.create_table(
        "partner_credit_usages",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("grant_id", sa.Integer(), nullable=False),
        sa.Column("ride_id", sa.Integer(), nullable=False),
        sa.Column("amount_applied_usd", sa.Numeric(10, 2), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["grant_id"], ["partner_credit_grants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["ride_id"], ["rides.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("grant_id", "ride_id", name="uq_partner_credit_usage_grant_ride"),
    )
    op.create_index("ix_partner_credit_usages_grant_id", "partner_credit_usages", ["grant_id"])
    op.create_index("ix_partner_credit_usages_ride_id", "partner_credit_usages", ["ride_id"])


def downgrade() -> None:
    op.drop_index("ix_partner_credit_usages_ride_id", "partner_credit_usages")
    op.drop_index("ix_partner_credit_usages_grant_id", "partner_credit_usages")
    op.drop_table("partner_credit_usages")

    op.drop_index("ix_partner_credit_grants_expiry_date", "partner_credit_grants")
    op.drop_index("ix_partner_credit_grants_status", "partner_credit_grants")
    op.drop_index("ix_partner_credit_grants_rider_id", "partner_credit_grants")
    op.drop_index("ix_partner_credit_grants_organization_id", "partner_credit_grants")
    op.drop_table("partner_credit_grants")

    op.drop_index("ix_partner_organizations_partner_admin_user_id", "partner_organizations")
    op.drop_index("ix_partner_organizations_org_type", "partner_organizations")
    op.drop_index("ix_partner_organizations_status", "partner_organizations")
    op.drop_table("partner_organizations")

    sa.Enum(name="partnercreditstatus").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="partnerorgstatus").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="partnerorgtype").drop(op.get_bind(), checkfirst=True)
