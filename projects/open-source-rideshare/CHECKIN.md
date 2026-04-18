# CHECKIN.md — OpenRide Review Queue

This file tracks branches that need review before merging to `master`.

---

## Needs Your Input

### feature/rider-emergency-safety — driver hearing impairment capability flags

**Branch:** `feature/rider-emergency-safety`
**Author:** thorn
**Date:** 2026-04-18
**Commit:** 0cd7cb9

**Summary:**
Adds driver-side accessibility capability flags so drivers can declare they are
able to accommodate riders with hearing impairments. The matching engine uses
this as a soft preference: when the rider has `hearing_impairment=True`,
hearing-impairment-capable drivers are ranked first. If no capable driver is
available, matching continues normally against all drivers.

**Migration:** `b2c3d4e5f6a7` (down_revision `a1b2c3d4e5f6`)
- Adds `hearing_impairment_capable BOOLEAN NOT NULL DEFAULT false` to `driver_profiles`
- Adds `sign_language_capable BOOLEAN NOT NULL DEFAULT false` to `driver_profiles`

**Endpoints added:**
- `GET  /api/v1/drivers/me/accessibility` — read current capability flags (driver auth)
- `PUT  /api/v1/drivers/me/accessibility` — partial update; send only the fields to change

**Files added:**
- `backend/app/db/migrations/versions/b2c3d4e5f6a7_add_driver_accessibility_capability_flags.py`
- `backend/app/schemas/driver_accessibility.py` — `DriverAccessibilityUpdate` (both fields optional) and `DriverAccessibilityResponse` (both fields required)
- `backend/app/services/driver_accessibility.py` — `get_accessibility` and `update_accessibility`; raises `ValueError` when driver profile not found
- `backend/app/api/v1/driver_accessibility.py` — router; maps `ValueError` → 404
- `backend/tests/test_driver_accessibility.py` — 33 tests

**Files modified:**
- `backend/app/models/driver.py` — two new Boolean columns on `DriverProfile`
- `backend/app/services/matching.py` — `DriverCandidate` gets `hearing_impairment_capable` field; `find_candidates` and `match_ride` accept `rider_hearing_impairment` parameter; sort key updated for soft preference
- `backend/app/main.py` — `driver_accessibility` router imported and registered

**Key design decisions:**
- Soft preference (not hard filter): if `rider_hearing_impairment=True` but no capable driver exists, the engine falls back to the standard distance/rating sort. This ensures no match is lost solely because of the preference, which matters for rider safety.
- Sort key for hearing-impairment preference: `(not hearing_impairment_capable, distance_km, -rating_avg)`. Among capable drivers, the existing distance/rating ranking is preserved. Non-capable drivers always appear after all capable ones.
- `sign_language_capable` is added alongside `hearing_impairment_capable` as a natural companion flag (a driver may know sign language without broadly flagging as hearing-impairment capable, or vice versa). It is not yet used in the matching sort but is exposed through the API for future matching iterations and for display in rider/driver apps.
- WebSocket `send_ride_offer` already carries `rider_hearing_impairment` from commit `2732b7e`; confirmed wired correctly, no changes needed.

**Test results:** 33 new tests, all passing. Full suite: 5071 passed, 477 skipped, 0 failures (was 5038 before this PR).

---

### feature/rider-emergency-safety — trip share links

**Branch:** `feature/rider-emergency-safety`
**Author:** thorn
**Date:** 2026-04-18
**Commit:** 9fd42b5

**Summary:**
Adds the Trip Share Link feature: riders generate a short-lived (24h) public
token URL during a ride. Anyone with the link can view read-only ride info
(driver name, vehicle, status, pickup/dropoff, ETA) without logging in — the
safety equivalent of Uber's "Share My Trip."

**Endpoints added:**
- `POST   /api/v1/riders/me/rides/{ride_id}/share-link` — create link (201); auto-revokes any existing active link for the same ride, so only one is active at a time
- `GET    /api/v1/riders/me/rides/{ride_id}/share-link` — fetch active link (200 / 404)
- `DELETE /api/v1/riders/me/rides/{ride_id}/share-link` — revoke active link (204 / 404)
- `GET    /api/v1/trip-share/{token}` — public read-only view (200 / 404 / 410); no auth required

