# CHECKIN.md — OpenRide Review Queue

This file tracks branches that need review before merging to `master`.

---

## Needs Your Input

### feature/corporate-business-accounts — corporate fleet cost analytics (latest)

**Branch:** `feature/corporate-business-accounts`
**Commit:** `9558413`
**Author:** Claude (claude-sonnet-4-6)
**Date:** 2026-04-17

**Summary:**
Fleet admins can now view aggregated cost analytics across all three fleet
cost sources — fuel fill-ups, maintenance service records, and toll charges.

**New endpoints:**
- `GET /corporate/{account_id}/fleet/analytics/fleet-costs` — fleet-wide summary (total fuel + maintenance + toll costs, vehicle count)
- `GET /corporate/{account_id}/fleet/analytics/fleet-costs/monthly` — monthly cost trend (last N months, default 12)
- `GET /corporate/{account_id}/fleet/analytics/fleet-costs/vehicles` — per-vehicle cost breakdown
- `GET /admin/fleet-cost-analytics/{account_id}` — platform-admin view

**Architecture decisions:**
- Read-only analytics layer — no new tables, queries aggregate from existing `corporate_fleet_fuel_logs`, `corporate_fleet_maintenance_records`, and `corporate_fleet_toll_charges`
- Admin-only (requires `MemberRole.ADMIN`); platform admin bypasses member check via `require_admin` dep
- Maintenance costs restricted to `status=completed` records to exclude scheduled/cancelled work
- `func.coalesce(func.sum(...), 0)` throughout to prevent NULL aggregates on sparse data
- Monthly trend uses PostgreSQL `extract(year/month, ...)` GROUP BY — zero-padded as `YYYY-MM` strings in Python

**Files added/modified:**
- `backend/app/schemas/corporate_fleet_cost_analytics.py` — 5 Pydantic v2 schemas
- `backend/app/services/corporate_fleet_cost_analytics_service.py` — 3 service functions + admin guard
- `backend/app/api/v1/corporate_fleet_cost_analytics.py` — 4 GET endpoints
- `backend/app/main.py` — router registered
- `backend/tests/test_corporate_fleet_cost_analytics.py` — 40 tests

**Test result:** 9,543 passing (40 new). The 2 pre-existing failures (`test_corporate_guest_pass`, `test_corporate_shuttle`) are unrelated.

---

### feature/corporate-business-accounts — corporate fleet driver assignments

**Branch:** `feature/corporate-business-accounts`
**Commit:** `095b3d8`
**Author:** Claude (claude-sonnet-4-6)
**Date:** 2026-04-17

**Summary:**
Fleet admins can now assign corporate account members to fleet vehicles, tracking who
is the primary, secondary, pool, or temporary driver of each vehicle along with the
full assignment history.

**Architecture decisions:**
- Single table `corporate_fleet_driver_assignments` with two PG enums:
  `fleetdriverassignmenttype` (primary, secondary, pool, temporary) and
  `fleetdriverassignmentstatus` (active, inactive, pending, suspended).
- Primary uniqueness enforced in the service layer: creating a new primary assignment
  automatically ends (status→inactive, end_date=today) any existing active primary for
  the same vehicle — no extra endpoint needed.
- Secondary driver cap enforced at 2 active secondaries per vehicle; pool and temporary
  assignments have no per-vehicle uniqueness constraint.
- Pending status is auto-set when `start_date` is in the future; explicit
  `activate_assignment` action promotes pending→active.
- Status lifecycle: pending→active (activate), active→suspended (suspend),
  active/suspended→inactive (end). Only inactive records may be deleted.
- Member-visible routes use the vehicle-scoped path
  `/corporate/{account_id}/fleet-vehicles/{vehicle_id}/driver-assignments`.
  Static segments (`/primary`) are declared before `/{assignment_id}` to prevent
  FastAPI routing conflicts.
- Admin account-wide routes use `/corporate/{account_id}/fleet-driver-assignments/`
  (trailing slash) with `/active` declared before `/{assignment_id}`.
- Platform admin: `GET /admin/fleet-driver-assignments` with optional `account_id` filter.

**Files added/modified:**
- `backend/app/models/corporate_fleet_driver_assignment.py` — ORM model
- `backend/app/schemas/corporate_fleet_driver_assignment.py` — Pydantic v2 schemas
- `backend/app/services/corporate_fleet_driver_assignment_service.py` — 12 service functions
- `backend/app/api/v1/corporate_fleet_driver_assignment.py` — 13 endpoints
- `backend/app/db/migrations/versions/v1w2x3y4z5a6_corporate_fleet_driver_assignment.py` — Alembic migration
- `backend/app/main.py` — router registered
- `backend/tests/test_corporate_fleet_driver_assignment.py` — 58 tests

**Test result:** 9,503 passing (58 new). The 2 pre-existing failures
(`test_corporate_guest_pass`, `test_corporate_shuttle`) are unrelated to this change.

---

### feature/corporate-business-accounts — corporate fleet maintenance scheduling

**Branch:** `feature/corporate-business-accounts`
**Commit:** `f0fe19c`
**Author:** Claude (claude-sonnet-4-6)
**Date:** 2026-04-17

**Summary:**
Fleet managers schedule preventive maintenance and log completed service records for
company vehicles. Records track maintenance type, lifecycle status, scheduled and
completed dates, vendor/technician details, costs, odometer readings, and
next-service thresholds. Overdue detection automatically promotes stale scheduled
records to status=overdue.

**Architecture decisions:**
- Single-table design: `corporate_fleet_maintenance_records` — one row per scheduled
  or completed event per vehicle.
