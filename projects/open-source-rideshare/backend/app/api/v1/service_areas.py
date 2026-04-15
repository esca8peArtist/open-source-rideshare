"""Public service area endpoints.

These routes expose the cooperative's operating boundaries to the public
(riders, drivers, and prospective members) without requiring authentication.
Admin CRUD for managing service area boundaries lives in app/api/v1/admin.py.

Public endpoints:
  GET  /service-areas
      List all active service areas (name, description, status).
      Useful for a coverage map on the marketing site or app onboarding.

  GET  /service-areas/{area_id}
      Get details for a single active service area.

  POST /service-areas/check
      Check whether a proposed ride (pickup + dropoff coordinates)
      falls within the cooperative's current service areas.
      Returns the same ServiceAreaValidation response used internally
      during ride requests, so the client can give riders a clear
      "not in service area" message before they even try to book.
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.schemas.service_area import (
    ServiceAreaListResponse,
    ServiceAreaResponse,
    ServiceAreaValidation,
)
from app.services.service_areas import (
    get_service_area,
    list_service_areas,
    validate_ride_locations,
)

router = APIRouter(tags=["service-areas"])


class RideCoverageRequest(BaseModel):
    """Request body for checking whether a pickup/dropoff pair is covered."""

    pickup_lat: float = Field(..., ge=-90.0, le=90.0, description="Pickup latitude")
    pickup_lng: float = Field(..., ge=-180.0, le=180.0, description="Pickup longitude")
    dropoff_lat: float = Field(..., ge=-90.0, le=90.0, description="Dropoff latitude")
    dropoff_lng: float = Field(..., ge=-180.0, le=180.0, description="Dropoff longitude")


# ---------------------------------------------------------------------------
# List active service areas
# ---------------------------------------------------------------------------


@router.get(
    "/service-areas",
    response_model=ServiceAreaListResponse,
    summary="List active service areas",
    description=(
        "Returns all active service areas. "
        "Use this to display a coverage map or inform riders whether service "
        "is available in their city before they sign up."
    ),
)
async def list_active_service_areas(
    db: AsyncSession = Depends(get_db),
) -> ServiceAreaListResponse:
    """Public: list every currently-active service area."""
    areas = await list_service_areas(db, active_only=True)
    return ServiceAreaListResponse(
        areas=[
            ServiceAreaResponse(
                id=a.id,
                name=a.name,
                description=a.description,
                is_active=a.is_active,
                created_at=a.created_at,
                updated_at=a.updated_at,
            )
            for a in areas
        ],
        total=len(areas),
    )


# ---------------------------------------------------------------------------
# Get a single active service area
# ---------------------------------------------------------------------------


@router.get(
    "/service-areas/{area_id}",
    response_model=ServiceAreaResponse,
    summary="Get a service area",
    description="Returns details for a single active service area by ID.",
)
async def get_active_service_area(
    area_id: int,
    db: AsyncSession = Depends(get_db),
) -> ServiceAreaResponse:
    """Public: fetch one service area (only if active)."""
    area = await get_service_area(db, area_id)
    if not area or not area.is_active:
        raise HTTPException(status_code=404, detail="Service area not found")
    return ServiceAreaResponse(
        id=area.id,
        name=area.name,
        description=area.description,
        is_active=area.is_active,
        created_at=area.created_at,
        updated_at=area.updated_at,
    )


# ---------------------------------------------------------------------------
# Check ride coverage (pickup + dropoff)
# ---------------------------------------------------------------------------


@router.post(
    "/service-areas/check",
    response_model=ServiceAreaValidation,
    summary="Check ride coverage",
    description=(
        "Check whether a pickup and dropoff location are both within the "
        "cooperative's current service areas. "
        "If no service areas are configured, all locations are considered covered "
        "(the cooperative hasn't set up geofencing yet). "
        "Call this before showing the 'Request Ride' button to surface a clear "
        "'not in service area' message when appropriate."
    ),
)
async def check_ride_coverage(
    req: RideCoverageRequest,
    db: AsyncSession = Depends(get_db),
) -> ServiceAreaValidation:
    """Public: check whether a pickup/dropoff pair is within service areas."""
    result = await validate_ride_locations(
        db,
        pickup_lat=req.pickup_lat,
        pickup_lng=req.pickup_lng,
        dropoff_lat=req.dropoff_lat,
        dropoff_lng=req.dropoff_lng,
    )
    return ServiceAreaValidation(
        valid=result["valid"],
        pickup_covered=result["pickup_covered"],
        dropoff_covered=result["dropoff_covered"],
        message=result.get("message"),
    )
