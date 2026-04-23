"""Schemas for driver document expiry endpoints.

GET /drivers/me/document-expiry  — driver sees their own expiring/expired docs
GET /admin/document-expiry       — admin fleet view of all expiring/expired docs
"""

from __future__ import annotations

from datetime import date
from typing import List

from pydantic import BaseModel


class DocumentExpiryItem(BaseModel):
    """A single expiring or expired document belonging to the authenticated driver."""

    document_type: str
    """One of ``"license"``, ``"vehicle_registration"``, ``"vehicle_insurance"``."""

    expiry_date: date
    """Calendar date on which the document expires."""

    days_remaining: int
    """Days until expiry.  Negative values indicate the document is already expired."""

    is_expired: bool
    """Convenience flag — True when ``days_remaining < 0``."""

    urgency: str
    """
    Human-readable urgency level:

    * ``"expired"``  — already past expiry date
    * ``"critical"`` — expires within 7 days
    * ``"warning"``  — expires within 30 days
    * ``"ok"``       — expires after 30 days (returned when days_ahead > 30)
    """


class DriverDocumentExpiryResponse(BaseModel):
    """Response for ``GET /drivers/me/document-expiry``."""

    driver_user_id: int
    """User ID of the authenticated driver."""

    documents: List[DocumentExpiryItem]
    """All expiring/expired documents within the requested look-ahead window.
    Sorted by days_remaining ascending (most urgent first)."""

    has_expired: bool
    """True if at least one document has already expired."""

    has_warning: bool
    """True if at least one document is expiring within the look-ahead window
    (includes already-expired documents)."""


class AdminDocumentExpiryItem(BaseModel):
    """A single expiring/expired document in the admin fleet view."""

    driver_user_id: int
    """User ID of the driver who owns this document."""

    document_type: str
    """One of ``"license"``, ``"vehicle_registration"``, ``"vehicle_insurance"``."""

    expiry_date: date
    """Calendar date on which the document expires."""

    days_remaining: int
    """Days until expiry.  Negative values indicate the document is already expired."""


class AdminDocumentExpiryResponse(BaseModel):
    """Response for ``GET /admin/document-expiry``."""

    days_ahead: int
    """The look-ahead window (in days) used to generate this report."""

    total: int
    """Total number of document records in the response."""

    items: List[AdminDocumentExpiryItem]
    """All expiring/expired documents across all drivers, sorted by
    (document_type, days_remaining) ascending."""
