# CHECKIN.md — OpenRide Review Queue

This file tracks branches that need review before merging to `master`.

---

## Needs Your Input

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