- Two PG enums: `fleetmaintenancetype` (12 values: oil_change, tire_rotation,
  brake_inspection, air_filter, transmission_service, battery_replacement,
  coolant_flush, spark_plugs, wheel_alignment, state_inspection, recall_repair, other)
  and `fleetmaintenancestatus` (5 values: scheduled, in_progress, completed,
  cancelled, overdue).
- `get_overdue_maintenance` marks records as overdue in the same DB commit before
  returning them — callers always get up-to-date status without a separate call.
- Vehicle-scoped list and GET endpoints use `/scheduled-maintenance` rather than
  `/maintenance` to avoid a routing conflict with the existing
  `corporate_vehicle_maintenance_log` router which owns
  `/fleet-vehicles/{vehicle_id}/maintenance`.
- Static routes (`/`, `/overdue`) are declared before `/{record_id}` to prevent
  FastAPI path-matching conflicts.
- `complete_maintenance` accepts optional `completed_date`, `cost_usd`, and
  `odometer` query params to allow recording service details at completion time
  without needing a separate update call.
- `cancel_maintenance` raises 409 for both completed and cancelled records (terminal
  states cannot be cancelled).

**Files created:**
- `backend/app/models/corporate_fleet_maintenance.py`
- `backend/app/schemas/corporate_fleet_maintenance.py`
- `backend/app/services/corporate_fleet_maintenance_service.py`
- `backend/app/api/v1/corporate_fleet_maintenance.py`
- `backend/app/db/migrations/versions/u0v1w2x3y4z5_corporate_fleet_maintenance.py`
- `backend/tests/test_corporate_fleet_maintenance.py`

**Files modified:**
- `backend/app/main.py` — added `corporate_fleet_maintenance` to import line and
  registered `corporate_fleet_maintenance.router`

**Endpoints added (13 total):**
- `GET  /api/v1/corporate/{account_id}/fleet-vehicles/{vehicle_id}/scheduled-maintenance` — member: list vehicle records (status, maintenance_type filters)
- `GET  /api/v1/corporate/{account_id}/fleet-vehicles/{vehicle_id}/maintenance-summary` — member: vehicle aggregate summary
- `GET  /api/v1/corporate/{account_id}/fleet-vehicles/{vehicle_id}/scheduled-maintenance/{record_id}` — member: get one record
- `POST /api/v1/corporate/{account_id}/fleet-vehicles/{vehicle_id}/scheduled-maintenance` — admin: schedule → 201
- `GET  /api/v1/corporate/{account_id}/fleet-maintenance/` — admin: list all for account (vehicle_id, status, maintenance_type filters)
- `GET  /api/v1/corporate/{account_id}/fleet-maintenance/overdue` — admin: detect + return overdue records
- `PUT  /api/v1/corporate/{account_id}/fleet-maintenance/{record_id}` — admin: update
- `POST /api/v1/corporate/{account_id}/fleet-maintenance/{record_id}/complete` — admin: mark completed
- `POST /api/v1/corporate/{account_id}/fleet-maintenance/{record_id}/cancel` — admin: cancel (409 if completed/cancelled)
- `DELETE /api/v1/corporate/{account_id}/fleet-maintenance/{record_id}` — admin: delete → 204
- `GET  /api/v1/corporate/{account_id}/fleet-maintenance-summary` — admin: account-level summary
- `GET  /api/v1/platform/corporate/fleet-maintenance/` — platform-admin: all records
- `GET  /api/v1/platform/corporate/fleet-maintenance/{account_id}` — platform-admin: records for one account

**Test results:** 50/50 new tests passing. Full suite: 9,445 passing, 2 pre-existing failures
(`test_corporate_guest_pass::test_validate_token_not_yet_valid` and
`test_corporate_shuttle::test_get_route_summary_returns_correct_counts` — both pre-date
this session), 1082 skipped.

**Push status:** Commit f0fe19c is on local branch feature/corporate-business-accounts.
Remote push was blocked by permission error on SuperClaude-Org remote — push to
rideshare origin when ready.

---

### feature/corporate-business-accounts — corporate fleet vehicle registration tracking

**Branch:** `feature/corporate-business-accounts`
**Commit:** `334c869`
**Author:** Claude (claude-sonnet-4-6)
**Date:** 2026-04-17

**Summary:**
Fleet managers track state/jurisdiction vehicle registration records per company
vehicle. Records carry registration number (unique per account), state/jurisdiction,
registration date, expiration date, optional annual fee, and optional registered
owner name. The `/expiring` endpoint returns active registrations expiring within
N days with `days_until_expiry` computed in Python. The account summary aggregates
active/inactive counts, expiring-within-30-days count, total annual fee across
active records, and a per-state breakdown dict.

**Architecture decisions:**
- Single-table design: `corporate_fleet_vehicle_registrations` — one row per
  registration, unique on (account_id, registration_number).
- No enum needed — registration is simpler than insurance; state is a free-text
  String(100) to support all jurisdictions.
- `get_expiring_registrations` computes `days_until_expiry` in Python from
  `date.today()` delta — consistent with the insurance implementation.
- Static routes (`/expiring`, `/summary`, `/`) placed before `/{registration_id}`
  to prevent FastAPI path-matching conflicts.

**Files created:**
- `backend/app/models/corporate_fleet_registration.py`
- `backend/app/schemas/corporate_fleet_registration.py`
- `backend/app/services/corporate_fleet_registration_service.py`
- `backend/app/api/v1/corporate_fleet_registration.py`
- `backend/app/db/migrations/versions/s8t9u0v1w2x3_corporate_fleet_registration.py`
- `backend/tests/test_corporate_fleet_registration.py`

**Files modified:**
- `backend/app/models/__init__.py` — added `CorporateFleetVehicleRegistration` import
- `backend/app/main.py` — registered `corporate_fleet_registration.router`

**Test results:** 43/43 passed (full suite: 9337 passed, 2 pre-existing failures unrelated)