**Files added:**
- `backend/app/schemas/trip_share.py` — `TripShareLinkResponse` and `TripShareView` (public read-only)
- `backend/app/services/trip_share.py` — in-memory store; `create_trip_share_link` (UUID4 token, 24h expiry, auto-revoke); `get_active_link_for_ride`; `revoke_trip_share_link`; `get_trip_share_view` (returns realistic stub ride data; raises `LookupError` for unknown token, `ValueError("expired")` for revoked/expired)
- `backend/app/api/v1/trip_share.py` — router with authenticated rider endpoints and unauthenticated public endpoint; maps `LookupError` → 404, `ValueError("expired")` → 410
- `backend/app/models/trip_share.py` — `TripShareLink` SQLAlchemy model
- `backend/app/db/migrations/versions/u5v6w7x8y9z0_add_trip_share_links.py` — Alembic migration; `down_revision = t4u5v6w7x8y9`
- `backend/tests/test_trip_share.py` — 40 tests across schemas, service, router (authenticated and public), and store reset

**Key design decisions:**
- Only one active link per ride at a time. `create_trip_share_link` revokes any prior active link before inserting a new one, so re-generating a link automatically invalidates the old URL.
- The public `GET /api/v1/trip-share/{token}` endpoint has no `require_rider` or `get_current_user` dependency — it is genuinely unauthenticated by design (covered by `test_public_endpoint_requires_no_auth`).
- 410 Gone (not 401/403) for expired or revoked tokens — semantically the resource existed and has since been removed, which is more informative for link recipients.
- `_reset_store` uses `.clear()` on the module-level dict rather than replacing it, so test imports of `_links` stay bound to the live object across the autouse fixture.
- Ride data in `get_trip_share_view` is stubbed (consistent with all other in-memory services in this codebase). A follow-up can wire it to the real rides store when that moves in-memory or adds an injectable DB query.

**Test results:** 40 new tests, all passing. Full suite: 4,148 passed, 507 skipped (was 4,108 before this PR).

---

### feature/rider-emergency-safety — rider saved payment methods

**Branch:** `feature/rider-emergency-safety`
**Author:** thorn
**Date:** 2026-04-18
**Commit:** 8a1f1e7

**Summary:**
Adds a complete saved payment method system for riders. Before booking a ride,
riders can add and manage payment cards. The flow mirrors Stripe's recommended
SetupIntent pattern: call setup-intent to get a client_secret, let the frontend
collect and confirm card details, then POST the resulting payment_method_id back
to save it.

Feature includes auto-default promotion (first card is always default; deleting
the default auto-promotes the oldest remaining), 409 guard on duplicate Stripe
payment_method_id, and graceful stub fallback when Stripe is unconfigured.

**Endpoints added:**
- `POST /api/v1/riders/me/payment-methods/setup-intent` — create Stripe SetupIntent (200)
- `POST /api/v1/riders/me/payment-methods` — save confirmed method (201)
- `GET  /api/v1/riders/me/payment-methods` — list all, newest-first with total (200)
- `DELETE /api/v1/riders/me/payment-methods/{id}` — remove; auto-promote default (204)
- `PUT  /api/v1/riders/me/payment-methods/{id}/default` — set as default (200)

**Files added:**
- `backend/app/models/payment_method.py` — `RiderPaymentMethod` SQLAlchemy model
- `backend/app/schemas/payment_method.py` — `PaymentMethodCreate` (card_last4 digit
  validator), `PaymentMethodResponse`, `PaymentMethodListResponse`, `SetupIntentResponse`
- `backend/app/services/payment_method.py` — in-memory store; `create_setup_intent`
  degrades to stub; `remove_payment_method` auto-promotes default; `set_default_payment_method`
  clears all others in one pass
- `backend/app/api/v1/rider_payment_methods.py` — router; `require_rider` on every endpoint
- `backend/app/db/migrations/versions/t4u5v6w7x8y9_add_rider_payment_methods.py` — Alembic
  migration; down_revision = s3t4u5v6w7x8
- `backend/tests/test_rider_payment_methods.py` — 45 tests across schema, service, and router

**Key design decisions:**
- In-memory store is consistent with all other newer rider services in this codebase.
- `require_rider` enforced on all 5 endpoints — drivers use payouts, not payment methods.
- Auto-default: first method saved is always default; no explicit flag in the create payload
  (prevents the ambiguity of "which is default if I add two at once").
