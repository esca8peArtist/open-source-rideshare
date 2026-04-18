import json
from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import and_, case, cast, Date, extract, func, literal_column, not_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.api.deps import require_admin
from app.config import settings
from app.db.database import get_db
from app.services.pricing import get_time_multipliers, set_pricing_overrides, set_time_multipliers
from app.schemas.demand_pricing import DemandPricingConfigResponse, DemandPricingConfigUpdate
from app.services.service_areas import (
    create_service_area,
    delete_service_area,
    get_service_area,
    list_service_areas,
    update_service_area,
)
from app.services.verification import VerificationError, get_verification_status, review_document
from app.models.audit import AuditLog
from app.models.driver import DriverProfile
from app.models.driver_shift import DriverShift, ShiftStatus
from app.models.feedback import Dispute, DisputeStatus, DisputeType, RideFeedback
from app.models.ride import CancellationCategory, Ride, RideStatus
from app.models.safety import SOSAlert, SOSStatus
from app.models.service_area import ServiceArea
from app.models.user import User, UserRole
from app.models.verification import DriverDocument, VerificationStatus
from app.models.payment import Payment, PaymentStatus, PaymentType
from app.schemas.feedback import DisputeResolve
from app.schemas.admin import (
    AdminBulkSetPreferenceRequest,
    AdminScheduledRidesListResponse,
    AdminDisputeListResponse,
    AdminDisputeResponse,
    AdminDriverResponse,
    AdminFeedbackListResponse,
    AdminFeedbackResponse,
    AdminNotificationLogEntry,
    AdminNotificationLogListResponse,
    AdminPaymentResponse,
    AdminRideResponse,
    AdminRiderResponse,
    AdminSetPreferenceRequest,
    AdminSOSAlertResponse,
    AdminSOSListResponse,
    AdminSOSResolveRequest,
    AdminUserPreferencesResponse,
    BulkActionResult,
    BulkDriverIdsRequest,
    BulkDriverSuspendRequest,
    BulkRiderIdsRequest,
    BulkRiderSuspendRequest,
    SOSActiveMapResponse,
    SOSMapPin,
    CancellationReasonBreakdown,
    CancellationStats,
    CancellationTimeseriesPoint,
    DashboardStats,
    DisputeStats,
    DriverActivityEntry,
    DriverActivityListResponse,
    DriverMetrics,
    DriverPanicFrequencyEntry,
    DriverPanicFrequencyResponse,
    DriverStatusChangeEntry,
    ActiveShiftEntry,
    ActiveShiftsResponse,
    DriverSafetyHistoryEntry,
    DriverSafetyHistoryResponse,
    DriverShiftEntry,
    DriverShiftHistoryResponse,
    DriverStatusHistoryResponse,
    DriversListResponse,
    FeedbackStats,
    PaginationResponse,
    PaymentsListResponse,
    PlatformSettings,
    RecentDriverStatusChangeEntry,
    RecentDriverStatusChangesResponse,
    RevenueDataPoint,
    RideActivityDataPoint,
    RideMetrics,
    RiderSafetyHistoryEntry,
    RiderSafetyHistoryResponse,
    RidersListResponse,
    RidesListResponse,
    SOSFrequencyEntry,
    SOSFrequencyResponse,
    SOSStats,
    SOSTimeseriesPoint,
    SuspendRequest,
    TimeMultiplierSchedule,
    TopDriverEntry,
    TopEarnerDriverEntry,
    TopEarnersResponse,
    TopSpenderRiderEntry,
    BroadcastRequest,
    BroadcastResult,
    BroadcastSegment,
    TripAnomalyEntry,
    TripAnomalyListResponse,
    UserSearchResponse,
    UserSearchResult,
    GeofenceViolationEntry,
    GeofenceViolationListResponse,
    GeofenceViolationType,
    SpeedingIncidentEntry,
    SpeedingIncidentListResponse,
    RouteDeviationIncidentEntry,
    RouteDeviationIncidentListResponse,
)
from app.schemas.service_area import (
    ServiceAreaCreate,
    ServiceAreaListResponse,
    ServiceAreaResponse,
    ServiceAreaUpdate,
)
from app.schemas.verification import (
    DocumentResponse,
    DocumentReviewRequest,
    VerificationStatusResponse,
)

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin)])


def _ride_to_response(ride: Ride) -> AdminRideResponse:
    return AdminRideResponse(
        id=ride.id,
        status=ride.status.value,
        pickup_address=ride.pickup_address,
        dropoff_address=ride.dropoff_address,
        estimated_fare=ride.estimated_fare,
        actual_fare=ride.actual_fare,
        distance_km=ride.distance_km,
        duration_min=ride.duration_min,
        tip_amount=ride.tip_amount,
        rider_id=ride.rider_id,
        driver_id=ride.driver_id,
        rider_name=ride.rider.name if ride.rider else None,
        driver_name=ride.driver.name if ride.driver else None,
        rider_rating=ride.rider_rating,
        driver_rating=ride.driver_rating,
        cancellation_reason=ride.cancellation_reason,
        requested_at=ride.requested_at,
        matched_at=ride.matched_at,
        started_at=ride.started_at,
        completed_at=ride.completed_at,
        cancelled_at=ride.cancelled_at,
        scheduled_for=ride.scheduled_for,
    )


def _driver_to_response(profile: DriverProfile) -> AdminDriverResponse:
    return AdminDriverResponse(
        id=profile.id,
        user_id=profile.user_id,
        user_name=profile.user.name if profile.user else None,
        user_phone=profile.user.phone if profile.user else None,
        vehicle_type=profile.vehicle_type,
        vehicle_make=profile.vehicle_make,
        vehicle_model=profile.vehicle_model,
        vehicle_year=profile.vehicle_year,
        vehicle_color=profile.vehicle_color,
        license_plate=profile.license_plate,
        license_number=profile.license_number,
        insurance_policy=profile.insurance_policy,
        background_check_status=profile.background_check_status,
        rating_avg=profile.rating_avg,
        total_trips=profile.total_trips,
        is_online=profile.is_online,
        is_approved=profile.is_approved,
        created_at=profile.created_at,
        updated_at=profile.updated_at,
    )


def _payment_to_response(payment: Payment) -> AdminPaymentResponse:
    ride = payment.ride
    return AdminPaymentResponse(
        id=payment.id,
        ride_id=payment.ride_id,
        amount=payment.amount,
        platform_fee=payment.platform_fee,
        driver_payout=payment.driver_payout,
        tip_amount=payment.tip_amount,
        status=payment.status.value,
        created_at=payment.created_at,
        rider_name=ride.rider.name if ride and ride.rider else None,
        driver_name=ride.driver.name if ride and ride.driver else None,
        pickup_address=ride.pickup_address if ride else None,
        dropoff_address=ride.dropoff_address if ride else None,
    )


RIDE_SORT_COLUMNS = {
    "requested_at": Ride.requested_at,
    "status": Ride.status,
    "estimated_fare": Ride.estimated_fare,
    "actual_fare": Ride.actual_fare,
}

DRIVER_SORT_COLUMNS = {
    "created_at": DriverProfile.created_at,
    "rating_avg": DriverProfile.rating_avg,
    "total_trips": DriverProfile.total_trips,
}

PAYMENT_SORT_COLUMNS = {
    "created_at": Payment.created_at,
    "amount": Payment.amount,
    "status": Payment.status,
}


# ---- Rides ----

@router.get("/rides", response_model=RidesListResponse)
async def list_rides(
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    status_filter: str | None = Query(None, alias="status"),
    search: str | None = None,
    sort_by: str = "requested_at",
    sort_dir: str = "desc",
    date_from: str | None = None,
    date_to: str | None = None,
):
    query = select(Ride).options(
        joinedload(Ride.rider), joinedload(Ride.driver)
    )

    if status_filter and status_filter != "all":
        query = query.where(Ride.status == RideStatus(status_filter))

    if search:
        query = query.where(
            or_(
                Ride.pickup_address.ilike(f"%{search}%"),
                Ride.dropoff_address.ilike(f"%{search}%"),
            )
        )

    if date_from:
        query = query.where(Ride.requested_at >= datetime.fromisoformat(date_from))
    if date_to:
        query = query.where(Ride.requested_at <= datetime.fromisoformat(date_to))

    count_query = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_query)).scalar() or 0

    col = RIDE_SORT_COLUMNS.get(sort_by, Ride.requested_at)
    order = col.desc() if sort_dir == "desc" else col.asc()
    query = query.order_by(order).offset((page - 1) * per_page).limit(per_page)

    result = await db.execute(query)
    rides = result.unique().scalars().all()

    return RidesListResponse(
        rides=[_ride_to_response(r) for r in rides],
        pagination=PaginationResponse(page=page, per_page=per_page, total=total),
    )


@router.get("/rides/{ride_id}", response_model=AdminRideResponse)
async def get_ride(ride_id: int, db: AsyncSession = Depends(get_db)):
    query = select(Ride).options(
        joinedload(Ride.rider), joinedload(Ride.driver)
    ).where(Ride.id == ride_id)
    result = await db.execute(query)
    ride = result.unique().scalar_one_or_none()
    if not ride:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ride not found")
    return _ride_to_response(ride)


# ---- Drivers ----

@router.get("/drivers", response_model=DriversListResponse)
async def list_drivers(
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    status_filter: str | None = Query(None, alias="status"),
    search: str | None = None,
    sort_by: str = "created_at",
    sort_dir: str = "desc",
):
    query = select(DriverProfile).options(joinedload(DriverProfile.user))

    if status_filter and status_filter != "all":
        if status_filter == "approved":
            query = query.where(DriverProfile.is_approved.is_(True))
        elif status_filter == "pending":
            query = query.where(DriverProfile.is_approved.is_(False))
        elif status_filter == "online":
            query = query.where(DriverProfile.is_online.is_(True))
        elif status_filter == "offline":
            query = query.where(
                DriverProfile.is_approved.is_(True),
                DriverProfile.is_online.is_(False),
            )

    if search:
        query = query.join(DriverProfile.user).where(
            or_(
                User.name.ilike(f"%{search}%"),
                User.phone.ilike(f"%{search}%"),
                DriverProfile.license_plate.ilike(f"%{search}%"),
            )
        )

    count_query = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_query)).scalar() or 0

    col = DRIVER_SORT_COLUMNS.get(sort_by, DriverProfile.created_at)
    order = col.desc() if sort_dir == "desc" else col.asc()
    query = query.order_by(order).offset((page - 1) * per_page).limit(per_page)

    result = await db.execute(query)
    drivers = result.unique().scalars().all()

    return DriversListResponse(
        drivers=[_driver_to_response(d) for d in drivers],
        pagination=PaginationResponse(page=page, per_page=per_page, total=total),
    )


