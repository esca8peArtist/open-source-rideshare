from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1 import accessibility, admin, admin_financials, admin_ride_export, analytics, audit, auth, background_checks, blocklist, bulk_notifications, busy_hours, chat, complaints, cooperative, corporate_accounts, demand_heatmap, device_tokens, document_expiry, driver_availability, driver_destination, driver_documents, driver_earnings_goals, driver_earnings_summary, driver_expenses, driver_insurance, driver_onboarding, driver_performance, driver_payouts, driver_referrals, driver_subscriptions, driver_tax, driver_tiers, drivers, fare_disputes, fare_splits, incentives, lost_found, notification_preferences, notifications, payments, payouts, platform_config, pools, promos, receipts, recurring_rides, ride_feedback, ride_preferences, rider_memberships, rider_ratings, rider_referrals, rider_rewards, rides, safety, saved_locations, scheduled_rides, service_areas, surge_price_lock, tips, trip_heatmap, vehicle_inspection, vehicle_maintenance, vehicles, waypoints
from app.api.v1.surge_zones import admin_router as surge_zones_admin_router, public_router as surge_zones_public_router
from app.api.v1.surge_waitlist import rider_router as surge_waitlist_rider_router, public_router as surge_waitlist_public_router, admin_router as surge_waitlist_admin_router
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
app.include_router(driver_expenses.router, prefix="/api/v1")
app.include_router(driver_earnings_summary.router, prefix="/api/v1")
app.include_router(admin_financials.router, prefix="/api/v1")
app.include_router(admin_ride_export.router, prefix="/api/v1")
app.include_router(trip_heatmap.router, prefix="/api/v1")
app.include_router(demand_heatmap.router, prefix="/api/v1")
app.include_router(platform_config.router, prefix="/api/v1")
app.include_router(busy_hours.router, prefix="/api/v1")
app.include_router(ride_preferences.router, prefix="/api/v1")
app.include_router(complaints.router, prefix="/api/v1")
app.include_router(surge_zones_admin_router, prefix="/api/v1")
app.include_router(surge_zones_public_router, prefix="/api/v1")
app.include_router(surge_waitlist_rider_router, prefix="/api/v1")
app.include_router(surge_waitlist_public_router, prefix="/api/v1")
app.include_router(surge_waitlist_admin_router, prefix="/api/v1")
app.include_router(bulk_notifications.router, prefix="/api/v1")
app.include_router(driver_referrals.router, prefix="/api/v1")
app.include_router(driver_earnings_goals.router, prefix="/api/v1")
app.include_router(driver_tiers.router, prefix="/api/v1")
app.include_router(surge_price_lock.router, prefix="/api/v1")
app.include_router(rider_memberships.router, prefix="/api/v1")
app.include_router(scheduled_rides.router, prefix="/api/v1")
app.include_router(service_areas.router, prefix="/api/v1")
app.include_router(corporate_accounts.router, prefix="/api/v1")
app.include_router(fare_disputes.router, prefix="/api/v1")
app.include_router(blocklist.router, prefix="/api/v1")
app.include_router(driver_subscriptions.router, prefix="/api/v1")
app.include_router(driver_payouts.router, prefix="/api/v1")
app.include_router(driver_tax.router, prefix="/api/v1")
app.include_router(rider_referrals.router, prefix="/api/v1")
app.include_router(cooperative.router, prefix="/api/v1")
app.include_router(rider_rewards.router, prefix="/api/v1")
app.include_router(accessibility.router, prefix="/api/v1")
app.include_router(document_expiry.router, prefix="/api/v1")
app.include_router(vehicle_maintenance.router, prefix="/api/v1")
app.include_router(receipts.router, prefix="/api/v1")
app.include_router(ride_feedback.router, prefix="/api/v1")
app.include_router(websocket.router)


@app.get("/health")
async def health():
    return {"status": "ok", "service": settings.app_name}