- `card_last4` validated as exactly 4 numeric characters in the Pydantic schema.
- Stripe errors in `create_setup_intent` degrade gracefully to a stub response rather
  than 502 — the rest of the add-method flow can still proceed with a frontend-provided
  payment_method_id (e.g., in a dev/test environment).

**Test results:** 45 new tests pass. Full suite: 4,108 passed, 507 skipped.

---

### feature/rider-emergency-safety — admin safety report stats + safe arrival confirmation

**Branch:** `feature/rider-emergency-safety`
**Author:** thorn
**Date:** 2026-04-18
**Commit:** 10ed745

**Summary:**
Two features that close the loop on the rider safety reporting system.

Feature 1 adds `GET /admin/safety-reports/stats` — a single endpoint that gives
platform admins an at-a-glance view of the safety report backlog and trends:
total count, breakdown by status and category, escalation rate, rolling 7-day and
30-day intake counts, and average resolution time for resolved reports.

Feature 2 adds safe arrival confirmation: after completing a ride, riders can POST
to `/riders/me/rides/{ride_id}/safe-arrival` to create an audit record. The record
is immediately retrievable via GET. Business rules enforce that the ride must be
COMPLETED, must belong to the authenticated rider, and only one confirmation per
ride is allowed (409 on duplicate).

**Files changed:**
- `backend/app/schemas/rider_safety_report.py` — new `SafetyReportStats` Pydantic
  response model with all seven stat fields
- `backend/app/services/rider_safety_report.py` — new `get_safety_report_stats(db)`
  function; computes all stats from the in-memory store in O(n)
- `backend/app/api/v1/rider_safety_report.py` — new `GET /admin/safety-reports/stats`
  endpoint with `require_admin` dependency
- `backend/app/schemas/rider_safety.py` — new `SafeArrivalCreate` and
  `SafeArrivalResponse` schemas
- `backend/app/services/rider_safety.py` — new `confirm_safe_arrival` and
  `get_safe_arrival` functions; `_safe_arrivals` in-memory store; `_reset_store`
  extended to clear it
- `backend/app/api/v1/rider_safety.py` — new `POST /riders/me/rides/{ride_id}/safe-arrival`
  (201) and `GET /riders/me/rides/{ride_id}/safe-arrival` (200/404) endpoints
- `backend/app/models/safety.py` — new `SafeArrival` SQLAlchemy model with ride_id
  (FK, unique), user_id (FK), confirmed_at (server_default), notes (nullable)
- `backend/app/db/migrations/versions/s3t4u5v6w7x8_add_safe_arrivals.py` — Alembic
  migration creating the `safe_arrivals` table; down_revision = r2s3t4u5v6w7
- `backend/tests/test_rider_safety_report.py` — 20 new stats tests in new
  `TestGetSafetyReportStats` class (added to existing file)
- `backend/tests/test_safe_arrival.py` — new file: 47 tests across TestSchemas,
  TestConfirmSafeArrival, TestGetSafeArrival, TestRouter

**Key design decisions:**
- `confirm_safe_arrival` does a real DB read to validate ride existence and
  ownership (same pattern as `post_create_safety_report`). The actual audit record
  is stored in-memory like every other safety service in this codebase.
- `LookupError` for 404 scenarios (ride not found or wrong owner), `ValueError`
  for 400 (wrong status), `RuntimeError` for 409 (duplicate). The router maps
  each exception type to the correct HTTP status code cleanly.
- Stats endpoint uses a single O(n) pass over the in-memory store rather than
  multiple filtered queries — keeps it simple and consistent with the rest of the
  codebase.
- `avg_resolution_hours` is `None` (not 0) when no resolved reports exist, so
  callers can distinguish "no data yet" from "resolved instantly".
- The `/admin/safety-reports/stats` route is declared before
  `/admin/safety-reports/{report_id}/review` in the router to prevent FastAPI
  from matching the literal string "stats" as a report_id path parameter.

**Test results:** 89 new tests pass. Full suite: 4,063 passed, 507 skipped.

---

### feature/rider-emergency-safety — driver earnings comparison vs platform average

**Branch:** `feature/rider-emergency-safety`
**Author:** thorn
**Date:** 2026-04-17
**Commit:** f58b341

**Summary:**
Adds `GET /driver/me/earnings-comparison` — shows a driver how their trailing
4-week average weekly earnings stack up against all active platform drivers in
the same window. Gives drivers a clear sense of where they stand and whether
they're above or below average.