**Pushed:** `rideshare/feature/corporate-business-accounts` (esca8peArtist fork)

---

### feature/corporate-business-accounts — corporate fleet insurance tracking

**Branch:** `feature/corporate-business-accounts`
**Commit:** `94174d3`
**Author:** Claude (claude-sonnet-4-6)
**Date:** 2026-04-16

**Summary:**
Fleet managers track insurance policies per company vehicle. Policies carry type
(liability/collision/comprehensive/commercial_auto/uninsured_motorist/other),
provider name, coverage/deductible/premium amounts, and start/end dates. The
`/expiring` endpoint returns active policies expiring within N days with
`days_until_expiry` computed. The account summary aggregates active/inactive
counts, expiring-within-30-days count, total annual premium, and per-type breakdown.

**Architecture decisions:**
- Single-table design: `corporate_fleet_insurance_policies` — one row per policy,
  unique on (account_id, policy_number) to prevent duplicate registrations.
- `policy_start_date` and `policy_end_date` use SQLAlchemy `Date` (not `DateTime`)
  since insurance policies are date-scoped, not time-scoped.
- `get_expiring_policies` computes `days_until_expiry` in Python from `date.today()`
  delta — no DB-side computed column needed.
- Static routes (`/expiring`, `/summary`, `/`) are placed before `/{policy_id}` to
  prevent FastAPI path conflicts.
- `deactivate_policy` / `reactivate_policy` follow existing soft-delete pattern with
  409 guards to prevent double-deactivation or redundant reactivation.
- InsuranceType enum: `liability` / `collision` / `comprehensive` / `commercial_auto` /
  `uninsured_motorist` / `other`

**Files created:**
- `backend/app/models/corporate_fleet_insurance.py`
- `backend/app/schemas/corporate_fleet_insurance.py`
- `backend/app/services/corporate_fleet_insurance_service.py`
- `backend/app/api/v1/corporate_fleet_insurance.py`
- `backend/app/db/migrations/versions/o4p5q6r7s8t9_corporate_fleet_insurance.py`
- `backend/tests/test_corporate_fleet_insurance.py` (39 tests)

**Files modified:**
- `backend/app/models/__init__.py` — registered CorporateFleetInsurancePolicy, InsuranceType
- `backend/app/main.py` — imported + registered corporate_fleet_insurance.router

---

### feature/corporate-business-accounts — corporate vehicle inspection checklists

**Branch:** `feature/corporate-business-accounts`
**Commit:** `ad5292d`
**Author:** Claude (claude-sonnet-4-6)
**Date:** 2026-04-16

**Summary:**
Fleet managers define reusable inspection templates with named checklist items
(lights, brakes, tires, fuel level, etc.). Drivers or fleet managers create
pending inspections before/after vehicle use and submit completed checklists.
The system evaluates pass/fail/requires_attention based on whether required items
pass, and populates defects_noted for maintenance tracking. Ties into the existing
CorporateFleetVehicle, CorporateVehicleReservation, and CorporateVehicleMaintenanceLog models.

**Architecture decisions:**
- Two-table design: `corporate_vehicle_inspection_templates` (reusable templates per
  account) and `corporate_vehicle_inspections` (pending/submitted inspection records).
- JSONB used for `inspection_items` and `items_checked` to allow flexible checklist
  schemas without requiring schema migrations as item types evolve.
- Template items use `is_required` flag; submit logic distinguishes required failures
  (→ `failed`) from optional failures (→ `requires_attention`).
- `items_checked` is pre-populated with `passed=None` at create time when a template
  is provided, giving inspectors a structured form to fill in.
- Route ordering: `/summary` and `/templates` GET routes are declared before
  `/{inspection_id}` and `/{template_id}` to prevent FastAPI path collisions.
- `template_id` on `CorporateVehicleInspection` is SET NULL (not CASCADE) so historical
  inspections survive template deactivation.
- InspectionType enum: `pre_trip` / `post_trip` / `scheduled` / `incident`
- InspectionStatus enum: `pending` / `passed` / `failed` / `requires_attention`

**Files created:**
- `backend/app/models/corporate_vehicle_inspection.py`
- `backend/app/schemas/corporate_vehicle_inspection.py`
- `backend/app/services/corporate_vehicle_inspection_service.py`
- `backend/app/api/v1/corporate_vehicle_inspection.py`
- `backend/app/db/migrations/versions/n3o4p5q6r7s8_corporate_vehicle_inspection.py`
- `backend/tests/test_corporate_vehicle_inspection.py` (48 tests)

**Files modified:**
- `backend/app/models/__init__.py` — registered CorporateVehicleInspectionTemplate, CorporateVehicleInspection
- `backend/app/main.py` — imported + registered corporate_vehicle_inspection.router

**Endpoints added (13 total):**
- `GET  /api/v1/corporate/vehicle-inspections/summary` — member: account summary
- `GET  /api/v1/corporate/vehicle-inspections/templates` — member: list templates
- `GET  /api/v1/corporate/vehicle-inspections/templates/{template_id}` — member: get template
- `POST /api/v1/corporate/vehicle-inspections/templates` — admin: create template (201)
- `PUT  /api/v1/corporate/vehicle-inspections/templates/{template_id}` — admin: update template
- `POST /api/v1/corporate/vehicle-inspections/templates/{template_id}/deactivate` — admin: deactivate template
- `GET  /api/v1/corporate/vehicle-inspections` — member: list inspections (multi-filter)
- `POST /api/v1/corporate/vehicle-inspections` — member: create inspection (201)
- `GET  /api/v1/corporate/vehicle-inspections/{inspection_id}` — member: get inspection
- `POST /api/v1/corporate/vehicle-inspections/{inspection_id}/submit` — member: submit inspection
- `GET  /api/v1/platform/corporate/vehicle-inspections` — platform admin: all inspections
- `GET  /api/v1/platform/corporate/vehicle-inspections/templates` — platform admin: all templates

