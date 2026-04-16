"""Corporate member fine-grained permissions.

Enterprise accounts grant specific named permission scopes to individual
members beyond the binary admin/member role.

Tables created:
  corporate_member_permissions — one row per (account_id, member_id, scope).

Revision ID: k0l1m2n3o4p5
Revises:     j9k0l1m2n3o4
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "k0l1m2n3o4p5"
down_revision: str = "j9k0l1m2n3o4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TYPE permissionscope AS ENUM (
            'billing_admin',
            'hr_admin',
            'fleet_manager',
            'report_viewer',
            'booking_approver',
            'data_exporter',
            'sso_admin'
        )
        """
    )

    op.create_table(
        "corporate_member_permissions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("member_id", sa.Integer(), nullable=False),
        sa.Column(
            "permission_scope",
            sa.Enum(
                "billing_admin",
                "hr_admin",
                "fleet_manager",
                "report_viewer",
                "booking_approver",
                "data_exporter",
                "sso_admin",
                name="permissionscope",
            ),
            nullable=False,
        ),
        sa.Column("granted_by_id", sa.Integer(), nullable=True),
        sa.Column(
            "granted_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column("notes", sa.String(500), nullable=True),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["corporate_accounts_v2.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["member_id"],
            ["users.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["granted_by_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint(
            "account_id",
            "member_id",
            "permission_scope",
            name="uq_corp_member_permission_account_member_scope",
        ),
    )

    op.create_index(
        "ix_corp_member_permission_account_id",
        "corporate_member_permissions",
        ["account_id"],
    )
    op.create_index(
        "ix_corp_member_permission_member_id",
        "corporate_member_permissions",
        ["member_id"],
    )
    op.create_index(
        "ix_corp_member_permission_active",
        "corporate_member_permissions",
        ["account_id", "is_active"],
        postgresql_where=sa.text("is_active = true"),
    )


def downgrade() -> None:
    op.drop_index(
        "ix_corp_member_permission_active",
        table_name="corporate_member_permissions",
    )
    op.drop_index(
        "ix_corp_member_permission_member_id",
        table_name="corporate_member_permissions",
    )
    op.drop_index(
        "ix_corp_member_permission_account_id",
        table_name="corporate_member_permissions",
    )
    op.drop_table("corporate_member_permissions")
    op.execute("DROP TYPE IF EXISTS permissionscope")
