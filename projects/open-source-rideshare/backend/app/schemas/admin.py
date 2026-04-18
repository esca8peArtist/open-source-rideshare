import enum
from datetime import datetime

from pydantic import BaseModel, Field


class PaginationResponse(BaseModel):
    page: int
    per_page: int
    total: int


class AdminRideResponse(BaseModel):
    id: int
    status: str
    pickup_address: str
    dropoff_address: str
    estimated_fare: float
    actual_fare: float | None = None
    distance_km: float | None = None
    duration_min: float | None = None
    tip_amount: float = 0.0
    rider_id: int
    driver_id: int | None = None
    rider_name: str | None = None
    driver_name: str | None = None
    rider_rating: int | None = None
    driver_rating: int | None = None
    cancellation_reason: str | None = None
    requested_at: datetime
    matched_at: datetime | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    cancelled_at: datetime | None = None
    scheduled_for: datetime | None = None

    model_config = {"from_attributes": True}


class RidesListResponse(BaseModel):
    rides: list[AdminRideResponse]
    pagination: PaginationResponse


class AdminScheduledRidesListResponse(BaseModel):
    rides: list[AdminRideResponse]
    total: int
    page: int
    per_page: int


class AdminDriverResponse(BaseModel):
    id: int
    user_id: int
    user_name: str | None = None
    user_phone: str | None = None
    vehicle_type: str
    vehicle_make: str
    vehicle_model: str
    vehicle_year: int
    vehicle_color: str
    license_plate: str
    license_number: str
    insurance_policy: str | None = None
    background_check_status: str
    rating_avg: float
    total_trips: int
    is_online: bool
    is_approved: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class DriversListResponse(BaseModel):
    drivers: list[AdminDriverResponse]
    pagination: PaginationResponse


class SuspendRequest(BaseModel):
    reason: str


class AdminPaymentResponse(BaseModel):
    id: int
    ride_id: int
    amount: float
    platform_fee: float
    driver_payout: float
    tip_amount: float = 0.0
    status: str
    created_at: datetime
    rider_name: str | None = None
    driver_name: str | None = None
    pickup_address: str | None = None
    dropoff_address: str | None = None

    model_config = {"from_attributes": True}


class PaymentsListResponse(BaseModel):
    payments: list[AdminPaymentResponse]
    pagination: PaginationResponse


class DashboardStats(BaseModel):
    active_rides: int
    online_drivers: int
    revenue_today: float
    total_users: int
    rides_today: int
    completed_today: int
    cancelled_today: int


class RevenueDataPoint(BaseModel):
    date: str
    revenue: float
    rides: int
    tips: float


class RideActivityDataPoint(BaseModel):
    hour: str
    rides: int


class PlatformSettings(BaseModel):
    base_fare: float
    per_km_rate: float
    per_min_rate: float
    platform_fee_percent: float
    max_search_radius_km: float
    surge_multiplier: float


class TimeMultiplierEntry(BaseModel):
    start_hour: int
    end_hour: int
    multiplier: float
    label: str


class TimeMultiplierSchedule(BaseModel):
    entries: list[TimeMultiplierEntry]


# ---- Admin SOS Monitoring ----


class AdminSOSAlertResponse(BaseModel):
    id: int
    user_id: int
    user_name: str | None = None
    user_phone: str | None = None
    ride_id: int | None = None
    ride_status: str | None = None
    pickup_address: str | None = None
    dropoff_address: str | None = None
    status: str
    latitude: float | None = None
    longitude: float | None = None
    message: str | None = None
    created_at: datetime
    resolved_at: datetime | None = None
    resolved_by: int | None = None
    resolution_notes: str | None = None


class AdminSOSListResponse(BaseModel):
    alerts: list[AdminSOSAlertResponse]
    pagination: PaginationResponse


class AdminSOSResolveRequest(BaseModel):
    resolution: str  # "resolved", "false_alarm", "escalated"
    notes: str | None = None