**Files added:**
- `backend/app/schemas/driver_earnings_comparison.py` — `EarningsPercentile`
  (rank, total_drivers, percentile 0–100) and `DriverEarningsComparison`
  (driver_avg, platform_avg, difference_usd/pct, percentile object,
  active_drivers_in_period, comparison_note)
- `backend/app/services/driver_earnings_comparison.py` — single aggregating
  query (GROUP BY driver_id over last 4 weeks); `_compute_percentile` (count
  of drivers earning strictly less / total); `_compute_difference_pct` (None
  when platform_avg is 0); `_build_comparison_note` (3 specialised paths)
- `backend/app/api/v1/driver_earnings_comparison.py` — `GET /driver/me/earnings-comparison`
- `backend/tests/test_driver_earnings_comparison.py` — 52 tests across 6 classes

**Key design decisions:**
- Single aggregating DB query (GROUP BY driver_id, completed rides, last 4 weeks).
  No N+1; all ranking runs in Python for testability without a live DB.
- Drivers with no rides in the window are included in the percentile ranking
  (with avg=0) but excluded from `active_drivers_in_period` count and platform
  avg calculation — keeps the platform avg honest (only earners count).
- `difference_pct` returns `None` rather than 0 when `platform_avg` is 0,
  so callers can distinguish "no data" from "exactly average".
- Percentile is "proportion of drivers earning strictly less" (0–100, higher =
  better). Rank is 1-based (1 = top earner).

**Test results:** 52 passed, 0 skipped. Total suite: 3,076 passing.

---

### feat/background-checks-firebase-push — driver availability integrated into ride matching

**Branch:** `feature/background-checks-firebase-push`
**Author:** thorn
**Date:** 2026-04-13

**Summary:**
Integrates the driver availability and scheduling system (added in a previous session) into
the ride matching/dispatch engine. When a ride request is processed, the matching engine now
filters candidates to only include drivers who are genuinely reachable: online flag set,
heartbeat within 15 minutes, and within a scheduled availability window (or no schedule at all
per the opt-in model).

**Files changed:**
- `backend/app/services/matching.py` — new imports (DriverOnlineStatus, DriverSchedule,
  datetime utilities); new `_HEARTBEAT_STALE_MINUTES` constant; new private method
  `_get_availability_eligible_driver_ids` that does a 2-query bulk DB pre-filter
  (status+heartbeat in one query, schedule slots in a second); `find_candidates` gains
  `availability_filter: bool = True` parameter that gates the pre-filter; `match_ride`
  threads `availability_filter` through to `find_candidates`
- `backend/tests/test_matching_availability.py` — 20 unit tests (22 collected, 2 DB-skipped):
  covers online/offline, stale heartbeat, no-schedule opt-in, inside/outside window,
  multi-slot scenarios, filter bypass, empty input, null heartbeat, boundary heartbeat,
  find_candidates and match_ride integration

**Key design decisions:**
- Two-query bulk approach: one SELECT on driver_online_status (filters is_online + heartbeat
  stale threshold at DB level), one SELECT on driver_schedules (bulk for all candidate
  driver_ids). Schedule window check runs in Python. This avoids N+1 queries.
- `availability_filter=False` bypasses all DB availability checks for admin/diagnostic use.
- A TODO comment in the code identifies the path to a fully DB-level implementation (DB view
  or materialized table) for very large driver pools.
- The 15-minute stale threshold in matching.py is documented to match the value in
  `services/driver_availability.py` (which uses 5 minutes for its own display logic).
  The matching engine uses 15 minutes to be more tolerant of temporary connection loss.

**Test results:** 20 passed, 2 skipped (PostgreSQL integration tests); 1994 existing tests
unaffected.

**Review notes:**
- The `availability_filter` param is additive and backward compatible — callers that don't
  pass it get the new filtering behavior (default True), which is the correct production
  default.
- A future improvement: when `find_candidates` expands the search radius in its retry loop,
  it could optionally re-run the availability filter only for newly added candidates rather
  than the full set. This is a performance micro-optimization, not a correctness issue.

---

### feat/background-checks-firebase-push — driver tipping system

**Branch:** `feature/background-checks-firebase-push`
**Author:** thorn
**Date:** 2026-04-13