@router.get("/drivers/activity", response_model=DriverActivityListResponse)
async def driver_activity_dashboard(
    is_online: bool | None = Query(None),
    is_approved: bool | None = Query(None),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    """Per-driver activity summary: recent trips, shift hours, and last-trip timestamp."""
    now = datetime.now(timezone.utc)
    cutoff_7d = now - timedelta(days=7)
    cutoff_30d = now - timedelta(days=30)

    base_filters = []
    if is_online is not None:
        base_filters.append(DriverProfile.is_online == is_online)
    if is_approved is not None:
        base_filters.append(DriverProfile.is_approved == is_approved)

    total = (await db.execute(
        select(func.count()).select_from(DriverProfile).where(*base_filters)
    )).scalar() or 0

    profiles_result = await db.execute(
        select(DriverProfile)
        .options(joinedload(DriverProfile.user))
        .where(*base_filters)
        .order_by(DriverProfile.id.asc())
        .offset((page - 1) * per_page)
        .limit(per_page)
    )
    profiles = profiles_result.unique().scalars().all()

    if not profiles:
        return DriverActivityListResponse(
            drivers=[],
            pagination=PaginationResponse(total=total, page=page, per_page=per_page),
        )

    driver_user_ids = [p.user_id for p in profiles]

    def _trips_agg(cutoff: datetime):
        return (
            select(Ride.driver_id, func.count().label("cnt"))
            .where(
                Ride.driver_id.in_(driver_user_ids),
                Ride.status == RideStatus.COMPLETED,
                Ride.completed_at >= cutoff,
            )
            .group_by(Ride.driver_id)
        )

    def _shift_agg(cutoff: datetime):
        return (
            select(DriverShift.driver_id, func.coalesce(func.sum(DriverShift.total_minutes), 0).label("mins"))
            .where(
                DriverShift.driver_id.in_(driver_user_ids),
                DriverShift.ended_at >= cutoff,
                DriverShift.total_minutes.isnot(None),
            )
            .group_by(DriverShift.driver_id)
        )

    trips_7d = {r.driver_id: r.cnt for r in (await db.execute(_trips_agg(cutoff_7d))).all()}
    trips_30d = {r.driver_id: r.cnt for r in (await db.execute(_trips_agg(cutoff_30d))).all()}
    shift_7d = {r.driver_id: r.mins for r in (await db.execute(_shift_agg(cutoff_7d))).all()}
    shift_30d = {r.driver_id: r.mins for r in (await db.execute(_shift_agg(cutoff_30d))).all()}

    last_trip_result = (await db.execute(
        select(Ride.driver_id, func.max(Ride.completed_at).label("last_at"))
        .where(
            Ride.driver_id.in_(driver_user_ids),
            Ride.status == RideStatus.COMPLETED,
        )
        .group_by(Ride.driver_id)
    )).all()
    last_trip_map = {r.driver_id: r.last_at for r in last_trip_result}

    entries = [
        DriverActivityEntry(
            driver_id=p.id,
            user_id=p.user_id,
            driver_name=p.user.name if p.user else None,
            is_online=p.is_online,
            is_approved=p.is_approved,
            rating_avg=p.rating_avg,
            total_trips=p.total_trips,
            trips_7d=trips_7d.get(p.user_id, 0),
            trips_30d=trips_30d.get(p.user_id, 0),
            shift_hours_7d=round((shift_7d.get(p.user_id) or 0) / 60, 2),
            shift_hours_30d=round((shift_30d.get(p.user_id) or 0) / 60, 2),
            last_trip_at=last_trip_map.get(p.user_id),
        )
        for p in profiles
    ]

    return DriverActivityListResponse(
        drivers=entries,
        pagination=PaginationResponse(total=total, page=page, per_page=per_page),
    )


_STATUS_EVENT_TYPES = [
    "driver_approved",
    "driver_suspended",
    "bulk_driver_approved",
    "bulk_driver_suspended",
    "bulk_driver_reactivated",
]

_ACTION_MAP = {
    "driver_approved": "approved",
    "driver_suspended": "suspended",
    "bulk_driver_approved": "approved",
    "bulk_driver_suspended": "suspended",
    "bulk_driver_reactivated": "reactivated",
}


def _parse_audit_reason(log: AuditLog) -> str | None:
    """Extract the suspension reason from metadata_json, if present."""
    if not log.metadata_json:
        return None
    try:
        data = json.loads(log.metadata_json)
        return data.get("reason")
    except (json.JSONDecodeError, AttributeError):
        return None


@router.get("/drivers/status-changes", response_model=RecentDriverStatusChangesResponse)
async def admin_get_recent_driver_status_changes(
    days: int = Query(7, ge=1, le=90),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Recent driver status changes (approve/suspend/reactivate) across all drivers.

    Returns events from the audit log ordered newest-first. Use ``days`` to
    control the lookback window (1–90 days).
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    base_query = (
        select(AuditLog)
        .where(
            AuditLog.target_type == "driver_profile",
            AuditLog.event_type.in_(_STATUS_EVENT_TYPES),
            AuditLog.timestamp >= cutoff,
        )
    )

    total = (await db.execute(
        select(func.count()).select_from(base_query.subquery())
    )).scalar() or 0

    result = await db.execute(
        base_query.order_by(AuditLog.timestamp.desc()).offset(skip).limit(limit)
    )
    logs = result.scalars().all()

    items = [
        RecentDriverStatusChangeEntry(
            id=log.id,
            timestamp=log.timestamp,
            event_type=log.event_type,
            action=_ACTION_MAP.get(log.event_type, log.event_type),
            driver_id=log.target_id,
            admin_id=log.actor_id,
            reason=_parse_audit_reason(log),
            description=log.description,
        )
        for log in logs
    ]

    return RecentDriverStatusChangesResponse(total=total, items=items)


@router.get("/drivers/{driver_id}/status-history", response_model=DriverStatusHistoryResponse)
async def admin_get_driver_status_history(
    driver_id: int,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Status-change history (approve/suspend/reactivate) for a single driver.

    Returns audit log entries for the given driver ordered newest-first. Returns
    404 if no driver profile with the given id exists.
    """
    profile_result = await db.execute(
        select(DriverProfile).where(DriverProfile.id == driver_id)
    )
    if profile_result.scalar_one_or_none() is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Driver not found")

    base_query = (
        select(AuditLog)
        .where(
            AuditLog.target_type == "driver_profile",
            AuditLog.target_id == driver_id,
            AuditLog.event_type.in_(_STATUS_EVENT_TYPES),
        )
    )

    total = (await db.execute(
        select(func.count()).select_from(base_query.subquery())
    )).scalar() or 0

    result = await db.execute(
        base_query.order_by(AuditLog.timestamp.desc()).offset(skip).limit(limit)
    )
    logs = result.scalars().all()

    items = [
        DriverStatusChangeEntry(
            id=log.id,
            timestamp=log.timestamp,
            event_type=log.event_type,
            action=_ACTION_MAP.get(log.event_type, log.event_type),
            admin_id=log.actor_id,
            reason=_parse_audit_reason(log),
            description=log.description,
        )
        for log in logs
    ]

    return DriverStatusHistoryResponse(driver_id=driver_id, total=total, items=items)


@router.get("/drivers/shifts/active", response_model=ActiveShiftsResponse)
async def admin_list_active_shifts(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> ActiveShiftsResponse:
    """All drivers currently on an active shift, newest-first by start time."""
    base_q = select(DriverShift).where(DriverShift.status == ShiftStatus.active)
    total = (await db.execute(select(func.count()).select_from(base_q.subquery()))).scalar() or 0

    result = await db.execute(
        base_q.order_by(DriverShift.started_at.desc()).offset(skip).limit(limit)
    )
    shifts = result.scalars().all()

    user_ids = [s.driver_id for s in shifts]
    profiles_by_user_id: dict[int, DriverProfile] = {}
    if user_ids:
        profiles_result = await db.execute(
            select(DriverProfile)
            .where(DriverProfile.user_id.in_(user_ids))
            .options(joinedload(DriverProfile.user))
        )
        profiles_by_user_id = {p.user_id: p for p in profiles_result.scalars().unique().all()}

    items = [
        ActiveShiftEntry(
            shift_id=s.id,
            driver_profile_id=profiles_by_user_id[s.driver_id].id if s.driver_id in profiles_by_user_id else 0,
            user_id=s.driver_id,
            driver_name=profiles_by_user_id[s.driver_id].user.name if s.driver_id in profiles_by_user_id else None,
            started_at=s.started_at,
            rides_completed=s.rides_completed,
        )
        for s in shifts
    ]

    return ActiveShiftsResponse(total=total, items=items)


@router.get("/drivers/{driver_id}/shift-history", response_model=DriverShiftHistoryResponse)
async def admin_get_driver_shift_history(
    driver_id: int,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    status_filter: str | None = Query(None, alias="status", description="Filter by status: active, completed, auto_ended."),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> DriverShiftHistoryResponse:
    """Shift session history for a single driver, newest-first.

    Returns 404 if the driver profile does not exist. Supports optional status
    filter and skip/limit pagination (max 200/page).
    """
    profile_result = await db.execute(
        select(DriverProfile).where(DriverProfile.id == driver_id)
    )
    profile = profile_result.scalar_one_or_none()
    if profile is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Driver not found")

    base_q = select(DriverShift).where(DriverShift.driver_id == profile.user_id)

    if status_filter is not None:
        try:
            target_status = ShiftStatus(status_filter.lower())
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Invalid status '{status_filter}'. Must be one of: active, completed, auto_ended.",
            )
        base_q = base_q.where(DriverShift.status == target_status)

    total = (await db.execute(select(func.count()).select_from(base_q.subquery()))).scalar() or 0
    result = await db.execute(
        base_q.order_by(DriverShift.started_at.desc()).offset(skip).limit(limit)
    )
    shifts = result.scalars().all()

    items = [
        DriverShiftEntry(
            id=s.id,
            status=s.status.value,
            started_at=s.started_at,
            ended_at=s.ended_at,
            total_minutes=s.total_minutes,
            rides_completed=s.rides_completed,
        )
        for s in shifts
    ]

    return DriverShiftHistoryResponse(driver_id=driver_id, total=total, items=items)


@router.get("/drivers/{driver_id}/safety-history", response_model=DriverSafetyHistoryResponse)
async def admin_get_driver_safety_history(
    driver_id: int,
    skip: int = Query(0, ge=0, description="Pagination offset."),
    limit: int = Query(50, ge=1, le=200, description="Maximum results per page."),
    status_filter: str | None = Query(None, alias="status", description="Filter by status: ACTIVE, RESOLVED, FALSE_ALARM."),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> DriverSafetyHistoryResponse:
    """Panic alert history for a single driver. Admin only.

    Returns all driver panic alerts for the given driver profile, newest-first.
    Supports optional filtering by status (ACTIVE/RESOLVED/FALSE_ALARM) and
    pagination via skip/limit. Returns 404 if the driver profile does not exist.
    """
    from app.schemas.driver_safety import DriverPanicAlertStatus
    from app.services.driver_safety import list_driver_panic_alerts

    profile_result = await db.execute(
        select(DriverProfile).where(DriverProfile.id == driver_id)
    )
    if profile_result.scalar_one_or_none() is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Driver not found")

    all_alerts = await list_driver_panic_alerts(db=db, driver_id=driver_id)

    if status_filter is not None:
        try:
            target_status = DriverPanicAlertStatus(status_filter.upper())
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Invalid status filter '{status_filter}'. Must be one of: ACTIVE, RESOLVED, FALSE_ALARM.",
            )
        all_alerts = [a for a in all_alerts if a["status"] == target_status]

    total = len(all_alerts)
    page_alerts = all_alerts[skip: skip + limit]

    items = [
        DriverSafetyHistoryEntry(
            id=a["id"],
            ride_id=a["ride_id"],
            rider_id=a["rider_id"],
            status=a["status"].value,
            location_lat=a["location_lat"],
            location_lng=a["location_lng"],
            triggered_at=a["triggered_at"],
            resolved_at=a["resolved_at"],
            resolved_by=a["resolved_by"],
            resolution_notes=a["resolution_notes"],
        )
        for a in page_alerts
    ]

    return DriverSafetyHistoryResponse(driver_id=driver_id, total=total, items=items)


@router.get("/drivers/{driver_id}", response_model=AdminDriverResponse)
async def get_driver(driver_id: int, db: AsyncSession = Depends(get_db)):
    query = select(DriverProfile).options(
        joinedload(DriverProfile.user)
    ).where(DriverProfile.id == driver_id)
    result = await db.execute(query)
    profile = result.unique().scalar_one_or_none()
    if not profile:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Driver not found")
    return _driver_to_response(profile)


@router.post("/drivers/{driver_id}/approve", status_code=status.HTTP_204_NO_CONTENT)
async def approve_driver(driver_id: int, admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(DriverProfile).where(DriverProfile.id == driver_id))
    profile = result.scalar_one_or_none()
    if not profile:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Driver not found")
    profile.is_approved = True
    profile.background_check_status = "approved"
    await db.commit()

    from app.services.audit_events import audit_admin_action
    await audit_admin_action(
        db, admin_id=admin.id, action="driver_approved",
        description=f"Driver profile #{driver_id} approved",
        target_type="driver_profile", target_id=driver_id,
    )


@router.post("/drivers/{driver_id}/suspend", status_code=status.HTTP_204_NO_CONTENT)
async def suspend_driver(
    driver_id: int, body: SuspendRequest, admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(DriverProfile).options(joinedload(DriverProfile.user)).where(DriverProfile.id == driver_id)
    )
    profile = result.unique().scalar_one_or_none()
    if not profile:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Driver not found")
    profile.is_approved = False
    profile.is_online = False
    profile.background_check_status = "suspended"
    if profile.user:
        profile.user.is_active = False
    await db.commit()

    from app.services.audit_events import audit_admin_action
    await audit_admin_action(
        db, admin_id=admin.id, action="driver_suspended",
        description=f"Driver profile #{driver_id} suspended: {body.reason}",
        target_type="driver_profile", target_id=driver_id,
        metadata={"reason": body.reason},
    )


@router.post("/drivers/{driver_id}/reactivate", status_code=status.HTTP_204_NO_CONTENT)
async def reactivate_driver(driver_id: int, admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(DriverProfile).options(joinedload(DriverProfile.user)).where(DriverProfile.id == driver_id)
    )
    profile = result.unique().scalar_one_or_none()
    if not profile:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Driver not found")
    profile.is_approved = True
    profile.background_check_status = "approved"
    if profile.user:
        profile.user.is_active = True
    await db.commit()


@router.post("/drivers/bulk-approve", response_model=BulkActionResult)
async def bulk_approve_drivers(
    body: BulkDriverIdsRequest,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Approve multiple driver profiles in a single request."""
    result = await db.execute(
        select(DriverProfile).where(DriverProfile.id.in_(body.driver_ids))
    )
    profiles = {p.id: p for p in result.scalars().all()}

    succeeded = []
    for driver_id in body.driver_ids:
        profile = profiles.get(driver_id)
        if profile is None:
            continue
        profile.is_approved = True
        profile.background_check_status = "approved"
        succeeded.append(driver_id)

    await db.commit()

    requested_set = set(body.driver_ids)
    succeeded_set = set(succeeded)
    not_found = sorted(requested_set - succeeded_set)

    from app.services.audit_events import audit_admin_action
    await audit_admin_action(
        db, admin_id=admin.id, action="bulk_driver_approved",
        description=f"Bulk approved {len(succeeded)} driver(s): {succeeded}",
        target_type="driver_profile", target_id=None,
        metadata={"succeeded": succeeded, "not_found": not_found},
    )

    return BulkActionResult(
        succeeded=succeeded,
        not_found=not_found,
        total_requested=len(body.driver_ids),
        total_succeeded=len(succeeded),
    )


@router.post("/drivers/bulk-suspend", response_model=BulkActionResult)
async def bulk_suspend_drivers(
    body: BulkDriverSuspendRequest,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Suspend multiple driver profiles in a single request."""
    result = await db.execute(
        select(DriverProfile).options(joinedload(DriverProfile.user)).where(DriverProfile.id.in_(body.driver_ids))
    )
    profiles = {p.id: p for p in result.unique().scalars().all()}

    succeeded = []
    for driver_id in body.driver_ids:
        profile = profiles.get(driver_id)
        if profile is None:
            continue
        profile.is_approved = False
        profile.is_online = False
        profile.background_check_status = "suspended"
        if profile.user:
            profile.user.is_active = False
        succeeded.append(driver_id)

    await db.commit()

    requested_set = set(body.driver_ids)
    succeeded_set = set(succeeded)
    not_found = sorted(requested_set - succeeded_set)

    from app.services.audit_events import audit_admin_action
    await audit_admin_action(
        db, admin_id=admin.id, action="bulk_driver_suspended",
        description=f"Bulk suspended {len(succeeded)} driver(s): {succeeded}. Reason: {body.reason}",
        target_type="driver_profile", target_id=None,
        metadata={"succeeded": succeeded, "not_found": not_found, "reason": body.reason},
    )

    return BulkActionResult(
        succeeded=succeeded,
        not_found=not_found,
        total_requested=len(body.driver_ids),
        total_succeeded=len(succeeded),
    )


@router.post("/drivers/bulk-reactivate", response_model=BulkActionResult)
async def bulk_reactivate_drivers(
    body: BulkDriverIdsRequest,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Reactivate multiple suspended driver profiles in a single request."""
    result = await db.execute(
        select(DriverProfile).options(joinedload(DriverProfile.user)).where(DriverProfile.id.in_(body.driver_ids))
    )
    profiles = {p.id: p for p in result.unique().scalars().all()}

    succeeded = []
    for driver_id in body.driver_ids:
        profile = profiles.get(driver_id)
        if profile is None:
            continue
        profile.is_approved = True
        profile.background_check_status = "approved"
        if profile.user:
            profile.user.is_active = True
        succeeded.append(driver_id)

    await db.commit()

    requested_set = set(body.driver_ids)
    succeeded_set = set(succeeded)
    not_found = sorted(requested_set - succeeded_set)

    from app.services.audit_events import audit_admin_action
    await audit_admin_action(
        db, admin_id=admin.id, action="bulk_driver_reactivated",
        description=f"Bulk reactivated {len(succeeded)} driver(s): {succeeded}",
        target_type="driver_profile", target_id=None,
        metadata={"succeeded": succeeded, "not_found": not_found},
    )

    return BulkActionResult(
        succeeded=succeeded,
        not_found=not_found,
        total_requested=len(body.driver_ids),
        total_succeeded=len(succeeded),
    )


# ---- Payments ----

@router.get("/payments", response_model=PaymentsListResponse)
async def list_payments(
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    status_filter: str | None = Query(None, alias="status"),
    date_from: str | None = None,
    date_to: str | None = None,
    sort_by: str = "created_at",
    sort_dir: str = "desc",
):
    query = select(Payment).options(
        joinedload(Payment.ride).joinedload(Ride.rider),
        joinedload(Payment.ride).joinedload(Ride.driver),
    )

    if status_filter and status_filter != "all":
        query = query.where(Payment.status == PaymentStatus(status_filter))

    if date_from:
        query = query.where(Payment.created_at >= datetime.fromisoformat(date_from))
    if date_to:
        query = query.where(Payment.created_at <= datetime.fromisoformat(date_to))

    count_query = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_query)).scalar() or 0

    col = PAYMENT_SORT_COLUMNS.get(sort_by, Payment.created_at)
    order = col.desc() if sort_dir == "desc" else col.asc()
    query = query.order_by(order).offset((page - 1) * per_page).limit(per_page)

    result = await db.execute(query)
    payments = result.unique().scalars().all()

    return PaymentsListResponse(
        payments=[_payment_to_response(p) for p in payments],
        pagination=PaginationResponse(page=page, per_page=per_page, total=total),
    )


@router.get("/payments/{payment_id}", response_model=AdminPaymentResponse)
async def get_payment(payment_id: int, db: AsyncSession = Depends(get_db)):
    query = select(Payment).options(
        joinedload(Payment.ride).joinedload(Ride.rider),
        joinedload(Payment.ride).joinedload(Ride.driver),
    ).where(Payment.id == payment_id)
    result = await db.execute(query)
    payment = result.unique().scalar_one_or_none()
    if not payment:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Payment not found")
    return _payment_to_response(payment)


# ---- Stats ----

@router.get("/stats", response_model=DashboardStats)
async def dashboard_stats(db: AsyncSession = Depends(get_db)):
    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    active_statuses = [
        RideStatus.REQUESTED, RideStatus.MATCHED,
        RideStatus.DRIVER_EN_ROUTE, RideStatus.ARRIVED, RideStatus.IN_PROGRESS,
    ]

    active_rides = (await db.execute(
        select(func.count()).select_from(Ride).where(Ride.status.in_(active_statuses))
    )).scalar() or 0

    online_drivers = (await db.execute(
        select(func.count()).select_from(DriverProfile).where(DriverProfile.is_online.is_(True))
    )).scalar() or 0

    revenue_today = (await db.execute(
        select(func.coalesce(func.sum(Payment.amount), 0.0)).where(
            Payment.status == PaymentStatus.COMPLETED,
            Payment.created_at >= today_start,
        )
    )).scalar() or 0.0

    total_users = (await db.execute(
        select(func.count()).select_from(User).where(User.is_active.is_(True))
    )).scalar() or 0

    rides_today = (await db.execute(
        select(func.count()).select_from(Ride).where(Ride.requested_at >= today_start)
    )).scalar() or 0

    completed_today = (await db.execute(
        select(func.count()).select_from(Ride).where(
            Ride.status == RideStatus.COMPLETED,
            Ride.completed_at >= today_start,
        )
    )).scalar() or 0

    cancelled_today = (await db.execute(
        select(func.count()).select_from(Ride).where(
            Ride.status == RideStatus.CANCELLED,
            Ride.cancelled_at >= today_start,
        )
    )).scalar() or 0

    return DashboardStats(
        active_rides=active_rides,
        online_drivers=online_drivers,
        revenue_today=float(revenue_today),
        total_users=total_users,
        rides_today=rides_today,
        completed_today=completed_today,
        cancelled_today=cancelled_today,
    )


@router.get("/stats/revenue", response_model=list[RevenueDataPoint])
async def revenue_timeseries(
    period: str = Query("month", pattern="^(week|month|year)$"),
    db: AsyncSession = Depends(get_db),
):
    now = datetime.now(timezone.utc)
    if period == "week":
        start = now - timedelta(days=7)
    elif period == "month":
        start = now - timedelta(days=30)
    else:
        start = now - timedelta(days=365)

    date_col = cast(Payment.created_at, Date)
    query = (
        select(
            date_col.label("date"),
            func.coalesce(func.sum(Payment.amount), 0.0).label("revenue"),
            func.count().label("rides"),
            func.coalesce(func.sum(Payment.tip_amount), 0.0).label("tips"),
        )
        .where(
            Payment.status == PaymentStatus.COMPLETED,
            Payment.created_at >= start,
        )
        .group_by(date_col)
        .order_by(date_col)
    )

    result = await db.execute(query)
    rows = result.all()

    return [
        RevenueDataPoint(
            date=str(row.date),
            revenue=float(row.revenue),
            rides=row.rides,
            tips=float(row.tips),
        )
        for row in rows
    ]


@router.get("/stats/ride-activity", response_model=list[RideActivityDataPoint])
async def ride_activity(
    period: str = Query("today", pattern="^(today|week)$"),
    db: AsyncSession = Depends(get_db),
):
    now = datetime.now(timezone.utc)
    if period == "today":
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    else:
        start = now - timedelta(days=7)

    hour_col = extract("hour", Ride.requested_at)
    query = (
        select(
            hour_col.label("hour"),
            func.count().label("rides"),
        )
        .where(Ride.requested_at >= start)
        .group_by(hour_col)
        .order_by(hour_col)
    )

    result = await db.execute(query)
    rows = result.all()

    return [
        RideActivityDataPoint(hour=f"{int(row.hour):02d}:00", rides=row.rides)
        for row in rows
    ]


# ---- Cancellation Stats ----


@router.get("/stats/cancellations", response_model=CancellationStats)
async def cancellation_stats(db: AsyncSession = Depends(get_db)):
    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = today_start - timedelta(days=7)

    total_cancellations = (await db.execute(
        select(func.count()).select_from(Ride).where(Ride.status == RideStatus.CANCELLED)
    )).scalar() or 0

    total_rides = (await db.execute(
        select(func.count()).select_from(Ride)
    )).scalar() or 0

    cancellation_rate = (total_cancellations / total_rides * 100) if total_rides > 0 else 0.0

    cancellations_today = (await db.execute(
        select(func.count()).select_from(Ride).where(
            Ride.status == RideStatus.CANCELLED,
            Ride.cancelled_at >= today_start,
        )
    )).scalar() or 0

    cancellations_this_week = (await db.execute(
        select(func.count()).select_from(Ride).where(
            Ride.status == RideStatus.CANCELLED,
            Ride.cancelled_at >= week_start,
        )
    )).scalar() or 0

    # Cancellation fees collected (completed payments)
    fees_collected = (await db.execute(
        select(func.coalesce(func.sum(Payment.amount), 0.0)).where(
            Payment.payment_type == PaymentType.CANCELLATION_FEE,
            Payment.status == PaymentStatus.COMPLETED,
        )
    )).scalar() or 0.0

    # Cancellation fees pending
    fees_pending = (await db.execute(
        select(func.coalesce(func.sum(Payment.amount), 0.0)).where(
            Payment.payment_type == PaymentType.CANCELLATION_FEE,
            Payment.status == PaymentStatus.PENDING,
        )
    )).scalar() or 0.0

    # Average time from request to cancellation (in minutes)
    avg_result = await db.execute(
        select(
            func.avg(
                extract("epoch", Ride.cancelled_at) - extract("epoch", Ride.requested_at)
            )
        ).where(
            Ride.status == RideStatus.CANCELLED,
            Ride.cancelled_at.isnot(None),
        )
    )
    avg_seconds = avg_result.scalar()
    avg_cancel_time_minutes = round(avg_seconds / 60, 1) if avg_seconds else None

    # Top cancellation reasons
    reason_query = (
        select(
            Ride.cancellation_reason.label("reason"),
            func.count().label("count"),
        )
        .where(
            Ride.status == RideStatus.CANCELLED,
            Ride.cancellation_reason.isnot(None),
            Ride.cancellation_reason != "",
        )
        .group_by(Ride.cancellation_reason)
        .order_by(func.count().desc())
        .limit(10)
    )
    reason_result = await db.execute(reason_query)
    reason_rows = reason_result.all()

    return CancellationStats(
        total_cancellations=total_cancellations,
        total_rides=total_rides,
        cancellation_rate=round(cancellation_rate, 1),
        cancellations_today=cancellations_today,
        cancellations_this_week=cancellations_this_week,
        fees_collected=float(fees_collected),
        fees_pending=float(fees_pending),
        avg_cancel_time_minutes=avg_cancel_time_minutes,
        top_reasons=[
            CancellationReasonBreakdown(reason=row.reason, count=row.count)
            for row in reason_rows
        ],
    )


@router.get("/stats/cancellations/timeseries", response_model=list[CancellationTimeseriesPoint])
async def cancellation_timeseries(
    period: str = Query("month", pattern="^(week|month|year)$"),
    db: AsyncSession = Depends(get_db),
):
    now = datetime.now(timezone.utc)
    if period == "week":
        start = now - timedelta(days=7)
    elif period == "month":
        start = now - timedelta(days=30)
    else:
        start = now - timedelta(days=365)

    date_col = cast(Ride.cancelled_at, Date)

    # Cancellation counts per day
    cancel_query = (
        select(
            date_col.label("date"),
            func.count().label("cancellations"),
        )
        .where(
            Ride.status == RideStatus.CANCELLED,
            Ride.cancelled_at >= start,
        )
        .group_by(date_col)
        .order_by(date_col)
    )
    cancel_result = await db.execute(cancel_query)
    cancel_rows = {str(row.date): row.cancellations for row in cancel_result.all()}

    # Cancellation fees collected per day
    fee_date_col = cast(Payment.created_at, Date)
    fee_query = (
        select(
            fee_date_col.label("date"),
            func.coalesce(func.sum(Payment.amount), 0.0).label("fees"),
        )
        .where(
            Payment.payment_type == PaymentType.CANCELLATION_FEE,
            Payment.status == PaymentStatus.COMPLETED,
            Payment.created_at >= start,
        )
        .group_by(fee_date_col)
        .order_by(fee_date_col)
    )
    fee_result = await db.execute(fee_query)
    fee_rows = {str(row.date): float(row.fees) for row in fee_result.all()}

    # Merge both datasets
    all_dates = sorted(set(cancel_rows.keys()) | set(fee_rows.keys()))
    return [
        CancellationTimeseriesPoint(
            date=d,
            cancellations=cancel_rows.get(d, 0),
            fees_collected=fee_rows.get(d, 0.0),
        )
        for d in all_dates
    ]


# ---- Settings ----

_platform_settings = {
    "base_fare": settings.base_fare,
    "per_km_rate": settings.per_km_rate,
    "per_min_rate": settings.per_minute_rate,
    "platform_fee_percent": 0.0,
    "max_search_radius_km": settings.driver_search_radius_km,
    "surge_multiplier": 1.0,
}


@router.get("/settings", response_model=PlatformSettings)
async def get_settings():
    return PlatformSettings(**_platform_settings)


@router.put("/settings", response_model=PlatformSettings)
async def update_settings(new_settings: PlatformSettings):
    _platform_settings.update(new_settings.model_dump())
    # Push pricing changes into the pricing engine so fares reflect admin config
    set_pricing_overrides({
        "base_fare": new_settings.base_fare,
        "per_km_rate": new_settings.per_km_rate,
        "per_minute_rate": new_settings.per_min_rate,
        "platform_fee_percent": new_settings.platform_fee_percent,
    })
    return PlatformSettings(**_platform_settings)


# ---- Time-of-day Multipliers ----

@router.get("/pricing/time-multipliers", response_model=TimeMultiplierSchedule)
async def get_time_multiplier_schedule():
    return TimeMultiplierSchedule(
        entries=[
            {"start_hour": e["start_hour"], "end_hour": e["end_hour"],
             "multiplier": e["multiplier"], "label": e["label"]}
            for e in get_time_multipliers()
        ]
    )


@router.put("/pricing/time-multipliers", response_model=TimeMultiplierSchedule)
async def update_time_multiplier_schedule(schedule: TimeMultiplierSchedule):
    set_time_multipliers([e.model_dump() for e in schedule.entries])
    return schedule


# ---- Driver Verification ----


@router.get("/drivers/{driver_id}/verification", response_model=VerificationStatusResponse)
async def get_driver_verification_status(
    driver_id: int,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(DriverProfile).where(DriverProfile.id == driver_id))
    profile = result.scalar_one_or_none()
    if not profile:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Driver not found")

    ver_status = await get_verification_status(db, driver_id)
    return VerificationStatusResponse(
        documents=[
            DocumentResponse(
                id=d.id,
                driver_profile_id=d.driver_profile_id,
                document_type=d.document_type.value,
                status=d.status.value,
                document_ref=d.document_ref,
                document_number=d.document_number,
                expiry_date=d.expiry_date,
                reviewed_by=d.reviewed_by,
                reviewed_at=d.reviewed_at,
                rejection_reason=d.rejection_reason,
                review_notes=d.review_notes,
                submitted_at=d.submitted_at,
            )
            for d in ver_status["documents"]
        ],
        missing_required=ver_status["missing_required"],
        all_required_approved=ver_status["all_required_approved"],
    )


@router.get("/verification/pending", response_model=list[DocumentResponse])
async def list_pending_documents(
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
):
    query = (
        select(DriverDocument)
        .where(DriverDocument.status == VerificationStatus.PENDING)
        .order_by(DriverDocument.submitted_at.asc())
        .offset((page - 1) * per_page)
        .limit(per_page)
    )
    result = await db.execute(query)
    docs = result.scalars().all()
    return [
        DocumentResponse(
            id=d.id,
            driver_profile_id=d.driver_profile_id,
            document_type=d.document_type.value,
            status=d.status.value,
            document_ref=d.document_ref,
            document_number=d.document_number,
            expiry_date=d.expiry_date,
            reviewed_by=d.reviewed_by,
            reviewed_at=d.reviewed_at,
            rejection_reason=d.rejection_reason,
            review_notes=d.review_notes,
            submitted_at=d.submitted_at,
        )
        for d in docs
    ]


@router.post("/verification/{document_id}/review", response_model=DocumentResponse)
async def review_driver_document(
    document_id: int,
    req: DocumentReviewRequest,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    try:
        new_status = VerificationStatus(req.status)
    except ValueError:
        raise HTTPException(status_code=422, detail=f"Invalid status: {req.status}")

    try:
        doc = await review_document(
            db,
            document_id=document_id,
            reviewer_id=admin.id,
            new_status=new_status,
            rejection_reason=req.rejection_reason,
            review_notes=req.review_notes,
        )
        await db.commit()
        await db.refresh(doc)
    except VerificationError as e:
        raise HTTPException(status_code=409, detail=str(e))

    from app.services.audit_events import audit_document_reviewed
    await audit_document_reviewed(
        db, document_id=doc.id, driver_profile_id=doc.driver_profile_id,
        reviewer_id=admin.id, decision=doc.status.value,
        reason=doc.rejection_reason,
    )

    return DocumentResponse(
        id=doc.id,
        driver_profile_id=doc.driver_profile_id,
        document_type=doc.document_type.value,
        status=doc.status.value,
        document_ref=doc.document_ref,
        document_number=doc.document_number,
        expiry_date=doc.expiry_date,
        reviewed_by=doc.reviewed_by,
        reviewed_at=doc.reviewed_at,
        rejection_reason=doc.rejection_reason,
        review_notes=doc.review_notes,
        submitted_at=doc.submitted_at,
    )


# ---- SOS Alert Monitoring ----


def _sos_to_response(alert: SOSAlert) -> AdminSOSAlertResponse:
    ride = alert.ride
    user = alert.user
    return AdminSOSAlertResponse(
        id=alert.id,
        user_id=alert.user_id,
        user_name=user.name if user else None,
        user_phone=user.phone if user else None,
        ride_id=alert.ride_id,
        ride_status=ride.status.value if ride else None,
        pickup_address=ride.pickup_address if ride else None,
        dropoff_address=ride.dropoff_address if ride else None,
        status=alert.status.value,
        latitude=alert.latitude,
        longitude=alert.longitude,
        message=alert.message,
        created_at=alert.created_at,
        resolved_at=alert.resolved_at,
        resolved_by=alert.resolved_by,
        resolution_notes=alert.resolution_notes,
    )


@router.get("/safety/sos", response_model=AdminSOSListResponse)
async def list_sos_alerts(
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    status_filter: str | None = Query(None, alias="status"),
):
    query = select(SOSAlert).options(
        joinedload(SOSAlert.user), joinedload(SOSAlert.ride)
    )

    if status_filter and status_filter != "all":
        query = query.where(SOSAlert.status == SOSStatus(status_filter))

    count_query = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_query)).scalar() or 0

    query = query.order_by(SOSAlert.created_at.desc()).offset((page - 1) * per_page).limit(per_page)
    result = await db.execute(query)
    alerts = result.unique().scalars().all()

    return AdminSOSListResponse(
        alerts=[_sos_to_response(a) for a in alerts],
        pagination=PaginationResponse(page=page, per_page=per_page, total=total),
    )


@router.get("/safety/sos/stats", response_model=SOSStats)
async def sos_stats(db: AsyncSession = Depends(get_db)):
    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    active_count = (await db.execute(
        select(func.count()).select_from(SOSAlert).where(SOSAlert.status == SOSStatus.ACTIVE)
    )).scalar() or 0

    resolved_today = (await db.execute(
        select(func.count()).select_from(SOSAlert).where(
            SOSAlert.status == SOSStatus.RESOLVED,
            SOSAlert.resolved_at >= today_start,
        )
    )).scalar() or 0

    false_alarms_today = (await db.execute(
        select(func.count()).select_from(SOSAlert).where(
            SOSAlert.status == SOSStatus.FALSE_ALARM,
            SOSAlert.resolved_at >= today_start,
        )
    )).scalar() or 0

    total_today = (await db.execute(
        select(func.count()).select_from(SOSAlert).where(SOSAlert.created_at >= today_start)
    )).scalar() or 0

    # Average resolution time for alerts resolved today
    avg_result = await db.execute(
        select(
            func.avg(
                extract("epoch", SOSAlert.resolved_at) - extract("epoch", SOSAlert.created_at)
            )
        ).where(
            SOSAlert.resolved_at.isnot(None),
            SOSAlert.resolved_at >= today_start,
        )
    )
    avg_seconds = avg_result.scalar()
    avg_minutes = round(avg_seconds / 60, 1) if avg_seconds else None

    return SOSStats(
        active_count=active_count,
        resolved_today=resolved_today,
        false_alarms_today=false_alarms_today,
        total_today=total_today,
        avg_resolution_minutes=avg_minutes,
    )


@router.get("/safety/sos/timeseries", response_model=list[SOSTimeseriesPoint])
async def sos_timeseries(
    period: str = Query("month", pattern="^(week|month|year)$"),
    db: AsyncSession = Depends(get_db),
):
    now = datetime.now(timezone.utc)
    if period == "week":
        start = now - timedelta(days=7)
    elif period == "month":
        start = now - timedelta(days=30)
    else:
        start = now - timedelta(days=365)

    date_col = cast(SOSAlert.created_at, Date)
    query = (
        select(
            date_col.label("date"),
            SOSAlert.status,
            func.count().label("cnt"),
        )
        .where(SOSAlert.created_at >= start)
        .group_by(date_col, SOSAlert.status)
        .order_by(date_col)
    )
    result = await db.execute(query)
    rows = result.all()

    # Aggregate per date
    by_date: dict[str, dict] = {}
    for row in rows:
        d = str(row.date)
        if d not in by_date:
            by_date[d] = {"active": 0, "resolved": 0, "false_alarms": 0}
        if row.status == SOSStatus.ACTIVE:
            by_date[d]["active"] += row.cnt
        elif row.status == SOSStatus.RESOLVED:
            by_date[d]["resolved"] += row.cnt
        elif row.status == SOSStatus.FALSE_ALARM:
            by_date[d]["false_alarms"] += row.cnt

    return [
        SOSTimeseriesPoint(
            date=d,
            total=v["active"] + v["resolved"] + v["false_alarms"],
            active=v["active"],
            resolved=v["resolved"],
            false_alarms=v["false_alarms"],
        )
        for d, v in sorted(by_date.items())
    ]


@router.get("/safety/sos/leaderboard", response_model=SOSFrequencyResponse)
async def sos_leaderboard(
    period: str = Query("all", pattern="^(week|month|year|all)$"),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    now = datetime.now(timezone.utc)
    period_starts = {
        "week": now - timedelta(days=7),
        "month": now - timedelta(days=30),
        "year": now - timedelta(days=365),
    }
    start = period_starts.get(period)

    base = select(
        SOSAlert.user_id,
        SOSAlert.status,
        func.count().label("cnt"),
        func.max(SOSAlert.created_at).label("last_sos_at"),
    )
    if start:
        base = base.where(SOSAlert.created_at >= start)
    base = base.group_by(SOSAlert.user_id, SOSAlert.status)

    rows = (await db.execute(base)).all()

    # Aggregate per user
    by_user: dict[int, dict] = {}
    for row in rows:
        uid = row.user_id
        if uid not in by_user:
            by_user[uid] = {"active": 0, "resolved": 0, "false_alarms": 0, "last_sos_at": row.last_sos_at}
        if row.status == SOSStatus.ACTIVE:
            by_user[uid]["active"] += row.cnt
        elif row.status == SOSStatus.RESOLVED:
            by_user[uid]["resolved"] += row.cnt
        elif row.status == SOSStatus.FALSE_ALARM:
            by_user[uid]["false_alarms"] += row.cnt
        if row.last_sos_at > by_user[uid]["last_sos_at"]:
            by_user[uid]["last_sos_at"] = row.last_sos_at

    if not by_user:
        return SOSFrequencyResponse(period=period, entries=[])

    # Sort by total descending, take top N
    sorted_uids = sorted(
        by_user.keys(),
        key=lambda uid: by_user[uid]["active"] + by_user[uid]["resolved"] + by_user[uid]["false_alarms"],
        reverse=True,
    )[:limit]

    # Fetch user info for top users
    user_rows = (
        await db.execute(select(User).where(User.id.in_(sorted_uids)))
    ).scalars().all()
    user_map = {u.id: u for u in user_rows}

    entries = []
    for uid in sorted_uids:
        v = by_user[uid]
        total = v["active"] + v["resolved"] + v["false_alarms"]
        u = user_map.get(uid)
        entries.append(
            SOSFrequencyEntry(
                user_id=uid,
                user_name=u.name if u else None,
                user_phone=u.phone if u else None,
                total=total,
                active=v["active"],
                resolved=v["resolved"],
                false_alarms=v["false_alarms"],
                false_alarm_rate=round(v["false_alarms"] / total * 100, 1) if total else 0.0,
                last_sos_at=v["last_sos_at"],
            )
        )

    return SOSFrequencyResponse(period=period, entries=entries)


@router.get("/safety/drivers/panic/leaderboard", response_model=DriverPanicFrequencyResponse)
async def driver_panic_leaderboard(
    period: str = Query("all", pattern="^(week|month|year|all)$"),
    limit: int = Query(20, ge=1, le=100),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Rank drivers by panic alert volume. Admin only.

    Useful for identifying drivers who trigger panic alerts frequently — whether
    due to genuine safety incidents or potential system abuse.

    Period filters: week (7d), month (30d), year (365d), all (default).
    Returns up to `limit` drivers (1–100, default 20) sorted by total descending.
    """
    from app.services.driver_safety import admin_list_all_driver_panic_alerts
    from app.schemas.driver_safety import DriverPanicAlertStatus

    now = datetime.now(timezone.utc)
    period_starts = {
        "week": now - timedelta(days=7),
        "month": now - timedelta(days=30),
        "year": now - timedelta(days=365),
    }
    period_start = period_starts.get(period)

    all_alerts = await admin_list_all_driver_panic_alerts(db=db, period_start=period_start)

    if not all_alerts:
        return DriverPanicFrequencyResponse(period=period, entries=[])

    # Aggregate by driver_id (this is the User.id of the driver, not profile id)
    by_driver: dict[int, dict] = {}
    for alert in all_alerts:
        did = alert["driver_id"]
        if did not in by_driver:
            by_driver[did] = {"active": 0, "resolved": 0, "false_alarms": 0, "last_panic_at": alert["triggered_at"]}
        if alert["status"] == DriverPanicAlertStatus.ACTIVE:
            by_driver[did]["active"] += 1
        elif alert["status"] == DriverPanicAlertStatus.RESOLVED:
            by_driver[did]["resolved"] += 1
        elif alert["status"] == DriverPanicAlertStatus.FALSE_ALARM:
            by_driver[did]["false_alarms"] += 1
        if alert["triggered_at"] > by_driver[did]["last_panic_at"]:
            by_driver[did]["last_panic_at"] = alert["triggered_at"]

    sorted_dids = sorted(
        by_driver.keys(),
        key=lambda did: by_driver[did]["active"] + by_driver[did]["resolved"] + by_driver[did]["false_alarms"],
        reverse=True,
    )[:limit]

    # Enrich with driver profile info — look up DriverProfile by user_id then fetch User
    profile_rows = (
        await db.execute(
            select(DriverProfile).options(joinedload(DriverProfile.user))
            .where(DriverProfile.user_id.in_(sorted_dids))
        )
    ).unique().scalars().all()
    profile_map = {p.user_id: p for p in profile_rows}

    entries = []
    for did in sorted_dids:
        v = by_driver[did]
        total = v["active"] + v["resolved"] + v["false_alarms"]
        profile = profile_map.get(did)
        driver_profile_id = profile.id if profile else did
        driver_name = profile.user.name if profile and profile.user else None
        driver_phone = profile.user.phone if profile and profile.user else None
        entries.append(
            DriverPanicFrequencyEntry(
                driver_profile_id=driver_profile_id,
                driver_name=driver_name,
                driver_phone=driver_phone,
                total=total,
                active=v["active"],
                resolved=v["resolved"],
                false_alarms=v["false_alarms"],
                false_alarm_rate=round(v["false_alarms"] / total * 100, 1) if total else 0.0,
                last_panic_at=v["last_panic_at"],
            )
        )

    return DriverPanicFrequencyResponse(period=period, entries=entries)


@router.get("/safety/sos/active-map", response_model=SOSActiveMapResponse)
async def sos_active_map(
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> SOSActiveMapResponse:
    """Snapshot of all active SOS alerts with location data for map display. Admin only.

    Returns every SOS alert currently in ACTIVE status, enriched with rider
    name/phone and seconds elapsed since the alert opened. Intended for polling
    by a dispatcher live-map view (e.g. refresh every 15–30 s). Alerts without
    a known location are included with latitude/longitude=None.
    """
    now = datetime.now(timezone.utc)
    result = await db.execute(
        select(SOSAlert)
        .options(joinedload(SOSAlert.user))
        .where(SOSAlert.status == SOSStatus.ACTIVE)
        .order_by(SOSAlert.created_at.asc())
    )
    alerts = result.unique().scalars().all()

    pins = [
        SOSMapPin(
            id=a.id,
            user_id=a.user_id,
            user_name=a.user.name if a.user else None,
            user_phone=a.user.phone if a.user else None,
            latitude=a.latitude,
            longitude=a.longitude,
            message=a.message,
            ride_id=a.ride_id,
            seconds_open=max(0, int((now - a.created_at).total_seconds())),
            created_at=a.created_at,
        )
        for a in alerts
    ]
    return SOSActiveMapResponse(pins=pins, total=len(pins), fetched_at=now)


@router.get("/safety/sos/{alert_id}", response_model=AdminSOSAlertResponse)
async def get_sos_alert(alert_id: int, db: AsyncSession = Depends(get_db)):
    query = select(SOSAlert).options(
        joinedload(SOSAlert.user), joinedload(SOSAlert.ride)
    ).where(SOSAlert.id == alert_id)
    result = await db.execute(query)
    alert = result.unique().scalar_one_or_none()
    if not alert:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="SOS alert not found")
    return _sos_to_response(alert)


@router.post("/safety/sos/{alert_id}/resolve", response_model=AdminSOSAlertResponse)
async def admin_resolve_sos(
    alert_id: int,
    req: AdminSOSResolveRequest,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(SOSAlert).options(
            joinedload(SOSAlert.user), joinedload(SOSAlert.ride)
        ).where(SOSAlert.id == alert_id)
    )
    alert = result.unique().scalar_one_or_none()
    if not alert:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="SOS alert not found")
    if alert.status != SOSStatus.ACTIVE:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Alert is not active")

    resolution_map = {
        "resolved": SOSStatus.RESOLVED,
        "false_alarm": SOSStatus.FALSE_ALARM,
    }
    new_status = resolution_map.get(req.resolution)
    if not new_status:
        raise HTTPException(status_code=422, detail=f"Invalid resolution: {req.resolution}")

    alert.status = new_status
    alert.resolved_at = datetime.now(timezone.utc)
    alert.resolved_by = admin.id
    alert.resolution_notes = req.notes
    await db.commit()
    await db.refresh(alert, ["user", "ride"])

    from app.services.audit_events import audit_sos_resolved
    await audit_sos_resolved(
        db, sos_id=alert.id, resolved_by=admin.id, status=req.resolution,
    )

    return _sos_to_response(alert)


# ---- Service Areas (Geofencing) ----


@router.get("/service-areas", response_model=ServiceAreaListResponse)
async def admin_list_service_areas(
    active_only: bool = False,
    db: AsyncSession = Depends(get_db),
):
    areas = await list_service_areas(db, active_only=active_only)
    return ServiceAreaListResponse(
        areas=[
            ServiceAreaResponse(
                id=a.id,
                name=a.name,
                description=a.description,
                is_active=a.is_active,
                created_at=a.created_at,
                updated_at=a.updated_at,
            )
            for a in areas
        ],
        total=len(areas),
    )


@router.post("/service-areas", response_model=ServiceAreaResponse, status_code=status.HTTP_201_CREATED)
async def admin_create_service_area(
    req: ServiceAreaCreate,
    db: AsyncSession = Depends(get_db),
):
    area = await create_service_area(
        db, name=req.name, coordinates=req.coordinates, description=req.description
    )
    await db.commit()
    await db.refresh(area)
    return ServiceAreaResponse(
        id=area.id,
        name=area.name,
        description=area.description,
        is_active=area.is_active,
        created_at=area.created_at,
        updated_at=area.updated_at,
    )


@router.get("/service-areas/{area_id}", response_model=ServiceAreaResponse)
async def admin_get_service_area(
    area_id: int,
    db: AsyncSession = Depends(get_db),
):
    area = await get_service_area(db, area_id)
    if not area:
        raise HTTPException(status_code=404, detail="Service area not found")
    return ServiceAreaResponse(
        id=area.id,
        name=area.name,
        description=area.description,
        is_active=area.is_active,
        created_at=area.created_at,
        updated_at=area.updated_at,
    )


@router.put("/service-areas/{area_id}", response_model=ServiceAreaResponse)
async def admin_update_service_area(
    area_id: int,
    req: ServiceAreaUpdate,
    db: AsyncSession = Depends(get_db),
):
    area = await update_service_area(
        db,
        area_id,
        name=req.name,
        coordinates=req.coordinates,
        description=req.description,
        is_active=req.is_active,
    )
    if not area:
        raise HTTPException(status_code=404, detail="Service area not found")
    await db.commit()
    await db.refresh(area)
    return ServiceAreaResponse(
        id=area.id,
        name=area.name,
        description=area.description,
        is_active=area.is_active,
        created_at=area.created_at,
        updated_at=area.updated_at,
    )


@router.delete("/service-areas/{area_id}", status_code=status.HTTP_204_NO_CONTENT)
async def admin_delete_service_area(
    area_id: int,
    db: AsyncSession = Depends(get_db),
):
    deleted = await delete_service_area(db, area_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Service area not found")
    await db.commit()


# ---- Dispute Management ----


def _dispute_to_admin_response(d: Dispute) -> AdminDisputeResponse:
    """Convert a Dispute model to admin response with related data."""
    filer_name = d.filer.name if d.filer else None
    resolver_name = d.resolver.name if d.resolver else None
    ride = d.ride
    # Determine filer role from ride relationship
    filer_role = None
    if ride:
        if d.filed_by == ride.rider_id:
            filer_role = "rider"
        elif d.filed_by == ride.driver_id:
            filer_role = "driver"

    return AdminDisputeResponse(
        id=d.id,
        ride_id=d.ride_id,
        filed_by=d.filed_by,
        filer_name=filer_name,
        filer_role=filer_role,
        dispute_type=d.dispute_type.value,
        status=d.status.value,
        description=d.description,
        resolution_notes=d.resolution_notes,
        resolved_by=d.resolved_by,
        resolver_name=resolver_name,
        refund_amount=d.refund_amount,
        created_at=d.created_at,
        updated_at=d.updated_at,
        resolved_at=d.resolved_at,
        ride_pickup=ride.pickup_address if ride else None,
        ride_dropoff=ride.dropoff_address if ride else None,
        ride_fare=ride.actual_fare or ride.estimated_fare if ride else None,
    )


@router.get("/disputes", response_model=AdminDisputeListResponse)
async def admin_list_disputes(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    status_filter: str | None = Query(None, alias="status"),
    dispute_type: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """List all disputes with filtering. Includes filer info and ride context."""
    query = select(Dispute).options(
        joinedload(Dispute.filer),
        joinedload(Dispute.resolver),
        joinedload(Dispute.ride),
    )
    if status_filter:
        query = query.where(Dispute.status == DisputeStatus(status_filter))
    if dispute_type:
        query = query.where(Dispute.dispute_type == DisputeType(dispute_type))

    count_q = select(func.count(Dispute.id))
    if status_filter:
        count_q = count_q.where(Dispute.status == DisputeStatus(status_filter))
    if dispute_type:
        count_q = count_q.where(Dispute.dispute_type == DisputeType(dispute_type))
    total = (await db.execute(count_q)).scalar() or 0

    query = query.order_by(Dispute.created_at.desc()).offset((page - 1) * per_page).limit(per_page)
    result = await db.execute(query)
    disputes = result.unique().scalars().all()

    return AdminDisputeListResponse(
        disputes=[_dispute_to_admin_response(d) for d in disputes],
        pagination=PaginationResponse(page=page, per_page=per_page, total=total),
    )


@router.get("/disputes/stats", response_model=DisputeStats)
async def admin_dispute_stats(
    db: AsyncSession = Depends(get_db),
):
    """Dispute dashboard statistics."""
    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    # Counts by status
    open_count = (await db.execute(
        select(func.count(Dispute.id)).where(Dispute.status == DisputeStatus.OPEN)
    )).scalar() or 0

    review_count = (await db.execute(
        select(func.count(Dispute.id)).where(Dispute.status == DisputeStatus.UNDER_REVIEW)
    )).scalar() or 0

    resolved_statuses = [
        DisputeStatus.RESOLVED_RIDER_FAVOR,
        DisputeStatus.RESOLVED_DRIVER_FAVOR,
        DisputeStatus.RESOLVED_PARTIAL,
        DisputeStatus.DISMISSED,
    ]
    resolved_today = (await db.execute(
        select(func.count(Dispute.id)).where(
            Dispute.status.in_(resolved_statuses),
            Dispute.resolved_at >= today_start,
        )
    )).scalar() or 0

    total_disputes = (await db.execute(select(func.count(Dispute.id)))).scalar() or 0

    # Average resolution time (hours) for resolved disputes
    avg_result = await db.execute(
        select(func.avg(
            extract("epoch", Dispute.resolved_at) - extract("epoch", Dispute.created_at)
        )).where(Dispute.resolved_at.isnot(None))
    )
    avg_seconds = avg_result.scalar()
    avg_hours = round(avg_seconds / 3600, 1) if avg_seconds else None

    # Total refunds issued
    refunds = (await db.execute(
        select(func.coalesce(func.sum(Dispute.refund_amount), 0.0)).where(
            Dispute.refund_amount.isnot(None)
        )
    )).scalar() or 0.0

    # Top dispute types
    type_counts = await db.execute(
        select(Dispute.dispute_type, func.count(Dispute.id).label("cnt"))
        .group_by(Dispute.dispute_type)
        .order_by(func.count(Dispute.id).desc())
        .limit(5)
    )
    top_types = [{"type": row[0].value, "count": row[1]} for row in type_counts.all()]

    return DisputeStats(
        open_count=open_count,
        under_review_count=review_count,
        resolved_today=resolved_today,
        total_disputes=total_disputes,
        avg_resolution_hours=avg_hours,
        refunds_issued_total=float(refunds),
        top_dispute_types=top_types,
    )


@router.get("/disputes/{dispute_id}", response_model=AdminDisputeResponse)
async def admin_get_dispute(
    dispute_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Get a single dispute with full context."""
    result = await db.execute(
        select(Dispute).options(
            joinedload(Dispute.filer),
            joinedload(Dispute.resolver),
            joinedload(Dispute.ride),
        ).where(Dispute.id == dispute_id)
    )
    dispute = result.unique().scalar_one_or_none()
    if not dispute:
        raise HTTPException(status_code=404, detail="Dispute not found")
    return _dispute_to_admin_response(dispute)


@router.post("/disputes/{dispute_id}/review", response_model=AdminDisputeResponse)
async def admin_review_dispute(
    dispute_id: int,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Move a dispute to under_review status."""
    from app.services.disputes import update_dispute_status

    try:
        dispute = await update_dispute_status(dispute_id, "under_review", db)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    if not dispute:
        raise HTTPException(status_code=404, detail="Dispute not found")

    # Reload with relationships
    result = await db.execute(
        select(Dispute).options(
            joinedload(Dispute.filer),
            joinedload(Dispute.resolver),
            joinedload(Dispute.ride),
        ).where(Dispute.id == dispute_id)
    )
    dispute = result.unique().scalar_one_or_none()
    return _dispute_to_admin_response(dispute)


@router.post("/disputes/{dispute_id}/resolve", response_model=AdminDisputeResponse)
async def admin_resolve_dispute(
    dispute_id: int,
    req: DisputeResolve,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Resolve a dispute with notes and optional refund."""
    from app.services.disputes import resolve_dispute

    try:
        dispute = await resolve_dispute(
            dispute_id=dispute_id,
            admin_id=admin.id,
            resolution_status=req.status,
            resolution_notes=req.resolution_notes,
            refund_amount=req.refund_amount,
            db=db,
        )
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    if not dispute:
        raise HTTPException(status_code=404, detail="Dispute not found")

    # Reload with relationships
    result = await db.execute(
        select(Dispute).options(
            joinedload(Dispute.filer),
            joinedload(Dispute.resolver),
            joinedload(Dispute.ride),
        ).where(Dispute.id == dispute_id)
    )
    dispute = result.unique().scalar_one_or_none()

    from app.services.audit_events import audit_dispute_resolved
    await audit_dispute_resolved(
        db, dispute_id=dispute_id, ride_id=dispute.ride_id,
        resolved_by=admin.id, resolution=req.status,
        refund_amount=req.refund_amount,
    )

    return _dispute_to_admin_response(dispute)


# ---- Feedback Overview ----


@router.get("/feedback", response_model=AdminFeedbackListResponse)
async def admin_list_feedback(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    role: str | None = Query(None),
    min_rating: int | None = Query(None, ge=1, le=5),
    max_rating: int | None = Query(None, ge=1, le=5),
    db: AsyncSession = Depends(get_db),
):
    """List all feedback with filtering by role and rating range."""
    query = select(RideFeedback).options(
        joinedload(RideFeedback.user),
        joinedload(RideFeedback.ride),
    )
    count_q = select(func.count(RideFeedback.id))

    if role:
        query = query.where(RideFeedback.role == role)
        count_q = count_q.where(RideFeedback.role == role)
    if min_rating is not None:
        query = query.where(RideFeedback.rating >= min_rating)
        count_q = count_q.where(RideFeedback.rating >= min_rating)
    if max_rating is not None:
        query = query.where(RideFeedback.rating <= max_rating)
        count_q = count_q.where(RideFeedback.rating <= max_rating)

    total = (await db.execute(count_q)).scalar() or 0

    query = query.order_by(RideFeedback.created_at.desc()).offset((page - 1) * per_page).limit(per_page)
    result = await db.execute(query)
    items = result.unique().scalars().all()

    return AdminFeedbackListResponse(
        feedback=[
            AdminFeedbackResponse(
                id=f.id,
                ride_id=f.ride_id,
                user_id=f.user_id,
                user_name=f.user.name if f.user else None,
                role=f.role,
                rating=f.rating,
                comment=f.comment,
                categories=f.categories.split(",") if f.categories else None,
                created_at=f.created_at,
                ride_pickup=f.ride.pickup_address if f.ride else None,
                ride_dropoff=f.ride.dropoff_address if f.ride else None,
            )
            for f in items
        ],
        pagination=PaginationResponse(page=page, per_page=per_page, total=total),
    )


@router.get("/feedback/stats", response_model=FeedbackStats)
async def admin_feedback_stats(
    db: AsyncSession = Depends(get_db),
):
    """Feedback dashboard statistics: averages, distribution, top categories."""
    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    total = (await db.execute(select(func.count(RideFeedback.id)))).scalar() or 0

    avg_driver = (await db.execute(
        select(func.avg(RideFeedback.rating)).where(RideFeedback.role == "rider")
    )).scalar()  # riders rate drivers

    avg_rider = (await db.execute(
        select(func.avg(RideFeedback.rating)).where(RideFeedback.role == "driver")
    )).scalar()  # drivers rate riders

    today_count = (await db.execute(
        select(func.count(RideFeedback.id)).where(RideFeedback.created_at >= today_start)
    )).scalar() or 0

    # Rating distribution
    dist_result = await db.execute(
        select(RideFeedback.rating, func.count(RideFeedback.id))
        .group_by(RideFeedback.rating)
        .order_by(RideFeedback.rating)
    )
    distribution = {str(row[0]): row[1] for row in dist_result.all()}

    # Top categories — parse comma-separated categories and count
    # Since categories are stored as comma-separated strings, count in Python
    cat_result = await db.execute(
        select(RideFeedback.categories).where(RideFeedback.categories.isnot(None))
    )
    cat_counts: dict[str, int] = {}
    for (cats_str,) in cat_result.all():
        for cat in cats_str.split(","):
            cat = cat.strip()
            if cat:
                cat_counts[cat] = cat_counts.get(cat, 0) + 1
    top_categories = sorted(
        [{"category": k, "count": v} for k, v in cat_counts.items()],
        key=lambda x: x["count"],
        reverse=True,
    )[:5]

    return FeedbackStats(
        total_feedback=total,
        avg_driver_rating=round(float(avg_driver), 2) if avg_driver else None,
        avg_rider_rating=round(float(avg_rider), 2) if avg_rider else None,
        feedback_today=today_count,
        rating_distribution=distribution,
        top_categories=top_categories,
    )


# ---- Ride Metrics Dashboard ----

DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


@router.get("/stats/ride-metrics", response_model=RideMetrics)
async def ride_metrics(
    period: str = Query("month", pattern="^(week|month|year)$"),
    db: AsyncSession = Depends(get_db),
):
    """Comprehensive ride performance metrics: funnel, timing, peaks."""
    now = datetime.now(timezone.utc)
    if period == "week":
        start = now - timedelta(days=7)
    elif period == "month":
        start = now - timedelta(days=30)
    else:
        start = now - timedelta(days=365)

    base_filter = Ride.requested_at >= start

    # Funnel counts
    total_requested = (await db.execute(
        select(func.count()).select_from(Ride).where(base_filter)
    )).scalar() or 0

    total_matched = (await db.execute(
        select(func.count()).select_from(Ride).where(
            base_filter, Ride.matched_at.isnot(None)
        )
    )).scalar() or 0

    total_completed = (await db.execute(
        select(func.count()).select_from(Ride).where(
            base_filter, Ride.status == RideStatus.COMPLETED
        )
    )).scalar() or 0

    total_cancelled = (await db.execute(
        select(func.count()).select_from(Ride).where(
            base_filter, Ride.status == RideStatus.CANCELLED
        )
    )).scalar() or 0

    match_rate = (total_matched / total_requested * 100) if total_requested else 0.0
    completion_rate = (total_completed / total_matched * 100) if total_matched else 0.0
    cancellation_rate = (total_cancelled / total_requested * 100) if total_requested else 0.0

    # Timing averages (only for completed rides with valid timestamps)
    timing_result = (await db.execute(
        select(
            func.avg(extract("epoch", Ride.matched_at - Ride.requested_at)).label("avg_wait"),
            func.avg(extract("epoch", Ride.started_at - Ride.matched_at)).label("avg_pickup"),
            func.avg(extract("epoch", Ride.completed_at - Ride.started_at)).label("avg_ride"),
            func.avg(extract("epoch", Ride.completed_at - Ride.requested_at)).label("avg_total"),
        ).where(
            base_filter,
            Ride.status == RideStatus.COMPLETED,
            Ride.matched_at.isnot(None),
            Ride.started_at.isnot(None),
            Ride.completed_at.isnot(None),
        )
    )).one()

    # Distance and fare averages
    dist_fare = (await db.execute(
        select(
            func.avg(Ride.distance_km).label("avg_dist"),
            func.avg(Ride.actual_fare).label("avg_fare"),
        ).where(
            base_filter,
            Ride.status == RideStatus.COMPLETED,
        )
    )).one()

    # Peak hours (top 24 hours sorted by ride count desc)
    hour_col = extract("hour", Ride.requested_at)
    peak_hours_result = await db.execute(
        select(
            hour_col.label("hour"),
            func.count().label("rides"),
        )
        .where(base_filter)
        .group_by(hour_col)
        .order_by(func.count().desc())
    )
    peak_hours = [
        {"hour": int(row.hour), "rides": row.rides}
        for row in peak_hours_result.all()
    ]

    # Peak days of week (0=Mon .. 6=Sun using isodow)
    dow_col = extract("isodow", Ride.requested_at)
    peak_days_result = await db.execute(
        select(
            dow_col.label("dow"),
            func.count().label("rides"),
        )
        .where(base_filter)
        .group_by(dow_col)
        .order_by(func.count().desc())
    )
    peak_days = [
        {"day_of_week": DAY_NAMES[int(row.dow) - 1], "rides": row.rides}
        for row in peak_days_result.all()
    ]

    return RideMetrics(
        period=period,
        funnel={
            "total_requested": total_requested,
            "total_matched": total_matched,
            "total_completed": total_completed,
            "total_cancelled": total_cancelled,
            "match_rate": round(match_rate, 2),
            "completion_rate": round(completion_rate, 2),
            "cancellation_rate": round(cancellation_rate, 2),
        },
        timing={
            "avg_wait_seconds": round(float(timing_result.avg_wait), 1) if timing_result.avg_wait else None,
            "avg_pickup_seconds": round(float(timing_result.avg_pickup), 1) if timing_result.avg_pickup else None,
            "avg_ride_duration_seconds": round(float(timing_result.avg_ride), 1) if timing_result.avg_ride else None,
            "avg_total_seconds": round(float(timing_result.avg_total), 1) if timing_result.avg_total else None,
        },
        avg_distance_km=round(float(dist_fare.avg_dist), 2) if dist_fare.avg_dist else None,
        avg_fare=round(float(dist_fare.avg_fare), 2) if dist_fare.avg_fare else None,
        peak_hours=peak_hours,
        peak_days=peak_days,
    )


# ---- Driver Metrics Dashboard ----


@router.get("/stats/driver-metrics", response_model=DriverMetrics)
async def driver_metrics(
    period: str = Query("month", pattern="^(week|month|year)$"),
    db: AsyncSession = Depends(get_db),
):
    """Driver performance and efficiency metrics."""
    now = datetime.now(timezone.utc)
    if period == "week":
        start = now - timedelta(days=7)
    elif period == "month":
        start = now - timedelta(days=30)
    else:
        start = now - timedelta(days=365)

    # Driver counts
    total_drivers = (await db.execute(
        select(func.count()).select_from(DriverProfile)
    )).scalar() or 0

    approved_drivers = (await db.execute(
        select(func.count()).select_from(DriverProfile).where(
            DriverProfile.is_approved.is_(True)
        )
    )).scalar() or 0

    online_now = (await db.execute(
        select(func.count()).select_from(DriverProfile).where(
            DriverProfile.is_online.is_(True)
        )
    )).scalar() or 0

    # Average rating across all approved drivers
    avg_rating = (await db.execute(
        select(func.avg(DriverProfile.rating_avg)).where(
            DriverProfile.is_approved.is_(True),
            DriverProfile.total_trips > 0,
        )
    )).scalar()

    # Average trips per driver (all-time from profile)
    avg_trips = (await db.execute(
        select(func.avg(DriverProfile.total_trips)).where(
            DriverProfile.is_approved.is_(True)
        )
    )).scalar()

    # Rides per active driver in period
    # Count completed rides in period, divide by number of distinct drivers who completed rides
    completed_in_period = (await db.execute(
        select(func.count()).select_from(Ride).where(
            Ride.completed_at >= start,
            Ride.status == RideStatus.COMPLETED,
        )
    )).scalar() or 0

    active_drivers_in_period = (await db.execute(
        select(func.count(func.distinct(Ride.driver_id))).where(
            Ride.completed_at >= start,
            Ride.status == RideStatus.COMPLETED,
            Ride.driver_id.isnot(None),
        )
    )).scalar() or 0

    rides_per_active = (
        completed_in_period / active_drivers_in_period
        if active_drivers_in_period else None
    )

    # Top 10 drivers by completed rides in period
    top_query = (
        select(
            Ride.driver_id,
            func.count().label("completed_count"),
        )
        .where(
            Ride.completed_at >= start,
            Ride.status == RideStatus.COMPLETED,
            Ride.driver_id.isnot(None),
        )
        .group_by(Ride.driver_id)
        .order_by(func.count().desc())
        .limit(10)
    )
    top_result = (await db.execute(top_query)).all()

    # Fetch driver profiles for top drivers
    top_driver_ids = [row.driver_id for row in top_result]
    top_drivers = []
    if top_driver_ids:
        profiles_result = await db.execute(
            select(DriverProfile).options(joinedload(DriverProfile.user)).where(
                DriverProfile.user_id.in_(top_driver_ids)
            )
        )
        profiles_by_user = {p.user_id: p for p in profiles_result.scalars().all()}

        for row in top_result:
            profile = profiles_by_user.get(row.driver_id)
            top_drivers.append(TopDriverEntry(
                driver_id=row.driver_id,
                driver_name=profile.user.name if profile and profile.user else None,
                total_trips=profile.total_trips if profile else 0,
                rating_avg=profile.rating_avg if profile else 0.0,
                completed_in_period=row.completed_count,
            ))

    # Rating distribution (1-5 buckets)
    rating_dist_result = await db.execute(
        select(
            case(
                (DriverProfile.rating_avg < 2.0, "1-2"),
                (DriverProfile.rating_avg < 3.0, "2-3"),
                (DriverProfile.rating_avg < 4.0, "3-4"),
                (DriverProfile.rating_avg < 4.5, "4-4.5"),
                else_="4.5-5",
            ).label("bucket"),
            func.count().label("count"),
        )
        .where(DriverProfile.is_approved.is_(True), DriverProfile.total_trips > 0)
        .group_by("bucket")
    )
    rating_distribution = {row.bucket: row.count for row in rating_dist_result.all()}

    return DriverMetrics(
        period=period,
        total_drivers=total_drivers,
        approved_drivers=approved_drivers,
        online_now=online_now,
        avg_rating=round(float(avg_rating), 2) if avg_rating else None,
        avg_trips_per_driver=round(float(avg_trips), 1) if avg_trips else None,
        rides_per_active_driver=round(float(rides_per_active), 1) if rides_per_active else None,
        top_drivers=top_drivers,
        rating_distribution=rating_distribution,
    )


# --- Demand Pricing Configuration ---


@router.get("/demand-pricing", response_model=DemandPricingConfigResponse)
async def get_demand_pricing_config(_admin=Depends(require_admin)):
    """Get current demand pricing configuration."""
    return DemandPricingConfigResponse(
        enabled=settings.demand_pricing_enabled,
        max_multiplier=settings.demand_pricing_max_multiplier,
        threshold=settings.demand_pricing_threshold,
        scale_factor=settings.demand_pricing_scale_factor,
    )


@router.put("/demand-pricing", response_model=DemandPricingConfigResponse)
async def update_demand_pricing_config(
    body: DemandPricingConfigUpdate,
    _admin=Depends(require_admin),
):
    """Update demand pricing configuration at runtime.

    Changes take effect immediately but do not persist across restarts.
    For permanent changes, set the corresponding OPENRIDE_ env vars.
    """
    if body.enabled is not None:
        settings.demand_pricing_enabled = body.enabled
    if body.max_multiplier is not None:
        if body.max_multiplier < 1.0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="max_multiplier must be >= 1.0",
            )
        settings.demand_pricing_max_multiplier = body.max_multiplier
    if body.threshold is not None:
        if body.threshold < 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="threshold must be >= 0",
            )
        settings.demand_pricing_threshold = body.threshold
    if body.scale_factor is not None:
        if body.scale_factor < 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="scale_factor must be >= 0",
            )
        settings.demand_pricing_scale_factor = body.scale_factor

    return DemandPricingConfigResponse(
        enabled=settings.demand_pricing_enabled,
        max_multiplier=settings.demand_pricing_max_multiplier,
        threshold=settings.demand_pricing_threshold,
        scale_factor=settings.demand_pricing_scale_factor,
    )


# ---- Document Verification ----


@router.get("/verification/documents")
async def list_documents(
    status_filter: str | None = Query(None, alias="status", pattern="^(pending|under_review|approved|rejected|expired)$"),
    document_type: str | None = Query(None, pattern="^(drivers_license|vehicle_registration|insurance|background_check|vehicle_inspection)$"),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """List all driver documents with optional filters."""
    from app.models.verification import DocumentType as DT

    query = select(DriverDocument).order_by(DriverDocument.submitted_at.desc())

    if status_filter:
        query = query.where(DriverDocument.status == VerificationStatus(status_filter))
    if document_type:
        query = query.where(DriverDocument.document_type == DT(document_type))

    # Count total
    from sqlalchemy import func as sqlfunc
    count_query = select(sqlfunc.count()).select_from(query.subquery())
    total = (await db.execute(count_query)).scalar() or 0

    # Paginate
    offset = (page - 1) * per_page
    result = await db.execute(query.offset(offset).limit(per_page))
    docs = result.scalars().all()

    return {
        "documents": [
            DocumentResponse(
                id=d.id,
                driver_profile_id=d.driver_profile_id,
                document_type=d.document_type.value,
                status=d.status.value,
                document_ref=d.document_ref,
                document_number=d.document_number,
                expiry_date=d.expiry_date,
                reviewed_by=d.reviewed_by,
                reviewed_at=d.reviewed_at,
                rejection_reason=d.rejection_reason,
                review_notes=d.review_notes,
                submitted_at=d.submitted_at,
            )
            for d in docs
        ],
        "total": total,
        "page": page,
        "per_page": per_page,
    }


@router.get("/verification/documents/{document_id}", response_model=DocumentResponse)
async def get_document(
    document_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Get a single document by ID."""
    result = await db.execute(
        select(DriverDocument).where(DriverDocument.id == document_id)
    )
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    return DocumentResponse(
        id=doc.id,
        driver_profile_id=doc.driver_profile_id,
        document_type=doc.document_type.value,
        status=doc.status.value,
        document_ref=doc.document_ref,
        document_number=doc.document_number,
        expiry_date=doc.expiry_date,
        reviewed_by=doc.reviewed_by,
        reviewed_at=doc.reviewed_at,
        rejection_reason=doc.rejection_reason,
        review_notes=doc.review_notes,
        submitted_at=doc.submitted_at,
    )


@router.post("/verification/documents/{document_id}/review", response_model=DocumentResponse)
async def review_driver_document(
    document_id: int,
    req: DocumentReviewRequest,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Admin reviews a document (approve, reject, or mark under_review)."""
    try:
        new_status = VerificationStatus(req.status)
    except ValueError:
        raise HTTPException(status_code=422, detail=f"Invalid status: {req.status}")

    try:
        doc = await review_document(
            db,
            document_id=document_id,
            reviewer_id=admin.id,
            new_status=new_status,
            rejection_reason=req.rejection_reason,
            review_notes=req.review_notes,
        )
        await db.commit()
        await db.refresh(doc)
    except VerificationError as e:
        detail = str(e)
        if "not found" in detail.lower():
            raise HTTPException(status_code=404, detail=detail)
        raise HTTPException(status_code=409, detail=detail)

    return DocumentResponse(
        id=doc.id,
        driver_profile_id=doc.driver_profile_id,
        document_type=doc.document_type.value,
        status=doc.status.value,
        document_ref=doc.document_ref,
        document_number=doc.document_number,
        expiry_date=doc.expiry_date,
        reviewed_by=doc.reviewed_by,
        reviewed_at=doc.reviewed_at,
        rejection_reason=doc.rejection_reason,
        review_notes=doc.review_notes,
        submitted_at=doc.submitted_at,
    )


@router.get("/verification/drivers/{driver_profile_id}", response_model=VerificationStatusResponse)
async def get_driver_verification_status(
    driver_profile_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Get verification status summary for a specific driver."""
    result = await db.execute(
        select(DriverProfile).where(DriverProfile.id == driver_profile_id)
    )
    profile = result.scalar_one_or_none()
    if not profile:
        raise HTTPException(status_code=404, detail="Driver profile not found")

    ver_status = await get_verification_status(db, driver_profile_id)
    return VerificationStatusResponse(
        documents=[
            DocumentResponse(
                id=d.id,
                driver_profile_id=d.driver_profile_id,
                document_type=d.document_type.value,
                status=d.status.value,
                document_ref=d.document_ref,
                document_number=d.document_number,
                expiry_date=d.expiry_date,
                reviewed_by=d.reviewed_by,
                reviewed_at=d.reviewed_at,
                rejection_reason=d.rejection_reason,
                review_notes=d.review_notes,
                submitted_at=d.submitted_at,
            )
            for d in ver_status["documents"]
        ],
        missing_required=ver_status["missing_required"],
        all_required_approved=ver_status["all_required_approved"],
    )


@router.get("/verification/stats")
async def get_verification_stats(
    db: AsyncSession = Depends(get_db),
):
    """Get aggregate verification statistics."""
    from sqlalchemy import func as sqlfunc

    # Count by status
    status_query = (
        select(
            DriverDocument.status,
            sqlfunc.count().label("count"),
        )
        .group_by(DriverDocument.status)
    )
    result = await db.execute(status_query)
    by_status = {row.status.value: row.count for row in result.all()}

    # Count by document type
    type_query = (
        select(
            DriverDocument.document_type,
            sqlfunc.count().label("count"),
        )
        .group_by(DriverDocument.document_type)
    )
    result = await db.execute(type_query)
    by_type = {row.document_type.value: row.count for row in result.all()}

    # Drivers with all required docs approved
    total_drivers = (await db.execute(select(sqlfunc.count()).select_from(DriverProfile))).scalar() or 0
    approved_drivers = (await db.execute(
        select(sqlfunc.count()).select_from(DriverProfile).where(DriverProfile.is_approved == True)
    )).scalar() or 0

    return {
        "by_status": by_status,
        "by_type": by_type,
        "total_documents": sum(by_status.values()),
        "total_drivers": total_drivers,
        "approved_drivers": approved_drivers,
        "pending_review": by_status.get("pending", 0) + by_status.get("under_review", 0),
    }


# ---- Notification Logs ----


@router.get("/notification-logs", response_model=AdminNotificationLogListResponse)
async def list_notification_logs(
    user_id: int | None = Query(None),
    notification_type: str | None = Query(None),
    channel: str | None = Query(None),
    status: str | None = Query(None),
    ride_id: int | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
) -> AdminNotificationLogListResponse:
    """List notification logs across all users. Admin only.

    Supports filtering by user, type, channel, delivery status, and ride.
    Results are ordered newest first.
    """
    from app.models.notification import NotificationLog

    query = select(NotificationLog)

    if user_id is not None:
        query = query.where(NotificationLog.user_id == user_id)
    if notification_type is not None:
        query = query.where(NotificationLog.notification_type == notification_type)
    if channel is not None:
        query = query.where(NotificationLog.channel == channel)
    if status is not None:
        query = query.where(NotificationLog.status == status)
    if ride_id is not None:
        query = query.where(NotificationLog.ride_id == ride_id)

    count_query = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_query)).scalar() or 0

    query = query.order_by(NotificationLog.created_at.desc()).offset(offset).limit(limit)
    result = await db.execute(query)
    logs = result.scalars().all()

    return AdminNotificationLogListResponse(
        logs=[AdminNotificationLogEntry.model_validate(log) for log in logs],
        total=total,
    )


# ---- Rider Management ----

def _rider_to_response(
    user: User,
    total_rides: int,
    completed_rides: int,
    cancelled_rides: int,
    avg_rider_rating: float | None,
) -> AdminRiderResponse:
    return AdminRiderResponse(
        id=user.id,
        name=user.name,
        phone=user.phone,
        email=user.email,
        is_active=user.is_active,
        phone_verified=user.phone_verified,
        referral_code=user.referral_code,
        created_at=user.created_at,
        total_rides=total_rides,
        completed_rides=completed_rides,
        cancelled_rides=cancelled_rides,
        avg_rider_rating=avg_rider_rating,
    )


@router.get("/riders", response_model=RidersListResponse)
async def list_riders(
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    search: str | None = Query(None, description="Filter by name or phone substring"),
    is_active: bool | None = Query(None, description="Filter by active/suspended status"),
    sort_by: str = Query("created_at", description="Field to sort by"),
    sort_dir: str = Query("desc", description="asc or desc"),
) -> RidersListResponse:
    """List all riders with optional filters. Admin only."""
    from app.models.ride import RideStatus

    query = select(User).where(User.role == "rider")

    if search:
        query = query.where(or_(User.name.ilike(f"%{search}%"), User.phone.ilike(f"%{search}%")))
    if is_active is not None:
        query = query.where(User.is_active == is_active)

    count_query = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_query)).scalar() or 0

    sort_col = {"name": User.name, "created_at": User.created_at, "phone": User.phone}.get(sort_by, User.created_at)
    if sort_dir == "asc":
        query = query.order_by(sort_col.asc())
    else:
        query = query.order_by(sort_col.desc())

    query = query.offset((page - 1) * per_page).limit(per_page)
    result = await db.execute(query)
    users = result.scalars().all()

    # Bulk fetch ride stats for all users on this page
    user_ids = [u.id for u in users]
    riders_data: list[AdminRiderResponse] = []
    if user_ids:
        stats_q = (
            select(
                Ride.rider_id,
                func.count(Ride.id).label("total"),
                func.sum(case((Ride.status == RideStatus.COMPLETED, 1), else_=0)).label("completed"),
                func.sum(case((Ride.status == RideStatus.CANCELLED, 1), else_=0)).label("cancelled"),
            )
            .where(Ride.rider_id.in_(user_ids))
            .group_by(Ride.rider_id)
        )
        stats_result = await db.execute(stats_q)
        stats_map = {row.rider_id: row for row in stats_result.all()}

        from app.models.rider_rating import RiderRating
        rating_q = (
            select(RiderRating.rider_id, func.avg(RiderRating.rating).label("avg_rating"))
            .where(RiderRating.rider_id.in_(user_ids))
            .group_by(RiderRating.rider_id)
        )
        rating_result = await db.execute(rating_q)
        rating_map = {row.rider_id: float(row.avg_rating) for row in rating_result.all()}

        for user in users:
            row = stats_map.get(user.id)
            riders_data.append(
                _rider_to_response(
                    user,
                    total_rides=int(row.total) if row else 0,
                    completed_rides=int(row.completed) if row else 0,
                    cancelled_rides=int(row.cancelled) if row else 0,
                    avg_rider_rating=rating_map.get(user.id),
                )
            )
    else:
        riders_data = []

    return RidersListResponse(
        riders=riders_data,
        pagination=PaginationResponse(page=page, per_page=per_page, total=total),
    )


@router.post("/riders/bulk-suspend", response_model=BulkActionResult)
async def bulk_suspend_riders(
    body: BulkRiderSuspendRequest,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> BulkActionResult:
    """Suspend multiple rider accounts in a single request. Admin only.

    Skips riders that are already suspended (not counted in succeeded).
    Returns not_found for any user_id that is not a rider. Supports 1–100 IDs.
    """
    result = await db.execute(
        select(User).where(User.id.in_(body.user_ids), User.role == "rider")
    )
    found = {u.id: u for u in result.scalars().all()}

    succeeded: list[int] = []
    not_found: list[int] = []
    for uid in body.user_ids:
        if uid not in found:
            not_found.append(uid)
            continue
        user = found[uid]
        if user.is_active:
            user.is_active = False
            succeeded.append(uid)

    if succeeded:
        await db.commit()
        from app.services.audit_events import audit_admin_action
        await audit_admin_action(
            db, admin_id=admin.id, action="bulk_rider_suspended",
            description=f"Bulk suspended {len(succeeded)} rider(s): {succeeded}. Reason: {body.reason}",
        )

    return BulkActionResult(
        succeeded=succeeded,
        not_found=not_found,
        total_requested=len(body.user_ids),
        total_succeeded=len(succeeded),
    )


@router.post("/riders/bulk-reactivate", response_model=BulkActionResult)
async def bulk_reactivate_riders(
    body: BulkRiderIdsRequest,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> BulkActionResult:
    """Reactivate multiple suspended rider accounts in a single request. Admin only.

    Skips riders that are already active (not counted in succeeded).
    Returns not_found for any user_id that is not a rider. Supports 1–100 IDs.
    """
    result = await db.execute(
        select(User).where(User.id.in_(body.user_ids), User.role == "rider")
    )
    found = {u.id: u for u in result.scalars().all()}

    succeeded: list[int] = []
    not_found: list[int] = []
    for uid in body.user_ids:
        if uid not in found:
            not_found.append(uid)
            continue
        user = found[uid]
        if not user.is_active:
            user.is_active = True
            succeeded.append(uid)

    if succeeded:
        await db.commit()
        from app.services.audit_events import audit_admin_action
        await audit_admin_action(
            db, admin_id=admin.id, action="bulk_rider_reactivated",
            description=f"Bulk reactivated {len(succeeded)} rider(s): {succeeded}",
        )

    return BulkActionResult(
        succeeded=succeeded,
        not_found=not_found,
        total_requested=len(body.user_ids),
        total_succeeded=len(succeeded),
    )


@router.get("/riders/{user_id}", response_model=AdminRiderResponse)
async def get_rider(user_id: int, db: AsyncSession = Depends(get_db)) -> AdminRiderResponse:
    """Get a single rider's details and ride statistics. Admin only."""
    from app.models.ride import RideStatus
    from app.models.rider_rating import RiderRating

    result = await db.execute(select(User).where(User.id == user_id, User.role == "rider"))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Rider not found")

    stats_q = (
        select(
            func.count(Ride.id).label("total"),
            func.sum(case((Ride.status == RideStatus.COMPLETED, 1), else_=0)).label("completed"),
            func.sum(case((Ride.status == RideStatus.CANCELLED, 1), else_=0)).label("cancelled"),
        )
        .where(Ride.rider_id == user_id)
    )
    stats_row = (await db.execute(stats_q)).one()

    rating_row = (
        await db.execute(
            select(func.avg(RiderRating.rating).label("avg_rating")).where(RiderRating.rider_id == user_id)
        )
    ).one()
    avg_rating = float(rating_row.avg_rating) if rating_row.avg_rating is not None else None

    return _rider_to_response(
        user,
        total_rides=int(stats_row.total) if stats_row.total else 0,
        completed_rides=int(stats_row.completed) if stats_row.completed else 0,
        cancelled_rides=int(stats_row.cancelled) if stats_row.cancelled else 0,
        avg_rider_rating=avg_rating,
    )


@router.post("/riders/{user_id}/suspend", status_code=status.HTTP_204_NO_CONTENT)
async def suspend_rider(
    user_id: int, body: SuspendRequest, admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db),
) -> None:
    """Suspend a rider account. Sets is_active=False. Admin only."""
    result = await db.execute(select(User).where(User.id == user_id, User.role == "rider"))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Rider not found")
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Rider is already suspended")
    user.is_active = False
    await db.commit()

    from app.services.audit_events import audit_admin_action
    await audit_admin_action(
        db, admin_id=admin.id, action="rider_suspended",
        description=f"Rider user #{user_id} suspended: {body.reason}",
        target_type="user", target_id=user_id,
        metadata={"reason": body.reason},
    )


@router.post("/riders/{user_id}/reactivate", status_code=status.HTTP_204_NO_CONTENT)
async def reactivate_rider(
    user_id: int, admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db),
) -> None:
    """Reactivate a suspended rider account. Sets is_active=True. Admin only."""
    result = await db.execute(select(User).where(User.id == user_id, User.role == "rider"))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Rider not found")
    if user.is_active:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Rider is already active")
    user.is_active = True
    await db.commit()

    from app.services.audit_events import audit_admin_action
    await audit_admin_action(
        db, admin_id=admin.id, action="rider_reactivated",
        description=f"Rider user #{user_id} reactivated",
        target_type="user", target_id=user_id,
    )


@router.get("/riders/{rider_id}/safety-history", response_model=RiderSafetyHistoryResponse)
async def admin_get_rider_safety_history(
    rider_id: int,
    skip: int = Query(0, ge=0, description="Pagination offset."),
    limit: int = Query(50, ge=1, le=200, description="Maximum results per page."),
    status_filter: str | None = Query(None, alias="status", description="Filter by status: active, resolved, false_alarm."),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> RiderSafetyHistoryResponse:
    """SOS alert history for a single rider. Admin only.

    Returns all SOS alerts triggered by the given rider, newest-first.
    Supports optional filtering by status (active/resolved/false_alarm) and
    pagination via skip/limit. Returns 404 if the rider does not exist.
    """
    user_result = await db.execute(
        select(User).where(User.id == rider_id, User.role == "rider")
    )
    if user_result.scalar_one_or_none() is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Rider not found")

    base_query = select(SOSAlert).where(SOSAlert.user_id == rider_id)

    if status_filter is not None:
        try:
            base_query = base_query.where(SOSAlert.status == SOSStatus(status_filter))
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Invalid status filter '{status_filter}'. Must be one of: active, resolved, false_alarm.",
            )

    total = (await db.execute(
        select(func.count()).select_from(base_query.subquery())
    )).scalar() or 0

    result = await db.execute(
        base_query.order_by(SOSAlert.created_at.desc()).offset(skip).limit(limit)
    )
    alerts = result.scalars().all()

    items = [
        RiderSafetyHistoryEntry(
            id=a.id,
            ride_id=a.ride_id,
            status=a.status.value,
            lat=a.latitude,
            lng=a.longitude,
            message=a.message,
            triggered_at=a.created_at,
            resolved_at=a.resolved_at,
            resolved_by=a.resolved_by,
            resolution_notes=a.resolution_notes,
        )
        for a in alerts
    ]

    return RiderSafetyHistoryResponse(rider_id=rider_id, total=total, items=items)


# ---- Top Earners / Spenders Leaderboard ----


@router.get("/stats/top-earners", response_model=TopEarnersResponse)
async def top_earners(
    role: str = Query("driver", pattern="^(driver|rider)$", description="driver or rider"),
    period: str = Query("month", pattern="^(week|month|year|all)$"),
    limit: int = Query(10, ge=1, le=50),
    _admin=Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Top drivers by earnings or top riders by spending for a given period.

    Admin only.

    For role=driver: ranks drivers by sum of actual_fare on completed rides.
    For role=rider: ranks riders by sum of actual_fare on completed rides they took.
    Returns up to `limit` entries (default 10, max 50).
    """
    now = datetime.now(timezone.utc)
    if period == "week":
        start = now - timedelta(days=7)
    elif period == "month":
        start = now - timedelta(days=30)
    elif period == "year":
        start = now - timedelta(days=365)
    else:
        start = datetime(2000, 1, 1, tzinfo=timezone.utc)

    base_filter = [
        Ride.status == RideStatus.COMPLETED,
        Ride.completed_at >= start,
    ]

    if role == "driver":
        group_col = Ride.driver_id
        id_label = "user_id"
        base_filter.append(Ride.driver_id.isnot(None))
    else:
        group_col = Ride.rider_id
        id_label = "user_id"

    fare_expr = func.coalesce(Ride.actual_fare, Ride.estimated_fare)

    rows_result = await db.execute(
        select(
            group_col.label("user_id"),
            func.count().label("completed_trips"),
            func.sum(fare_expr).label("total_earned"),
            func.avg(fare_expr).label("avg_fare"),
        )
        .where(*base_filter)
        .group_by(group_col)
        .order_by(func.sum(fare_expr).desc())
        .limit(limit)
    )
    rows = rows_result.all()

    user_ids = [r.user_id for r in rows]
    users_by_id: dict[int, User] = {}
    if user_ids:
        users_result = await db.execute(
            select(User).where(User.id.in_(user_ids))
        )
        users_by_id = {u.id: u for u in users_result.scalars().all()}

    if role == "driver":
        entries = [
            TopEarnerDriverEntry(
                driver_id=row.user_id,
                driver_name=users_by_id[row.user_id].name if row.user_id in users_by_id else "Unknown",
                completed_trips=row.completed_trips,
                total_earned_dollars=round(float(row.total_earned or 0), 2),
                avg_fare_dollars=round(float(row.avg_fare or 0), 2),
            )
            for row in rows
        ]
    else:
        entries = [
            TopSpenderRiderEntry(
                rider_id=row.user_id,
                rider_name=users_by_id[row.user_id].name if row.user_id in users_by_id else "Unknown",
                completed_trips=row.completed_trips,
                total_spent_dollars=round(float(row.total_earned or 0), 2),
                avg_fare_dollars=round(float(row.avg_fare or 0), 2),
            )
            for row in rows
        ]

    return TopEarnersResponse(period=period, role=role, entries=entries)


# ---- Unified User Search ----


@router.get("/users/search", response_model=UserSearchResponse)
async def search_users(
    q: str = Query(..., min_length=1, max_length=200, description="Search query (name, phone, or email)"),
    role: str = Query("all", pattern="^(all|driver|rider)$", description="Filter by role"),
    limit: int = Query(20, ge=1, le=100),
    _admin=Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Unified search across riders and drivers by name, phone, or email.

    Admin only. Searches User.name, User.phone, and User.email.
    Use role=driver or role=rider to narrow results.
    Returns up to `limit` results (default 20, max 100).
    """
    search_term = f"%{q}%"
    name_match = User.name.ilike(search_term)
    phone_match = User.phone.ilike(search_term)
    email_match = User.email.ilike(search_term)
    text_filter = or_(name_match, phone_match, email_match)

    role_filter_clause = []
    if role == "driver":
        role_filter_clause = [User.role == UserRole.DRIVER]
    elif role == "rider":
        role_filter_clause = [User.role == UserRole.RIDER]

    users_result = await db.execute(
        select(User)
        .where(text_filter, *role_filter_clause)
        .order_by(User.name.asc())
        .limit(limit)
    )
    users = users_result.scalars().all()

    total = (await db.execute(
        select(func.count()).select_from(User).where(text_filter, *role_filter_clause)
    )).scalar() or 0

    # Fetch driver profiles for any driver users
    driver_user_ids = [u.id for u in users if u.role == UserRole.DRIVER]
    profiles_by_user: dict[int, DriverProfile] = {}
    if driver_user_ids:
        profiles_result = await db.execute(
            select(DriverProfile).where(DriverProfile.user_id.in_(driver_user_ids))
        )
        profiles_by_user = {p.user_id: p for p in profiles_result.scalars().all()}

    results = []
    for user in users:
        profile = profiles_by_user.get(user.id)
        results.append(UserSearchResult(
            user_id=user.id,
            name=user.name,
            phone=user.phone,
            email=user.email,
            role=user.role.value,
            is_active=user.is_active,
            created_at=user.created_at,
            driver_is_approved=profile.is_approved if profile else None,
            driver_total_trips=profile.total_trips if profile else None,
            driver_rating_avg=profile.rating_avg if profile else None,
        ))

    return UserSearchResponse(
        query=q,
        role_filter=role,
        results=results,
        total=total,
    )


# ---- Admin Notification Preferences ----

_VALID_NOTIF_TYPES: frozenset[str] = frozenset(
    {
        "ride_matched",
        "ride_cancelled",
        "ride_completed",
        "driver_en_route",
        "driver_arrived",
        "payment_received",
        "sos_alert",
        "rating_received",
        "account_verification",
        "payout_completed",
        "ride_reminder",
        "fare_split_request",
        "promo_applied",
        "promo_expiring",
        "background_check_approved",
        "background_check_action_required",
    }
)
_VALID_NOTIF_CHANNELS: frozenset[str] = frozenset({"push", "sms", "email"})


def _validate_notif_type_channel(notification_type: str, channel: str) -> None:
    if notification_type not in _VALID_NOTIF_TYPES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Invalid notification_type '{notification_type}'",
        )
    if channel not in _VALID_NOTIF_CHANNELS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Invalid channel '{channel}'",
        )


@router.get(
    "/users/{user_id}/notification-preferences",
    response_model=AdminUserPreferencesResponse,
)
async def admin_get_user_notification_preferences(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
) -> AdminUserPreferencesResponse:
    """View the full notification preference map for any user. Admin only.

    Returns all (notification_type × channel) combinations with their effective
    enabled value.  Combinations without an explicit DB record appear as
    enabled=True (the default opt-in state).
    """
    from app.services.notification_preferences import get_user_preferences

    target = await db.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="User not found")

    prefs = await get_user_preferences(db, user_id)
    return AdminUserPreferencesResponse(user_id=user_id, preferences=prefs)