class SOSStats(BaseModel):
    active_count: int
    resolved_today: int
    false_alarms_today: int
    total_today: int
    avg_resolution_minutes: float | None = None


class SOSTimeseriesPoint(BaseModel):
    date: str
    total: int
    active: int
    resolved: int
    false_alarms: int


class SOSFrequencyEntry(BaseModel):
    user_id: int
    user_name: str | None = None
    user_phone: str | None = None
    total: int
    active: int
    resolved: int
    false_alarms: int
    false_alarm_rate: float
    last_sos_at: datetime


class SOSFrequencyResponse(BaseModel):
    period: str
    entries: list[SOSFrequencyEntry]


class DriverPanicFrequencyEntry(BaseModel):
    driver_profile_id: int
    driver_name: str | None = None
    driver_phone: str | None = None
    total: int
    active: int
    resolved: int
    false_alarms: int
    false_alarm_rate: float
    last_panic_at: datetime


class DriverPanicFrequencyResponse(BaseModel):
    period: str
    entries: list[DriverPanicFrequencyEntry]


# ---- Admin Cancellation Stats ----


class CancellationReasonBreakdown(BaseModel):
    reason: str
    count: int


class CancellationStats(BaseModel):
    total_cancellations: int
    total_rides: int
    cancellation_rate: float
    cancellations_today: int
    cancellations_this_week: int
    fees_collected: float
    fees_pending: float
    avg_cancel_time_minutes: float | None = None
    top_reasons: list[CancellationReasonBreakdown]


class CancellationTimeseriesPoint(BaseModel):
    date: str
    cancellations: int
    fees_collected: float


# ---- Admin Dispute Management ----


class AdminDisputeResponse(BaseModel):
    id: int
    ride_id: int
    filed_by: int
    filer_name: str | None = None
    filer_role: str | None = None
    dispute_type: str
    status: str
    description: str
    resolution_notes: str | None = None
    resolved_by: int | None = None
    resolver_name: str | None = None
    refund_amount: float | None = None
    created_at: datetime
    updated_at: datetime
    resolved_at: datetime | None = None
    ride_pickup: str | None = None
    ride_dropoff: str | None = None
    ride_fare: float | None = None


class AdminDisputeListResponse(BaseModel):
    disputes: list[AdminDisputeResponse]
    pagination: PaginationResponse


class DisputeStats(BaseModel):
    open_count: int
    under_review_count: int
    resolved_today: int
    total_disputes: int
    avg_resolution_hours: float | None = None
    refunds_issued_total: float
    top_dispute_types: list[dict]


# ---- Admin Feedback Overview ----


class AdminFeedbackResponse(BaseModel):
    id: int
    ride_id: int
    user_id: int
    user_name: str | None = None
    role: str
    rating: int
    comment: str | None = None
    categories: list[str] | None = None
    created_at: datetime
    ride_pickup: str | None = None
    ride_dropoff: str | None = None


class AdminFeedbackListResponse(BaseModel):
    feedback: list[AdminFeedbackResponse]
    pagination: PaginationResponse


class FeedbackStats(BaseModel):
    total_feedback: int
    avg_driver_rating: float | None = None
    avg_rider_rating: float | None = None
    feedback_today: int
    rating_distribution: dict
    top_categories: list[dict]


# ---- Admin Ride Metrics Dashboard ----


class RideFunnelMetrics(BaseModel):
    total_requested: int
    total_matched: int
    total_completed: int
    total_cancelled: int
    match_rate: float  # matched / requested
    completion_rate: float  # completed / matched
    cancellation_rate: float  # cancelled / requested


class RideTimingMetrics(BaseModel):
    avg_wait_seconds: float | None = None  # requested_at → matched_at
    avg_pickup_seconds: float | None = None  # matched_at → started_at
    avg_ride_duration_seconds: float | None = None  # started_at → completed_at
    avg_total_seconds: float | None = None  # requested_at → completed_at


class PeakHourEntry(BaseModel):
    hour: int
    rides: int


