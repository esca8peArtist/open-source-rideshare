from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1 import accessibility_ratings, admin, admin_driver_earnings_report, admin_financials, admin_ride_cancel, admin_safety_dashboard, admin_user_management, analytics, audit, auth, background_checks, boarding_verification, chat, check_in_timer, complaints, demand_heatmap, device_tokens, disputes, driver_accessibility, driver_availability, driver_check_in_timer, driver_destination, driver_documents, driver_earnings_comparison, driver_earnings_history, driver_earnings_goal, driver_earnings_summary, driver_fatigue, driver_insurance, driver_location, driver_mileage_report, driver_navigation, driver_onboarding, driver_performance, driver_public_profile, driver_rating_submit, driver_ratings, driver_referral, driver_revenue_projection, driver_ride_earnings, driver_safety, driver_safety_report, driver_shifts, driver_upcoming_rides, drivers, drivers_nearby, driver_welfare_summary, fare_splits, feedback, incentives, lost_found, notification_preferences, notifications, payments, payouts, platform_config, pools, promos, recurring_rides, ride_preferences, ride_receipt, rider_cancellation_stats, rider_favorite_drivers, rider_incident_flag, rider_payment_methods, rider_public_profile, rider_ratings, rider_safety, rider_safety_history, rider_safety_report, rider_spending_summary, rider_trip_history, rides, safety, saved_locations, tips, trip_share, vehicle_inspection, vehicles, waypoints
from app.api.v1.surge_zones import admin_router as surge_zones_admin_router, admin_analytics_router as surge_analytics_router, public_router as surge_zones_public_router
from app.api.v1.surge_waitlist import rider_router as surge_waitlist_rider_router, public_router as surge_waitlist_public_router, admin_router as surge_waitlist_admin_router
from app.api.v1.fare_preview import router as fare_preview_router
from app.api.v1.fare_forecast import router as fare_forecast_router
from app.api.v1.surge_status import router as surge_status_router
from app.api.v1.eta_estimate import router as eta_estimate_router
from app.api import websocket
from app.config import settings
from app.services.dispatch_scheduler import start_scheduler, stop_scheduler


@asynccontextmanager
async def lifespan(app: FastAPI):
    start_scheduler()
    yield
    await stop_scheduler()

app = FastAPI(
    title=settings.app_name,
    description="Open source rideshare infrastructure for cooperatives",
    version="0.1.0",
    lifespan=lifespan,
)