@router.put(
    "/users/{user_id}/notification-preferences/{notification_type}/{channel}",
    response_model=AdminUserPreferencesResponse,
)
async def admin_set_user_notification_preference(
    user_id: int,
    notification_type: str,
    channel: str,
    body: AdminSetPreferenceRequest,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
) -> AdminUserPreferencesResponse:
    """Override a single notification preference for any user. Admin only.

    Useful for support: re-enable a preference a user accidentally disabled,
    or disable a channel for a user experiencing delivery issues.
    """
    from app.services.notification_preferences import get_user_preferences, set_preference

    _validate_notif_type_channel(notification_type, channel)

    target = await db.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="User not found")

    await set_preference(db, user_id, notification_type, channel, body.enabled)
    await db.commit()

    prefs = await get_user_preferences(db, user_id)
    return AdminUserPreferencesResponse(user_id=user_id, preferences=prefs)


@router.put(
    "/users/{user_id}/notification-preferences",
    response_model=AdminUserPreferencesResponse,
)
async def admin_bulk_set_user_notification_preferences(
    user_id: int,
    body: AdminBulkSetPreferenceRequest,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
) -> AdminUserPreferencesResponse:
    """Bulk-override notification preferences for any user. Admin only.

    Each entry in ``updates`` must include ``notification_type``, ``channel``,
    and ``enabled``.  Invalid types or channels return 422.
    """
    from app.services.notification_preferences import bulk_set_preferences, get_user_preferences

    target = await db.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="User not found")

    for update in body.updates:
        _validate_notif_type_channel(
            update.get("notification_type", ""),
            update.get("channel", ""),
        )

    await bulk_set_preferences(db, user_id, body.updates)
    await db.commit()

    prefs = await get_user_preferences(db, user_id)
    return AdminUserPreferencesResponse(user_id=user_id, preferences=prefs)


