"""Driver safety check-in timer endpoints.

POST   /drivers/me/check-in-timer          — start a timer (5–120 min)
GET    /drivers/me/check-in-timer          — get active timer; triggers lazy expiry
POST   /drivers/me/check-in-timer/confirm  — confirm safe → CONFIRMED
DELETE /drivers/me/check-in-timer          — cancel timer → CANCELLED
GET    /drivers/me/check-in-timer/history  — list past timers (newest first)

A driver sets a countdown.  If they do not confirm safe before expiry,
their emergency contacts are notified.  Only one ACTIVE timer per driver
is allowed at any time.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.deps import require_driver
from app.models.user import User
from app.schemas.driver_check_in_timer import (
    DriverCheckInTimerResponse,
    StartDriverCheckInTimerRequest,
)
from app.services.driver_check_in_timer import (
    cancel_timer,
    confirm_timer,
    get_active_timer,
    list_timers,
    start_timer,
)

router = APIRouter(tags=["driver-check-in-timer"])


@router.post(
    "/drivers/me/check-in-timer",
    response_model=DriverCheckInTimerResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Start a driver safety check-in timer",
    description=(
        "Start a countdown timer.  If the driver does not confirm they are safe "
        "before `expires_at`, their emergency contacts are automatically alerted.  "
        "Only one ACTIVE timer is allowed per driver — starting a second raises 409."
    ),
)
async def post_start_timer(
    body: StartDriverCheckInTimerRequest,
    driver: User = Depends(require_driver),
) -> DriverCheckInTimerResponse:
    try:
        record = start_timer(
            driver_id=driver.id,
            duration_minutes=body.duration_minutes,
            notes=body.notes,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    return DriverCheckInTimerResponse(**record)


@router.get(
    "/drivers/me/check-in-timer",
    response_model=DriverCheckInTimerResponse,
    summary="Get active check-in timer",
    description=(
        "Return the driver's current ACTIVE check-in timer.  "
        "Lazily expires the timer if its expiry has passed.  "
        "Returns 404 if no active timer exists."
    ),
)
async def get_timer(
    driver: User = Depends(require_driver),
) -> DriverCheckInTimerResponse:
    record = get_active_timer(driver_id=driver.id)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No active check-in timer found.",
        )
    return DriverCheckInTimerResponse(**record)


@router.post(
    "/drivers/me/check-in-timer/confirm",
    response_model=DriverCheckInTimerResponse,
    summary="Confirm safe — dismiss check-in timer",
    description=(
        "Confirm the driver is safe.  Transitions the ACTIVE timer to CONFIRMED "
        "and stops the countdown.  Emergency contacts will not be alerted.  "
        "Returns 404 if no active timer exists."
    ),
)
async def post_confirm(
    driver: User = Depends(require_driver),
) -> DriverCheckInTimerResponse:
    try:
        record = confirm_timer(driver_id=driver.id)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    return DriverCheckInTimerResponse(**record)


@router.delete(
    "/drivers/me/check-in-timer",
    response_model=DriverCheckInTimerResponse,
    summary="Cancel check-in timer",
    description=(
        "Cancel the active check-in timer without confirming safety.  The timer "
        "transitions to CANCELLED and no notification is sent.  Returns 404 if "
        "no active timer exists."
    ),
)
async def delete_timer(
    driver: User = Depends(require_driver),
) -> DriverCheckInTimerResponse:
    try:
        record = cancel_timer(driver_id=driver.id)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    return DriverCheckInTimerResponse(**record)


@router.get(
    "/drivers/me/check-in-timer/history",
    response_model=list[DriverCheckInTimerResponse],
    summary="Check-in timer history",
    description="Return all past check-in timers for the driver, newest first.",
)
async def get_timer_history(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    driver: User = Depends(require_driver),
) -> list[DriverCheckInTimerResponse]:
    records = list_timers(driver_id=driver.id, skip=skip, limit=limit)
    return [DriverCheckInTimerResponse(**r) for r in records]
