from datetime import datetime

from pydantic import BaseModel


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

    model_config = {"from_attributes": True}


class RidesListResponse(BaseModel):
    rides: list[AdminRideResponse]
    pagination: PaginationResponse


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
