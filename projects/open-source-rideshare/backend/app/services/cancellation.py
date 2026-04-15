"""Ride cancellation policy and fee system.

Implements two layers:

1. Stateless evaluation (legacy, kept for backward compatibility):
   evaluate_cancellation() — pure function used by dispatch layer.

2. DB-backed policy + fee system (new):
   get_active_policy()     — returns the one active CancellationPolicy from DB.
   calculate_rider_fee()   — computes fee for a rider cancellation.
   calculate_driver_fee()  — computes fee for a driver cancellation.
   record_cancellation()   — creates a CancellationRecord for a ride.
   waive_fee()             — admin waives a fee.
   admin_get_all()         — paginated list of records for admin review.
   admin_get_summary()     — aggregate statistics.

Fee logic:
  - Rider cancels within grace_period_seconds → no fee.
  - Rider cancels after grace period → rider_fee_flat + (fare * rider_fee_percent).
  - Driver cancels within driver_free_cancels_per_day → no fee.
  - Driver exceeds daily free limit → driver_cancel_penalty.
  - Admin/System cancellations → no fee.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.cancellation import (
    CancelledBy,
    CancellationPolicy,
    CancellationRecord,
    FeeChargedTo,
    FeeStatus,
)
from app.models.ride import RideStatus

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Legacy stateless evaluation (backward-compatible)
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Service error
# ---------------------------------------------------------------------------


class CancellationError(Exception):
    """Business-logic error raised by the cancellation service.

    status_code maps to the appropriate HTTP response code.
    """

    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


# ---------------------------------------------------------------------------
# Default policy (used when no active policy exists in DB)
# ---------------------------------------------------------------------------

_DEFAULT_POLICY = CancellationPolicy(
    rider_grace_period_seconds=120,
    rider_fee_flat=Decimal("5.00"),
    rider_fee_percent=Decimal("0.0000"),
    driver_free_cancels_per_day=3,
    driver_cancel_penalty=Decimal("2.00"),
    is_active=True,
)


# ---------------------------------------------------------------------------
# Policy retrieval
# ---------------------------------------------------------------------------


async def get_active_policy(db: AsyncSession) -> CancellationPolicy:
    """Return the single active CancellationPolicy from the database.

    If no active policy is configured a default policy object is returned
    (not persisted). This ensures the system works out-of-the-box without
    requiring admin setup.
    """
    result = await db.execute(
        select(CancellationPolicy)
        .where(CancellationPolicy.is_active == True)  # noqa: E712
        .order_by(CancellationPolicy.id.desc())
        .limit(1)
    )
    policy = result.scalar_one_or_none()
    if policy is None:
        return _DEFAULT_POLICY
    return policy


# ---------------------------------------------------------------------------
# Fee calculation (pure — no DB access)
# ---------------------------------------------------------------------------


def calculate_rider_fee(
    policy: CancellationPolicy,
    estimated_fare: float,
    booking_time: datetime,
    cancel_time: datetime,
) -> tuple[Decimal, bool]:
    """Compute the fee owed by a rider cancelling a ride.

    Returns
    -------
    (fee, grace_period_expired)
      fee                 Decimal amount to charge (0.00 if within grace).
      grace_period_expired True when the grace window had already closed.

    The flat fee and percentage are additive. By default rider_fee_percent
    is 0.0000, making the total equal to rider_fee_flat alone.
    """
    elapsed_seconds = (cancel_time - booking_time).total_seconds()
    grace_expired = elapsed_seconds > float(policy.rider_grace_period_seconds)

    if not grace_expired:
        return Decimal("0.00"), False

    flat = Decimal(str(policy.rider_fee_flat))
    pct = Decimal(str(policy.rider_fee_percent))
    fare = Decimal(str(estimated_fare))
    fee = flat + (fare * pct)
    fee = fee.quantize(Decimal("0.01"))
    return fee, True


def calculate_driver_fee(
    policy: CancellationPolicy,
    driver_cancel_count_today: int,
) -> Decimal:
    """Compute the fee owed by a driver cancelling a ride.

    Parameters
    ----------
    policy                    Active cancellation policy.
    driver_cancel_count_today Number of cancellations the driver has already
                              made today (not including this one).

    Returns the penalty if (existing_count + 1) exceeds the daily free limit,
    otherwise returns 0.00.
    """
    if (driver_cancel_count_today + 1) > int(policy.driver_free_cancels_per_day):
        return Decimal(str(policy.driver_cancel_penalty)).quantize(Decimal("0.01"))
    return Decimal("0.00")


# ---------------------------------------------------------------------------
# Internal DB helpers
# ---------------------------------------------------------------------------


async def _count_driver_cancels_today(db: AsyncSession, driver_id: int) -> int:
    """Count driver-initiated cancellations for driver_id today (UTC)."""
    from app.models.ride import Ride

    today_start = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    result = await db.execute(
        select(func.count())
        .select_from(CancellationRecord)
        .join(Ride, Ride.id == CancellationRecord.ride_id)
        .where(
            and_(
                Ride.driver_id == driver_id,
                CancellationRecord.cancelled_by == CancelledBy.driver,
                CancellationRecord.cancelled_at >= today_start,
            )
        )
    )
    return result.scalar() or 0


async def _load_record(db: AsyncSession, record_id: int) -> CancellationRecord:
    result = await db.execute(
        select(CancellationRecord).where(CancellationRecord.id == record_id)
    )
    record = result.scalar_one_or_none()
    if not record:
        raise CancellationError("Cancellation record not found", status_code=404)
    return record


# ---------------------------------------------------------------------------
# Core service functions
# ---------------------------------------------------------------------------


async def record_cancellation(
    db: AsyncSession,
    ride_id: int,
    cancelled_by: CancelledBy,
    reason: str | None,
    estimated_fare: float,
    booking_time: datetime,
    driver_id: int | None = None,
) -> CancellationRecord:
    """Create a CancellationRecord for a cancelled ride.

    Fetches the active policy, calculates the applicable fee, and inserts
    the record. The ride's status is NOT updated here — the caller (router
    layer) is responsible for updating ride.status = CANCELLED before or
    after calling this function.

    Raises
    ------
    CancellationError(404)  Ride does not exist.
    CancellationError(409)  A cancellation record already exists for this ride.

    Returns the newly created CancellationRecord (flushed, not committed).
    """
    from app.models.ride import Ride

    result = await db.execute(select(Ride).where(Ride.id == ride_id))
    ride = result.scalar_one_or_none()
    if not ride:
        raise CancellationError("Ride not found", status_code=404)

    existing = await db.execute(
        select(CancellationRecord).where(CancellationRecord.ride_id == ride_id)
    )
    if existing.scalar_one_or_none() is not None:
        raise CancellationError(
            "A cancellation record already exists for this ride", status_code=409
        )

    policy = await get_active_policy(db)
    cancel_time = datetime.now(timezone.utc)

    fee = Decimal("0.00")
    grace_expired = False
    fee_charged_to = FeeChargedTo.none

    if cancelled_by == CancelledBy.rider:
        fee, grace_expired = calculate_rider_fee(
            policy,
            estimated_fare=estimated_fare,
            booking_time=booking_time,
            cancel_time=cancel_time,
        )
        if fee > Decimal("0.00"):
            fee_charged_to = FeeChargedTo.rider

    elif cancelled_by == CancelledBy.driver:
        effective_driver_id = driver_id or getattr(ride, "driver_id", None)
        count_today = 0
        if effective_driver_id:
            count_today = await _count_driver_cancels_today(db, effective_driver_id)
        fee = calculate_driver_fee(policy, count_today)
        if fee > Decimal("0.00"):
            fee_charged_to = FeeChargedTo.driver

    # No-fee records (admin/system or within grace) start as "waived" immediately
    initial_status = FeeStatus.pending if fee > Decimal("0.00") else FeeStatus.waived

    record = CancellationRecord(
        ride_id=ride_id,
        cancelled_by=cancelled_by,
        cancellation_reason=reason,
        cancelled_at=cancel_time,
        grace_period_expired=grace_expired,
        fee_applied=fee,
        fee_charged_to=fee_charged_to,
        fee_status=initial_status,
    )
    db.add(record)
    await db.flush()

    logger.info(
        "Cancellation recorded: ride=%d by=%s fee=%.2f charged_to=%s",
        ride_id,
        cancelled_by.value,
        fee,
        fee_charged_to.value,
    )
    return record


async def waive_fee(
    db: AsyncSession,
    cancellation_record_id: int,
    admin_id: int,
    reason: str,
) -> CancellationRecord:
    """Admin waives the fee on a cancellation record.

    Sets fee_status=waived and records the admin and reason.

    Raises
    ------
    CancellationError(404)  Record not found.
    CancellationError(409)  Fee is already waived or refunded.
    """
    record = await _load_record(db, cancellation_record_id)

    if record.fee_status in (FeeStatus.waived, FeeStatus.refunded):
        raise CancellationError(
            f"Fee is already {record.fee_status.value} — cannot waive again",
            status_code=409,
        )

    record.fee_status = FeeStatus.waived
    record.waived_by_admin_id = admin_id
    record.waive_reason = reason

    await db.flush()
    logger.info(
        "Admin %d waived fee on cancellation record %d", admin_id, cancellation_record_id
    )
    return record


async def admin_get_all(
    db: AsyncSession,
    skip: int = 0,
    limit: int = 50,
    fee_status_filter: FeeStatus | None = None,
) -> list[CancellationRecord]:
    """Paginated list of cancellation records for admin review.

    Filtered by fee_status when provided. Results are newest-first.
    """
    query = (
        select(CancellationRecord)
        .order_by(CancellationRecord.created_at.desc())
        .limit(limit)
        .offset(skip)
    )
    if fee_status_filter is not None:
        query = query.where(CancellationRecord.fee_status == fee_status_filter)

    result = await db.execute(query)
    return list(result.scalars().all())


async def admin_get_summary(db: AsyncSession) -> dict:
    """Aggregate statistics for the admin dashboard.

    Returns a dict with total cancellation counts, fee sums by status,
    and cancellation counts by party (rider/driver/admin/system).
    """
    agg_result = await db.execute(
        select(
            func.count(CancellationRecord.id).label("total"),
            func.coalesce(func.sum(CancellationRecord.fee_applied), 0).label("total_fees"),
        )
    )
    agg_row = agg_result.one()

    async def _sum_by_status(status: FeeStatus) -> float:
        r = await db.execute(
            select(func.coalesce(func.sum(CancellationRecord.fee_applied), 0)).where(
                CancellationRecord.fee_status == status
            )
        )
        return float(r.scalar() or 0)

    async def _count_by_party(party: CancelledBy) -> int:
        r = await db.execute(
            select(func.count()).where(CancellationRecord.cancelled_by == party)
        )
        return r.scalar() or 0

    return {
        "total_cancellations": agg_row.total,
        "total_fees_assessed_usd": float(agg_row.total_fees),
        "total_fees_pending_usd": await _sum_by_status(FeeStatus.pending),
        "total_fees_charged_usd": await _sum_by_status(FeeStatus.charged),
        "total_fees_waived_usd": await _sum_by_status(FeeStatus.waived),
        "total_fees_refunded_usd": await _sum_by_status(FeeStatus.refunded),
        "cancellations_by_rider": await _count_by_party(CancelledBy.rider),
        "cancellations_by_driver": await _count_by_party(CancelledBy.driver),
        "cancellations_by_admin": await _count_by_party(CancelledBy.admin),
        "cancellations_by_system": await _count_by_party(CancelledBy.system),
    }
