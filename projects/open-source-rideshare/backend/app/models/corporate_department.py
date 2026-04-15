"""Corporate Department model.

Companies can organise their employees into named departments (Engineering,
Sales, Marketing, etc.).  Each department may optionally be linked to a cost
center and carry its own monthly budget cap.

CorporateDepartment       — one row per named department within an account
CorporateDepartmentMember — junction: employee ↔ department with optional head flag
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


class CorporateDepartment(Base):
    """A named organisational unit within a corporate account.

    Attributes:
        account_id: FK to corporate_accounts_v2 (CASCADE delete).
        name: Human-readable label (e.g. "Engineering", "Sales – EMEA").
        code: Short alphanumeric identifier, unique per account (e.g. "ENG").
            Normalised to uppercase on write.  Used in reports.
        description: Optional longer description.
        cost_center_id: Optional FK to corporate_cost_centers.  When set,
            rides tagged to this department inherit that cost centre.
        monthly_budget: Optional monthly spend cap for the department.
            NULL means no cap.
        is_active: Soft-delete flag.  Inactive departments cannot receive new
            members but existing members and historical rides are preserved.
        created_by_id: FK to users — admin who created the department.
        created_at: Creation timestamp.
        updated_at: Last modification timestamp.
    """

    __tablename__ = "corporate_departments"
    __table_args__ = (
        UniqueConstraint(
            "account_id", "code", name="uq_corp_dept_account_code"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    account_id: Mapped[int] = mapped_column(
        ForeignKey("corporate_accounts_v2.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    code: Mapped[str] = mapped_column(String(50), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    cost_center_id: Mapped[int | None] = mapped_column(
        ForeignKey("corporate_cost_centers.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    monthly_budget: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 2), nullable=True
    )

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    created_by_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"),
        nullable=False,
        index=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    account = relationship("BusinessAccount", foreign_keys=[account_id])
    cost_center = relationship("CorporateCostCenter", foreign_keys=[cost_center_id])
    created_by = relationship("User", foreign_keys=[created_by_id])
    dept_members: Mapped[list["CorporateDepartmentMember"]] = relationship(
        "CorporateDepartmentMember",
        back_populates="department",
        cascade="all, delete-orphan",
    )


class CorporateDepartmentMember(Base):
    """Association between a corporate department and a platform user (employee).

    Attributes:
        department_id: FK to corporate_departments (CASCADE delete).
        user_id: FK to users — the employee.
        is_department_head: Whether this employee is the department head.
        added_by_id: FK to users — admin who added the member.
        added_at: Timestamp when the membership was created.
    """

    __tablename__ = "corporate_department_members"
    __table_args__ = (
        UniqueConstraint(
            "department_id", "user_id", name="uq_corp_dept_member"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    department_id: Mapped[int] = mapped_column(
        ForeignKey("corporate_departments.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"),
        nullable=False,
        index=True,
    )

    is_department_head: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )

    added_by_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"),
        nullable=False,
    )

    added_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    department: Mapped["CorporateDepartment"] = relationship(
        "CorporateDepartment", back_populates="dept_members"
    )
    user = relationship("User", foreign_keys=[user_id])
    added_by = relationship("User", foreign_keys=[added_by_id])
