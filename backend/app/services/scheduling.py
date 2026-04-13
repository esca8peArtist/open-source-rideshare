"""Scheduled ride validation and dispatch logic.

Riders can schedule rides in advance. The flow:
1. Rider creates a scheduled ride → status = SCHEDULED
2. Before the scheduled time (configurable), the system dispatches → status = REQUESTED
3. Normal matching proceeds from there

Validation rules:
- Must be at least `schedule_min_advance_minutes` in the future
- Cannot be more than `schedule_max_advance_hours` ahead
- A rider cannot have overlapping scheduled rides (same pickup window)
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from app.config import settings


# Overlap window: two scheduled rides are considered overlapping if they're
# within this many minutes of each other.
OVERLAP_WINDOW_MINUTES: int = 30


@dataclass(frozen=True)
class ScheduleValidation:
    valid: bool
    reason: str


def validate_schedule_time(scheduled_for: datetime, now: datetime | None = None) -> ScheduleValidation:
    """Validate that a requested schedule time is within allowed bounds."""
    if now is None:
        now = datetime.now(timezone.utc)

    # Ensure timezone-aware
    if scheduled_for.tzinfo is None:
        return ScheduleValidation(valid=False, reason="Scheduled time must include timezone")

    min_time = now + timedelta(minutes=settings.schedule_min_advance_minutes)
    max_time = now + timedelta(hours=settings.schedule_max_advance_hours)

    if scheduled_for < min_time:
        return ScheduleValidation(
            valid=False,
            reason=f"Must schedule at least {settings.schedule_min_advance_minutes} minutes in advance",
        )

    if scheduled_for > max_time:
        return ScheduleValidation(
            valid=False,
            reason=f"Cannot schedule more than {settings.schedule_max_advance_hours} hours in advance",
        )

    return ScheduleValidation(valid=True, reason="OK")


def check_overlap(
    scheduled_for: datetime,
    existing_times: list[datetime],
) -> ScheduleValidation:
    """Check that a new scheduled ride doesn't overlap with existing ones."""
    window = timedelta(minutes=OVERLAP_WINDOW_MINUTES)
    for existing in existing_times:
        if abs(scheduled_for - existing) < window:
            return ScheduleValidation(
                valid=False,
                reason=f"You already have a ride scheduled within {OVERLAP_WINDOW_MINUTES} minutes of this time",
            )
    return ScheduleValidation(valid=True, reason="OK")


def is_ready_for_dispatch(scheduled_for: datetime, now: datetime | None = None) -> bool:
    """Check if a scheduled ride should be dispatched for matching.

    Returns True when current time is within `schedule_dispatch_before_minutes`
    of the scheduled pickup time.
    """
    if now is None:
        now = datetime.now(timezone.utc)
    dispatch_at = scheduled_for - timedelta(minutes=settings.schedule_dispatch_before_minutes)
    return now >= dispatch_at