@router.delete(
    "/users/{user_id}/notification-preferences/{notification_type}/{channel}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def admin_reset_user_notification_preference(
    user_id: int,
    notification_type: str,
    channel: str,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
) -> None:
    """Reset a single notification preference to the default (enabled) for any user. Admin only.

    Deletes the explicit preference record.  Returns 204 whether or not a
    record existed.
    """
    from app.services.notification_preferences import reset_preference

    _validate_notif_type_channel(notification_type, channel)

    target = await db.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="User not found")

    await reset_preference(db, user_id, notification_type, channel)
    await db.commit()


# ---- Scheduled Rides ----


@router.get("/rides/scheduled", response_model=AdminScheduledRidesListResponse)
async def list_scheduled_rides_admin(
    rider_id: int | None = Query(None, description="Filter by rider ID"),
    from_date: datetime | None = Query(None, description="Only rides scheduled at or after this time (UTC)"),
    to_date: datetime | None = Query(None, description="Only rides scheduled at or before this time (UTC)"),
    include_past: bool = Query(False, description="Include rides scheduled in the past (default: upcoming only)"),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    _admin=Depends(require_admin),
) -> AdminScheduledRidesListResponse:
    """List all SCHEDULED rides with optional filters. Admin only.

    By default returns upcoming scheduled rides (scheduled_for > now).
    Set include_past=true to include all historical scheduled rides regardless
    of whether they were dispatched. Supports pagination.
    """
    now = datetime.now(timezone.utc)

    filters = [Ride.status == RideStatus.SCHEDULED]

    if not include_past:
        filters.append(Ride.scheduled_for > now)

    if rider_id is not None:
        filters.append(Ride.rider_id == rider_id)

    if from_date is not None:
        filters.append(Ride.scheduled_for >= from_date)

    if to_date is not None:
        filters.append(Ride.scheduled_for <= to_date)

    total_result = await db.execute(
        select(func.count()).select_from(Ride).where(*filters)
    )
    total = total_result.scalar() or 0

    rides_result = await db.execute(
        select(Ride)
        .options(joinedload(Ride.rider), joinedload(Ride.driver))
        .where(*filters)
        .order_by(Ride.scheduled_for.asc())
        .offset((page - 1) * per_page)
        .limit(per_page)
    )
    rides = rides_result.scalars().all()

    return AdminScheduledRidesListResponse(
        rides=[_ride_to_response(r) for r in rides],
        total=total,
        page=page,
        per_page=per_page,
    )


