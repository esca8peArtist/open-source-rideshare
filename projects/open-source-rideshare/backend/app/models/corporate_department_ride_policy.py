"""Corporate Department-Level Ride Policy model.

Adds a middle tier to the corporate ride policy hierarchy:

  Account policy (base)
    └── Department policy (overrides account fields per department)
          └── Member policy override (highest precedence, per individual)

Each department can optionally define its own ride policy.  Override
fields are nullable — ``NULL`` means "inherit from the account policy".
Only one policy row is permitted per department (unique constraint).

When an employee belongs to multiple departments, each with an active
policy, the *most restrictive* value is applied per field:
  - ``require_purpose`` / ``business_hours_only``: True is more restrictive.
  - ``max_per_ride_usd``: lower value is more restrictive (minimum wins).
  - ``allowed_vehicle_categories``: intersection of all lists is applied
    (empty intersection → empty list → no vehicle type allowed).
  - ``approved_purposes``: intersection of all approved purpose lists.

Table: corporate_department_ride_policies
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


class CorporateDepartmentRidePolicy(Base):
    """Per-department ride policy override within a corporate account.

    Attributes:
        account_id:                  FK to corporate_accounts_v2 (CASCADE).
        department_id:               FK to corporate_departments (CASCADE).
                                     Unique — one policy per department.
        set_by_id:                   FK to users — admin who last set/updated
                                     this policy (SET NULL on user deletion).
        allowed_vehicle_categories:  JSONB list of allowed vehicle types.
                                     NULL = inherit from account policy.
        max_per_ride_usd:            Per-ride cost cap for this department.
                                     NULL = inherit from account policy.
        require_purpose:             Whether employees in this department must
                                     supply a trip purpose.  NULL = inherit.
        approved_purposes:           JSONB list of allowed purpose codes.
                                     NULL = inherit.
        business_hours_only:         Time-of-day restriction for this
                                     department.  NULL = inherit.
        notes:                       Optional admin-facing annotation (max 500
                                     chars) explaining why this policy exists.
        is_active:                   Soft-delete flag.  Inactive policies are
                                     not applied during effective-policy
                                     resolution.
        created_at:                  Immutable creation timestamp.
        updated_at:                  Last-modified timestamp (auto-updated).

    Constraints:
        UniqueConstraint on department_id — one row per department.
    """

    __tablename__ = "corporate_department_ride_policies"
    __table_args__ = (
        UniqueConstraint(
            "department_id",
            name="uq_corp_dept_ride_policy_department",
        ),
        Index("ix_corp_dept_ride_policy_account_id", "account_id"),
        Index("ix_corp_dept_ride_policy_department_id", "department_id"),
        Index(
            "ix_corp_dept_ride_policy_account_active",
            "account_id",
            "is_active",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    account_id: Mapped[int] = mapped_column(
        ForeignKey("corporate_accounts_v2.id", ondelete="CASCADE"),
        nullable=False,
    )
    department_id: Mapped[int] = mapped_column(
        ForeignKey("corporate_departments.id", ondelete="CASCADE"),
        nullable=False,
    )
    set_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Override fields — NULL means "inherit from account policy"
    allowed_vehicle_categories: Mapped[list[str] | None] = mapped_column(
        JSONB, nullable=True
    )
    max_per_ride_usd: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 2), nullable=True
    )
    require_purpose: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    approved_purposes: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    business_hours_only: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    notes: Mapped[str | None] = mapped_column(String(500), nullable=True)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    # Relationships
    account = relationship("BusinessAccount", foreign_keys=[account_id])
    department = relationship("CorporateDepartment", foreign_keys=[department_id])
    set_by = relationship("User", foreign_keys=[set_by_id])