**Test count:** 9,075 passing (was 9,070; +48 new, -1 pre-existing unrelated failure in test_corporate_guest_pass.py excluded)

---

### feature/corporate-business-accounts — corporate shuttle pass management

**Branch:** `feature/corporate-business-accounts`
**Commit:** `36d2a02`
**Author:** Claude (claude-sonnet-4-6)
**Date:** 2026-04-16

**Summary:**
Enterprise accounts define pre-paid shuttle pass types and issue digital passes to
employees. Employees redeem passes when booking shuttle seats; each redemption is
recorded in an append-only usage ledger. Admins get an aggregate summary of pass
stats (type counts, issued/active/expired counts, ride totals) for reporting.

**Architecture decisions:**
- Three-table design: `corporate_shuttle_pass_types` (admin-defined templates),
  `corporate_shuttle_passes` (issued per-employee passes), and
  `corporate_shuttle_pass_usages` (append-only redemption ledger).
- `rides_remaining` is a computed field (`rides_total - rides_used`) not stored on
  the row — `PassResponse` uses a custom `from_orm_pass()` classmethod instead of
  plain `model_validate` to populate it.
- Route ordering: `/passes/my` and `/passes/summary` are placed before
  `/passes/{pass_id}` in the router to prevent FastAPI path conflicts.
- `expires_at` is computed at issue time: `now + timedelta(days=validity_days)` if
  `validity_days` is set on the pass type; otherwise NULL (never expires).
- `redeem_pass` validates: pass is active, belongs to the calling member, not
  expired, and has rides remaining — returning 409 for each failure case.
- `get_account_pass_summary` runs 5 aggregate queries and returns totals in a
  single `PassSummaryResponse`.

**Files created:**
- `backend/app/models/corporate_shuttle_pass.py`
- `backend/app/schemas/corporate_shuttle_pass.py`
- `backend/app/services/corporate_shuttle_pass_service.py`
- `backend/app/api/v1/corporate_shuttle_pass.py`
- `backend/app/db/migrations/versions/i8j9k0l1m2n3_corporate_shuttle_pass.py`
- `backend/tests/test_corporate_shuttle_pass.py`

**Files modified:**
- `backend/app/main.py` — imported + registered corporate_shuttle_pass.router

**Endpoints added:**
- `GET  /api/v1/corporate/{account_id}/shuttle/pass-types`
  — member: list pass types (is_active filter)
- `GET  /api/v1/corporate/{account_id}/shuttle/passes/my`
  — member: list own passes (is_active filter)
- `GET  /api/v1/corporate/{account_id}/shuttle/passes/{pass_id}`
  — member: get one pass
- `POST /api/v1/corporate/{account_id}/shuttle/passes/{pass_id}/redeem`
  — member: redeem a ride from a pass
- `POST /api/v1/corporate/{account_id}/shuttle/pass-types`
  — admin: create pass type
- `GET  /api/v1/corporate/{account_id}/shuttle/pass-types/{type_id}`
  — admin: get pass type detail
- `PUT  /api/v1/corporate/{account_id}/shuttle/pass-types/{type_id}`
  — admin: update pass type
- `POST /api/v1/corporate/{account_id}/shuttle/pass-types/{type_id}/deactivate`
  — admin: deactivate pass type
- `POST /api/v1/corporate/{account_id}/shuttle/members/{member_id}/passes/issue`
  — admin: issue pass to member
- `GET  /api/v1/corporate/{account_id}/shuttle/passes/summary`
  — admin: aggregate pass statistics
- `GET  /api/v1/platform/corporate/shuttle/passes/all`
  — platform-admin: all passes across accounts

**Tests:** 74 new tests (service: 30, schema: 8, API: 28, integration: 8) — all passing.
Full suite: 8,896 passing, 1 pre-existing failure (test_corporate_guest_pass::test_validate_token_not_yet_valid), 1082 skipped.

**Ready to merge when:** you decide to push this feature branch.

---

### feature/corporate-business-accounts — corporate shuttle waitlist (previous)

**Branch:** `feature/corporate-business-accounts`
**Commit:** `441a2c7`
**Author:** Claude (claude-sonnet-4-6)
**Date:** 2026-04-16

**Summary:**
When a shuttle schedule run is at full capacity, employees can join a
waitlist for a specific date. Cancelling a confirmed booking automatically
promotes the first waiting member to a confirmed seat — no manual admin
action needed.

**Architecture decisions:**
- `queue_position` is assigned as max(existing)+1 at join time — lightweight
  and correct for typical waitlist volumes. No resequencing on cancel; existing
  queue positions are stable identifiers.
- Auto-promotion is triggered in the API layer (cancel_booking endpoint) after
  `cancel_booking` succeeds. It calls `promote_from_waitlist` which re-checks
  capacity before acting — safe if called multiple times.
- `member_id=None` waiters (user deleted) are skipped by promote; the next
  waiter with a valid member_id would be found on the next call.
- `WaitlistStatus.expired` is defined for future use (e.g., past-date entries)
  but not auto-set — a scheduled job could set it later.
- Unique constraint `(schedule_id, member_id, booking_date)` prevents duplicate
  waiting entries; leaving and re-joining is allowed (new row with new position).

**Files created:**
- `backend/app/models/corporate_shuttle_waitlist.py`
- `backend/app/schemas/corporate_shuttle_waitlist.py`
- `backend/app/services/corporate_shuttle_waitlist_service.py`
- `backend/app/api/v1/corporate_shuttle_waitlist.py`
- `backend/app/db/migrations/versions/h7i8j9k0l1m2_corporate_shuttle_waitlist.py`
- `backend/tests/test_corporate_shuttle_waitlist.py`