# ---- Trip Anomaly Detection ----

_SAFETY_CANCELLATIONS = (
    CancellationCategory.SAFETY_CONCERN,
    CancellationCategory.DRIVER_NO_SHOW,
    CancellationCategory.DRIVER_NOT_ACCEPTABLE,
)

# A completed ride whose actual fare is more than 50% above the estimate
_EXCESSIVE_FARE_MULTIPLIER = 1.5
# Rides lasting longer than this (minutes) are flagged as anomalously long
_LONG_DURATION_THRESHOLD_MIN = 90


def _detect_anomaly_types(ride: Ride) -> list[str]:
    types = []
    if ride.route_deviation_flagged_at:
        types.append("route_deviation")
    if ride.driver_no_show_reported_at:
        types.append("driver_no_show")
    if ride.cancellation_category in _SAFETY_CANCELLATIONS:
        types.append("safety_cancellation")
    if ride.actual_fare is not None and ride.actual_fare > ride.estimated_fare * _EXCESSIVE_FARE_MULTIPLIER:
        types.append("excessive_fare")
    if ride.duration_min is not None and ride.duration_min > _LONG_DURATION_THRESHOLD_MIN:
        types.append("long_duration")
    return types


def _anomaly_detected_at(ride: Ride) -> datetime:
    candidates = [
        ride.route_deviation_flagged_at,
        ride.driver_no_show_reported_at,
        ride.cancelled_at if ride.cancellation_category in _SAFETY_CANCELLATIONS else None,
        ride.completed_at if (
            ride.actual_fare is not None and ride.actual_fare > ride.estimated_fare * _EXCESSIVE_FARE_MULTIPLIER
        ) else None,
        ride.completed_at if (ride.duration_min is not None and ride.duration_min > _LONG_DURATION_THRESHOLD_MIN) else None,
    ]
    timestamps = [t for t in candidates if t is not None]
    return min(timestamps) if timestamps else ride.requested_at


