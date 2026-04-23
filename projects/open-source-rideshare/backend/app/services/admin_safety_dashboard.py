"""Admin safety dashboard service.

Aggregates all active safety events across the platform into a single
consolidated view for admin operators.

Includes:
- Active SOS alerts (status = ACTIVE)
- Route deviation flags (IN_PROGRESS rides with route_deviation_flagged_at set)
- Speeding flags (IN_PROGRESS rides with speeding_flagged_at set)
- Expired check-in timers from the last 24 hours
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.check_in_timer import CheckInTimerStatus, RiderCheckInTimer
from app.models.ride import Ride, RideStatus
from app.models.safety import SOSAlert, SOSStatus
from app.schemas.admin_safety_dashboard import (
    AdminSafetyDashboard,
    ExpiredCheckInRow,
    RouteDeviationRow,
    SOSAlertRow,
    SpeedingFlagRow,
)

logger = logging.getLogger(__name__)


async def _fetch_active_sos(db: AsyncSession) -> list[SOSAlertRow]:
    result = await db.execute(
        select(SOSAlert).where(SOSAlert.status == SOSStatus.ACTIVE)
    )
    alerts = result.scalars().all()
    return [
        SOSAlertRow(
            id=a.id,
            user_id=a.user_id,
            ride_id=a.ride_id,
            latitude=a.latitude,
            longitude=a.longitude,
            message=a.message,
            created_at=a.created_at,
        )
        for a in alerts
    ]


async def _fetch_route_deviations(db: AsyncSession) -> list[RouteDeviationRow]:
    result = await db.execute(
        select(Ride).where(
            Ride.status == RideStatus.IN_PROGRESS,
            Ride.route_deviation_flagged_at.is_not(None),
        )
    )
    rides = result.scalars().all()
    return [
        RouteDeviationRow(
            ride_id=r.id,
            rider_id=r.rider_id,
            driver_id=r.driver_id,
            flagged_at=r.route_deviation_flagged_at,
        )
        for r in rides
    ]


async def _fetch_speeding_flags(db: AsyncSession) -> list[SpeedingFlagRow]:
    result = await db.execute(
        select(Ride).where(
            Ride.status == RideStatus.IN_PROGRESS,
            Ride.speeding_flagged_at.is_not(None),
        )
    )
    rides = result.scalars().all()
    return [
        SpeedingFlagRow(
            ride_id=r.id,
            rider_id=r.rider_id,
            driver_id=r.driver_id,
            flagged_at=r.speeding_flagged_at,
        )
        for r in rides
    ]


async def _fetch_expired_check_ins(db: AsyncSession) -> list[ExpiredCheckInRow]:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    result = await db.execute(
        select(RiderCheckInTimer).where(
            RiderCheckInTimer.status == CheckInTimerStatus.EXPIRED,
            RiderCheckInTimer.expires_at >= cutoff,
        )
    )
    timers = result.scalars().all()
    return [
        ExpiredCheckInRow(
            id=t.id,
            rider_id=t.rider_id,
            expires_at=t.expires_at,
            expired_notified_at=t.expired_notified_at,
        )
        for t in timers
    ]


async def get_safety_dashboard(db: AsyncSession) -> AdminSafetyDashboard:
    """Return a consolidated snapshot of all active safety events.

    Runs four DB queries in parallel via asyncio.gather for efficiency.
    Expired check-ins are limited to the last 24 hours to keep the list
    operationally relevant.
    """
    sos_alerts, route_deviations, speeding_flags, expired_check_ins = await asyncio.gather(
        _fetch_active_sos(db),
        _fetch_route_deviations(db),
        _fetch_speeding_flags(db),
        _fetch_expired_check_ins(db),
    )

    return AdminSafetyDashboard(
        active_sos_alerts=sos_alerts,
        route_deviation_flags=route_deviations,
        speeding_flags=speeding_flags,
        expired_check_ins=expired_check_ins,
        total_active_sos=len(sos_alerts),
        total_route_deviations=len(route_deviations),
        total_speeding_flags=len(speeding_flags),
        total_expired_check_ins=len(expired_check_ins),
    )