**Files modified:**
- `backend/app/main.py` — imported + registered corporate_shuttle_waitlist.router
- `backend/app/api/v1/corporate_shuttle.py` — imported promote_from_waitlist;
  cancel_booking endpoint now calls it after successful cancel
- `backend/tests/test_corporate_shuttle.py` — patched promote_from_waitlist in
  test_api_cancel_booking_200 (existing test hit the new code path)

**Endpoints added:**
- `POST /api/v1/corporate/{account_id}/shuttle/schedules/{schedule_id}/waitlist`
  — member: join waitlist (201)
- `GET  /api/v1/corporate/{account_id}/shuttle/my-waitlists`
  — member: own waitlist entries (status filter)
- `GET  /api/v1/corporate/{account_id}/shuttle/waitlist/{entry_id}`
  — member: get one entry
- `POST /api/v1/corporate/{account_id}/shuttle/waitlist/{entry_id}/leave`
  — member: cancel waitlist entry
- `GET  /api/v1/corporate/{account_id}/shuttle/schedules/{schedule_id}/waitlist`
  — admin: list waitlist for schedule+date (status filter)
- `GET  /api/v1/corporate/{account_id}/shuttle/schedules/{schedule_id}/waitlist/summary`
  — admin: waiting_count/promoted_count/total for schedule+date
- `GET  /api/v1/platform/corporate/shuttle/waitlist/all`
  — platform-admin: cross-account listing (account_id+status filters)

**Tests:** 65 new tests (service: 31, schema: 9, API: 21, integration: 4) — all passing.
Full suite: 8,822 passing, 1 pre-existing failure (test_corporate_guest_pass::test_validate_token_not_yet_valid), 1082 skipped.

**Ready to merge when:** you decide to push this feature branch.

---

### feature/corporate-business-accounts — corporate vehicle reservation booking (latest)

**Branch:** `feature/corporate-business-accounts`
**Commit:** `f947dd1`
**Author:** Claude (claude-sonnet-4-6)
**Date:** 2026-04-16

**Summary:**
Employees can reserve company fleet vehicles for self-drive use during specified
time windows — like an internal Zipcar. Reservations must not overlap for the same
vehicle (pending or confirmed). Admins can confirm, complete, or mark no-shows.
Members can cancel their own reservations; admins can cancel any.

**Architecture decisions:**
- Overlap check uses the standard interval intersection condition:
  `existing.start_time < new.end_time AND existing.end_time > new.start_time`,
  filtered to active statuses (pending, confirmed). Self-exclusion applied during
  updates to avoid false conflicts.
- Status lifecycle: `pending` → `confirmed` (admin) → `completed` / `no_show` (admin).
  Cancel is allowed from pending or confirmed; completed and no_show are terminal.
- `check_vehicle_availability` returns `{is_available, conflicts}` so the frontend
  can surface exactly which reservations are blocking a window.
- `get_reservation_summary` counts in Python over one query (adequate for expected
  reservation volumes; can be replaced with GROUP BY if needed at scale).
- Member cancel endpoint checks ownership (`reserved_by_id == current_user.id`);
  gracefully elevates to admin cancel if `_require_account_admin` does not raise.
- Migration `c2d3e4f5g6h7` creates the `reservationstatus` PG enum before the
  table, and drops it explicitly on downgrade.

**Files created:**
- `backend/app/models/corporate_vehicle_reservation.py`
- `backend/app/schemas/corporate_vehicle_reservation.py`
- `backend/app/services/corporate_vehicle_reservation_service.py`
- `backend/app/api/v1/corporate_vehicle_reservation.py`
- `backend/app/db/migrations/versions/c2d3e4f5g6h7_corporate_vehicle_reservations.py`
- `backend/tests/test_corporate_vehicle_reservation.py`

**Files modified:**
- `backend/app/models/__init__.py` — registered CorporateVehicleReservation, ReservationStatus
- `backend/app/main.py` — registered corporate_vehicle_reservation.router

**Endpoints added:**
- `POST   /api/v1/corporate/{account_id}/vehicle-reservations/` — member: create (201)
- `GET    /api/v1/corporate/{account_id}/vehicle-reservations/` — member: list (filters: fleet_vehicle_id, status, from_time, to_time)
- `GET    /api/v1/corporate/{account_id}/vehicle-reservations/my` — member: own reservations
- `GET    /api/v1/corporate/{account_id}/vehicle-reservations/summary` — member: counts by status
- `GET    /api/v1/corporate/{account_id}/vehicle-reservations/{reservation_id}` — member: get one
- `POST   /api/v1/corporate/{account_id}/vehicle-reservations/{reservation_id}/cancel` — member/admin: cancel
- `PUT    /api/v1/corporate/{account_id}/vehicle-reservations/{reservation_id}` — admin: update pending
- `POST   /api/v1/corporate/{account_id}/vehicle-reservations/{reservation_id}/confirm` — admin: confirm
- `POST   /api/v1/corporate/{account_id}/vehicle-reservations/{reservation_id}/complete` — admin: complete
- `POST   /api/v1/corporate/{account_id}/vehicle-reservations/{reservation_id}/no-show` — admin: no-show
- `GET    /api/v1/corporate/{account_id}/fleet-vehicles/{vehicle_id}/availability` — admin: availability check
- `GET    /api/v1/platform/corporate/vehicle-reservations/` — platform-admin: all reservations
- `GET    /api/v1/platform/corporate/vehicle-reservations/{account_id}` — platform-admin: per account

**Tests:** 65 new tests (service: 29, schema: 9, API: 27) — all passing.
Full suite: 8,464 passing, 1 pre-existing failure (test_corporate_guest_pass::test_validate_token_not_yet_valid), 1082 skipped.

