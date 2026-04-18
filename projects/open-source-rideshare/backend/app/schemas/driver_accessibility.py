"""Pydantic schemas for the driver accessibility capabilities API."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class DriverAccessibilityUpdate(BaseModel):
    """Request body for updating driver accessibility capability flags.

    All fields are optional — send only the fields you want to change.
    """

    hearing_impairment_capable: bool | None = None
    sign_language_capable: bool | None = None
    service_animal_friendly: bool | None = None


class DriverAccessibilityResponse(BaseModel):
    """Driver accessibility capability flags as returned by the API."""

    hearing_impairment_capable: bool
    sign_language_capable: bool
    service_animal_friendly: bool
    updated_at: datetime

    model_config = {"from_attributes": True}
