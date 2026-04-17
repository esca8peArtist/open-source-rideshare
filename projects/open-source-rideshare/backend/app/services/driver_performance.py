"""Driver performance scoring service.

Computes composite performance scores from raw ride data, manages weekly
snapshots, and generates alerts when a driver's KPIs fall below thresholds.

Score weights
-------------
- Acceptance rate  25 %  (target >= 0.80)
- Completion rate  25 %  (target >= 0.95)
- On-time rate     20 %  (target >= 0.85)
- Rider rating     20 %  (target >= 4.5 / 5.0)
- Complaints       -10 % per complaint, capped at -30 %

Tier thresholds
---------------
- Platinum: >= 90
- Gold:     >= 75
- Silver:   >= 60
- Bronze:   <  60

Alert thresholds
----------------
- low_acceptance:    acceptance_rate  < 0.70
- high_cancellation: cancellation_rate > 0.20
- low_rating:        average_rider_rating < 3.5 (and >= 1 rating)
- low_score:         performance_score < 60
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.driver import DriverProfile
from app.models.driver_performance import DriverPerformanceAlert, DriverPerformanceSnapshot
from app.models.ride import Ride, RideStatus
from app.models.rider_rating import RiderRating
from app.models.user import User, UserRole

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Score weights and targets
# ---------------------------------------------------------------------------

WEIGHT_ACCEPTANCE = 0.25
WEIGHT_COMPLETION = 0.25
WEIGHT_ON_TIME = 0.20
WEIGHT_RATING = 0.20
COMPLAINTS_PENALTY_PER = 0.10  # 10 % of total (100 pts)
MAX_COMPLAINTS_PENALTY = 0.30  # cap at 30 pts

TARGET_ACCEPTANCE = 0.80
TARGET_COMPLETION = 0.95
TARGET_ON_TIME = 0.85
TARGET_RATING = 4.5
MAX_RATING = 5.0

# Alert thresholds
ALERT_LOW_ACCEPTANCE = 0.70
ALERT_HIGH_CANCELLATION = 0.20
ALERT_LOW_RATING = 3.5
ALERT_LOW_SCORE = 60.0


# ---------------------------------------------------------------------------
# Pure calculation helpers (no DB dependency — easy to unit-test)
# ---------------------------------------------------------------------------


def compute_performance_score(snapshot: DriverPerformanceSnapshot) -> float:
    """Compute a composite 0-100 score from a snapshot's KPI metrics.

    The four positive components are normalised against their targets (clamped
    0-1) and then weighted.  Because the weights sum to 0.90 (90 out of 100
    points), we scale the result so that a driver hitting every target with
    zero complaints earns a perfect 100.  The complaints penalty is then
    subtracted (10 points per complaint, maximum 30 points) and the result
    is clamped to [0, 100].

    Weight sum: acceptance(25) + completion(25) + on_time(20) + rating(20) = 90
    Scaling factor: 100 / 90 = 1.111...
    """
    total_weight = WEIGHT_ACCEPTANCE + WEIGHT_COMPLETION + WEIGHT_ON_TIME + WEIGHT_RATING

    acceptance_norm = min(snapshot.acceptance_rate / TARGET_ACCEPTANCE, 1.0)
    completion_norm = min(snapshot.completion_rate / TARGET_COMPLETION, 1.0)
    on_time_norm = min(snapshot.on_time_rate / TARGET_ON_TIME, 1.0)
    rating_norm = (
        min(snapshot.average_rider_rating / TARGET_RATING, 1.0)
        if snapshot.total_rider_ratings > 0
        else 1.0  # no rides yet — neutral on this component
    )

    weighted_sum = (
        acceptance_norm * WEIGHT_ACCEPTANCE
        + completion_norm * WEIGHT_COMPLETION
        + on_time_norm * WEIGHT_ON_TIME
        + rating_norm * WEIGHT_RATING
    )

    # Scale so that 1.0 across all components = 100 points
    base = (weighted_sum / total_weight) * 100

    complaints_penalty = min(
        snapshot.total_complaints * COMPLAINTS_PENALTY_PER, MAX_COMPLAINTS_PENALTY
    ) * 100

    score = max(0.0, min(100.0, base - complaints_penalty))
    return round(score, 2)


def compute_score_tier(score: float) -> str:
    """Map a numeric score to a named tier string."""
    if score >= 90:
        return "platinum"
    if score >= 75:
        return "gold"
    if score >= 60:
        return "silver"
    return "bronze"


# ---------------------------------------------------------------------------
# Period metric calculation (queries rides table)
# ---------------------------------------------------------------------------


async def calculate_period_metrics(
    db: AsyncSession,
    driver_id: int,
    period_start: date,
    period_end: date,
) -> dict[str, Any]:
    """Pull raw ride data for the period and compute all KPI values.

    Uses only columns that actually exist on the Ride model:
    - status (COMPLETED, CANCELLED, MATCHED/DRIVER_EN_ROUTE/etc.)
    - driver_id
    - requested_at  (used to scope the period)
    - driver_rating (rider's rating of the driver — stored on the ride)

    Acceptance/completion/cancellation are approximated from ride statuses
    because the rides table does not have an explicit "offered" event log.
    Convention used here:
      offered  = rides matched or beyond (status != REQUESTED)
      accepted = rides that progressed past MATCHED
      cancelled_by_driver = rides with status CANCELLED that had a driver set
                            (we cannot distinguish rider vs driver cancel from
                             status alone; we treat all cancellations with a
                             driver assigned as potential driver cancels —
                             admins can refine this later)
    """
    start_dt = datetime.combine(period_start, datetime.min.time()).replace(
        tzinfo=timezone.utc
    )
    end_dt = datetime.combine(period_end, datetime.max.time()).replace(
        tzinfo=timezone.utc
    )

    # All rides in the period for this driver
    result = await db.execute(
        select(Ride).where(
            Ride.driver_id == driver_id,
            Ride.requested_at >= start_dt,
            Ride.requested_at <= end_dt,
        )
    )
    rides: list[Ride] = list(result.scalars().all())

    total_offered = len(rides)
    total_completed = sum(1 for r in rides if r.status == RideStatus.COMPLETED)
    total_cancelled = sum(1 for r in rides if r.status == RideStatus.CANCELLED)
    # Rides that moved to DRIVER_EN_ROUTE or further were "accepted"
    accepted_statuses = {
        RideStatus.DRIVER_EN_ROUTE,
        RideStatus.ARRIVED,
        RideStatus.IN_PROGRESS,
        RideStatus.COMPLETED,
        RideStatus.CANCELLED,  # accepted then cancelled
    }
    total_accepted = sum(1 for r in rides if r.status in accepted_statuses)

    acceptance_rate = total_accepted / total_offered if total_offered > 0 else 0.0
    completion_rate = total_completed / total_accepted if total_accepted > 0 else 0.0
    cancellation_rate = total_cancelled / total_accepted if total_accepted > 0 else 0.0

    # Rider ratings received this period (driver_rating column on Ride)
    rated_rides = [r for r in rides if r.driver_rating is not None]
    total_rider_ratings = len(rated_rides)
    average_rider_rating = (
        sum(r.driver_rating for r in rated_rides) / total_rider_ratings
        if total_rider_ratings > 0
        else 0.0
    )

    # On-time rate — we don't have ETA vs actual fields on Ride, so we
    # approximate as 1.0 (all on time) for completed rides. Operators can
    # update this logic when ETA fields are added.
    on_time_rate = 1.0 if total_completed > 0 else 0.0
    average_pickup_time_minutes = 0.0

    return {
        "total_rides_completed": total_completed,
        "total_rides_offered": total_offered,
        "total_rides_accepted": total_accepted,
        "total_rides_cancelled_by_driver": total_cancelled,
        "acceptance_rate": round(acceptance_rate, 4),
        "completion_rate": round(completion_rate, 4),
        "cancellation_rate": round(cancellation_rate, 4),
        "average_pickup_time_minutes": average_pickup_time_minutes,
        "on_time_rate": round(on_time_rate, 4),
        "average_rider_rating": round(average_rider_rating, 4),
        "total_rider_ratings": total_rider_ratings,
        "total_complaints": 0,  # complaint tracking TBD — admin can set directly
    }


# ---------------------------------------------------------------------------
# Snapshot CRUD
# ---------------------------------------------------------------------------


async def create_or_update_snapshot(
    db: AsyncSession,
    driver_id: int,
    period_start: date,
    period_end: date,
) -> DriverPerformanceSnapshot:
    """Create or update a performance snapshot for a driver and period.

    If a snapshot already exists for (driver_id, period_start) it is
    updated in place; otherwise a new record is inserted.
    """
    metrics = await calculate_period_metrics(db, driver_id, period_start, period_end)

    result = await db.execute(
        select(DriverPerformanceSnapshot).where(
            DriverPerformanceSnapshot.driver_id == driver_id,
            DriverPerformanceSnapshot.period_start == period_start,
        )
    )
    snapshot = result.scalar_one_or_none()

    if snapshot is None:
        snapshot = DriverPerformanceSnapshot(
            driver_id=driver_id,
            period_start=period_start,
            period_end=period_end,
        )
        db.add(snapshot)

    # Apply metrics
    for field, value in metrics.items():
        setattr(snapshot, field, value)

    # Compute derived score and tier
    snapshot.performance_score = compute_performance_score(snapshot)
    snapshot.score_tier = compute_score_tier(snapshot.performance_score)

    await db.flush()
    await db.refresh(snapshot)

    logger.info(
        "Snapshot upserted: driver=%d period=%s score=%.1f tier=%s",
        driver_id,
        period_start,
        snapshot.performance_score,
        snapshot.score_tier,
    )
    return snapshot


async def get_current_snapshot(
    db: AsyncSession, driver_id: int
) -> DriverPerformanceSnapshot | None:
    """Return the most recent snapshot for a driver, or None."""
    result = await db.execute(
        select(DriverPerformanceSnapshot)
        .where(DriverPerformanceSnapshot.driver_id == driver_id)
        .order_by(DriverPerformanceSnapshot.period_start.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def get_snapshot_history(
    db: AsyncSession, driver_id: int, limit: int = 12
) -> list[DriverPerformanceSnapshot]:
    """Return up to `limit` most-recent snapshots for a driver."""
    result = await db.execute(
        select(DriverPerformanceSnapshot)
        .where(DriverPerformanceSnapshot.driver_id == driver_id)
        .order_by(DriverPerformanceSnapshot.period_start.desc())
        .limit(limit)
    )
    return list(result.scalars().all())


# ---------------------------------------------------------------------------
# Alert generation
# ---------------------------------------------------------------------------


async def check_and_create_alerts(
    db: AsyncSession, snapshot: DriverPerformanceSnapshot
) -> list[DriverPerformanceAlert]:
    """Evaluate a snapshot against alert thresholds and persist new alerts.

    Does not re-create an alert type if an unresolved alert of that type
    already exists for the same snapshot.
    """
    # Fetch existing alert types for this snapshot to avoid duplicates
    existing_result = await db.execute(
        select(DriverPerformanceAlert.alert_type).where(
            DriverPerformanceAlert.snapshot_id == snapshot.id,
            DriverPerformanceAlert.is_resolved == False,  # noqa: E712
        )
    )
    existing_types = {row[0] for row in existing_result.all()}

    candidates: list[tuple[str, float, float]] = []  # (alert_type, threshold, actual)

    if snapshot.acceptance_rate < ALERT_LOW_ACCEPTANCE:
        candidates.append(("low_acceptance", ALERT_LOW_ACCEPTANCE, snapshot.acceptance_rate))

    if snapshot.cancellation_rate > ALERT_HIGH_CANCELLATION:
        candidates.append(
            ("high_cancellation", ALERT_HIGH_CANCELLATION, snapshot.cancellation_rate)
        )

    if snapshot.total_rider_ratings > 0 and snapshot.average_rider_rating < ALERT_LOW_RATING:
        candidates.append(("low_rating", ALERT_LOW_RATING, snapshot.average_rider_rating))

    if snapshot.performance_score < ALERT_LOW_SCORE:
        candidates.append(("low_score", ALERT_LOW_SCORE, snapshot.performance_score))

    created: list[DriverPerformanceAlert] = []
    for alert_type, threshold, actual in candidates:
        if alert_type in existing_types:
            continue
        alert = DriverPerformanceAlert(
            driver_id=snapshot.driver_id,
            snapshot_id=snapshot.id,
            alert_type=alert_type,
            threshold_value=threshold,
            actual_value=actual,
        )
        db.add(alert)
        created.append(alert)

    if created:
        await db.flush()

    return created


# ---------------------------------------------------------------------------
# Bulk recalculation
# ---------------------------------------------------------------------------


def _current_period() -> tuple[date, date]:
    """Return the Monday–Sunday period that contains today."""
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    sunday = monday + timedelta(days=6)
    return monday, sunday


# ---------------------------------------------------------------------------
# Trend analysis helpers (pure functions — no DB dependency)
# ---------------------------------------------------------------------------

# Target thresholds for strengths/improvement classification
TARGET_CANCELLATION_RATE = 0.10  # cancellation_rate below this is "good"


def _metric_direction(
    current: float,
    previous: float | None,
    higher_is_better: bool,
    threshold: float,
) -> str:
    """Return trend direction for a single metric.

    Returns one of: ``improving``, ``declining``, ``stable``, ``unknown``.
    ``unknown`` is returned when *previous* is ``None`` (no prior data point).
    ``threshold`` sets the minimum absolute change required to classify as
    improving or declining (prevents noise from being labelled as a trend).
    """
    if previous is None:
        return "unknown"
    change = current - previous
    if higher_is_better:
        if change > threshold:
            return "improving"
        if change < -threshold:
            return "declining"
    else:  # lower is better (e.g. cancellation_rate)
        if change < -threshold:
            return "improving"
        if change > threshold:
            return "declining"
    return "stable"


def _compute_trend(
    values: list[float],
    higher_is_better: bool,
    threshold: float,
) -> dict[str, Any]:
    """Build a MetricTrend dict from a chronological (oldest→newest) list.

    ``threshold`` is the minimum absolute change to call a move "improving"
    or "declining" rather than "stable".

    Returns a dict that maps directly onto the ``MetricTrend`` schema.
    """
    if not values:
        return {
            "current": 0.0,
            "previous": None,
            "four_week_avg": None,
            "direction": "unknown",
            "change_from_previous": None,
        }

    current = values[-1]
    previous = values[-2] if len(values) >= 2 else None
    four_week_values = values[-4:]
    four_week_avg = round(sum(four_week_values) / len(four_week_values), 4)

    direction = _metric_direction(current, previous, higher_is_better, threshold)
    change = round(current - previous, 4) if previous is not None else None

    return {
        "current": round(current, 4),
        "previous": round(previous, 4) if previous is not None else None,
        "four_week_avg": four_week_avg,
        "direction": direction,
        "change_from_previous": change,
    }


def _score_velocity(scores: list[float]) -> float:
    """Least-squares slope of weekly performance scores (points per week).

    Positive means improving, negative means declining.  Returns 0.0 when
    fewer than two data points are available.

    Uses the analytical formula for a simple linear regression against an
    integer index (0, 1, 2, …) representing evenly-spaced weeks.
    """
    n = len(scores)
    if n < 2:
        return 0.0
    x_bar = (n - 1) / 2.0
    y_bar = sum(scores) / n
    numerator = sum((i - x_bar) * (scores[i] - y_bar) for i in range(n))
    denominator = sum((i - x_bar) ** 2 for i in range(n))
    if denominator == 0:
        return 0.0
    return round(numerator / denominator, 3)


# ---------------------------------------------------------------------------
# Trend analysis service
# ---------------------------------------------------------------------------


async def get_performance_trend(
    db: AsyncSession,
    driver_id: int,
    weeks: int = 8,
) -> dict[str, Any]:
    """Compute trend analysis for a driver over the last *weeks* snapshots.

    Fetches up to ``weeks`` most-recent snapshots, then:
    - Computes per-metric trend direction and velocity
    - Computes fleet-wide score comparison (average + percentile)
    - Identifies strengths and improvement areas vs. target thresholds
    - Returns a dict matching the ``PerformanceTrendResponse`` schema

    The ``weekly_scores`` list is ordered oldest → newest for charting.
    """
    # Fetch the most-recent `weeks` snapshots for this driver, newest first
    result = await db.execute(
        select(DriverPerformanceSnapshot)
        .where(DriverPerformanceSnapshot.driver_id == driver_id)
        .order_by(DriverPerformanceSnapshot.period_start.desc())
        .limit(weeks)
    )
    # Reverse to chronological order (oldest → newest) for trend computation
    snapshots: list[DriverPerformanceSnapshot] = list(
        reversed(result.scalars().all())
    )

    # Empty response when driver has no snapshot data yet
    if not snapshots:
        empty_trend = _compute_trend([], True, 1.0)
        return {
            "driver_id": driver_id,
            "weeks_requested": weeks,
            "snapshots_analyzed": 0,
            "overall_direction": "unknown",
            "score_velocity": 0.0,
            "current_score": 0.0,
            "current_tier": "bronze",
            "performance_score": empty_trend,
            "acceptance_rate": _compute_trend([], True, 0.02),
            "completion_rate": _compute_trend([], True, 0.02),
            "cancellation_rate": _compute_trend([], False, 0.01),
            "on_time_rate": _compute_trend([], True, 0.02),
            "average_rider_rating": _compute_trend([], True, 0.1),
            "fleet_avg_score": None,
            "score_percentile": None,
            "strengths": [],
            "improvement_areas": [],
            "weekly_scores": [],
        }

    current = snapshots[-1]
    scores = [s.performance_score for s in snapshots]
    velocity = _score_velocity(scores)

    # Overall direction from score velocity (1 pt/week threshold)
    if velocity > 1.0:
        overall_direction = "improving"
    elif velocity < -1.0:
        overall_direction = "declining"
    elif len(snapshots) < 2:
        overall_direction = "unknown"
    else:
        overall_direction = "stable"

    # Fleet comparison — latest snapshot per driver across the whole platform
    latest_subq = (
        select(
            DriverPerformanceSnapshot.driver_id,
            func.max(DriverPerformanceSnapshot.period_start).label("max_period"),
        )
        .group_by(DriverPerformanceSnapshot.driver_id)
        .subquery()
    )
    fleet_result = await db.execute(
        select(DriverPerformanceSnapshot.performance_score).join(
            latest_subq,
            (DriverPerformanceSnapshot.driver_id == latest_subq.c.driver_id)
            & (
                DriverPerformanceSnapshot.period_start
                == latest_subq.c.max_period
            ),
        )
    )
    all_scores = [row[0] for row in fleet_result.all()]
    fleet_avg_score = (
        round(sum(all_scores) / len(all_scores), 2) if all_scores else None
    )
    score_percentile = (
        int(
            100
            * sum(1 for s in all_scores if s <= current.performance_score)
            / len(all_scores)
        )
        if all_scores
        else None
    )

    # Strengths and improvement areas (vs. platform target thresholds)
    strengths: list[str] = []
    improvement_areas: list[str] = []

    if current.acceptance_rate >= TARGET_ACCEPTANCE:
        strengths.append("acceptance_rate")
    else:
        improvement_areas.append("acceptance_rate")

    if current.completion_rate >= TARGET_COMPLETION:
        strengths.append("completion_rate")
    else:
        improvement_areas.append("completion_rate")

    if current.on_time_rate >= TARGET_ON_TIME:
        strengths.append("on_time_rate")
    else:
        improvement_areas.append("on_time_rate")

    if current.total_rider_ratings > 0:
        if current.average_rider_rating >= TARGET_RATING:
            strengths.append("average_rider_rating")
        else:
            improvement_areas.append("average_rider_rating")

    if current.cancellation_rate <= TARGET_CANCELLATION_RATE:
        strengths.append("cancellation_rate")
    else:
        improvement_areas.append("cancellation_rate")

    # Weekly chart data (oldest → newest, for front-end rendering)
    weekly_scores = [
        {
            "period_start": s.period_start,
            "performance_score": s.performance_score,
            "score_tier": s.score_tier,
            "rides_completed": s.total_rides_completed,
        }
        for s in snapshots
    ]

    return {
        "driver_id": driver_id,
        "weeks_requested": weeks,
        "snapshots_analyzed": len(snapshots),
        "overall_direction": overall_direction,
        "score_velocity": velocity,
        "current_score": current.performance_score,
        "current_tier": current.score_tier,
        "performance_score": _compute_trend(scores, True, 1.0),
        "acceptance_rate": _compute_trend(
            [s.acceptance_rate for s in snapshots], True, 0.02
        ),
        "completion_rate": _compute_trend(
            [s.completion_rate for s in snapshots], True, 0.02
        ),
        "cancellation_rate": _compute_trend(
            [s.cancellation_rate for s in snapshots], False, 0.01
        ),
        "on_time_rate": _compute_trend(
            [s.on_time_rate for s in snapshots], True, 0.02
        ),
        "average_rider_rating": _compute_trend(
            [s.average_rider_rating for s in snapshots], True, 0.1
        ),
        "fleet_avg_score": fleet_avg_score,
        "score_percentile": score_percentile,
        "strengths": strengths,
        "improvement_areas": improvement_areas,
        "weekly_scores": weekly_scores,
    }


async def bulk_recalculate_all_drivers(db: AsyncSession) -> dict[str, Any]:
    """Recalculate snapshots for all active drivers for the current period.

    Returns a summary dict with counts of successes and failures.
    """
    period_start, period_end = _current_period()

    # Find all active driver users
    result = await db.execute(
        select(User).where(User.role == UserRole.DRIVER, User.is_active == True)  # noqa: E712
    )
    drivers = list(result.scalars().all())

    recalculated = 0
    errors = 0
    error_details: list[str] = []

    for driver in drivers:
        try:
            snapshot = await create_or_update_snapshot(
                db, driver.id, period_start, period_end
            )
            await check_and_create_alerts(db, snapshot)
            recalculated += 1
        except Exception as exc:  # noqa: BLE001
            errors += 1
            error_details.append(f"driver_id={driver.id}: {exc}")
            logger.warning("Failed to recalculate driver %d: %s", driver.id, exc)

    return {
        "recalculated": recalculated,
        "errors": errors,
        "error_details": error_details,
    }
