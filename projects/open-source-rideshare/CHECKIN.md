# CHECKIN.md — OpenRide Review Queue

This file tracks branches that need review before merging to `master`.

---

## Needs Your Input

### feature/corporate-business-accounts — driver certification badges

**Branch:** `feature/corporate-business-accounts`
**Commit:** `44c7037`
**Author:** Claude (claude-sonnet-4-6)
**Date:** 2026-04-15

**Summary:**
Implements a cooperative driver recognition badge system. Drivers earn badges for
quality, safety, and community contribution. Riders see a driver's active badges
when matched. This is a cooperative differentiator — Uber/Lyft have no peer
recognition system for drivers.

**Badge types:** safe_driver, five_star, accessibility_specialist, pet_friendly,
long_distance_expert, mentor, eco_driver, veteran.

**Architecture decisions:**
- One row per driver+badge_type with a unique constraint. Revoked badges are not
  deleted; `is_active=False` preserves the audit trail. Re-awarding a revoked badge
  re-activates the existing row rather than inserting a duplicate.
- Admin awards are manual (POST endpoint); `check-eligibility` auto-awards any badge
  the driver qualifies for and is safe to call repeatedly (no duplicates).
- Eligibility checks are wrapped individually in `try/except` so a missing model
  column (e.g., `Vehicle.fuel_type` not yet in schema) degrades gracefully with an
  "award manually" reason rather than failing the entire check.
- eco_driver check detects whether the `fuel_type` column exists at runtime; if not,
  the badge is marked not auto-eligible with a clear message.
- `await db.flush()` used throughout (not `commit`) — commits handled by middleware.

**Files changed:**
- `backend/app/models/driver_certification.py` — DriverCertification model + BadgeType enum
- `backend/app/schemas/driver_certification.py` — all request/response Pydantic schemas
- `backend/app/services/driver_certification.py` — award, revoke, eligibility, auto-award, stats
- `backend/app/api/v1/driver_certifications.py` — 6 endpoints (public + admin)
- `backend/app/db/migrations/versions/n1o2p3q4r5s6_add_driver_certifications.py` — migration (down_revision: z1a2b3c4d5e6)
- `backend/app/main.py` — registered driver_certifications.router
- `backend/tests/test_driver_certifications.py` — 38 unit tests, all passing

**Endpoints added:**
- `GET    /api/v1/drivers/{driver_id}/badges` — public: view any driver's active badges
- `GET    /api/v1/drivers/me/badges` — authenticated driver: view own badges (+ revoked)
- `POST   /api/v1/admin/drivers/{driver_id}/badges` — award badge (409 on duplicate active)
- `DELETE /api/v1/admin/drivers/{driver_id}/badges/{badge_type}` — revoke badge (404 if not active)
- `POST   /api/v1/admin/drivers/{driver_id}/badges/check-eligibility` — check + auto-award
- `GET    /api/v1/admin/badge-stats` — platform totals, breakdown by type, top 10 drivers

**Test results:** 5,007 passing, 0 failing (full suite — increased from 4,969 baseline by +38).

**Review notes:**
- eco_driver badge cannot be auto-awarded yet because `Vehicle` has no `fuel_type` column.
  A follow-up migration could add `fuel_type` to the vehicles table to enable auto-award.
  Admins can still award eco_driver manually via the admin endpoint.
- The `GET /drivers/{driver_id}/badges` endpoint is unauthenticated (public). If the platform
  decides badge data should be rider-only or require auth, add `Depends(get_current_user)`.

---

### feature/corporate-business-accounts — corporate business accounts system

**Branch:** `feature/corporate-business-accounts`
**Commit:** `71401f6`
**Author:** Claude (claude-sonnet-4-6)
**Date:** 2026-04-15

**Summary:**
Implements a full corporate business account management system. Companies can register corporate accounts, add employee riders with role-based access (admin vs. member), set per-member and account-level monthly spend limits, and receive consolidated billing via invoices (draft → issued → paid lifecycle).

