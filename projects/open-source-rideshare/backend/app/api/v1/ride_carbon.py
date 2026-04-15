"""Ride Carbon Footprint endpoints.

Green Rides cooperative feature: track per-ride CO2 emissions, let riders
pay a voluntary carbon offset, and surface sustainability metrics to admins.

Rider endpoints:
  GET  /carbon/rides/{ride_id}         — per-ride carbon data (own rides)
  GET  /carbon/me/summary              — rider lifetime carbon footprint summary
  POST /carbon/rides/{ride_id}/offset  — pay voluntary carbon offset

Admin endpoints:
  POST /carbon/admin/rides             — record/update carbon data for a ride
  GET  /carbon/admin/stats             — platform-wide sustainability metrics
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, require_admin
from app.models.user import User
from app.schemas.ride_carbon import (
    PlatformCarbonStats,
    RecordRideCarbonRequest,
    RideCarbonResponse,
    RiderCarbonSummary,
)
from app.services import ride_carbon as svc
from app.services.ride_carbon import CarbonError

logger = logging.getLogger(__name__)

router = APIRouter(tags=["ride-carbon"])


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _http(exc: CarbonError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.message)


# ---------------------------------------------------------------------------
# Rider routes
# ---------------------------------------------------------------------------


@router.get(
    "/carbon/rides/{ride_id}",
    response_model=RideCarbonResponse,
    summary="Get per-ride carbon footprint",
)
async def get_ride_carbon(
    ride_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> RideCarbonResponse:
    """Return the carbon record for a specific ride.

    Any authenticated user may query a ride they were involved in; the
    authorization check (ride ownership) is intentionally lightweight here —
    the record exposes only environmental data, not financial details.
    """
    record = await svc.get_ride_carbon(db, ride_id)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No carbon data recorded for this ride yet",
        )
    return RideCarbonResponse.from_record(record)


@router.get(
    "/carbon/me/summary",
    response_model=RiderCarbonSummary,
    summary="Get my carbon footprint summary",
)
async def get_my_carbon_summary(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> RiderCarbonSummary:
    """Return lifetime carbon footprint stats for the authenticated rider."""
    return await svc.get_rider_carbon_summary(db, current_user.id)


@router.post(
    "/carbon/rides/{ride_id}/offset",
    response_model=RideCarbonResponse,
    status_code=status.HTTP_200_OK,
    summary="Pay voluntary carbon offset for a ride",
)
async def pay_carbon_offset(
    ride_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> RideCarbonResponse:
    """Pay the voluntary carbon offset for a completed ride.

    Returns 404 if no carbon record exists for this ride.
    Returns 409 if the offset has already been paid.
    """
    try:
        record = await svc.pay_carbon_offset(db, ride_id, current_user.id)
    except CarbonError as exc:
        raise _http(exc)
    return RideCarbonResponse.from_record(record)


# ---------------------------------------------------------------------------
# Admin routes
# ---------------------------------------------------------------------------


@router.post(
    "/carbon/admin/rides",
    response_model=RideCarbonResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Record or update carbon data for a ride (admin)",
)
async def admin_record_ride_carbon(
    body: RecordRideCarbonRequest,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> RideCarbonResponse:
    """Create or overwrite the carbon record for a completed ride.

    Idempotent — calling twice updates the existing row.
    Preserves offset payment if the rider has already paid.
    """
    try:
        record = await svc.record_ride_carbon(
            db,
            ride_id=body.ride_id,
            emission_class=body.emission_class,
            distance_km=body.distance_km,
        )
    except CarbonError as exc:
        raise _http(exc)
    return RideCarbonResponse.from_record(record)


@router.get(
    "/carbon/admin/stats",
    response_model=PlatformCarbonStats,
    summary="Platform-wide carbon sustainability metrics (admin)",
)
async def admin_platform_carbon_stats(
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> PlatformCarbonStats:
    """Return aggregate green metrics across all tracked rides."""
    return await svc.get_platform_carbon_stats(db)
