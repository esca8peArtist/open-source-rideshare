"""Background check expiry tracking service.

Surfaces approaching and past expiry for driver background checks
and records alert notifications so duplicates are not sent.

Public functions
----------------
get_expiring_background_checks(db, days_ahead)
    -> list[ExpiringBackgroundCheckRow]
    Query BackgroundCheck rows where status == CLEAR and expires_at falls
    within the window [today - 1 day, today + days_ahead].

run_expiry_scan(db)
    -> dict {"alerts_sent": int, "by_type": dict}
    Find checks needing 60/30/7-day or expired alerts, record
    BackgroundCheckAlert rows for those not yet alerted, return summary.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.background_check import (
    BackgroundCheck,
    BackgroundCheckAlert,
    BackgroundCheckAlertType,
    BackgroundCheckStatus,
)
from app.schemas.background_check_expiry import ExpiringBackgroundCheckRow

# Alert thresholds in ascending order — we pick the first (smallest) one
# that covers the remaining days.  A check at 5 days matches SEVEN_DAY (≤7),
# not THIRTY_DAY (≤30), because we stop at the first matching entry.
_ALERT_THRESHOLDS: list[tuple[int, BackgroundCheckAlertType]] = [
    (7, BackgroundCheckAlertType.SEVEN_DAY),
    (30, BackgroundCheckAlertType.THIRTY_DAY),
    (60, BackgroundCheckAlertType.SIXTY_DAY),
]


async def get_expiring_background_checks(
    db: AsyncSession,
    days_ahead: int = 60,
) -> list[ExpiringBackgroundCheckRow]:
    """Return CLEAR background checks whose expiry date falls within the window.

    The window is [today - 1 day, today + days_ahead].  Including yesterday
    surfaces checks that expired very recently without pulling in old history.
    """
    today = date.today()
    lower_bound = today - timedelta(days=1)
    upper_bound = today + timedelta(days=days_ahead)

    result = await db.execute(
        select(BackgroundCheck).where(
            BackgroundCheck.status == BackgroundCheckStatus.CLEAR,
            BackgroundCheck.expires_at.isnot(None),
            BackgroundCheck.expires_at >= lower_bound,
            BackgroundCheck.expires_at <= upper_bound,
        )
    )
    checks = result.scalars().all()

    rows: list[ExpiringBackgroundCheckRow] = []
    for check in checks:
        days_until = (check.expires_at - today).days
        rows.append(
            ExpiringBackgroundCheckRow(
                check_id=check.id,
                driver_profile_id=check.driver_profile_id,
                expires_at=check.expires_at,
                days_until_expiry=days_until,
                status=check.status.value,
            )
        )

    # Sort: already-expired first (most negative), then soonest expiry
    rows.sort(key=lambda r: r.days_until_expiry)
    return rows


async def run_expiry_scan(db: AsyncSession) -> dict:
    """Scan CLEAR background checks and send alerts that have not been sent yet.

    For each check, we evaluate whether it is within a threshold window
    (60/30/7 days before expiry, or already expired).  If the corresponding
    alert type has not already been recorded for that check, we create a
    BackgroundCheckAlert row.

    Returns a summary dict: {"alerts_sent": int, "by_type": {"60_day": n, ...}}
    """
    today = date.today()
    now = datetime.now(tz=timezone.utc)

    # Fetch all CLEAR checks that have an expiry date at or before today + 60 days
    upper_bound = today + timedelta(days=60)
    result = await db.execute(
        select(BackgroundCheck).where(
            BackgroundCheck.status == BackgroundCheckStatus.CLEAR,
            BackgroundCheck.expires_at.isnot(None),
            BackgroundCheck.expires_at <= upper_bound,
        )
    )
    checks = result.scalars().all()

    if not checks:
        await db.commit()
        return {"alerts_sent": 0, "by_type": {}}

    check_ids = [c.id for c in checks]

    # Load all existing alerts for these checks in one query
    existing_result = await db.execute(
        select(BackgroundCheckAlert).where(
            BackgroundCheckAlert.background_check_id.in_(check_ids)
        )
    )
    existing_alerts = existing_result.scalars().all()

    # Build a set of (check_id, alert_type) tuples already recorded
    already_sent: set[tuple[int, BackgroundCheckAlertType]] = {
        (a.background_check_id, a.alert_type) for a in existing_alerts
    }

    by_type: dict[str, int] = {}
    new_alerts: list[BackgroundCheckAlert] = []

    for check in checks:
        days_until = (check.expires_at - today).days

        # Determine which alert type applies for this check right now
        alert_type: BackgroundCheckAlertType | None = None
        if days_until < 0:
            alert_type = BackgroundCheckAlertType.EXPIRED
        else:
            for threshold, candidate_type in _ALERT_THRESHOLDS:
                if days_until <= threshold:
                    alert_type = candidate_type
                    # Use the most specific (smallest) threshold
                    break

        if alert_type is None:
            continue

        key = (check.id, alert_type)
        if key in already_sent:
            continue

        alert = BackgroundCheckAlert(
            driver_profile_id=check.driver_profile_id,
            background_check_id=check.id,
            alert_type=alert_type,
            sent_at=now,
        )
        new_alerts.append(alert)
        already_sent.add(key)
        type_key = alert_type.value
        by_type[type_key] = by_type.get(type_key, 0) + 1

    for alert in new_alerts:
        db.add(alert)

    await db.commit()

    return {"alerts_sent": len(new_alerts), "by_type": by_type}