class PeakDayEntry(BaseModel):
    day_of_week: str
    rides: int


class RideMetrics(BaseModel):
    period: str
    funnel: RideFunnelMetrics
    timing: RideTimingMetrics
    avg_distance_km: float | None = None
    avg_fare: float | None = None
    peak_hours: list[PeakHourEntry]
    peak_days: list[PeakDayEntry]


# ---- Admin Driver Metrics Dashboard ----


class TopDriverEntry(BaseModel):
    driver_id: int
    driver_name: str | None = None
    total_trips: int
    rating_avg: float
    completed_in_period: int


class DriverMetrics(BaseModel):
    period: str
    total_drivers: int
    approved_drivers: int
    online_now: int
    avg_rating: float | None = None
    avg_trips_per_driver: float | None = None
    rides_per_active_driver: float | None = None
    top_drivers: list[TopDriverEntry]
    rating_distribution: dict


# ---- Admin Notification Logs ----


class AdminNotificationLogEntry(BaseModel):
    id: int
    user_id: int
    notification_type: str
    channel: str
    title: str
    body: str
    status: str
    error_message: str | None
    ride_id: int | None
    is_read: bool
    created_at: datetime
    read_at: datetime | None

    model_config = {"from_attributes": True}


class AdminNotificationLogListResponse(BaseModel):
    logs: list[AdminNotificationLogEntry]
    total: int


class AdminRiderResponse(BaseModel):
    id: int
    name: str
    phone: str
    email: str | None = None
    is_active: bool
    phone_verified: bool
    referral_code: str | None = None
    created_at: datetime
    total_rides: int = 0
    completed_rides: int = 0
    cancelled_rides: int = 0
    avg_rider_rating: float | None = None

    model_config = {"from_attributes": True}


class RidersListResponse(BaseModel):
    riders: list[AdminRiderResponse]
    pagination: PaginationResponse


class TopEarnerDriverEntry(BaseModel):
    """One driver in the top-earners leaderboard."""

    driver_id: int
    driver_name: str
    completed_trips: int
    total_earned_dollars: float
    avg_fare_dollars: float


class TopSpenderRiderEntry(BaseModel):
    """One rider in the top-spenders leaderboard."""

    rider_id: int
    rider_name: str
    completed_trips: int
    total_spent_dollars: float
    avg_fare_dollars: float


class TopEarnersResponse(BaseModel):
    """Admin leaderboard: top drivers by earnings or top riders by spending."""

    period: str
    role: str  # "driver" or "rider"
    entries: list[TopEarnerDriverEntry] | list[TopSpenderRiderEntry]


class UserSearchResult(BaseModel):
    """One user in unified admin search results."""

    user_id: int
    name: str
    phone: str
    email: str | None = None
    role: str  # "rider" or "driver"
    is_active: bool
    created_at: datetime
    # driver-specific fields (None for riders)
    driver_is_approved: bool | None = None
    driver_total_trips: int | None = None
    driver_rating_avg: float | None = None


class UserSearchResponse(BaseModel):
    """Admin unified user search response."""

    query: str
    role_filter: str  # "all", "driver", or "rider"
    results: list[UserSearchResult]
    total: int


class BulkDriverIdsRequest(BaseModel):
    driver_ids: list[int] = Field(..., min_length=1, max_length=100)


class BulkDriverSuspendRequest(BaseModel):
    driver_ids: list[int] = Field(..., min_length=1, max_length=100)
    reason: str = Field(..., min_length=1, max_length=500)


class BulkActionResult(BaseModel):
    succeeded: list[int]
    not_found: list[int]
    total_requested: int
    total_succeeded: int


class BulkRiderIdsRequest(BaseModel):
    user_ids: list[int] = Field(..., min_length=1, max_length=100)


class BulkRiderSuspendRequest(BaseModel):
    user_ids: list[int] = Field(..., min_length=1, max_length=100)
    reason: str = Field(..., min_length=1, max_length=500)


