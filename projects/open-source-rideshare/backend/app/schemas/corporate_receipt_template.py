"""Pydantic v2 schemas for Corporate Receipt Template.

Corporate accounts configure a custom receipt template applied to all ride
receipts for their employees.  Finance teams use this for branding, reference
number prefixes, footer notes, and custom line items.

Public surface
--------------
CustomLineItem              — single {"label", "value"} entry in the template.
ReceiptTemplateUpdate       — fields for creating or updating a template (all optional).
ReceiptTemplateResponse     — full template returned by the API.
ReceiptTemplateListResponse — paginated list for platform-admin cross-account view.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, field_validator


# ---------------------------------------------------------------------------
# Sub-schemas
# ---------------------------------------------------------------------------


class CustomLineItem(BaseModel):
    """A single custom line item to append to the receipt.

    Attributes:
        label: Heading for the line item, e.g. "Project Code".
        value: Content for the line item, e.g. "PROJ-123".
    """

    label: str
    value: str


# ---------------------------------------------------------------------------
# Write schemas
# ---------------------------------------------------------------------------


class ReceiptTemplateUpdate(BaseModel):
    """Payload for creating or updating a corporate receipt template.

    All fields are optional — unset fields are left unchanged on update.
    Supply ``None`` explicitly for a field to clear it.

    Attributes:
        company_name: Display name shown at the top of receipts.
        logo_url: URL of the company logo.  Must start with ``http://`` or
            ``https://`` when provided.
        header_message: Introductory text printed below the company name.
        footer_message: Footer note, e.g. expense submission instructions.
        reference_prefix: Short prefix for receipt reference numbers (max 20 chars).
        show_driver_details: Include driver name and photo on receipts.
        show_route_map: Include route map on receipts.
        custom_line_items: List of ``{"label", "value"}`` objects appended to
            each receipt.
        is_active: Whether the template should be applied to new receipts.
    """

    company_name: Optional[str] = None
    logo_url: Optional[str] = None
    header_message: Optional[str] = None
    footer_message: Optional[str] = None
    reference_prefix: Optional[str] = None
    show_driver_details: Optional[bool] = None
    show_route_map: Optional[bool] = None
    custom_line_items: Optional[list[CustomLineItem]] = None
    is_active: Optional[bool] = None

    @field_validator("logo_url")
    @classmethod
    def logo_url_must_be_url(cls, v: Optional[str]) -> Optional[str]:
        """Validate that logo_url, when provided, looks like an HTTP URL."""
        if v is not None and not (
            v.startswith("http://") or v.startswith("https://")
        ):
            raise ValueError(
                "logo_url must start with 'http://' or 'https://'"
            )
        return v

    @field_validator("reference_prefix")
    @classmethod
    def reference_prefix_max_length(cls, v: Optional[str]) -> Optional[str]:
        """Validate that reference_prefix does not exceed 20 characters."""
        if v is not None and len(v) > 20:
            raise ValueError(
                "reference_prefix must not exceed 20 characters"
            )
        return v


# ---------------------------------------------------------------------------
# Read schemas
# ---------------------------------------------------------------------------


class ReceiptTemplateResponse(BaseModel):
    """Full receipt template configuration for a corporate account.

    Returned by GET and PUT receipt-template endpoints.
    """

    model_config = {"from_attributes": True}

    id: int
    account_id: int
    company_name: Optional[str]
    logo_url: Optional[str]
    header_message: Optional[str]
    footer_message: Optional[str]
    reference_prefix: Optional[str]
    show_driver_details: bool
    show_route_map: bool
    custom_line_items: Optional[list[CustomLineItem]]
    is_active: bool
    created_by_id: Optional[int]
    updated_by_id: Optional[int]
    created_at: datetime
    updated_at: datetime


class ReceiptTemplateListResponse(BaseModel):
    """Paginated list of receipt templates across all corporate accounts.

    Returned by the platform-admin list endpoint.

    Attributes:
        total: Total number of templates matching the query (before pagination).
        limit: Page size used in this request.
        offset: Page offset used in this request.
        items: Templates for this page.
    """

    total: int
    limit: int
    offset: int
    items: list[ReceiptTemplateResponse]
