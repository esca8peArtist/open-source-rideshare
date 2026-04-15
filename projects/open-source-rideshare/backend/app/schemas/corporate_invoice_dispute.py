"""Pydantic v2 schemas for Corporate Invoice Disputes.

Corporate account members can formally dispute charges on invoices.
Platform admins review and resolve disputes.

Public surface
--------------
SubmitDisputeRequest     — body for submitting a new dispute.
UpdateDisputeRequest     — body for updating a pending dispute.
ReviewDisputeRequest     — body for marking a dispute under review (empty).
ResolveDisputeRequest    — body for resolving a dispute (upheld or denied).
WithdrawDisputeRequest   — body for withdrawing a dispute (empty).
InvoiceDisputeResponse   — full dispute record returned by the API.
InvoiceDisputeListResponse — paginated list of dispute records.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, field_validator

from app.models.corporate_invoice_dispute import DisputeStatus, DisputeType


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------


class SubmitDisputeRequest(BaseModel):
    """Payload for submitting a new invoice dispute.

    Attributes:
        dispute_type: Structured category for the dispute.
        description: Required free-text explanation (minimum 10 characters).
        disputed_rides: Optional list of specific ride IDs being disputed.
        disputed_amount_usd: Optional specific amount being disputed (must be >= 0).
    """

    dispute_type: DisputeType
    description: str
    disputed_rides: Optional[List[int]] = None
    disputed_amount_usd: Optional[Decimal] = None

    @field_validator("description")
    @classmethod
    def description_min_length(cls, v: str) -> str:
        if len(v) < 10:
            raise ValueError("description must be at least 10 characters")
        return v

    @field_validator("disputed_amount_usd")
    @classmethod
    def amount_non_negative(cls, v: Optional[Decimal]) -> Optional[Decimal]:
        if v is not None and v < 0:
            raise ValueError("disputed_amount_usd must be >= 0")
        return v


class UpdateDisputeRequest(BaseModel):
    """Payload for updating a pending dispute (only allowed while submitted).

    Attributes:
        description: Updated free-text explanation.
        dispute_type: Updated dispute category.
        disputed_rides: Updated list of specific ride IDs.
        disputed_amount_usd: Updated disputed amount.
    """

    description: Optional[str] = None
    dispute_type: Optional[DisputeType] = None
    disputed_rides: Optional[List[int]] = None
    disputed_amount_usd: Optional[Decimal] = None


class ReviewDisputeRequest(BaseModel):
    """Payload for marking a dispute as under review.

    No fields required — the action is indicated by the endpoint.
    """


class ResolveDisputeRequest(BaseModel):
    """Payload for resolving a dispute.

    Attributes:
        resolution: Final status — must be resolved_upheld or resolved_denied.
        resolution_note: Optional admin note explaining the resolution decision.
    """

    resolution: DisputeStatus
    resolution_note: Optional[str] = None

    @field_validator("resolution")
    @classmethod
    def resolution_must_be_terminal(cls, v: DisputeStatus) -> DisputeStatus:
        allowed = {DisputeStatus.resolved_upheld, DisputeStatus.resolved_denied}
        if v not in allowed:
            raise ValueError(
                "resolution must be 'resolved_upheld' or 'resolved_denied'"
            )
        return v


class WithdrawDisputeRequest(BaseModel):
    """Payload for withdrawing a dispute.

    No fields required — the action is indicated by the endpoint.
    """


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------


class InvoiceDisputeResponse(BaseModel):
    """Full dispute record returned by the API.

    Attributes:
        id: Primary key.
        invoice_id: Invoice this dispute belongs to.
        account_id: Corporate account that owns the invoice.
        submitted_by_id: Member who submitted the dispute.
        dispute_type: Structured dispute category.
        description: Free-text explanation.
        disputed_rides: Optional list of disputed ride IDs.
        disputed_amount_usd: Optional specific disputed amount.
        status: Current lifecycle status of the dispute.
        resolution_note: Admin note explaining the resolution.
        resolved_by_id: Admin who resolved the dispute.
        resolved_at: When the dispute was resolved.
        created_at: When the dispute was submitted.
        updated_at: When the dispute record was last modified.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    invoice_id: int
    account_id: int
    submitted_by_id: Optional[int]
    dispute_type: DisputeType
    description: str
    disputed_rides: Optional[list]
    disputed_amount_usd: Optional[Decimal]
    status: DisputeStatus
    resolution_note: Optional[str]
    resolved_by_id: Optional[int]
    resolved_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime


class InvoiceDisputeListResponse(BaseModel):
    """Paginated list of invoice dispute records.

    Attributes:
        disputes: List of dispute records.
        total: Total number of records matching the query.
    """

    disputes: List[InvoiceDisputeResponse]
    total: int
