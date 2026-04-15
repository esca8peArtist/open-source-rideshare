"""Pydantic schemas for Corporate Department Management."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field, field_validator


# ---------------------------------------------------------------------------
# Department CRUD
# ---------------------------------------------------------------------------


class DepartmentCreate(BaseModel):
    """Payload for creating a department."""

    name: str = Field(..., min_length=1, max_length=200, description="Department name.")
    code: str = Field(
        ...,
        min_length=1,
        max_length=50,
        pattern=r"^[A-Za-z0-9_\-]+$",
        description="Short alphanumeric code, unique per account.  Stored uppercase.",
    )
    description: Optional[str] = Field(
        None, max_length=2000, description="Optional longer description."
    )
    cost_center_id: Optional[int] = Field(
        None, description="Optional FK to a cost center in this account."
    )
    monthly_budget: Optional[Decimal] = Field(
        None, gt=0, description="Optional monthly spend cap in USD."
    )

    @field_validator("code")
    @classmethod
    def uppercase_code(cls, v: str) -> str:
        return v.upper()


class DepartmentUpdate(BaseModel):
    """Payload for updating a department (all fields optional)."""

    name: Optional[str] = Field(None, min_length=1, max_length=200)
    code: Optional[str] = Field(
        None,
        min_length=1,
        max_length=50,
        pattern=r"^[A-Za-z0-9_\-]+$",
    )
    description: Optional[str] = Field(None, max_length=2000)
    cost_center_id: Optional[int] = None
    monthly_budget: Optional[Decimal] = Field(None, gt=0)

    @field_validator("code")
    @classmethod
    def uppercase_code(cls, v: Optional[str]) -> Optional[str]:
        return v.upper() if v is not None else v


class DepartmentResponse(BaseModel):
    """Full department representation."""

    id: int
    account_id: int
    name: str
    code: str
    description: Optional[str]
    cost_center_id: Optional[int]
    monthly_budget: Optional[Decimal]
    is_active: bool
    created_by_id: int
    member_count: int = Field(0, description="Number of active members in the department.")
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class DepartmentListResponse(BaseModel):
    """Paginated list of departments."""

    account_id: int
    total: int
    departments: list[DepartmentResponse]


# ---------------------------------------------------------------------------
# Department members
# ---------------------------------------------------------------------------


class AddMemberRequest(BaseModel):
    """Payload for adding a member to a department."""

    user_id: int = Field(..., description="ID of the account member to add.")
    is_department_head: bool = Field(
        False, description="Whether this member is the department head."
    )


class DepartmentMemberResponse(BaseModel):
    """Representation of a single department member."""

    department_id: int
    user_id: int
    is_department_head: bool
    added_by_id: int
    added_at: datetime

    model_config = {"from_attributes": True}


class DepartmentMembersResponse(BaseModel):
    """All members of a department."""

    department_id: int
    account_id: int
    total: int
    members: list[DepartmentMemberResponse]


# ---------------------------------------------------------------------------
# Department spend analytics
# ---------------------------------------------------------------------------


class DepartmentMemberSpend(BaseModel):
    """Per-member spend breakdown within a department."""

    user_id: int
    is_department_head: bool
    current_month_rides: int
    current_month_spend: Decimal


class DepartmentSpendResponse(BaseModel):
    """Spend analytics for a department for the current calendar month."""

    department_id: int
    account_id: int
    department_name: str
    current_month: str = Field(..., description="'YYYY-MM' string for the reported period.")
    total_rides: int
    total_spend: Decimal
    monthly_budget: Optional[Decimal]
    budget_utilization_pct: Optional[float] = Field(
        None,
        description="Current spend as a percentage of monthly_budget.  "
        "None when no budget is set.",
    )
    member_count: int
    members: list[DepartmentMemberSpend]
