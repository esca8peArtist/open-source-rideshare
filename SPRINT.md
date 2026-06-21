# OpenRide Sprint Plan — June 2026

**Date:** 2026-06-21  
**Status at sprint start:** 2769 tests passing; three Phase 2 features merged to master
(background checks + FCM, driver availability in matching, driver tipping system).
Phase 3 Sprint 1 compliance engine implemented in this session (see below).

---

## What Exists Today

The three features confirmed on master before this sprint:

| Feature | Tests | Key files |
|---|---|---|
| Driver background checks (Checkr + FCM) | 74 | `services/background_checks.py`, `models/background_check.py` |
| Driver availability in ride matching | 20 | `services/driver_availability.py`, `services/matching.py` |
| Driver tipping system | 37+ | `services/tips.py`, `models/tip.py`, `api/v1/tips.py` |

---

## This Session — Completed

**Sprint 1: Compliance Engine** (`feature/compliance-engine-sprint1`)

Implements the foundation that gates driver access to the platform based on
cooperative membership standing and document currency.

**Files added / changed:**
- `app/models/driver.py` — added `MembershipStatus` enum + 7 new fields:
  `membership_status`, `license_expiry`, `background_check_expiry`,
  `vehicle_inspection_expiry`, `insurance_endorsement_expiry`,
  `insurance_endorsement_verified_at`, `jurisdiction_id`
- `app/models/jurisdiction.py` — new `Jurisdiction` model (immutable per-city TNC config)
- `app/models/__init__.py` — registered `Jurisdiction`
- `app/services/compliance.py` — compliance gate logic: `check_driver_compliance()` +
  `run_nightly_compliance_check()` coroutine
- `app/schemas/compliance.py` — Pydantic schemas for all compliance request/response shapes
- `app/api/v1/compliance.py` — 5 REST endpoints (check, list jurisdictions, get jurisdiction,
  admin membership status update, admin doc expiry update)
- `app/main.py` — registered compliance router
- `app/db/migrations/versions/h2i3j4k5l6m7_add_compliance_engine.py` — Alembic migration
  (jurisdictions table + driver_profiles columns + Portland OR + Atlanta GA seed data)
- `tests/test_compliance.py` — 38 unit tests (all passing)

**Test results:** 2807 passed, 386 skipped, 0 failed (full suite, non-integration)

No external credentials required.

---

## Top 3 Next Features (No External Setup Required)

### 1. Go-Online Compliance Gate (Sprint 3 Item 1) — 6–8 hours

Modify the existing `POST /api/v1/driver/go-online` endpoint to call
`check_driver_compliance()` before allowing the status toggle.

**What it is:** Drivers with expired documents or suspended membership cannot
set `is_online = True`. The API returns a 403 with the first blocking issue's
user-facing message.

**Why it's next:** This is the primary consumer of the compliance engine just
shipped. Without it, the compliance data has no enforcement effect at runtime.

**Files to touch:**
- `backend/app/api/v1/drivers.py` — add compliance check to the go-online route
- `backend/app/services/compliance.py` — already complete; just needs to be called
- `backend/tests/test_compliance_gate.py` — new test file

**No external deps required.** Uses the compliance service already implemented.

---

### 2. Earnings API Line-Item Breakdown (Sprint 3 Item 2) — 8–10 hours

Enhance `GET /api/v1/driver/earnings` to return per-trip line items:
`base_fare`, `stripe_fee`, `cooperative_fee`, `driver_payout`, plus
period-bucketed aggregates (today, this week, this month, YTD).

**What it is:** Currently the earnings endpoint returns totals only. Drivers
need to see transparent per-trip breakdowns and period summaries to trust the
cooperative and to file accurate taxes.

**Why it's next:** Transparency is a core cooperative value. This is directly
visible to drivers and has no external dependencies.

**Files to touch:**
- `backend/app/api/v1/drivers.py` — update earnings endpoint
- `backend/app/schemas/driver.py` — add `EarningsLineItem`, update `EarningsSummary`
- `backend/tests/test_driver_earnings.py` — extend existing tests

