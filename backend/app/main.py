from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1 import admin, admin_financials, analytics, audit, auth, background_checks, chat, complaints, device_tokens, driver_availability, driver_documents, driver_insurance, driver_onboarding, driver_performance, drivers, fare_splits, incentives, lost_found, notification_preferences, notifications, payments, payouts, pools, promos, recurring_rides, ride_preferences, rider_ratings, rides, safety, saved_locations, tips, vehicle_inspection, vehicles, waypoints
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
app.include_router(driver_insurance.router, prefix="/api/v1")
app.include_router(vehicle_inspection.router, prefix="/api/v1")
app.include_router(driver_documents.router, prefix="/api/v1")
app.include_router(driver_onboarding.router, prefix="/api/v1")
app.include_router(driver_performance.router, prefix="/api/v1")
app.include_router(lost_found.router, prefix="/api/v1")
app.include_router(analytics.router, prefix="/api/v1")
app.include_router(admin_financials.router, prefix="/api/v1")
app.include_router(ride_preferences.router, prefix="/api/v1")
app.include_router(complaints.router, prefix="/api/v1")
app.include_router(surge_zones_admin_router, prefix="/api/v1")
app.include_router(surge_zones_public_router, prefix="/api/v1")
app.include_router(surge_waitlist_rider_router, prefix="/api/v1")
app.include_router(surge_waitlist_public_router, prefix="/api/v1")
app.include_router(surge_waitlist_admin_router, prefix="/api/v1")
app.include_router(websocket.router)


@app.get("/health")
async def health():
    return {"status": "ok", "service": settings.app_name}
