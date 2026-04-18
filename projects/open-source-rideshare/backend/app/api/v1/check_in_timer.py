"""Rider safety check-in timer endpoints.

POST   /riders/me/check-in-timer          — start a timer (5–120 min)
GET    /riders/me/check-in-timer          — get active timer; triggers lazy expiry
POST   /riders/me/check-in-timer/confirm  — confirm safe → CONFIRMED
DELETE /riders/me/check-in-timer          — cancel timer → CANCELLED
GET    /riders/me/check-in-timer/history  — list past timers (newest first)

A rider sets a countdown.  If they do not confirm safe before expiry,
their trusted contacts are notified.  Only one ACTIVE timer per rider
is allowed at any time.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.deps import get_current_user
from app.models.user import User
from app.schemas.check_in_timer import (
    CheckInTimerResponse,
    StartCheckInTimerRequest,
)
from app.services.check_in_timer import (
    cancel_timer,
    confirm_timer,
    get_active_timer,
    list_timers,
    start_timer,
)

router = APIRouter(tags=["check-in-timer"])


@router.post(
    "/riders/me/check-in-timer",
    response_model=CheckInTimerResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Start a safety check-in timer",
    description=(
        "Start a countdown timer.  If the rider does not confirm they are safe "
        "before `expires_at`, their trusted contacts (with panic or trip-end "
        "notifications enabled) are automatically alerted.  Only one ACTIVE "
        "timer is allowed per rider — starting a second raises 409."
    ),
)
async def post_start_timer(
    body: StartCheckInTimerRequest,
    rider: User = Depends(get_current_user),
) -> CheckInTimerResponse:
    try:
        record = start_timer(
            rider_id=rider.id,
            duration_minutes=body.duration_minutes,
            notes=body.notes,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    return CheckInTimerResponse(**record)


@router.get(
    "/riders/me/check-in-timer",
    response_model=CheckInTimerResponse,
    summary="Get active check-in timer",
    description=(
        "Return the rider's current ACTIVE check-in timer.  If the timer has "
        "passed its expiry time this call marks it EXPIRED and notifies trusted "
        "contacts (lazy expiry).  Returns 404 if no active timer exists."
    ),
)
async def get_timer(
    rider: User = Depends(get_current_user),
) -> CheckInTimerResponse:
    record = get_active_timer(rider_id=rider.id)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No active check-in timer found.",
        )
    return CheckInTimerResponse(**record)


@router.post(
    "/riders/me/check-in-timer/confirm",
    response_model=CheckInTimerResponse,
    summary="Confirm safe — dismiss check-in timer",
    description=(
        "Confirm the rider is safe.  Transitions the ACTIVE timer to CONFIRMED "
        "and stops the countdown.  Trusted contacts will not be alerted.  "
        "Returns 404 if no active timer exists."
    ),
)
async def post_confirm(
    rider: User = Depends(get_current_user),
) -> CheckInTimerResponse:
    try:
        record = confirm_timer(rider_id=rider.id)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    return CheckInTimerResponse(**record)


@router.delete(
    "/riders/me/check-in-timer",
    response_model=CheckInTimerResponse,
    summary="Cancel check-in timer",
    description=(
        "Cancel the active check-in timer without confirming safety.  The timer "
        "transitions to CANCELLED and no notification is sent.  Returns 404 if "
        "no active timer exists."
    ),
)
async def delete_timer(
    rider: User = Depends(get_current_user),
) -> CheckInTimerResponse:
    try:
        record = cancel_timer(rider_id=rider.id)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    return CheckInTimerResponse(**record)


@router.get(
    "/riders/me/check-in-timer/history",
    response_model=list[CheckInTimerResponse],
    summary="Check-in timer history",
    description="Return all past check-in timers for the rider, newest first.",
)
async def get_timer_history(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    rider: User = Depends(get_current_user),
) -> list[CheckInTimerResponse]:
    records = list_timers(rider_id=rider.id, skip=skip, limit=limit)
    return [CheckInTimerResponse(**r) for r in records]