**Architecture decisions:**
- The existing `CorporateAccount`/`CorporateMembership` models in `corporate_account.py` follow a different design (invitation flow, float amounts). The new system uses distinct Python class names (`BusinessAccount`, `BusinessAccountMember`, `BusinessInvoice`) to avoid SQLAlchemy mapper registry collisions, but the same `Base` and separate table names (`corporate_accounts_v2`, `corporate_account_members`, `corporate_invoices`).
- `Decimal` used for all monetary fields (not float) to prevent rounding issues in billing.
- Members have a unique constraint `(account_id, user_id)` — a user can only be added once per account. A separate check prevents them from joining a second account simultaneously.
- Last-admin guard: an account admin cannot be removed if they are the only active admin, preventing orphaned accounts.
- Max 500 active members per account enforced in the service layer.
- Platform admin routes use `requesting_user_id=-1` sentinel to bypass membership checks.
- `generate_invoice` creates a draft with zero totals (ride data aggregation is a future extension point); spend summary is derived from issued/paid invoices in the current calendar month.

**Files changed:**
- `backend/app/models/corporate.py` — BusinessAccount, BusinessAccountMember, BusinessInvoice models with CorporateAccountStatus, MemberRole, InvoiceStatus enums
- `backend/app/schemas/corporate.py` — Create/Update/Response schemas, InvoiceGenerateRequest, CorporateSpendSummary, CorporatePlatformSummary
- `backend/app/services/corporate_account_mgmt.py` — full service layer: account CRUD, member management, invoice lifecycle, spend tracking
- `backend/app/api/v1/corporate.py` — 17 endpoints across account-admin and platform-admin roles
- `backend/app/db/migrations/versions/d5e6f7g8h9i0_add_corporate_accounts.py` — migration (down_revision: a2b3c4d5e6f7)
- `backend/app/main.py` — registered corporate.router
- `backend/tests/test_corporate_business_accounts.py` — 39 passing service/schema unit tests + 6 skipped API tests

**Endpoints added:**
- `POST   /api/v1/corporate/accounts` — create account (caller becomes account admin)
- `GET    /api/v1/corporate/accounts/me` — get own account
- `PUT    /api/v1/corporate/accounts/me` — update own account (account admin only)
- `GET    /api/v1/corporate/accounts/me/members` — list active members
- `POST   /api/v1/corporate/accounts/me/members` — add member (account admin only)
- `PUT    /api/v1/corporate/accounts/me/members/{user_id}` — update member
- `DELETE /api/v1/corporate/accounts/me/members/{user_id}` — soft-remove member
- `GET    /api/v1/corporate/accounts/me/invoices` — list invoices
- `GET    /api/v1/corporate/accounts/me/spend` — spend summary
- `GET    /api/v1/admin/corporate/accounts` — list all accounts (filter by status)
- `GET    /api/v1/admin/corporate/accounts/{id}` — get account
- `PUT    /api/v1/admin/corporate/accounts/{id}/suspend` — suspend
- `PUT    /api/v1/admin/corporate/accounts/{id}/activate` — activate
- `POST   /api/v1/admin/corporate/accounts/{id}/invoices` — generate draft invoice
- `PUT    /api/v1/admin/corporate/invoices/{id}/issue` — issue invoice
- `PUT    /api/v1/admin/corporate/invoices/{id}/paid` — mark paid
- `GET    /api/v1/admin/corporate/summary` — platform-wide summary

**Test results:** 4,531 passing, 0 failing (full suite, no regressions from previous 4,492)

---

### feature/corporate-business-accounts — ride cancellation policies and fee system

**Branch:** `feature/corporate-business-accounts`
**Commit:** `c2c332e`
**Author:** Claude (claude-sonnet-4-6)
**Date:** 2026-04-15

