"""Cooperative member dividend / profit-sharing service.

Provides:
  - calculate_dividend  — preview allocation without persisting
  - declare_dividend    — create CooperativeDividend + DriverDividendShare records
  - admin_approve_dividend  — approve for distribution
  - admin_distribute_dividend  — mark all shares as paid
  - admin_cancel_dividend  — cancel pending/approved distribution
  - get_dividend        — single distribution (with shares)
  - list_dividends      — all distributions (newest first)
  - get_driver_dividend_history — driver's own share history
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.driver import DriverProfile
from app.models.driver_dividend import (
    CooperativeDividend,
    DividendShareStatus,
    DividendStatus,
    DriverDividendShare,
)
from app.models.ride import Ride, RideStatus
from app.models.user import User


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _quarter_date_range(year: int, quarter: int) -> tuple[date, date]:
    """Return (start_date, end_date) for a calendar quarter (inclusive)."""
    if not 1 <= quarter <= 4:
        raise ValueError(f"Quarter must be 1–4, got {quarter}")
    start_month = (quarter - 1) * 3 + 1
    end_month = start_month + 2
    start = date(year, start_month, 1)
    if end_month == 12:
        end = date(year, 12, 31)
    else:
        end = date(year, end_month + 1, 1) - timedelta(days=1)
    return start, end


def _to_dt(d: date) -> datetime:
    return datetime(d.year, d.month, d.day, tzinfo=timezone.utc)


async def _driver_rides_in_period(
    db: AsyncSession, year: int, quarter: int
) -> list[tuple[int, int, int]]:
    """Return [(user_id, driver_profile_id, ride_count)] for all drivers
    who completed at least one ride in the given quarter."""
    start_date, end_date = _quarter_date_range(year, quarter)
    start_dt = _to_dt(start_date)
    end_dt = datetime(end_date.year, end_date.month, end_date.day, 23, 59, 59, tzinfo=timezone.utc)

    result = await db.execute(
        select(
            Ride.driver_id,
            func.count(Ride.id).label("ride_count"),
        )
        .where(
            Ride.status == RideStatus.COMPLETED,
            Ride.completed_at >= start_dt,
            Ride.completed_at <= end_dt,
            Ride.driver_id.isnot(None),
        )
        .group_by(Ride.driver_id)
    )
    rows = result.all()  # [(driver_user_id, ride_count), ...]

    if not rows:
        return []

    # Fetch driver_profile_id for each driver user_id
    driver_user_ids = [r[0] for r in rows]
    profile_result = await db.execute(
        select(DriverProfile.user_id, DriverProfile.id).where(
            DriverProfile.user_id.in_(driver_user_ids)
        )
    )
    profile_map: dict[int, int] = {r[0]: r[1] for r in profile_result.all()}

    return [
        (row[0], profile_map.get(row[0], 0), row[1])
        for row in rows
        if profile_map.get(row[0])
    ]


async def _get_driver_names(db: AsyncSession, user_ids: list[int]) -> dict[int, str | None]:
    if not user_ids:
        return {}
    result = await db.execute(
        select(User.id, User.name).where(User.id.in_(user_ids))
    )
    return {r[0]: r[1] for r in result.all()}


# ---------------------------------------------------------------------------
# Calculate (preview — no DB writes)
# ---------------------------------------------------------------------------

async def calculate_dividend(
    db: AsyncSession,
    year: int,
    quarter: int,
    surplus_usd: float,
) -> dict:
    """Preview how a surplus would be distributed — does not persist anything.

    Returns a dict matching DividendCalculationPreview.
    """
    _quarter_date_range(year, quarter)  # validate

    driver_rows = await _driver_rides_in_period(db, year, quarter)
    total_rides = sum(r[2] for r in driver_rows)

    per_ride_payout = round(surplus_usd / total_rides, 4) if total_rides > 0 else 0.0

    driver_ids = [r[0] for r in driver_rows]
    names = await _get_driver_names(db, driver_ids)

    shares = []
    for user_id, profile_id, ride_count in driver_rows:
        share_pct = round(ride_count / total_rides * 100, 4) if total_rides > 0 else 0.0
        amount = round(ride_count * per_ride_payout, 2)
        shares.append(
            {
                "driver_share_id": 0,  # not persisted
                "driver_id": user_id,
                "driver_profile_id": profile_id,
                "driver_name": names.get(user_id),
                "qualifying_rides": ride_count,
                "share_pct": share_pct,
                "amount_usd": amount,
                "status": "preview",
                "paid_at": None,
            }
        )

    # Sort descending by rides for readability
    shares.sort(key=lambda s: s["qualifying_rides"], reverse=True)

    return {
        "year": year,
        "quarter": quarter,
        "total_platform_surplus_usd": round(surplus_usd, 2),
        "total_qualifying_rides": total_rides,
        "per_ride_payout_usd": per_ride_payout,
        "participating_drivers": len(shares),
        "driver_shares": shares,
    }


# ---------------------------------------------------------------------------
# Declare (persist)
# ---------------------------------------------------------------------------

async def declare_dividend(
    db: AsyncSession,
    year: int,
    quarter: int,
    surplus_usd: float,
    notes: str | None = None,
) -> CooperativeDividend:
    """Create a CooperativeDividend and all DriverDividendShare records.

    Raises ValueError if a distribution already exists for this period.
    """
    _quarter_date_range(year, quarter)  # validate

    # Check for existing
    existing = await db.execute(
        select(CooperativeDividend).where(
            CooperativeDividend.year == year,
            CooperativeDividend.quarter == quarter,
        )
    )
    if existing.scalar_one_or_none():
        raise ValueError(f"A dividend for Q{quarter} {year} already exists")

    driver_rows = await _driver_rides_in_period(db, year, quarter)
    total_rides = sum(r[2] for r in driver_rows)
    per_ride_payout = round(surplus_usd / total_rides, 4) if total_rides > 0 else 0.0

    dividend = CooperativeDividend(
        year=year,
        quarter=quarter,
        total_platform_surplus_usd=round(surplus_usd, 2),
        total_qualifying_rides=total_rides,
        per_ride_payout_usd=per_ride_payout,
        status=DividendStatus.pending,
        notes=notes,
    )
    db.add(dividend)
    await db.flush()  # get dividend.id

    for user_id, profile_id, ride_count in driver_rows:
        share_pct = round(ride_count / total_rides * 100, 4) if total_rides > 0 else 0.0
        amount = round(ride_count * per_ride_payout, 2)
        share = DriverDividendShare(
            dividend_id=dividend.id,
            driver_id=user_id,
            driver_profile_id=profile_id,
            qualifying_rides=ride_count,
            share_pct=share_pct,
            amount_usd=amount,
            status=DividendShareStatus.pending,
        )
        db.add(share)

    return dividend


# ---------------------------------------------------------------------------
# Admin state transitions
# ---------------------------------------------------------------------------

async def admin_approve_dividend(
    db: AsyncSession,
    dividend_id: int,
    admin_user_id: int,
) -> CooperativeDividend | None:
    """Approve a pending dividend for distribution.

    Returns None if dividend not found.
    Raises ValueError if not in pending status.
    """
    result = await db.execute(
        select(CooperativeDividend).where(CooperativeDividend.id == dividend_id)
    )
    dividend = result.scalar_one_or_none()
    if dividend is None:
        return None

    if dividend.status != DividendStatus.pending:
        raise ValueError(
            f"Cannot approve dividend in status '{dividend.status}' — must be pending"
        )

    dividend.status = DividendStatus.approved
    dividend.approved_by_user_id = admin_user_id
    dividend.approved_at = datetime.now(timezone.utc)
    return dividend


async def admin_distribute_dividend(
    db: AsyncSession,
    dividend_id: int,
) -> CooperativeDividend | None:
    """Mark all driver shares as paid and set the dividend as distributed.

    Returns None if dividend not found.
    Raises ValueError if not in approved status.
    """
    result = await db.execute(
        select(CooperativeDividend).where(CooperativeDividend.id == dividend_id)
    )
    dividend = result.scalar_one_or_none()
    if dividend is None:
        return None

    if dividend.status != DividendStatus.approved:
        raise ValueError(
            f"Cannot distribute dividend in status '{dividend.status}' — must be approved"
        )

    now = datetime.now(timezone.utc)

    # Mark all shares as paid
    shares_result = await db.execute(
        select(DriverDividendShare).where(
            DriverDividendShare.dividend_id == dividend_id,
            DriverDividendShare.status == DividendShareStatus.pending,
        )
    )
    for share in shares_result.scalars().all():
        share.status = DividendShareStatus.paid
        share.paid_at = now

    dividend.status = DividendStatus.distributed
    dividend.distributed_at = now
    return dividend


async def admin_cancel_dividend(
    db: AsyncSession,
    dividend_id: int,
    reason: str | None = None,
) -> CooperativeDividend | None:
    """Cancel a pending or approved dividend.

    Returns None if dividend not found.
    Raises ValueError if already distributed or already cancelled.
    """
    result = await db.execute(
        select(CooperativeDividend).where(CooperativeDividend.id == dividend_id)
    )
    dividend = result.scalar_one_or_none()
    if dividend is None:
        return None

    if dividend.status in (DividendStatus.distributed, DividendStatus.cancelled):
        raise ValueError(
            f"Cannot cancel dividend in status '{dividend.status}'"
        )

    # Cancel all pending shares
    shares_result = await db.execute(
        select(DriverDividendShare).where(
            DriverDividendShare.dividend_id == dividend_id,
            DriverDividendShare.status == DividendShareStatus.pending,
        )
    )
    for share in shares_result.scalars().all():
        share.status = DividendShareStatus.cancelled

    dividend.status = DividendStatus.cancelled
    dividend.cancellation_reason = reason
    return dividend


# ---------------------------------------------------------------------------
# Retrieval
# ---------------------------------------------------------------------------

async def list_dividends(db: AsyncSession) -> list[CooperativeDividend]:
    """All dividend distributions, newest first."""
    result = await db.execute(
        select(CooperativeDividend).order_by(
            CooperativeDividend.year.desc(),
            CooperativeDividend.quarter.desc(),
        )
    )
    return list(result.scalars().all())


async def get_dividend(db: AsyncSession, dividend_id: int) -> CooperativeDividend | None:
    """Fetch a single dividend with its shares pre-loaded."""
    result = await db.execute(
        select(CooperativeDividend)
        .options(selectinload(CooperativeDividend.shares))
        .where(CooperativeDividend.id == dividend_id)
    )
    return result.scalar_one_or_none()


async def get_driver_dividend_history(
    db: AsyncSession,
    driver_profile_id: int,
) -> list[dict]:
    """Return a driver's own share history across all distributions.

    Each entry includes the parent dividend's period and status so the driver
    can see when to expect payment.
    """
    result = await db.execute(
        select(DriverDividendShare, CooperativeDividend)
        .join(CooperativeDividend, DriverDividendShare.dividend_id == CooperativeDividend.id)
        .where(DriverDividendShare.driver_profile_id == driver_profile_id)
        .order_by(CooperativeDividend.year.desc(), CooperativeDividend.quarter.desc())
    )
    rows = result.all()

    history = []
    for share, dividend in rows:
        history.append(
            {
                "dividend_id": dividend.id,
                "year": dividend.year,
                "quarter": dividend.quarter,
                "qualifying_rides": share.qualifying_rides,
                "share_pct": float(share.share_pct),
                "amount_usd": float(share.amount_usd),
                "dividend_status": dividend.status,
                "share_status": share.status,
                "paid_at": share.paid_at,
            }
        )
    return history


async def build_dividend_detail(
    db: AsyncSession,
    dividend: CooperativeDividend,
) -> dict:
    """Build the full admin detail dict including driver names."""
    # Ensure shares are loaded
    if not dividend.shares:
        shares_result = await db.execute(
            select(DriverDividendShare).where(
                DriverDividendShare.dividend_id == dividend.id
            )
        )
        shares = list(shares_result.scalars().all())
    else:
        shares = list(dividend.shares)

    driver_ids = [s.driver_id for s in shares]
    names = await _get_driver_names(db, driver_ids)

    share_items = []
    for share in shares:
        share_items.append(
            {
                "driver_share_id": share.id,
                "driver_id": share.driver_id,
                "driver_profile_id": share.driver_profile_id,
                "driver_name": names.get(share.driver_id),
                "qualifying_rides": share.qualifying_rides,
                "share_pct": float(share.share_pct),
                "amount_usd": float(share.amount_usd),
                "status": share.status,
                "paid_at": share.paid_at,
            }
        )
    share_items.sort(key=lambda s: s["qualifying_rides"], reverse=True)

    return {
        "id": dividend.id,
        "year": dividend.year,
        "quarter": dividend.quarter,
        "total_platform_surplus_usd": float(dividend.total_platform_surplus_usd),
        "total_qualifying_rides": dividend.total_qualifying_rides,
        "per_ride_payout_usd": float(dividend.per_ride_payout_usd),
        "status": dividend.status,
        "approved_by_user_id": dividend.approved_by_user_id,
        "notes": dividend.notes,
        "cancellation_reason": dividend.cancellation_reason,
        "declared_at": dividend.declared_at,
        "approved_at": dividend.approved_at,
        "distributed_at": dividend.distributed_at,
        "shares": share_items,
    }