**No external deps required.** All data already exists in the `payments` table.

---

### 3. Dispatcher Nightly Compliance Cron Integration (Sprint 1 Item 2 close-out) — 3–4 hours

Wire `run_nightly_compliance_check()` into the existing dispatch scheduler
so it runs automatically at 02:00 UTC nightly.

**What it is:** The nightly cron function exists in `services/compliance.py`
but is not yet called by anything. The dispatch scheduler in
`services/dispatch_scheduler.py` already provides the scheduling infrastructure.

**Why it's next:** Without the cron, expired documents are never auto-detected —
the compliance gate can only catch them at go-online time. The nightly run also
sends proactive warnings before expiry (push notifications — 14/7/1 day ahead
for license, 30/14/1 for background check) once notification sends are connected.

**Files to touch:**
- `backend/app/services/dispatch_scheduler.py` — add nightly compliance job
- `backend/tests/test_dispatch_scheduler.py` — extend tests
- `backend/tests/test_compliance.py` — scheduler integration tests

**No external deps required.** Push notifications degrade gracefully if Firebase
is not configured.

---

## Top 2 Features Requiring External Setup

### 4. Checkr Background Check Integration (Sprint 2 Item 1) — 20–25 hours

Full Checkr API client: `create_candidate()`, `request_check()`, webhook handler
with HMAC-SHA256 signature verification, FCRA adverse action flow.

**External setup required:**
- Checkr business account at https://checkr.com
- `OPENRIDE_CHECKR_API_KEY` and `OPENRIDE_CHECKR_WEBHOOK_SECRET` environment variables
- Webhook URL registered in Checkr console (requires a publicly reachable server)
- Checkr package name configured (`OPENRIDE_CHECKR_DEFAULT_PACKAGE`, default already set)

The service already has a graceful fallback when credentials are absent; unit tests
can mock all Checkr calls. Only the staging/production E2E tests require live credentials.

**Files to add:**
- `backend/app/services/background_checks.py` — already partially exists; extend it
- `backend/app/api/v1/background_checks.py` — webhook endpoint

---

### 5. Firebase Cloud Messaging Push Notifications (Sprint 1 Item 3 / Phase 2) — 8–12 hours

Send push notifications to drivers when compliance documents are near-expiry, and
to riders/drivers for ride events.

**External setup required:**
- Google Firebase project with Cloud Messaging enabled
- `OPENRIDE_FIREBASE_CREDENTIALS_JSON` — full service account JSON as env var
- `OPENRIDE_NOTIFICATIONS_PUSH_ENABLED=true`
- `OPENRIDE_FIREBASE_PROJECT_ID` — Firebase project ID
- Mobile apps must register device tokens via `POST /api/v1/device-tokens/register`

The `notification_providers.py` service already implements graceful degradation when
Firebase is not configured. The device token model and registration endpoint are
already in place. What's missing is the proactive compliance notification sends.

---

## Recommended Starting Point

Start with **item 1 (Go-Online Compliance Gate)**. It's a 1-day task that makes
the compliance engine ship complete functionality to drivers. It requires no external
setup and is the single highest-value change: without it, compliance data is
collected but never enforced at the go-online boundary.

After that, **item 3 (Nightly Cron)** is a half-day task that closes out Sprint 1
as fully operational.

**Item 2 (Earnings Breakdown)** is the next independent sprint after that.

---

## Estimated Hours Summary

| # | Feature | Hours | Requires External? |
|---|---|---|---|
| 1 | Go-online compliance gate | 6–8 | No |
| 2 | Earnings API line-item breakdown | 8–10 | No |
| 3 | Nightly compliance cron integration | 3–4 | No |
| 4 | Checkr background check integration | 20–25 | Yes (Checkr account) |
| 5 | Firebase push notifications | 8–12 | Yes (Firebase project) |