class SOSMapPin(BaseModel):
    id: int
    user_id: int
    user_name: str | None = None
    user_phone: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    message: str | None = None
    ride_id: int | None = None
    seconds_open: int
    created_at: datetime


class SOSActiveMapResponse(BaseModel):
    pins: list[SOSMapPin]
    total: int
    fetched_at: datetime


class AdminUserPreferencesResponse(BaseModel):
    """Admin view of a single user's full notification preference map."""

    user_id: int
    preferences: dict[str, dict[str, bool]]


class AdminSetPreferenceRequest(BaseModel):
    """Admin request body for overriding a single notification preference."""

    enabled: bool


class AdminBulkSetPreferenceRequest(BaseModel):
    """Admin request body for bulk-overriding notification preferences."""

    updates: list[dict]  # each: {notification_type, channel, enabled}


class DriverActivityEntry(BaseModel):
    driver_id: int
    user_id: int
    driver_name: str | None = None
    is_online: bool
    is_approved: bool
    rating_avg: float
    total_trips: int
    trips_7d: int
    trips_30d: int
    shift_hours_7d: float
    shift_hours_30d: float
    last_trip_at: datetime | None = None

    model_config = {"from_attributes": True}


class DriverActivityListResponse(BaseModel):
    drivers: list[DriverActivityEntry]
    pagination: PaginationResponse


# ---- Admin Driver Status History ----


class DriverStatusChangeEntry(BaseModel):
    """One status-change event in a single driver's history."""

    id: int
    timestamp: datetime
    event_type: str  # raw value: "driver_approved", "driver_suspended", etc.
    action: str  # human-friendly: "approved", "suspended", "reactivated"
    admin_id: int | None
    reason: str | None  # extracted from metadata_json for suspensions
    description: str


class DriverStatusHistoryResponse(BaseModel):
    """Paginated status-change history for one driver."""

    driver_id: int
    total: int
    items: list[DriverStatusChangeEntry]


class RecentDriverStatusChangeEntry(BaseModel):
    """One status-change event across all drivers (recent feed)."""

    id: int
    timestamp: datetime
    event_type: str
    action: str
    driver_id: int  # target_id (driver_profile.id)
    admin_id: int | None
    reason: str | None
    description: str


class RecentDriverStatusChangesResponse(BaseModel):
    """Paginated feed of recent driver status changes across all drivers."""

    total: int
    items: list[RecentDriverStatusChangeEntry]


# ---- Admin Per-User Safety History ----


class RiderSafetyHistoryEntry(BaseModel):
    """One SOS alert event in a rider's safety history."""

    id: int
    ride_id: int | None
    status: str
    lat: float | None
    lng: float | None
    message: str | None
    triggered_at: datetime
    resolved_at: datetime | None
    resolved_by: int | None
    resolution_notes: str | None

    model_config = {"from_attributes": True}


class RiderSafetyHistoryResponse(BaseModel):
    """Paginated SOS alert history for one rider."""

    rider_id: int
    total: int
    items: list[RiderSafetyHistoryEntry]


class DriverSafetyHistoryEntry(BaseModel):
    """One panic alert event in a driver's safety history."""

    id: str
    ride_id: int
    rider_id: int
    status: str
    location_lat: float | None
    location_lng: float | None
    triggered_at: datetime
    resolved_at: datetime | None
    resolved_by: int | None
    resolution_notes: str | None


class DriverSafetyHistoryResponse(BaseModel):
    """Paginated panic alert history for one driver."""

    driver_id: int
    total: int
    items: list[DriverSafetyHistoryEntry]


# ---- Admin Driver Shift History ----


class DriverShiftEntry(BaseModel):
    """One shift session in a driver's shift history."""

    id: int
    status: str
    started_at: datetime
    ended_at: datetime | None
    total_minutes: float | None
    rides_completed: int

    model_config = {"from_attributes": True}