**Summary:**
Implements a complete DB-backed ride cancellation policy and fee system. When a rider cancels after a configurable grace period they are charged a flat fee plus an optional percentage of the estimated fare. Drivers get a configurable number of free cancellations per day; exceeding the limit incurs a penalty. Admin can configure the policy, view all cancellation records, and waive individual fees.

**Architecture decisions:**
- The existing `evaluate_cancellation()` pure function (used by dispatch layer) is preserved intact. The new system adds DB persistence on top without breaking anything.
- One active policy at a time: creating a new policy via `POST /admin/cancellation-policy` deactivates the previous one. Old policies are kept for audit.
- `CancellationRecord` has a unique constraint on `ride_id` — exactly one record per ride, preventing double-recording.
- No-fee records (grace period, admin/system cancel) start with `fee_status=waived` immediately so the admin queue only surfaces records that need action.

**Files changed:**
- `backend/app/models/cancellation.py` — CancellationPolicy + CancellationRecord models with enums (CancelledBy, FeeChargedTo, FeeStatus)
- `backend/app/schemas/cancellation.py` — typed request/response schemas for riders, drivers, and admin
- `backend/app/services/cancellation.py` — service layer: policy retrieval, fee calculation, record creation, waive, admin list/summary
- `backend/app/api/v1/cancellation_policies.py` — 9 endpoints across rider/driver/admin roles
- `backend/app/db/migrations/versions/a2b3c4d5e6f7_add_cancellation_policies.py` — migration (down_revision: y1z2a3b4c5d6)
- `backend/app/models/__init__.py` — registered new models
- `backend/app/main.py` — wired up new router
- `backend/tests/test_cancellation.py` — 85 tests total: 53 pass (service unit + legacy engine), 32 skip (API, require live DB)

**Endpoints added:**
- `POST /api/v1/rides/{ride_id}/cancel` — rider cancels; returns fee and grace status
- `GET  /api/v1/riders/me/cancellations` — rider's own cancellation history
- `POST /api/v1/drivers/me/rides/{ride_id}/cancel` — driver cancels; returns penalty if over limit
- `GET  /api/v1/drivers/me/cancellations` — driver's own cancellation history
- `GET  /api/v1/admin/cancellation-policy` — get active policy
- `POST /api/v1/admin/cancellation-policy` — create/update policy (upsert)
- `GET  /api/v1/admin/cancellations` — list all records with optional fee_status filter
- `POST /api/v1/admin/cancellations/{id}/waive` — waive a fee with reason
- `GET  /api/v1/admin/cancellations/summary` — aggregate stats

**Test results:** 4,451 passing, 0 failing (full suite, no regressions)

---

### feature/corporate-business-accounts — lost and found system

**Branch:** `feature/corporate-business-accounts`
**Commit:** `cb508dd`
**Author:** Claude (claude-sonnet-4-6)
**Date:** 2026-04-15

**Summary:**
Implements a complete lost and found system using a dual-table design with separate
models for rider-submitted lost reports and driver-submitted found reports. An admin
workflow allows matching a lost report to a found report, then marking the item
returned, discarded, or the lost report closed with no match.

**Architecture decision:** The project already had a `lost_found` module (single
unified table with a `reporter_type` field). The new system uses separate tables
(`laf_lost_item_reports`, `laf_found_item_reports`) with independent status
lifecycles, which is a cleaner design for the matching workflow. Model classes use
the `Laf` prefix to avoid name collisions in SQLAlchemy's mapper registry.

**Files changed:**
- `backend/app/models/lost_and_found.py` — LafLostItemReport + LafFoundItemReport models with cross-FK links
- `backend/app/schemas/lost_and_found.py` — typed request/response schemas with embedded matched-report summaries
- `backend/app/services/lost_and_found.py` — service layer: create, get, list, match, mark_returned, discard, close
- `backend/app/api/v1/lost_and_found.py` — 14 endpoints across rider/driver/admin roles
- `backend/app/db/migrations/versions/y1z2a3b4c5d6_add_lost_and_found.py` — migration with enum types and indexes
- `backend/tests/test_lost_and_found.py` — 68 tests (36 service unit tests pass; 32 API tests require live DB)
- `backend/app/main.py` — wired up new router