**Summary:**
Adds a standalone driver tipping system. Riders can tip their driver within
48 hours of ride completion. Tips are stored as integer cents to avoid
floating-point errors. Stripe is used for payment processing when credentials
are present; the feature degrades gracefully without them.

**Files changed:**
- `backend/app/models/tip.py` — new `TipRecord` model with `TipStatus` enum
- `backend/app/schemas/tip.py` — `TipRequest` (50–5000 cents) and `TipResponse`
- `backend/app/services/tips.py` — `submit_tip`, `get_tip_for_ride`, validation, notifications
- `backend/app/api/v1/tips.py` — 4 endpoints (POST tip, GET ride tip, GET driver tips, GET admin tips)
- `backend/app/models/__init__.py` — registers `TipRecord`
- `backend/app/main.py` — includes tips router
- `backend/tests/test_tips.py` — 37 tests (18 pass without DB, 19 require PostgreSQL test DB)

**Endpoints added:**
- `POST /api/v1/rides/{ride_id}/tip` — rider submits tip
- `GET  /api/v1/rides/{ride_id}/tip` — rider or driver fetches tip
- `GET  /api/v1/drivers/me/tips` — driver tip history with pagination
- `GET  /api/v1/admin/tips` — admin list with status/driver/date filters

**Test results:** 18 passed, 19 skipped (DB-dependent integration tests skip gracefully
when `OPENRIDE_TEST_DATABASE_URL` is not available, consistent with all other test files).

**Review notes:**
- The legacy `add_tip` on `payments.py` (using float dollars) is left untouched to
  avoid breaking the existing payment flow. The new `TipRecord` is the canonical path
  going forward; a follow-up can deprecate the old field.
- Driver earnings endpoint (`GET /driver/earnings`) already aggregates `tip_amount`
  from the `Payment` model. The new `TipRecord` amounts are separate and would need
  a follow-up to roll them into earnings totals once the migration is complete.

---

### feat/rider-emergency-safety — panic button + trusted contact alerts

**Branch:** `feature/rider-emergency-safety`
**Author:** thorn
**Date:** 2026-04-17
**Commit:** b2086d9

**Summary:**
Two connected rider safety features. The panic button lets a rider trigger an
emergency alert during an active ride; the alert goes into an admin queue sorted
oldest-first (most urgent). Trusted contacts can be designated to receive
stub notifications on trip start, trip end, and panic events.

**Files added:**
- `backend/app/schemas/rider_safety.py` — PanicAlertStatus, TriggerPanicRequest,
  PanicAlertResponse, AdminResolvePanicRequest, PanicAlertListResponse,
  TrustedContactNotificationType, TrustedContactDeliveryStatus,
  TrustedContactCreate, TrustedContactUpdate, TrustedContactResponse,
  TrustedContactNotificationResponse, TrustedContactNotificationLogResponse
- `backend/app/services/rider_safety.py` — trigger_panic, get_panic_alert,
  cancel_panic_alert, admin_list_active_panic_alerts, admin_resolve_panic_alert,
  add_trusted_contact, list_trusted_contacts, get_trusted_contact,
  update_trusted_contact, deactivate_trusted_contact, get_notification_log,
  send_trusted_contact_notifications (stub — logs to store, no real SMS/email)
- `backend/app/api/v1/rider_safety.py` — 10 endpoints across rider + admin
- `backend/tests/test_rider_safety.py` — 95 tests, all passing

**Files modified:**
- `backend/app/main.py` — registers rider_safety.router at /api/v1

**Key design decisions:**
- One ACTIVE panic alert per ride enforced at service layer; raises ValueError
  if duplicate attempted.
- Cancel within 30s sets FALSE_ALARM; after 30s sets RESOLVED. This lets riders
  undo accidental triggers while still creating a record.
- Admin list is sorted oldest-first by triggered_at (most urgent = longest
  unattended). Pagination supported.
- Trusted contacts are soft-deleted (is_active=False) so notification history
  is preserved. Deactivated contacts do not count toward the 3-contact limit.
- Notification sending is stubbed: records are written with delivery_status=SENT.
  A future implementation would call an actual SMS/email provider here and update
  delivery_status based on provider response.
- 404 on ownership mismatches — the API does not reveal whether a resource exists
  when the requestor does not own it.

**Test results:** 95 passed, 0 skipped.

---