@router.get("/safety/anomalies", response_model=TripAnomalyListResponse)
async def list_trip_anomalies(
    db: AsyncSession = Depends(get_db),
    period: str = Query("all", pattern="^(week|month|year|all)$"),
    anomaly_type: str = Query("all", pattern="^(route_deviation|driver_no_show|safety_cancellation|excessive_fare|long_duration|all)$"),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
):
    """Return rides with detected anomalies.

    Anomaly types:
    - route_deviation: driver deviated >1 km from pickup→dropoff path
    - driver_no_show: driver no-show was reported or auto-detected
    - safety_cancellation: ride cancelled for safety, driver no-show, or unacceptable driver
    - excessive_fare: actual fare >50% above the estimated fare
    - long_duration: ride lasted longer than 90 minutes
    """
    now = datetime.now(timezone.utc)
    period_start: datetime | None = None
    if period == "week":
        period_start = now - timedelta(days=7)
    elif period == "month":
        period_start = now - timedelta(days=30)
    elif period == "year":
        period_start = now - timedelta(days=365)

    type_conditions: dict[str, object] = {
        "route_deviation": Ride.route_deviation_flagged_at.is_not(None),
        "driver_no_show": Ride.driver_no_show_reported_at.is_not(None),
        "safety_cancellation": Ride.cancellation_category.in_(list(_SAFETY_CANCELLATIONS)),
        "excessive_fare": and_(
            Ride.actual_fare.is_not(None),
            Ride.actual_fare > Ride.estimated_fare * _EXCESSIVE_FARE_MULTIPLIER,
        ),
        "long_duration": and_(
            Ride.duration_min.is_not(None),
            Ride.duration_min > _LONG_DURATION_THRESHOLD_MIN,
        ),
    }

    if anomaly_type == "all":
        anomaly_filter = or_(*type_conditions.values())
    else:
        anomaly_filter = type_conditions[anomaly_type]

    base_query = (
        select(Ride)
        .options(joinedload(Ride.rider), joinedload(Ride.driver))
        .where(anomaly_filter)
    )
    if period_start is not None:
        base_query = base_query.where(Ride.requested_at >= period_start)

    count_result = await db.execute(
        select(func.count()).select_from(base_query.subquery())
    )
    total = count_result.scalar() or 0

    rows_result = await db.execute(
        base_query
        .order_by(Ride.requested_at.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
    )
    rides = rows_result.unique().scalars().all()

    entries = []
    for ride in rides:
        detected_types = _detect_anomaly_types(ride)
        if not detected_types:
            continue
        entries.append(
            TripAnomalyEntry(
                ride_id=ride.id,
                rider_id=ride.rider_id,
                rider_name=ride.rider.name if ride.rider else None,
                driver_id=ride.driver_id,
                driver_name=ride.driver.name if ride.driver else None,
                pickup_address=ride.pickup_address,
                dropoff_address=ride.dropoff_address,
                status=ride.status.value,
                estimated_fare=ride.estimated_fare,
                actual_fare=ride.actual_fare,
                duration_min=ride.duration_min,
                anomaly_types=detected_types,
                detected_at=_anomaly_detected_at(ride),
                requested_at=ride.requested_at,
            )
        )

    return TripAnomalyListResponse(
        anomalies=entries,
        total=total,
        page=page,
        per_page=per_page,
    )


_VALID_BROADCAST_CHANNELS = {"push", "sms", "email"}


@router.post("/notifications/broadcast", response_model=BroadcastResult, status_code=status.HTTP_200_OK)
async def broadcast_notification(
    payload: BroadcastRequest,
    db: AsyncSession = Depends(get_db),
):
    """Send a notification to all users in a segment.

    Segments:
    - all_riders: all active users with role=rider
    - all_drivers: all active users with role=driver
    - all_users: all active non-admin users

    Invalid channels are silently dropped; if none remain, defaults to push.
    """
    from app.services.notifications import Notification, NotificationChannel, NotificationType, send_notification

    # Validate / filter channels
    requested_channels = [c for c in payload.channels if c in _VALID_BROADCAST_CHANNELS]
    if not requested_channels:
        requested_channels = ["push"]

    channel_enums = [NotificationChannel(c) for c in requested_channels]

    # Build user query for the target segment
    role_filter = {
        BroadcastSegment.ALL_RIDERS: UserRole.RIDER,
        BroadcastSegment.ALL_DRIVERS: UserRole.DRIVER,
    }

    if payload.segment == BroadcastSegment.ALL_USERS:
        user_query = select(User).where(
            User.is_active.is_(True),
            User.role != UserRole.ADMIN,
        )
    else:
        user_query = select(User).where(
            User.is_active.is_(True),
            User.role == role_filter[payload.segment],
        )

    result = await db.execute(user_query)
    users = result.scalars().all()

    sent = 0
    failed = 0
    for user in users:
        notification = Notification(
            user_id=user.id,
            type=NotificationType.ADMIN_BROADCAST,
            title=payload.title,
            body=payload.body,
            channels=channel_enums,
        )
        ok = await send_notification(
            notification,
            db=db,
            phone=user.phone,
            email=user.email,
        )
        if ok:
            sent += 1
        else:
            failed += 1

    return BroadcastResult(
        segment=payload.segment.value,
        title=payload.title,
        total_targeted=len(users),
        total_sent=sent,
        total_failed=failed,
        channels=requested_channels,
        sent_at=datetime.now(timezone.utc),
    )


# ---- Geofence Violations ----


def _classify_violation(pickup_covered: bool, dropoff_covered: bool) -> GeofenceViolationType:
    """Classify a ride's geofence violation based on coverage flags.

    Both uncovered → both_outside.
    Only pickup uncovered → pickup_outside.
    Only dropoff uncovered → dropoff_outside.
    """
    if not pickup_covered and not dropoff_covered:
        return GeofenceViolationType.BOTH_OUTSIDE
    if not pickup_covered:
        return GeofenceViolationType.PICKUP_OUTSIDE
    return GeofenceViolationType.DROPOFF_OUTSIDE


@router.get("/geofence/violations", response_model=GeofenceViolationListResponse)
async def list_geofence_violations(
    db: AsyncSession = Depends(get_db),
    period: Literal["week", "month", "year", "all"] = Query("month"),
    violation_type: Literal["all", "pickup_outside", "dropoff_outside", "both_outside"] = Query("all"),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
):
    """Return rides whose pickup or dropoff location falls outside all active service areas.

    Violation types:
    - pickup_outside: pickup location is outside every active service area
    - dropoff_outside: dropoff location is outside every active service area
    - both_outside: both pickup and dropoff are outside every active service area
    """
    from geoalchemy2.functions import ST_Within

    # Fast-path: if there are no active service areas, nothing can violate geofence rules
    sa_count_result = await db.execute(
        select(func.count()).select_from(ServiceArea).where(ServiceArea.is_active.is_(True))
    )
    service_areas_active = sa_count_result.scalar() or 0
    if service_areas_active == 0:
        return GeofenceViolationListResponse(
            violations=[],
            total=0,
            page=page,
            per_page=per_page,
            service_areas_active=0,
        )

    # Period filter
    now = datetime.now(timezone.utc)
    period_start: datetime | None = None
    if period == "week":
        period_start = now - timedelta(days=7)
    elif period == "month":
        period_start = now - timedelta(days=30)
    elif period == "year":
        period_start = now - timedelta(days=365)

    # Correlated EXISTS subqueries: True when the ride's location IS within at least one active SA
    pickup_in_sa = (
        select(literal_column("1"))
        .select_from(ServiceArea)
        .where(
            ServiceArea.is_active.is_(True),
            ST_Within(Ride.pickup_location, ServiceArea.boundary),
        )
        .correlate(Ride)
        .exists()
    )
    dropoff_in_sa = (
        select(literal_column("1"))
        .select_from(ServiceArea)
        .where(
            ServiceArea.is_active.is_(True),
            ST_Within(Ride.dropoff_location, ServiceArea.boundary),
        )
        .correlate(Ride)
        .exists()
    )

    # Base query: rides WHERE at least one location is outside any active SA
    base_stmt = (
        select(
            Ride,
            pickup_in_sa.label("pickup_covered"),
            dropoff_in_sa.label("dropoff_covered"),
        )
        .where(or_(not_(pickup_in_sa), not_(dropoff_in_sa)))
    )
    if period_start is not None:
        base_stmt = base_stmt.where(Ride.requested_at >= period_start)

    # violation_type filter — translate string to classification and apply as a HAVING-style subfilter.
    # We use a CASE expression in the WHERE clause to compare per-row classification.
    if violation_type != "all":
        # Map the requested type to its (pickup_covered, dropoff_covered) pattern
        _vtype_filter = {
            "both_outside": and_(not_(pickup_in_sa), not_(dropoff_in_sa)),
            "pickup_outside": and_(not_(pickup_in_sa), dropoff_in_sa),
            "dropoff_outside": and_(pickup_in_sa, not_(dropoff_in_sa)),
        }
        base_stmt = base_stmt.where(_vtype_filter[violation_type])

    # Total count
    count_result = await db.execute(
        select(func.count()).select_from(base_stmt.subquery())
    )
    total = count_result.scalar() or 0

    # Paginated rows
    offset = (page - 1) * per_page
    rows_result = await db.execute(
        base_stmt.order_by(Ride.requested_at.desc()).offset(offset).limit(per_page)
    )
    rows = rows_result.all()

    violations = []
    for row in rows:
        ride: Ride = row.Ride
        vtype = _classify_violation(bool(row.pickup_covered), bool(row.dropoff_covered))
        violations.append(
            GeofenceViolationEntry(
                ride_id=ride.id,
                rider_id=ride.rider_id,
                driver_id=ride.driver_id,
                pickup_address=ride.pickup_address,
                dropoff_address=ride.dropoff_address,
                violation_type=vtype,
                status=ride.status.value,
                requested_at=ride.requested_at,
            )
        )

    return GeofenceViolationListResponse(
        violations=violations,
        total=total,
        page=page,
        per_page=per_page,
        service_areas_active=service_areas_active,
    )


@router.get("/safety/speeding-incidents", response_model=SpeedingIncidentListResponse)
async def list_speeding_incidents(
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
    period: str = Query("all", pattern="^(week|month|year|all)$"),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
):
    """Return rides where driver speeding was detected.

    Filtered to rides where ``speeding_flagged_at`` is not null.
    The ``period`` filter narrows by ``speeding_flagged_at`` timestamp.
    """
    now = datetime.now(timezone.utc)
    period_start: datetime | None = None
    if period == "week":
        period_start = now - timedelta(days=7)
    elif period == "month":
        period_start = now - timedelta(days=30)
    elif period == "year":
        period_start = now - timedelta(days=365)

    base_query = (
        select(Ride)
        .options(joinedload(Ride.rider), joinedload(Ride.driver))
        .where(Ride.speeding_flagged_at.is_not(None))
    )
    if period_start is not None:
        base_query = base_query.where(Ride.speeding_flagged_at >= period_start)

    count_result = await db.execute(
        select(func.count()).select_from(base_query.subquery())
    )
    total = count_result.scalar() or 0

    rows_result = await db.execute(
        base_query
        .order_by(Ride.speeding_flagged_at.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
    )
    rides = rows_result.unique().scalars().all()

    entries = [
        SpeedingIncidentEntry(
            ride_id=ride.id,
            rider_id=ride.rider_id,
            rider_name=ride.rider.name if ride.rider else None,
            driver_id=ride.driver_id,
            driver_name=ride.driver.name if ride.driver else None,
            pickup_address=ride.pickup_address,
            dropoff_address=ride.dropoff_address,
            status=ride.status.value,
            speeding_flagged_at=ride.speeding_flagged_at,
            requested_at=ride.requested_at,
        )
        for ride in rides
    ]

    return SpeedingIncidentListResponse(
        incidents=entries,
        total=total,
        page=page,
        per_page=per_page,
    )


@router.get("/safety/route-deviation-incidents", response_model=RouteDeviationIncidentListResponse)
async def list_route_deviation_incidents(
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
    period: str = Query("all", pattern="^(week|month|year|all)$"),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
):
    """Return rides where the driver deviated significantly from the direct route.

    Filtered to rides where ``route_deviation_flagged_at`` is not null.
    The ``period`` filter narrows by ``route_deviation_flagged_at`` timestamp.
    """
    now = datetime.now(timezone.utc)
    period_start: datetime | None = None
    if period == "week":
        period_start = now - timedelta(days=7)
    elif period == "month":
        period_start = now - timedelta(days=30)
    elif period == "year":
        period_start = now - timedelta(days=365)

    base_query = (
        select(Ride)
        .options(joinedload(Ride.rider), joinedload(Ride.driver))
        .where(Ride.route_deviation_flagged_at.is_not(None))
    )
    if period_start is not None:
        base_query = base_query.where(Ride.route_deviation_flagged_at >= period_start)

    count_result = await db.execute(
        select(func.count()).select_from(base_query.subquery())
    )
    total = count_result.scalar() or 0

    rows_result = await db.execute(
        base_query
        .order_by(Ride.route_deviation_flagged_at.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
    )
    rides = rows_result.unique().scalars().all()

    entries = [
        RouteDeviationIncidentEntry(
            ride_id=ride.id,
            rider_id=ride.rider_id,
            rider_name=ride.rider.name if ride.rider else None,
            driver_id=ride.driver_id,
            driver_name=ride.driver.name if ride.driver else None,
            pickup_address=ride.pickup_address,
            dropoff_address=ride.dropoff_address,
            status=ride.status.value,
            route_deviation_flagged_at=ride.route_deviation_flagged_at,
            requested_at=ride.requested_at,
        )
        for ride in rides
    ]

    return RouteDeviationIncidentListResponse(
        incidents=entries,
        total=total,
        page=page,
        per_page=per_page,
    )