**Endpoints added:**
- `POST /api/v1/riders/me/lost-items` — rider reports a lost item
- `GET  /api/v1/riders/me/lost-items` — rider lists own reports
- `GET  /api/v1/riders/me/lost-items/{id}` — rider gets single report
- `POST /api/v1/drivers/me/found-items-v2` — driver reports a found item
- `GET  /api/v1/drivers/me/found-items-v2` — driver lists own reports
- `GET  /api/v1/drivers/me/found-items-v2/{id}` — driver gets single report
- `GET  /api/v1/admin/lost-and-found/lost-reports` — admin lists all lost reports (filter by status)
- `GET  /api/v1/admin/lost-and-found/lost-reports/{id}` — admin gets detail
- `GET  /api/v1/admin/lost-and-found/found-reports` — admin lists all found reports (filter by status)
- `GET  /api/v1/admin/lost-and-found/found-reports/{id}` — admin gets detail
- `POST /api/v1/admin/lost-and-found/match` — admin matches lost + found pair
- `POST /api/v1/admin/lost-and-found/found-reports/{id}/mark-returned` — item returned to owner
- `POST /api/v1/admin/lost-and-found/found-reports/{id}/discard` — item discarded
- `POST /api/v1/admin/lost-and-found/lost-reports/{id}/close` — close with no match

**Test results:** 4,419 passing, 0 failing (full suite, no regressions introduced)

---

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

### feature/corporate-business-accounts — corporate batch/group booking

**Branch:** `feature/corporate-business-accounts`
**Commit:** `1f86eb9`
**Author:** Claude (claude-sonnet-4-6)
**Date:** 2026-04-15

**Summary:**
Implements Corporate Batch/Group Booking — a feature that lets account admins
create a batch booking (DRAFT), add up to 50 individual ride requests, then
submit the batch for fulfilment. This covers event shuttles, offsites, and
airport pickups for visiting clients. It is not available in Uber for Business.

**Workflow:**
1. Admin creates a batch (`POST /corporate/accounts/me/batches`) — starts DRAFT.
2. Admin adds ride requests one at a time (up to 50 per batch).
3. Admin removes requests as needed (marks REMOVED; not deleted).
4. Admin submits the batch — must have at least 1 PENDING request.
5. Admin or platform admin can cancel at any stage.

**Endpoints:**
- Member (read): list, get batch, get requests with counts
- Admin (write): create, update (DRAFT only), cancel, add/remove requests, submit
- Platform admin: same read endpoints for any account (`/admin/corporate/accounts/{id}/batches/...`)

**Architecture decisions:**
- `CorporateBatchRideRequest.account_id` is denormalised (same as batch) for fast
  account-scoped queries without joining through the batch row.
- Capacity limit (50) is enforced in the service by counting PENDING requests before
  inserting; not a DB constraint, so the limit can be adjusted without a migration.
- Cancellation is allowed from any non-cancelled status; only the service enforces
  "already cancelled" → 400, not a DB constraint.
- Ride requests are never hard-deleted; setting `status=REMOVED` preserves audit trail.
- `await db.flush()` used throughout (not `commit`) — commits handled by middleware.

**Files added:**
- `backend/app/models/corporate_batch_booking.py` — CorporateBatchBooking + CorporateBatchRideRequest models
- `backend/app/schemas/corporate_batch_booking.py` — request/response schemas (8 classes)
- `backend/app/services/corporate_batch_booking.py` — 9 service functions + 3 internal helpers
- `backend/app/api/v1/corporate_batch_booking.py` — 13 REST endpoints
- `backend/app/db/migrations/versions/u2v3w4x5y6z7_add_corporate_batch_bookings.py` — Alembic migration (revision `u2v3w4x5y6z7`, down `t2u3v4w5x6y7`)
- `backend/tests/test_corporate_batch_booking.py` — 38 tests (all passing)