class DriverShiftHistoryResponse(BaseModel):
    """Paginated shift history for one driver."""

    driver_id: int
    total: int
    items: list[DriverShiftEntry]


class ActiveShiftEntry(BaseModel):
    """One driver currently on an active shift."""

    shift_id: int
    driver_profile_id: int
    user_id: int
    driver_name: str | None
    started_at: datetime
    rides_completed: int


class ActiveShiftsResponse(BaseModel):
    """List of drivers currently on active shifts."""

    total: int
    items: list[ActiveShiftEntry]


# ---- Trip Anomaly Detection ----


class TripAnomalyEntry(BaseModel):
    """A ride that has one or more detected anomaly flags."""

    ride_id: int
    rider_id: int
    rider_name: str | None = None
    driver_id: int | None = None
    driver_name: str | None = None
    pickup_address: str
    dropoff_address: str
    status: str
    estimated_fare: float
    actual_fare: float | None = None
    duration_min: float | None = None
    anomaly_types: list[str]
    detected_at: datetime
    requested_at: datetime


class TripAnomalyListResponse(BaseModel):
    """Paginated list of rides with anomaly flags."""

    anomalies: list[TripAnomalyEntry]
    total: int
    page: int
    per_page: int


# ---- Admin Notification Broadcast ----


class BroadcastSegment(str, enum.Enum):
    ALL_RIDERS = "all_riders"
    ALL_DRIVERS = "all_drivers"
    ALL_USERS = "all_users"


class BroadcastRequest(BaseModel):
    """Request body for an admin notification broadcast."""

    segment: BroadcastSegment
    title: str = Field(..., min_length=1, max_length=200)
    body: str = Field(..., min_length=1, max_length=1000)
    channels: list[str] = Field(
        default=["push"],
        description="Channels to use: push, sms, email",
    )


class BroadcastResult(BaseModel):
    """Result of an admin notification broadcast."""

    segment: str
    title: str
    total_targeted: int
    total_sent: int
    total_failed: int
    channels: list[str]
    sent_at: datetime


# ---- Geofence Violations ----


class GeofenceViolationType(str, enum.Enum):
    PICKUP_OUTSIDE = "pickup_outside"
    DROPOFF_OUTSIDE = "dropoff_outside"
    BOTH_OUTSIDE = "both_outside"


class GeofenceViolationEntry(BaseModel):
    ride_id: int
    rider_id: int
    driver_id: int | None = None
    pickup_address: str
    dropoff_address: str
    violation_type: GeofenceViolationType
    status: str
    requested_at: datetime

    model_config = {"from_attributes": True}


class GeofenceViolationListResponse(BaseModel):
    violations: list[GeofenceViolationEntry]
    total: int
    page: int
    per_page: int
    service_areas_active: int


# ---- Driver Speeding Incidents ----


class SpeedingIncidentEntry(BaseModel):
    """A ride where the driver was detected exceeding the speed threshold."""

    ride_id: int
    rider_id: int
    rider_name: str | None = None
    driver_id: int | None = None
    driver_name: str | None = None
    pickup_address: str
    dropoff_address: str
    status: str
    speeding_flagged_at: datetime
    requested_at: datetime

    model_config = {"from_attributes": True}


class SpeedingIncidentListResponse(BaseModel):
    incidents: list[SpeedingIncidentEntry]
    total: int
    page: int
    per_page: int


# ---- Route Deviation Incidents ----


class RouteDeviationIncidentEntry(BaseModel):
    """A ride where the driver was detected deviating significantly from the direct route."""

    ride_id: int
    rider_id: int
    rider_name: str | None = None
    driver_id: int | None = None
    driver_name: str | None = None
    pickup_address: str
    dropoff_address: str
    status: str
    route_deviation_flagged_at: datetime
    requested_at: datetime

    model_config = {"from_attributes": True}


class RouteDeviationIncidentListResponse(BaseModel):
    incidents: list[RouteDeviationIncidentEntry]
    total: int
    page: int
    per_page: int