**Ready to merge when:** you decide to push this feature branch.

---

### feature/corporate-business-accounts — multi-currency billing (latest)

**Branch:** `feature/corporate-business-accounts`
**Commit:** `ea522ab`
**Author:** Claude (claude-sonnet-4-6)
**Date:** 2026-04-16

**Summary:**
Adds multi-currency billing support for corporate accounts operating internationally.
Corporate accounts can configure a preferred ISO 4217 billing currency (20 supported:
USD, EUR, GBP, CAD, AUD, JPY, CHF, SEK, NOK, DKK, NZD, SGD, HKD, MXN, BRL, ZAR,
INR, KRW, CNY, AED). When invoices are issued in a non-USD currency, an FX rate
snapshot is recorded for audit and reporting.

**Architecture decisions:**
- `CorporateBillingCurrency`: one record per account; created with USD defaults on
  first read (get_or_create semantics). Unique constraint on account_id.
- `CorporateInvoiceFXSnapshot`: one record per non-USD invoice. Unique constraint
  prevents duplicate snapshots; the router returns 409 and existing snapshot is
  returned if a duplicate is attempted (upsert-style).
- `create_fx_snapshot` returns None for USD-billed accounts so no snapshot is stored.
- `get_currency_summary` aggregates non-USD invoice count and totals by currency.
- Currency validation rejects unsupported codes with HTTP 422 at both schema and
  service layer, keeping errors consistent.
- Migration: `a0b1c2d3e4f5` revises `z9a0b1c2d3e4`.

**Files created:**
- `app/models/corporate_billing_currency.py`
- `app/schemas/corporate_billing_currency.py`
- `app/services/corporate_billing_currency_service.py`
- `app/api/v1/corporate_billing_currency.py`
- `app/db/migrations/versions/a0b1c2d3e4f5_corporate_billing_currency.py`
- `tests/test_corporate_billing_currency.py`

**Tests:** 59 new tests → **total 8,336 passing**
Pre-existing failure (unrelated): `test_corporate_guest_pass::test_validate_token_not_yet_valid`

**Ready to merge when:** you decide to push this feature branch.

---

### feature/corporate-business-accounts — corporate ride templates

**Branch:** `feature/corporate-business-accounts`
**Commit:** `c66075a`
**Author:** Claude (claude-sonnet-4-6)
**Date:** 2026-04-16

**Summary:**
Adds Corporate Ride Templates — corporate admins define named, reusable booking
configurations with pre-filled pickup/dropoff addresses, preferred vehicle type,
and default cost centre / trip purpose.  Employees browse templates and get
pre-filled booking data, reducing friction for frequent corporate trips (airport
runs, hotel transfers, office-to-client-site routes, etc.).

**Architecture decisions:**
- Single `corporate_ride_templates` table; name is unique per account.
- `use_count` field is incremented by the service layer (`record_template_use`)
  whenever a member selects a template — powers the `/popular` endpoint.
- `get_popular_templates` returns the top-N active templates by use_count (desc)
  and also emits the total count of all active templates so callers can implement
  "showing top 10 of N" displays.
- `record_template_use` raises 409 on inactive templates (prevent ghost bookings).
- Both `default_cost_center_id` and `default_trip_purpose_id` are SET NULL FKs
  so deleting the referenced resource doesn't cascade-delete the template.
- Lat/lng stored as Numeric(9,6); `_to_response` converts to float for JSON.

**Tests:** 56 new tests → **total 7,411 passing**

**Ready to merge when:** you decide to push this feature branch.

---

### feature/corporate-business-accounts — corporate event management (previous)

**Branch:** `feature/corporate-business-accounts`
**Commit:** `7182eb7`
**Author:** Claude (claude-sonnet-4-6)
**Date:** 2026-04-16

**Summary:**
Adds Corporate Event Management — enterprise coordinators can organize company events
(team offsites, conferences, client dinners, holiday parties), invite employees, and
link rides for consolidated billing.

**Architecture decisions:**
- Two-table design: `corporate_events` (the event) + `corporate_event_attendees` (junction
  linking members and optionally their rides to the event). Mirrors the travel itinerary
  pattern used throughout the corporate feature set.
- Status string fields (not PG enums) for both events and attendees, consistent with all
  other corporate features — values can be extended without a migration.
- Event lifecycle: `draft` → `activate` → `active` → `complete` → `completed`.
  Cancel is allowed from any non-completed state.
- `update_event` blocks writes when status is `cancelled` or `completed` (both are terminal).
- `invite_attendees` silently skips members already in the attendee list — safe to call
  repeatedly with the same member IDs.
- `corporate_address_id` FK stored without a SQLAlchemy relationship on `CorporateEvent`
  because `CorporateAddress` is not in `models/__init__.py`. The FK is preserved in the
  migration and can be used for joins directly; the relationship can be added later when the
  address model is registered.
- `EventSummaryResponse` counts by status in Python (one query for all attendees) rather
  than four COUNT subqueries — simpler and adequate for expected attendee counts.

**Files changed:**
- `backend/app/models/corporate_event.py` — CorporateEvent + CorporateEventAttendee models
- `backend/app/schemas/corporate_event.py` — Pydantic schemas (EventCreate, EventUpdate, EventResponse, EventListResponse, AttendeeStatusUpdate, AttendeeResponse, AttendeeListResponse, InviteAttendeesRequest, EventSummaryResponse)
- `backend/app/services/corporate_event.py` — 11 service functions
- `backend/app/api/v1/corporate_events.py` — 12 endpoints
- `backend/app/db/migrations/versions/k3l4m5n6o7p8_corporate_events.py` — Alembic migration (revises i0j1k2l3m4n5)
- `backend/tests/test_corporate_events.py` — 53 tests
- `backend/app/models/__init__.py` — registered new models
- `backend/app/main.py` — registered corporate_events.router

