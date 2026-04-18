"""Pre-ride boarding verification endpoints.

POST   /rides/{ride_id}/boarding-pin          — driver generates a verification PIN
GET    /rides/{ride_id}/boarding-pin          — rider/driver fetches the active PIN
POST   /rides/{ride_id}/boarding-verification — rider submits boarding confirmation
GET    /rides/{ride_id}/boarding-verification — get verification status for a ride

GET    /admin/boarding-mismatch-alerts        — admin: list unresolved mismatch alerts
POST   /admin/boarding-mismatch-alerts/{alert_id}/resolve — admin: resolve an alert

Business rules enforced in the service layer.  This module handles HTTP
mapping only: 403 on ownership mismatches (do not leak existence to
non-participants), 404 when no resource exists, 400 on invalid state
transitions.
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_admin
from app.db.database import get_db
from app.models.ride import Ride, RideStatus
from app.models.user import User
from app.schemas.boarding_verification import (
    BoardingPinResponse,
    BoardingVerificationResponse,
    ConfirmBoardingRequest,
    MismatchAlertListResponse,
    MismatchAlertResponse,
    ResolveMismatchAlertRequest,
)
from app.services.boarding_verification import (
    admin_list_mismatch_alerts,
    admin_resolve_mismatch_alert,
    confirm_boarding,
    generate_pin,
    get_pin,
    get_verification,
)
from sqlalchemy import select

logger = logging.getLogger(__name__)

router = APIRouter(tags=["boarding-verification"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _get_ride_or_404(ride_id: int, db: AsyncSession) -> Ride:
    result = await db.execute(select(Ride).where(Ride.id == ride_id))
    ride = result.scalar_one_or_none()
    if ride is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ride not found.")
    return ride


def _require_driver_of_ride(ride: Ride, user: User) -> None:
    if ride.driver_id != user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not the driver for this ride.")


def _require_rider_of_ride(ride: Ride, user: User) -> None:
    if ride.rider_id != user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not the rider for this ride.")


def _require_participant(ride: Ride, user: User) -> None:
    if ride.driver_id != user.id and ride.rider_id != user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not a participant in this ride.")


# ---------------------------------------------------------------------------
# PIN endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/rides/{ride_id}/boarding-pin",
    response_model=BoardingPinResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Generate boarding verification PIN",
    description=(
        "Generates a 4-digit PIN that the rider can use to verify driver identity "
        "before boarding.  The driver reads the PIN aloud; the rider confirms it "
        "matches before getting in the car.  The PIN is valid for 15 minutes.  "
        "Only the assigned driver may call this endpoint.  Calling it again "
        "invalidates the previous PIN."
    ),
)
async def post_generate_pin(
    ride_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> BoardingPinResponse:
    ride = await _get_ride_or_404(ride_id, db)
    _require_driver_of_ride(ride, user)

    try:
        record = generate_pin(
            ride_id=ride_id,
            driver_id=user.id,
            ride_status=ride.status.value,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    return BoardingPinResponse(
        ride_id=record["ride_id"],
        pin=record["pin"],
        generated_at=record["generated_at"],
        expires_at=record["expires_at"],
        expired=False,
    )


@router.get(
    "/rides/{ride_id}/boarding-pin",
    response_model=BoardingPinResponse,
    summary="Get active boarding PIN for a ride",
    description=(
        "Returns the current active boarding PIN.  Both the driver and rider "
        "may call this endpoint.  Returns 404 if no PIN has been generated yet."
    ),
)
async def get_boarding_pin(
    ride_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> BoardingPinResponse:
    ride = await _get_ride_or_404(ride_id, db)
    _require_participant(ride, user)

    record = get_pin(ride_id)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No boarding PIN has been generated for this ride yet.",
        )

    return BoardingPinResponse(
        ride_id=record["ride_id"],
        pin=record["pin"],
        generated_at=record["generated_at"],
        expires_at=record["expires_at"],
        expired=record.get("expired", False),
    )


# ---------------------------------------------------------------------------
# Verification endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/rides/{ride_id}/boarding-verification",
    response_model=BoardingVerificationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Submit boarding verification",
    description=(
        "The rider submits the PIN they received verbally from the driver, along "
        "with optional confirmation of the driver name and license plate.  "
        "If the PIN matches, confirmed=true is stored.  If it does not match "
        "or no active PIN exists, confirmed=false and a safety alert is raised.  "
        "Only the assigned rider may call this endpoint.  Only one verification "
        "is allowed per ride."
    ),
)
async def post_confirm_boarding(
    ride_id: int,
    body: ConfirmBoardingRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> BoardingVerificationResponse:
    ride = await _get_ride_or_404(ride_id, db)
    _require_rider_of_ride(ride, user)

    try:
        record = confirm_boarding(
            ride_id=ride_id,
            rider_id=user.id,
            pin_entered=body.pin_entered,
            confirmed_driver_name=body.confirmed_driver_name,
            confirmed_plate=body.confirmed_plate,
            notes=body.notes,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    return BoardingVerificationResponse(**record)


@router.get(
    "/rides/{ride_id}/boarding-verification",
    response_model=BoardingVerificationResponse,
    summary="Get boarding verification status",
    description=(
        "Returns the boarding verification record for the ride if one exists.  "
        "Both the driver and rider may call this endpoint.  Returns 404 if no "
        "verification has been submitted yet."
    ),
)
async def get_boarding_verification(
    ride_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> BoardingVerificationResponse:
    ride = await _get_ride_or_404(ride_id, db)
    _require_participant(ride, user)

    record = get_verification(ride_id)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No boarding verification has been submitted for this ride.",
        )

    return BoardingVerificationResponse(**record)


# ---------------------------------------------------------------------------
# Admin endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/admin/boarding-mismatch-alerts",
    response_model=MismatchAlertListResponse,
    summary="List boarding mismatch alerts",
    description="Admin: returns unresolved PIN mismatch alerts.  Pass resolved=true to include resolved ones.",
)
async def admin_get_mismatch_alerts(
    include_resolved: bool = Query(default=False, alias="resolved"),
    user: User = Depends(require_admin),
) -> MismatchAlertListResponse:
    alerts = admin_list_mismatch_alerts(include_resolved=include_resolved)
    return MismatchAlertListResponse(
        alerts=[MismatchAlertResponse(**a) for a in alerts],
        total=len(alerts),
    )


@router.post(
    "/admin/boarding-mismatch-alerts/{alert_id}/resolve",
    response_model=MismatchAlertResponse,
    summary="Resolve a boarding mismatch alert",
    description="Admin: mark a PIN mismatch alert as resolved after investigation.",
)
async def admin_resolve_alert(
    alert_id: int,
    body: ResolveMismatchAlertRequest,
    user: User = Depends(require_admin),
) -> MismatchAlertResponse:
    try:
        alert = admin_resolve_mismatch_alert(alert_id, body.resolution_notes)
    except KeyError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Alert not found.")
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    return MismatchAlertResponse(**alert)
