"""Driver wait time billing service.

When a driver marks arrival, the clock starts.  After a configurable grace
period the rider is billed per-minute for making the driver wait.  If the
rider never shows within MAX_WAIT_MINUTES the ride can be treated as a
no-show cancellation.

All calculation helpers are pure functions so they can be unit-tested without
a database.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone


# ---------------------------------------------------------------------------
# Configurable policy constants
# ---------------------------------------------------------------------------

#: Free waiting time after driver arrives (seconds).
WAIT_GRACE_SECONDS: int = 120  # 2 minutes

#: Per-minute rate charged to the rider *after* the grace period (USD).
WAIT_RATE_PER_MIN: float = 0.25

#: Maximum minutes a driver should wait before the ride qualifies as a
#: no-show.  Callers decide what to do with this flag.
MAX_WAIT_MINUTES: int = 10


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class WaitTimeCalc:
    """Result of a point-in-time wait time calculation."""

    elapsed_seconds: int
    """Total seconds since driver arrived."""

    elapsed_minutes: float
    """elapsed_seconds / 60 (convenience)."""

    grace_seconds_remaining: int
    """Seconds of free waiting time left; 0 once grace period is over."""

    billable_minutes: float
    """Minutes beyond the grace period that are billed to the rider."""

    accrued_fee: float
    """Rounded dollar amount owed by the rider for wait time."""

    is_no_show: bool
    """True when elapsed_minutes >= MAX_WAIT_MINUTES."""


# ---------------------------------------------------------------------------
# Pure calculation helpers
# ---------------------------------------------------------------------------


def calculate_wait_fee(
    driver_arrived_at: datetime,
    now: datetime | None = None,
) -> WaitTimeCalc:
    """Compute the current wait time status from the arrival timestamp.

    Args:
        driver_arrived_at: UTC timestamp when the driver marked arrival.
        now: Override for "current time" (useful in tests).

    Returns:
        WaitTimeCalc with elapsed time, accrued fee, and no-show flag.
    """
    if now is None:
        now = datetime.now(timezone.utc)

    # Ensure both datetimes are timezone-aware UTC before differencing.
    if driver_arrived_at.tzinfo is None:
        driver_arrived_at = driver_arrived_at.replace(tzinfo=timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    elapsed_seconds = max(0, int((now - driver_arrived_at).total_seconds()))
    elapsed_minutes = elapsed_seconds / 60.0

    grace_seconds_remaining = max(0, WAIT_GRACE_SECONDS - elapsed_seconds)
    billable_seconds = max(0, elapsed_seconds - WAIT_GRACE_SECONDS)
    billable_minutes = billable_seconds / 60.0

    accrued_fee = round(billable_minutes * WAIT_RATE_PER_MIN, 2)
    is_no_show = elapsed_minutes >= MAX_WAIT_MINUTES

    return WaitTimeCalc(
        elapsed_seconds=elapsed_seconds,
        elapsed_minutes=round(elapsed_minutes, 2),
        grace_seconds_remaining=grace_seconds_remaining,
        billable_minutes=round(billable_minutes, 3),
        accrued_fee=accrued_fee,
        is_no_show=is_no_show,
    )


def compute_final_wait_fee(
    driver_arrived_at: datetime | None,
    ride_started_at: datetime | None,
) -> float:
    """Return the wait fee to add to the final fare when completing a ride.

    The fee is calculated up to the moment the rider was picked up
    (ride_started_at), not the completion time, so the rider is only charged
    for actual waiting — not the trip itself.

    Returns 0.0 when driver_arrived_at is not set or the ride started before
    the grace period elapsed.
    """
    if driver_arrived_at is None:
        return 0.0
    reference = ride_started_at if ride_started_at is not None else datetime.now(timezone.utc)
    calc = calculate_wait_fee(driver_arrived_at, now=reference)
    return calc.accrued_fee
