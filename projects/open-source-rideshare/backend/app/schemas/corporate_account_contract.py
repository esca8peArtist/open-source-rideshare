"""Pydantic v2 schemas for the Corporate Account Contract feature.

Tracks the service agreement between the platform and a corporate client,
including term dates, committed volume, account manager details, and the
lifecycle (draft → active → expired / terminated).

Public surface
--------------
ContractCreate       — fields for creating a new draft contract.
ContractUpdate       — partial update (all fields optional).
TerminateRequest     — payload for the terminate action.
ContractResponse     — full contract representation returned by the API.
ContractListResponse — paginated list of contracts.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, EmailStr, field_validator, model_validator


class ContractCreate(BaseModel):
    """Fields for creating a new draft corporate account contract.

    Attributes:
        contract_number: Optional unique reference.  Auto-generated when omitted.
        contract_start_date: Inclusive start of the agreement term.
        contract_end_date: Inclusive end of the agreement term; null = open-ended.
        auto_renews: Whether the contract auto-renews near expiry.
        renewal_term_days: Duration of each renewal cycle in days.
        renewal_notice_days: Days before expiry that renewal notice is sent.
        committed_monthly_rides: Optional minimum ride commitment per month.
        committed_monthly_spend_usd: Optional minimum spend commitment in USD.
        negotiated_discount_pct: Discount percentage for this account (0–100).
        account_manager_name: Name of the assigned platform account manager.
        account_manager_email: Email of the assigned platform account manager.
        contract_document_url: URL to the signed contract document.
        notes: Free-text internal notes.
        signed_by_name: Name of the corporate signatory.
        signed_at: When the contract was signed.
    """

    contract_number: Optional[str] = None
    contract_start_date: date
    contract_end_date: Optional[date] = None
    auto_renews: bool = False
    renewal_term_days: Optional[int] = None
    renewal_notice_days: int = 30
    committed_monthly_rides: Optional[int] = None
    committed_monthly_spend_usd: Optional[Decimal] = None
    negotiated_discount_pct: Optional[Decimal] = None
    account_manager_name: Optional[str] = None
    account_manager_email: Optional[EmailStr] = None
    contract_document_url: Optional[str] = None
    notes: Optional[str] = None
    signed_by_name: Optional[str] = None
    signed_at: Optional[datetime] = None

    @field_validator("renewal_term_days")
    @classmethod
    def renewal_term_days_ge_1(cls, v: Optional[int]) -> Optional[int]:
        if v is not None and v < 1:
            raise ValueError("renewal_term_days must be >= 1")
        return v

    @field_validator("renewal_notice_days")
    @classmethod
    def renewal_notice_days_ge_1(cls, v: int) -> int:
        if v < 1:
            raise ValueError("renewal_notice_days must be >= 1")
        return v

    @field_validator("committed_monthly_rides")
    @classmethod
    def committed_monthly_rides_ge_0(cls, v: Optional[int]) -> Optional[int]:
        if v is not None and v < 0:
            raise ValueError("committed_monthly_rides must be >= 0")
        return v

    @field_validator("committed_monthly_spend_usd")
    @classmethod
    def committed_monthly_spend_ge_0(cls, v: Optional[Decimal]) -> Optional[Decimal]:
        if v is not None and v < 0:
            raise ValueError("committed_monthly_spend_usd must be >= 0")
        return v

    @field_validator("negotiated_discount_pct")
    @classmethod
    def discount_pct_range(cls, v: Optional[Decimal]) -> Optional[Decimal]:
        if v is not None and (v < 0 or v > 100):
            raise ValueError("negotiated_discount_pct must be between 0 and 100")
        return v

    @model_validator(mode="after")
    def end_date_after_start_date(self) -> "ContractCreate":
        if (
            self.contract_end_date is not None
            and self.contract_end_date <= self.contract_start_date
        ):
            raise ValueError("contract_end_date must be after contract_start_date")
        return self


class ContractUpdate(BaseModel):
    """Partial update payload for a corporate account contract.

    All fields are optional.  Only draft contracts may be updated via PATCH;
    terminated and expired contracts are immutable (the service layer enforces
    this with HTTP 409).
    """

    contract_number: Optional[str] = None
    contract_start_date: Optional[date] = None
    contract_end_date: Optional[date] = None
    auto_renews: Optional[bool] = None
    renewal_term_days: Optional[int] = None
    renewal_notice_days: Optional[int] = None
    committed_monthly_rides: Optional[int] = None
    committed_monthly_spend_usd: Optional[Decimal] = None
    negotiated_discount_pct: Optional[Decimal] = None
    account_manager_name: Optional[str] = None
    account_manager_email: Optional[EmailStr] = None
    contract_document_url: Optional[str] = None
    notes: Optional[str] = None
    signed_by_name: Optional[str] = None
    signed_at: Optional[datetime] = None

    @field_validator("renewal_term_days")
    @classmethod
    def renewal_term_days_ge_1(cls, v: Optional[int]) -> Optional[int]:
        if v is not None and v < 1:
            raise ValueError("renewal_term_days must be >= 1")
        return v

    @field_validator("renewal_notice_days")
    @classmethod
    def renewal_notice_days_ge_1(cls, v: Optional[int]) -> Optional[int]:
        if v is not None and v < 1:
            raise ValueError("renewal_notice_days must be >= 1")
        return v

    @field_validator("committed_monthly_rides")
    @classmethod
    def committed_monthly_rides_ge_0(cls, v: Optional[int]) -> Optional[int]:
        if v is not None and v < 0:
            raise ValueError("committed_monthly_rides must be >= 0")
        return v

    @field_validator("committed_monthly_spend_usd")
    @classmethod
    def committed_monthly_spend_ge_0(cls, v: Optional[Decimal]) -> Optional[Decimal]:
        if v is not None and v < 0:
            raise ValueError("committed_monthly_spend_usd must be >= 0")
        return v

    @field_validator("negotiated_discount_pct")
    @classmethod
    def discount_pct_range(cls, v: Optional[Decimal]) -> Optional[Decimal]:
        if v is not None and (v < 0 or v > 100):
            raise ValueError("negotiated_discount_pct must be between 0 and 100")
        return v


class TerminateRequest(BaseModel):
    """Request body for the contract termination action.

    Attributes:
        reason: Mandatory reason for terminating the contract early.
    """

    reason: str

    @field_validator("reason")
    @classmethod
    def reason_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("reason must not be empty")
        return v


class ContractResponse(BaseModel):
    """Full contract representation returned by the API.

    Includes all persisted fields plus the status as a plain string so that
    API consumers do not need to know the internal enum names.
    """

    model_config = {"from_attributes": True}

    id: int
    account_id: int
    contract_number: str
    status: str
    contract_start_date: date
    contract_end_date: Optional[date]
    auto_renews: bool
    renewal_term_days: Optional[int]
    renewal_notice_days: int
    committed_monthly_rides: Optional[int]
    committed_monthly_spend_usd: Optional[Decimal]
    negotiated_discount_pct: Optional[Decimal]
    account_manager_name: Optional[str]
    account_manager_email: Optional[str]
    contract_document_url: Optional[str]
    notes: Optional[str]
    signed_by_name: Optional[str]
    signed_at: Optional[datetime]
    activated_at: Optional[datetime]
    terminated_at: Optional[datetime]
    termination_reason: Optional[str]
    created_by_id: Optional[int]
    updated_by_id: Optional[int]
    created_at: datetime
    updated_at: datetime


class ContractListResponse(BaseModel):
    """Paginated list of corporate account contracts.

    Attributes:
        contracts: List of contract response objects for the current page.
        total: Total number of contracts matching the query (across all pages).
    """

    contracts: list[ContractResponse]
    total: int
