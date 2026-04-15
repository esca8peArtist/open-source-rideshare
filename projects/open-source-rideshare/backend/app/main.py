from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1 import accessibility, admin, admin_financials, admin_ride_export, airport_queue, analytics, announcements, audit, auth, background_checks, blocklist, board_elections, bulk_notifications, busy_hours, cancellation_policies, chat, complaints, cooperative, corporate, corporate_account_contacts, corporate_account_dashboard, corporate_accounts, corporate_addresses, corporate_admin_audit_log, corporate_api_keys, corporate_batch_booking, corporate_billing_contacts, corporate_blackout_periods, corporate_budget_alerts, corporate_cost_center, corporate_credit_accounts, corporate_custom_fields, corporate_data_export, corporate_delegates, corporate_departments, corporate_driver_pool, corporate_employee_expense, corporate_employee_invitations, corporate_expense_reports, corporate_fare_agreements, corporate_guest_pass, corporate_invoice, corporate_notification_settings, corporate_ride_approval, corporate_ride_policy, corporate_scheduled_reports, corporate_spending_analytics, corporate_sso_config, corporate_trip_purpose, corporate_webhooks, demand_heatmap, device_tokens, document_expiry, driver_availability, driver_certifications, driver_destination, driver_documents, driver_dividends, driver_earnings_goals, driver_earnings_guarantee, driver_earnings_summary, driver_expenses, driver_incidents, driver_insurance, driver_languages, driver_location, driver_mentorship, driver_onboarding, driver_performance, driver_payouts, driver_proposals, driver_quest, driver_rating_appeals, driver_referrals, driver_shifts, driver_subscriptions, driver_tax, driver_tiers, driver_incentive_zones, driver_work_preferences, drivers, fare_disputes, fare_splits, hardship_fund, incentives, lost_and_found, lost_found, notification_preferences, notifications, partner_orgs, payments, payouts, platform_config, pools, privacy, promos, receipts, recurring_rides, ride_carbon, ride_feedback, ride_preferences, rider_cooperative, rider_memberships, rider_ratings, rider_referrals, rider_rewards, rides, safety, safety_alerts, saved_locations, scheduled_rides, service_areas, surge_price_lock, tips, trip_heatmap, trusted_contacts, vehicle_inspection, vehicle_maintenance, vehicles, waypoints
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
app.include_router(lost_and_found.router, prefix="/api/v1")
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
app.include_router(driver_quest.router, prefix="/api/v1")
app.include_router(driver_proposals.router, prefix="/api/v1")
app.include_router(driver_dividends.router, prefix="/api/v1")
app.include_router(driver_earnings_guarantee.router, prefix="/api/v1")
app.include_router(cancellation_policies.router, prefix="/api/v1")
app.include_router(driver_rating_appeals.router, prefix="/api/v1")
app.include_router(trusted_contacts.router, prefix="/api/v1")
app.include_router(driver_incidents.router, prefix="/api/v1")
app.include_router(driver_location.router, prefix="/api/v1")
app.include_router(driver_shifts.router, prefix="/api/v1")
app.include_router(corporate.router, prefix="/api/v1")
app.include_router(rider_cooperative.router, prefix="/api/v1")
app.include_router(partner_orgs.router, prefix="/api/v1")
app.include_router(airport_queue.router, prefix="/api/v1")
app.include_router(hardship_fund.router, prefix="/api/v1")
app.include_router(driver_mentorship.router, prefix="/api/v1")
app.include_router(privacy.router, prefix="/api/v1")
app.include_router(ride_carbon.router, prefix="/api/v1")
app.include_router(driver_incentive_zones.router, prefix="/api/v1")
app.include_router(board_elections.router, prefix="/api/v1")
app.include_router(announcements.router, prefix="/api/v1")
app.include_router(safety_alerts.router, prefix="/api/v1")
app.include_router(driver_certifications.router, prefix="/api/v1")
app.include_router(driver_languages.router, prefix="/api/v1")
app.include_router(driver_work_preferences.router, prefix="/api/v1")
app.include_router(corporate_ride_policy.router, prefix="/api/v1")
app.include_router(corporate_ride_approval.router, prefix="/api/v1")
app.include_router(corporate_cost_center.router, prefix="/api/v1")
app.include_router(corporate_invoice.router, prefix="/api/v1")
app.include_router(corporate_spending_analytics.router, prefix="/api/v1")
app.include_router(corporate_batch_booking.router, prefix="/api/v1")
app.include_router(corporate_trip_purpose.router, prefix="/api/v1")
app.include_router(corporate_guest_pass.router, prefix="/api/v1")
app.include_router(corporate_employee_expense.router, prefix="/api/v1")
app.include_router(corporate_data_export.router, prefix="/api/v1")
app.include_router(corporate_budget_alerts.router, prefix="/api/v1")
app.include_router(corporate_blackout_periods.router, prefix="/api/v1")
app.include_router(corporate_fare_agreements.router, prefix="/api/v1")
app.include_router(corporate_employee_invitations.router, prefix="/api/v1")
app.include_router(corporate_expense_reports.router, prefix="/api/v1")
app.include_router(corporate_departments.router, prefix="/api/v1")
app.include_router(corporate_billing_contacts.router, prefix="/api/v1")
app.include_router(corporate_admin_audit_log.router, prefix="/api/v1")
app.include_router(corporate_custom_fields.router, prefix="/api/v1")
app.include_router(corporate_delegates.router, prefix="/api/v1")
app.include_router(corporate_addresses.router, prefix="/api/v1")
app.include_router(corporate_webhooks.router, prefix="/api/v1")
app.include_router(corporate_api_keys.router, prefix="/api/v1")
app.include_router(corporate_scheduled_reports.router, prefix="/api/v1")
app.include_router(corporate_credit_accounts.router, prefix="/api/v1")
app.include_router(corporate_account_contacts.router, prefix="/api/v1")
app.include_router(corporate_driver_pool.router, prefix="/api/v1")
app.include_router(corporate_sso_config.router, prefix="/api/v1")
app.include_router(corporate_notification_settings.router, prefix="/api/v1")
app.include_router(corporate_account_dashboard.router, prefix="/api/v1")
app.include_router(websocket.router)


@app.get("/health")
async def health():
    return {"status": "ok", "service": settings.app_name}