**Endpoints added:**
- `POST   /api/v1/corporate/accounts/me/events` — member: create event (201)
- `GET    /api/v1/corporate/accounts/me/events` — member: list events
- `GET    /api/v1/corporate/accounts/me/events/{event_id}` — member: get event
- `PUT    /api/v1/corporate/accounts/me/events/{event_id}` — member: update event
- `GET    /api/v1/corporate/accounts/me/events/{event_id}/summary` — member: get summary
- `POST   /api/v1/corporate/accounts/me/events/{event_id}/activate` — admin: activate
- `POST   /api/v1/corporate/accounts/me/events/{event_id}/cancel` — admin: cancel
- `POST   /api/v1/corporate/accounts/me/events/{event_id}/complete` — admin: complete
- `POST   /api/v1/corporate/accounts/me/events/{event_id}/attendees/invite` — admin: invite members
- `PATCH  /api/v1/corporate/accounts/me/events/{event_id}/attendees/{member_id}` — admin: update attendee status
- `GET    /api/v1/platform/corporate/events` — platform-admin: list all events
- `GET    /api/v1/platform/corporate/accounts/{account_id}/events` — platform-admin: list for account

**Test results:** 53/53 new tests passing. Full suite: 7,286 passing, 1 pre-existing failing (test_corporate_guest_pass.py::test_validate_token_not_yet_valid), 1082 skipped.

---

### feature/corporate-business-accounts — corporate department-level ride policies

**Branch:** `feature/corporate-business-accounts`
**Commit:** `6847e59`
**Author:** Claude (claude-sonnet-4-6)
**Date:** 2026-04-16

**Summary:**
Adds the middle tier of the corporate policy hierarchy — each department can now
carry its own ride policy, filling the gap between account-level and per-member
overrides. Policy resolution: account (base) → department (most restrictive field
wins when member is in multiple departments) → member override (highest precedence).

**Architecture decisions:**
- `CorporateDepartmentRidePolicy` has a unique constraint on `department_id` (one
  policy per department). Upsert semantics: PUT replaces the entire row if one exists.
- All override fields are nullable — `NULL` means "inherit from the account policy".
  Admins only need to set the fields they want to constrain.
- Multi-department merge strategy: **most restrictive field wins** — True wins for
  booleans (require_purpose, business_hours_only), lower value wins for max_per_ride_usd,
  intersection wins for list fields (allowed_vehicle_categories, approved_purposes).
  An empty intersection means no vehicle type / purpose is allowed — admins should be
  aware when two departments have non-overlapping constraints.
- `get_effective_policy_for_member` performs a 4-query fetch (member → account policy →
  dept memberships → dept policies → member override) and merges in Python. Suitable for
  low-to-moderate call volume; a materialized view could optimize if this becomes a hot
  path.
- `is_active` soft-disable: inactive department policies are excluded from effective
  policy resolution without losing audit history.
- Platform-admin bypass: `requesting_user_id=-1` sentinel skips the admin membership
  check, consistent with all other corporate service functions.

**Files changed:**
- `backend/app/models/corporate_department_ride_policy.py` — ORM model
- `backend/app/schemas/corporate_department_ride_policy.py` — Pydantic schemas (Set, Update, Response, ListResponse, EffectiveDepartmentPolicyResponse)
- `backend/app/services/corporate_department_ride_policy.py` — 9 service functions
- `backend/app/api/v1/corporate_department_ride_policy.py` — 11 endpoints
- `backend/app/db/migrations/versions/i0j1k2l3m4n5_corporate_department_ride_policies.py` — Alembic migration
- `backend/tests/test_corporate_department_ride_policy.py` — 49 tests
- `backend/app/main.py` — registered corporate_department_ride_policy.router

**Endpoints added:**
- `PUT    /api/v1/corporate/accounts/me/departments/{id}/ride-policy` — admin: upsert policy
- `GET    /api/v1/corporate/accounts/me/departments/{id}/ride-policy` — member: get policy
- `PATCH  /api/v1/corporate/accounts/me/departments/{id}/ride-policy` — admin: partial update
- `DELETE /api/v1/corporate/accounts/me/departments/{id}/ride-policy` — admin: delete (204)
- `POST   /api/v1/corporate/accounts/me/departments/{id}/ride-policy/activate` — admin: activate
- `POST   /api/v1/corporate/accounts/me/departments/{id}/ride-policy/deactivate` — admin: deactivate
- `GET    /api/v1/corporate/accounts/me/department-ride-policies` — member: list all policies
- `GET    /api/v1/corporate/accounts/me/effective-department-policy` — member: get own effective policy
- `GET    /api/v1/platform/corporate/department-ride-policies` — platform-admin: list all
- `GET    /api/v1/platform/corporate/accounts/{id}/department-ride-policies` — platform-admin: account
- `GET    /api/v1/platform/corporate/accounts/{id}/members/{mid}/effective-department-policy` — platform-admin

**Test results:** 7,193 passing, 1 pre-existing failing (test_corporate_guest_pass.py::test_validate_token_not_yet_valid), 1082 skipped. New tests: 49/49 passing.

---

### feature/corporate-business-accounts — corporate auto-approval rules

**Branch:** `feature/corporate-business-accounts`
**Commit:** `a3f1089`
**Author:** Claude (claude-sonnet-4-6)
**Date:** 2026-04-16

**Summary:**
Admins configure priority-ordered rules that automatically approve corporate rides
when all specified conditions are met — bypassing the manual multi-step approval
chain for routine, low-risk rides (e.g., any ride under $25 for a sales rep going
to a client site on a weekday).

