"""Ride cancellation policy engine.

Implements fair cancellation rules for a cooperative rideshare platform:
- Free cancellation within a grace period after matching
- Cancellation fee if driver is already en route / arrived (compensates driver time)
- Tracks who cancelled for dispute resolution and pattern detection
- No punitive fees for cancelling before a driver is matched
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from app.config import settings
from app.models.ride import RideStatus


# Configurable defaults — can be overridden via admin API later.
FREE_CANCEL_GRACE_SECONDS: int = 120  # 2 minutes after match
EN_ROUTE_CANCEL_FEE: float = 3.00  # flat fee if driver is en route
ARRIVED_CANCEL_FEE: float = 5.00  # higher fee if driver has arrived
MAX_CANCEL_FEE_PERCENT: float = 50.0  # fee never exceeds this % of estimated fare


@dataclass(frozen=True)
class CancellationResult:
    allowed: bool
    fee: float
    reason: str


def evaluate_cancellation(
    ride_status: RideStatus,
    cancelled_by: str,  # "rider" or "driver"
    estimated_fare: float,
    matched_at: datetime | None,
    now: datetime | None = None,
    dispatch_retry_count: int = 0,
) -> CancellationResult:
    """Determine whether a cancellation is allowed and what fee applies.

    Returns a CancellationResult with the decision.
    """
    if now is None:
        now = datetime.now(timezone.utc)

    # Already terminal — can't cancel
    if ride_status in (RideStatus.COMPLETED, RideStatus.CANCELLED):
        return CancellationResult(allowed=False, fee=0.0, reason="Ride is already completed or cancelled")

    # In-progress rides can't be cancelled (must be completed or use SOS)
    if ride_status == RideStatus.IN_PROGRESS:
        return CancellationResult(allowed=False, fee=0.0, reason="Cannot cancel a ride in progress")

    # Scheduled rides: always free (no driver matched yet)
    if ride_status == RideStatus.SCHEDULED:
        return CancellationResult(allowed=True, fee=0.0, reason="Free cancellation — ride was scheduled, not yet dispatched")

    # Pre-match: always free (includes rides actively being retried by dispatch)
    if ride_status == RideStatus.REQUESTED:
        if dispatch_retry_count > 0:
            return CancellationResult(
                allowed=True, fee=0.0,
                reason=f"Free cancellation — cancelled during dispatch retry (attempt {dispatch_retry_count})",
            )
        return CancellationResult(allowed=True, fee=0.0, reason="Free cancellation — no driver matched yet")

    # Driver-initiated cancellation is always free (driver absorbs their own cost)
    if cancelled_by == "driver":
        return CancellationResult(allowed=True, fee=0.0, reason="Driver-initiated cancellation — no fee")

    # Rider cancelling after match — check grace period
    if matched_at is not None:
        elapsed = (now - matched_at).total_seconds()
        if elapsed <= FREE_CANCEL_GRACE_SECONDS:
            return CancellationResult(
                allowed=True,
                fee=0.0,
                reason=f"Free cancellation — within {FREE_CANCEL_GRACE_SECONDS}s grace period",
            )

    # Past grace period — fee depends on ride status
    fee = 0.0
    if ride_status == RideStatus.MATCHED:
        fee = EN_ROUTE_CANCEL_FEE
        reason = "Cancellation fee — driver was matched and grace period expired"
    elif ride_status == RideStatus.DRIVER_EN_ROUTE:
        fee = EN_ROUTE_CANCEL_FEE
        reason = "Cancellation fee — driver is en route"
    elif ride_status == RideStatus.ARRIVED:
        fee = ARRIVED_CANCEL_FEE
        reason = "Cancellation fee — driver has arrived at pickup"
    else:
        reason = "Cancellation with fee"

    # Cap fee at MAX_CANCEL_FEE_PERCENT of estimated fare
    max_fee = estimated_fare * (MAX_CANCEL_FEE_PERCENT / 100.0)
    fee = min(fee, max_fee)
    fee = round(fee, 2)

    return CancellationResult(allowed=True, fee=fee, reason=reason)