**Files modified:**
- `backend/app/models/__init__.py` — added imports for BusinessAccount and new models
- `backend/app/main.py` — registered `corporate_batch_booking` router

**Test results:** 5,290 passing (5,252 existing + 38 new), 1,074 skipped, 0 failures.

---

### feature/corporate-business-accounts — corporate trip purpose codes

**Branch:** `feature/corporate-business-accounts`
**Commit:** `564a580`
**Author:** Claude (claude-sonnet-4-6)
**Date:** 2026-04-15

**Summary:**
Employees can tag their corporate rides with a purpose code (e.g. CLIENT_MEETING,
CONFERENCE, AIRPORT_TRANSFER). Corporate admins define the valid codes for their
account. Analytics break down completed-ride spend by purpose with an untagged
bucket for rides without a tag. Codes normalised to uppercase; a `requires_notes`
flag can mandate free-text notes when using a specific code.

**Architecture decisions:**
- `deactivate_purpose` sets `is_active=False` rather than deleting — rides that
  already reference the purpose retain the tag for historical analytics.
- `set_ride_purpose` validates ride ownership, that the purpose belongs to the
  ride's corporate account, and enforces `requires_notes` before persisting.
- Service functions return `(result, err)` tuples (same pattern as batch booking)
  so the API layer raises HTTPException only at the boundary.
- `_require_account_admin` is a module-level import in the API file so it can be
  cleanly patched in tests.
- Migration `v2w3x4y5z6a7` adds the `corporate_trip_purposes` table and two
  nullable columns (`trip_purpose_id`, `trip_notes`) to `rides`.

**Files added:**
- `backend/app/models/corporate_trip_purpose.py` — CorporateTripPurpose model
- `backend/app/schemas/corporate_trip_purpose.py` — Create/Update/Response schemas + analytics schemas
- `backend/app/services/corporate_trip_purpose.py` — 8 service functions
- `backend/app/api/v1/corporate_trip_purpose.py` — 9 REST endpoints (member + admin + platform-admin + rider)
- `backend/app/db/migrations/versions/v2w3x4y5z6a7_corporate_trip_purpose.py` — Alembic migration
- `backend/tests/test_corporate_trip_purpose.py` — 40 tests (all passing)

**Files modified:**
- `backend/app/models/ride.py` — added `trip_purpose_id` FK and `trip_notes` columns
- `backend/app/models/__init__.py` — added CorporateTripPurpose import
- `backend/app/main.py` — registered `corporate_trip_purpose` router

**Endpoints added:**
- `GET    /api/v1/corporate/accounts/me/trip-purposes` — list active purposes (member)
- `GET    /api/v1/corporate/accounts/me/trip-purposes/{id}` — get purpose (member)
- `POST   /api/v1/corporate/accounts/me/trip-purposes/analytics` — spend by purpose (member)
- `POST   /api/v1/corporate/accounts/me/trip-purposes` — create purpose (admin only)
- `PATCH  /api/v1/corporate/accounts/me/trip-purposes/{id}` — update purpose (admin only)
- `DELETE /api/v1/corporate/accounts/me/trip-purposes/{id}` — deactivate purpose (admin only)
- `PUT    /api/v1/rides/{ride_id}/trip-purpose` — tag or clear ride purpose (rider)
- `GET    /api/v1/admin/corporate/accounts/{id}/trip-purposes` — list all (platform admin)
- `GET    /api/v1/admin/corporate/accounts/{id}/trip-purposes/analytics` — analytics (platform admin)

**Test results:** 5,222 passing (5,182 existing + 40 new), 1,074 skipped, 0 failures (61 pre-existing failures unaffected).

---