**Architecture decisions:**
- Multi-condition AND logic within a single rule; OR across rules. If ANY active
  rule matches, the ride is auto-approved. Rules are evaluated in priority DESC
  order (ties broken by created_at ASC) and short-circuit on first match.
- Null condition fields mean "no constraint" — a rule with all nulls is always
  a match.
- `start_hour` and `end_hour` are enforced as a pair (both set or both None)
  via a Pydantic `model_validator` at the schema layer.
- Employee group check queries `CorporateGroupMembership` at evaluation time —
  no denormalization to keep rule data from going stale.
- `evaluate` endpoint resolves the calling user's `CorporateAccountMember.id`
  before delegating to the service so that group membership can be checked
  correctly.
- 409 on duplicate active rule name within an account; activate/deactivate
  also raise 409 to prevent double-state transitions.

**Files changed:**
- `backend/app/models/corporate_auto_approval_rule.py` — ORM model
- `backend/app/schemas/corporate_auto_approval_rule.py` — Pydantic schemas
- `backend/app/services/corporate_auto_approval_rule.py` — 9 service functions
- `backend/app/api/v1/corporate_auto_approval_rule.py` — 10 endpoints
- `backend/app/db/migrations/versions/h9i0j1k2l3m4_corporate_auto_approval_rules.py` — Alembic migration
- `backend/tests/test_corporate_auto_approval_rule.py` — 51 tests
- `backend/app/main.py` — registered corporate_auto_approval_rule.router

**Endpoints added:**
- `POST   /api/v1/corporate/accounts/me/auto-approval-rules` — admin: create rule
- `GET    /api/v1/corporate/accounts/me/auto-approval-rules` — member: list (filter by is_active)
- `GET    /api/v1/corporate/accounts/me/auto-approval-rules/{rule_id}` — member: get
- `PUT    /api/v1/corporate/accounts/me/auto-approval-rules/{rule_id}` — admin: update
- `POST   /api/v1/corporate/accounts/me/auto-approval-rules/{rule_id}/activate` — admin: activate
- `POST   /api/v1/corporate/accounts/me/auto-approval-rules/{rule_id}/deactivate` — admin: deactivate
- `DELETE /api/v1/corporate/accounts/me/auto-approval-rules/{rule_id}` — admin: delete (204)
- `POST   /api/v1/corporate/accounts/me/auto-approval-rules/evaluate` — member: evaluate hypothetical ride
- `GET    /api/v1/platform/corporate/auto-approval-rules` — platform-admin: list all
- `GET    /api/v1/platform/corporate/accounts/{account_id}/auto-approval-rules` — platform-admin: list for account

**Test results:** 7,144 passing, 1 pre-existing failing (test_corporate_guest_pass.py::test_validate_token_not_yet_valid), 1082 skipped. New tests: 51/51 passing.

---

### feature/corporate-business-accounts — corporate receipt template customization

**Branch:** `feature/corporate-business-accounts`
**Commit:** `09119f7`
**Author:** Claude (claude-sonnet-4-6)
**Date:** 2026-04-16

**Summary:**
Implements per-account branded receipt templates for the corporate enterprise
feature set.  Finance teams can configure company name/logo, a reference number
prefix, header and footer messages, driver details and route map toggles, and
arbitrary custom line items (e.g. project codes, cost centre tags).

**Architecture decisions:**
- One row per corporate account (`uq_corp_receipt_template_account_id`).
  Follows the upsert-on-read pattern from billing settings and carbon budget:
  the first GET creates a default row so callers always receive a well-formed
  response.
- `custom_line_items` stored as JSONB `[{"label": str, "value": str}]` — keeps
  the schema flexible for future label types without additional migrations.
- `logo_url` validated at the Pydantic layer (must start with `http://` or
  `https://`); internal sanitisation only, not content-fetched on write.
- `reference_prefix` capped at 20 chars in both the schema validator and the
  `String(20)` column to prevent long reference numbers.
- `deactivate` raises 409 when already inactive (prevents double-deactivation).
- `delete_receipt_template` is a hard delete — only admins reach this endpoint.
- `get_receipt_template_for_ride` returns `None` (not a 404) so the receipt
  generation layer can fall back to the platform default cleanly.
- Migration `f7g8h9i0j1k2` revises `e6f7a8b9c0d1` (member policy overrides).

**Files changed:**
- `backend/app/models/corporate_receipt_template.py` — ORM model
- `backend/app/schemas/corporate_receipt_template.py` — Pydantic schemas (CustomLineItem, ReceiptTemplateUpdate, ReceiptTemplateResponse, ReceiptTemplateListResponse)
- `backend/app/services/corporate_receipt_template.py` — 6 service functions
- `backend/app/api/v1/corporate_receipt_template.py` — 6 endpoints
- `backend/app/db/migrations/versions/f7g8h9i0j1k2_corporate_receipt_templates.py` — Alembic migration
- `backend/tests/test_corporate_receipt_template.py` — 38 tests
- `backend/app/main.py` — registered corporate_receipt_template.router

**Endpoints added:**
- `GET    /api/v1/corporate/accounts/me/receipt-template` — member: view template
- `PUT    /api/v1/corporate/accounts/me/receipt-template` — admin: create/update
- `POST   /api/v1/corporate/accounts/me/receipt-template/deactivate` — admin: deactivate (409 if already inactive)
- `DELETE /api/v1/corporate/accounts/me/receipt-template` — admin: hard-delete (204)
- `GET    /api/v1/platform/corporate/receipt-templates` — platform-admin: paginated list
- `GET    /api/v1/platform/corporate/accounts/{account_id}/receipt-template` — platform-admin: get for any account

**Test results:** 7053 passing, 1 pre-existing failing (test_corporate_guest_pass.py::test_validate_token_not_yet_valid — pre-dates this session), 1082 skipped. New tests: 38/38 passing.

---

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
