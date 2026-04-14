# CHECKIN.md — OpenRide Review Queue

This file tracks branches that need review before merging to `master`.

---

## Needs Your Input

### feature/driver-revenue-projections — driver revenue projections and earnings comparison

**Branch:** `feature/driver-revenue-projections`
**Author:** Claude (claude-sonnet-4-6)
**Date:** 2026-04-14

**Summary:**
Adds two new authenticated driver endpoints to help drivers understand their earning
potential and how they compare to the rest of the platform.

`GET /api/v1/analytics/drivers/me/revenue-projections` returns a personalized earnings
projection for the next week, month, or quarter with conservative/moderate/optimistic
scenario multipliers. Drivers with fewer than 5 completed rides receive a projection
built from platform-wide averages with `is_new_driver_estimate: true` so they can
always see a useful estimate from their first session.

`GET /api/v1/analytics/drivers/me/earnings-comparison` shows how a driver's metrics
(rides, gross earnings, tips, completion rate) compare against platform averages for the
same period and provides a percentile rank across all active drivers.

**Files changed:**
- `backend/app/services/driver_revenue.py` — pure business logic; no FastAPI imports;
  contains `get_driver_revenue_projection`, `get_driver_earnings_comparison`, and
  internal helpers (`_fetch_driver_rides`, `_fetch_tips_for_rides`,
  `_fetch_platform_fees_for_rides`, `_build_projection`, `_percentile`)
- `backend/app/schemas/driver_revenue.py` — Pydantic schemas:
  `RevenueProjectionResponse`, `EarningsComparisonResponse`, and constituent models
- `backend/app/api/v1/analytics.py` — two new endpoints added to the existing analytics
  router; input validation raises 422 for unrecognised period/scenario values
- `backend/tests/test_driver_revenue_projections.py` — 48 tests (33 unit via AsyncMock,
  15 integration that run when the test DB is available)

**Key design decisions:**
- New-driver threshold (< 5 rides) uses named constants so it is easy to tune.
- Platform fee percentage is derived from the actual `payments.platform_fee` column when
  records exist, falling back to the `DEFAULT_PLATFORM_FEE_PCT = 0.12` constant.
- The bulk-tip approach in earnings comparison avoids N+1 queries by loading all tips for
  the period in a single query and distributing them by `ride.driver_id`.
- `_percentile` counts values strictly below, which is the standard "exclusive"
  percentile rank (consistent with how sports/academic rankings work).
- `avg_hourly_rate` uses net earnings (after fee deduction) and falls back to the
  platform-average ride duration when `duration_min` is absent from ride records.

**Test results:** 33 unit tests pass; 15 integration tests skip without test DB.
Full suite: 2802 passed, 465 skipped — no regressions against prior 2769 baseline.

**Review notes:**
- The earnings comparison completion rate percentile uses platform constant `0.91` for
  the comparison distribution since we don't fetch per-driver cancelled-ride counts for
  all drivers in this query. A future improvement could add a subquery or a materialized
  view for per-driver completion rates across the period.
- Projection notes are hardcoded strings. If the platform grows multi-language support,
  these should be moved to a translations layer.

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