_cors_origins: list[str] = (
    ["*"]
    if settings.debug
    else [o.strip() for o in settings.allowed_origins.split(",") if o.strip()]
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/api/v1")
app.include_router(rides.router, prefix="/api/v1")
app.include_router(drivers.router, prefix="/api/v1")
app.include_router(payments.router, prefix="/api/v1")
app.include_router(admin.router, prefix="/api/v1")
app.include_router(safety.router, prefix="/api/v1")
app.include_router(pools.router, prefix="/api/v1")
app.include_router(promos.router, prefix="/api/v1")
app.include_router(vehicles.router, prefix="/api/v1")
app.include_router(chat.router, prefix="/api/v1")
app.include_router(saved_locations.router, prefix="/api/v1")
app.include_router(recurring_rides.router, prefix="/api/v1")
app.include_router(waypoints.router, prefix="/api/v1")
app.include_router(fare_splits.router, prefix="/api/v1")
app.include_router(notifications.router, prefix="/api/v1")
app.include_router(payouts.router, prefix="/api/v1")
app.include_router(audit.router, prefix="/api/v1")
app.include_router(background_checks.router, prefix="/api/v1")
app.include_router(device_tokens.router, prefix="/api/v1")
app.include_router(tips.router, prefix="/api/v1")
app.include_router(incentives.router, prefix="/api/v1")
app.include_router(rider_ratings.router, prefix="/api/v1")
app.include_router(notification_preferences.router, prefix="/api/v1")
app.include_router(driver_availability.router, prefix="/api/v1")
app.include_router(driver_destination.router, prefix="/api/v1")
app.include_router(driver_insurance.router, prefix="/api/v1")
app.include_router(vehicle_inspection.router, prefix="/api/v1")
app.include_router(driver_documents.router, prefix="/api/v1")
app.include_router(driver_onboarding.router, prefix="/api/v1")
app.include_router(driver_performance.router, prefix="/api/v1")
app.include_router(lost_found.router, prefix="/api/v1")
app.include_router(analytics.router, prefix="/api/v1")
app.include_router(admin_financials.router, prefix="/api/v1")
app.include_router(admin_driver_earnings_report.router, prefix="/api/v1")
app.include_router(admin_ride_cancel.router, prefix="/api/v1")
app.include_router(admin_safety_dashboard.router, prefix="/api/v1")
app.include_router(admin_user_management.router, prefix="/api/v1")
app.include_router(ride_preferences.router, prefix="/api/v1")
app.include_router(driver_accessibility.router, prefix="/api/v1")
app.include_router(complaints.router, prefix="/api/v1")
app.include_router(surge_zones_admin_router, prefix="/api/v1")
app.include_router(surge_analytics_router, prefix="/api/v1")
app.include_router(surge_zones_public_router, prefix="/api/v1")
app.include_router(surge_waitlist_rider_router, prefix="/api/v1")
app.include_router(surge_waitlist_public_router, prefix="/api/v1")
app.include_router(surge_waitlist_admin_router, prefix="/api/v1")
app.include_router(rider_safety.router, prefix="/api/v1")
app.include_router(driver_safety.router, prefix="/api/v1")
app.include_router(driver_referral.router, prefix="/api/v1")
app.include_router(platform_config.router, prefix="/api/v1")
app.include_router(driver_welfare_summary.router, prefix="/api/v1")
app.include_router(driver_earnings_goal.router, prefix="/api/v1")
app.include_router(driver_revenue_projection.router, prefix="/api/v1")
app.include_router(driver_earnings_comparison.router, prefix="/api/v1")
app.include_router(rider_trip_history.router, prefix="/api/v1")
app.include_router(driver_earnings_history.router, prefix="/api/v1")
app.include_router(driver_ride_earnings.router, prefix="/api/v1")
app.include_router(driver_earnings_summary.router, prefix="/api/v1")
app.include_router(driver_mileage_report.router, prefix="/api/v1")
app.include_router(rider_safety_history.router, prefix="/api/v1")
app.include_router(rider_cancellation_stats.router, prefix="/api/v1")
app.include_router(rider_spending_summary.router, prefix="/api/v1")
app.include_router(rider_favorite_drivers.router, prefix="/api/v1")
app.include_router(demand_heatmap.router, prefix="/api/v1")
app.include_router(driver_location.router, prefix="/api/v1")
app.include_router(fare_preview_router, prefix="/api/v1")
app.include_router(fare_forecast_router, prefix="/api/v1")
app.include_router(surge_status_router, prefix="/api/v1")
app.include_router(drivers_nearby.router, prefix="/api/v1")
app.include_router(eta_estimate_router, prefix="/api/v1")
app.include_router(driver_ratings.router, prefix="/api/v1")
app.include_router(driver_public_profile.router, prefix="/api/v1")
app.include_router(rider_public_profile.router, prefix="/api/v1")
app.include_router(driver_shifts.router, prefix="/api/v1")
app.include_router(ride_receipt.router, prefix="/api/v1")
app.include_router(rider_safety_report.router, prefix="/api/v1")
app.include_router(driver_safety_report.router, prefix="/api/v1")
app.include_router(rider_payment_methods.router, prefix="/api/v1")
app.include_router(trip_share.router, prefix="/api/v1")
app.include_router(check_in_timer.router, prefix="/api/v1")
app.include_router(driver_check_in_timer.router, prefix="/api/v1")
app.include_router(driver_fatigue.router, prefix="/api/v1")
app.include_router(driver_upcoming_rides.router, prefix="/api/v1")
app.include_router(boarding_verification.router, prefix="/api/v1")
app.include_router(driver_rating_submit.router, prefix="/api/v1")
app.include_router(feedback.router, prefix="/api/v1")
app.include_router(disputes.router, prefix="/api/v1")
app.include_router(driver_navigation.router, prefix="/api/v1")
app.include_router(accessibility_ratings.router, prefix="/api/v1")
app.include_router(rider_incident_flag.router, prefix="/api/v1")
app.include_router(websocket.router)


@app.get("/health")
async def health():
    return {"status": "ok", "service": settings.app_name}
