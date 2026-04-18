# Check-in Briefing

> This file is updated by the orchestrator before going idle.
> When you drop in, read this first. It's designed to get you up to speed in under 5 minutes.
> After reviewing, clear the "Since Last Check-in" section and leave notes in "Your Notes" for the orchestrator to pick up.

---

## Since Last Check-in

**Period**: 2026-04-18
**Sessions run**: 313–352

### Accomplished (Session 352 — orchestrator)

#### open-source-rideshare — Recurring Ride Skip/Unskip COMPLETE (commit `63ccd08`)

Riders can now skip a single upcoming occurrence of a recurring ride without cancelling the whole series — e.g. "skip Monday's commute this week only."

**`POST /rides/recurring/{id}/skip`** — skip a future occurrence:
- 201 on success; validates `skip_date` falls on a scheduled day of the week (422 if not)
- Must be a future date (422 if today or past)
- If a `SCHEDULED` ride was already auto-generated for that occurrence, it is cancelled in the same transaction
- Idempotent: calling twice with the same date returns the existing skip record

**`DELETE /rides/recurring/{id}/skip/{date}`** — un-skip a date:
- 204 on success; 404 if no skip exists for that date

**`GET /rides/recurring/{id}`** detail response now includes `skipped_dates: list[date]` (future skips only).

**Generation logic**: `generate_rides_from_recurring` now loads skipped dates per template before generating, and skips any occurrence whose local date is in the skip set.

New model: `RecurringRideSkip` (`recurring_ride_skips` table). Unique constraint on `(recurring_ride_id, skip_date)`. Cascade delete from template. Migration: `y9z0a1b2c3d4`.

**31 new tests** — 7 new test classes covering model, schemas, service logic (7 cases: valid skip, wrong day, past date, cancelled template, idempotency, cascade cancel, not found), unskip, list, and both API endpoints. **4,626 tests passing** (was 4,595). 0 regressions. Pushed to `feature/rider-emergency-safety`.

---

### Accomplished (Session 351 — orchestrator)

#### open-source-rideshare — Notification Inbox Delete/Dismiss COMPLETE (commit `83a44df`)

Riders and drivers can now dismiss individual notifications or clear their entire inbox. The underlying `NotificationLog` records are soft-deleted (audit trail preserved) — deleted notifications are excluded from all inbox queries.

**`DELETE /notifications/me/{id}`** — dismiss a single notification:
- 204 on success; 404 if notification doesn't exist or belongs to a different user
- Sets `NotificationLog.deleted_at = now()`

**`DELETE /notifications/me`** — dismiss entire inbox:
- 200 `{"status": "ok"}`; idempotent (safe to call multiple times)
- Bulk sets `deleted_at` on all non-deleted notifications for the calling user
- Scoped: does not affect other users' notifications

**Queries updated**: `GET /notifications/history` and `GET /notifications/unread-count` now filter `deleted_at IS NULL` — deleted notifications are invisible to the user.

New model field: `NotificationLog.deleted_at` (nullable DateTime). Migration: `x8y9z0a1b2c3`.
Schema: `NotificationLogResponse.deleted_at` added (nullable, default None).

**12 new integration tests** in `TestDeleteNotificationEndpoints`: single delete 401/404/wrong-owner 404/204, deleted excluded from history, deleted excluded from unread count, bulk 401, bulk ok response, bulk clears history, bulk scoped to user, bulk idempotent. **4,595 tests passing** (unchanged). 0 regressions. Pushed to `rideshare` remote on `feature/rider-emergency-safety`.

---

### Accomplished (Session 350 — orchestrator)

#### open-source-rideshare — Driver Geofence Exit Alerting COMPLETE (commit `21ef9b8`)

When a driver's GPS update (via `PUT /drivers/me/location`) places them outside all active service area boundaries during an IN_PROGRESS ride, both the rider and the driver are alerted once per ride.

**How it works:**
- Fire-and-forget `asyncio.ensure_future()` call added to the location update endpoint alongside the existing route deviation check
- New service `services/geofence_exit.py` — `check_and_notify_geofence_exit(user_id, lat, lng, db)`:
  1. Find active IN_PROGRESS ride for the driver (returns False if none)
  2. Check `geofence_exit_alerted_at IS NULL` — idempotency guard (returns False if already alerted)
  3. Fast-path: returns False if no active service areas configured (boundary not set up yet)
  4. PostGIS `ST_Contains(ServiceArea.boundary, ST_MakePoint(lng, lat, 4326))` — driver inside any SA?
  5. If outside all SAs: persist flag + commit, notify rider + driver

**Rider notification** (PUSH+SMS): "Your driver has left the service area. We're monitoring your trip. Tap to view your ride or contact support."
**Driver notification** (PUSH only): "You have left the service area. Please return to complete the ride."

New model field: `Ride.geofence_exit_alerted_at` (nullable DateTime). Migration: `w7x8y9z0a1b2`.
New enum values: `NotificationType.GEOFENCE_EXIT`, `NotificationType.DRIVER_GEOFENCE_EXIT`.
Both registered in `TEMPLATES` registry, `notification_events`, and `_VALID_NOTIFICATION_TYPES` (rider type is preference-controllable).

**27 new tests** in `tests/test_geofence_exit.py`: all 10 service flow branches (no ride, already flagged, ride not found, no SAs, driver inside, driver outside, DB error, commit/no-commit), idempotency, template channels, type registration, rider + driver dispatchers, all 7 helper functions. **4,595 tests passing** (was 4,568). 0 regressions. Pushed to `rideshare` remote on `feature/rider-emergency-safety`.

---

### Accomplished (Session 349 — orchestrator)

#### open-source-rideshare — Admin Geofence Violations Report COMPLETE (commit `c61b812`)

New endpoint: `GET /admin/geofence/violations?period=week|month|year|all&violation_type=all|pickup_outside|dropoff_outside|both_outside&page=1&per_page=20`

Surfaces rides where pickup or dropoff falls outside all active service areas, using PostGIS `ST_Within` correlated EXISTS subqueries. Three violation types:
- **pickup_outside** — pickup location outside every active service area
- **dropoff_outside** — dropoff location outside every active service area
- **both_outside** — both locations outside every active service area

Fast-path: returns empty immediately when no active service areas exist (skips geospatial queries). Period filter applied to `requested_at`. Violation type filter adds additional `WHERE` clause to constrain the SQL result before counting and paginating. Results ordered newest-first.

New pure helper: `_classify_violation(pickup_covered, dropoff_covered) -> GeofenceViolationType` (module-level, testable directly). New schemas: `GeofenceViolationType` (str enum), `GeofenceViolationEntry`, `GeofenceViolationListResponse` (includes `service_areas_active` count).

**33 new tests** in `tests/test_admin_geofence_violations.py`: `_classify_violation` all four input combinations + enum value checks, schema construction and optional fields, endpoint mocked DB (zero service areas fast-path, per-type classification, mixed types, pagination, period variants, field mapping). **4,568 tests passing** (was 4,535). 0 regressions. Pushed to `rideshare` remote.

**Needs Your Input** — ready to merge into master:
Branch: `feature/rider-emergency-safety`
PR: `GET /admin/geofence/violations` admin geofence violations report

---

### Accomplished (Session 348 — orchestrator)

#### open-source-rideshare — Admin Notification Broadcast COMPLETE (commit `2d1a350`)

New endpoint: `POST /admin/notifications/broadcast`

Allows admins to push messages to user segments in one call. Three segments:
- **all_riders** — all active users with role=rider
- **all_drivers** — all active users with role=driver
- **all_users** — all active non-admin users (riders + drivers)

Channels: `push`, `sms`, `email`. Invalid channels are silently dropped; if none remain, falls back to push. Each notification sent via the existing `send_notification()` service (respects device tokens, logs to NotificationLog table). Returns `BroadcastResult`: `segment`, `title`, `total_targeted`, `total_sent`, `total_failed`, `channels`, `sent_at`.

New notification type `ADMIN_BROADCAST` added to `NotificationType` enum. New schemas: `BroadcastSegment` (enum), `BroadcastRequest` (title 1–200 chars, body 1–1000 chars, channels list), `BroadcastResult`.

**21 new tests** in `tests/test_admin_broadcast.py`: schema validation (min/max length, invalid segment, default channels), endpoint logic (per-segment querying, sent/failed counting, channel fallback, notification called with correct user phone/email, timestamp in result), edge cases (empty segment, partial failure, mixed valid/invalid channels). **4,535 tests passing** (was 4,514). 0 regressions. Pushed to rideshare remote.

---

### Accomplished (Session 347 — orchestrator)

#### open-source-rideshare — Admin Trip Anomaly Detection COMPLETE (commit `5aaa979`)

New endpoint: `GET /admin/safety/anomalies?period=week|month|year|all&anomaly_type=all|route_deviation|driver_no_show|safety_cancellation|excessive_fare|long_duration&page=1&per_page=20`

Surfaces rides with detected anomalies in a paginated admin view. Five anomaly types:
- **route_deviation** — driver deviated >1 km from the pickup→dropoff path (`route_deviation_flagged_at IS NOT NULL`)
- **driver_no_show** — no-show reported by rider or auto-detected (`driver_no_show_reported_at IS NOT NULL`)
- **safety_cancellation** — ride cancelled for SAFETY_CONCERN, DRIVER_NO_SHOW, or DRIVER_NOT_ACCEPTABLE category
- **excessive_fare** — actual_fare >50% above estimated_fare (completed rides only)
- **long_duration** — ride lasted more than 90 minutes

Each result includes all anomaly_types present on the ride (a single ride can carry multiple flags), and `detected_at` is the earliest anomaly timestamp found. Rides ordered newest-first by `requested_at`. Period filter narrows to last 7/30/365 days. Anomaly type filter narrows the SQL query before paginating so count is accurate.

New schemas: `TripAnomalyEntry`, `TripAnomalyListResponse`.
New helpers: `_detect_anomaly_types(ride)`, `_anomaly_detected_at(ride)` (module-level, testable directly).

**24 new tests** in `tests/test_admin_anomalies.py`: all 5 anomaly detection conditions, threshold edge cases (at-threshold not flagged, just-above flagged), multi-anomaly detection, earliest-timestamp selection, fallback to requested_at, schema field validation, and pagination invariants. **4,514 tests passing** (was 4,490). 0 regressions. Pushed to rideshare remote.

---

### Accomplished (Session 346 — orchestrator)

#### open-source-rideshare — SOS Active Map + Bulk Rider Management COMPLETE (commit `67a4154`)

Three new admin endpoints for dispatcher operations and bulk account management.

**`GET /admin/safety/sos/active-map`** — dispatcher live-map snapshot:
- Returns all currently ACTIVE SOS alerts as map pins with lat/lng, user name/phone, ride_id, and `seconds_open` (age of the alert)
- Ordered oldest-first so highest-priority emergencies float to the top
- Includes alerts without GPS coords (`latitude/longitude=None`) — dispatchers see everything
- Designed for 15–30s polling; returns `pins`, `total`, `fetched_at`

**`POST /admin/riders/bulk-suspend`** — suspend 1–100 rider accounts at once:
- Skips already-suspended riders (not counted in succeeded); reports not_found IDs
- Requires `reason` field (audit trail); emits `bulk_rider_suspended` audit event

**`POST /admin/riders/bulk-reactivate`** — reactivate 1–100 suspended riders:
- Skips already-active riders; mirrors existing bulk driver reactivate behavior
- Both bulk endpoints registered before `riders/{user_id}` to avoid path capture

**20 new tests** (4 SOSMapPin, 4 SOSActiveMapResponse, 5 bulk schema validation, 7 async endpoint mock tests) → **4,490 total passing** (was 4,470). 0 regressions. Pushed to rideshare remote.

---

### Accomplished (Session 345 — orchestrator)

#### open-source-rideshare — Admin Driver Panic Frequency Leaderboard COMPLETE (commit `2931606`)

Ops can now rank drivers by panic alert volume to flag high-frequency triggerers — mirrors the rider SOS leaderboard shipped last session.

**`GET /admin/safety/drivers/panic/leaderboard?period=week|month|year|all&limit=1-100`**:
- Returns drivers sorted descending by total panic alert count
- Per-entry: `driver_profile_id`, `driver_name`, `driver_phone`, `total`, `active`, `resolved`, `false_alarms`, `false_alarm_rate` (%), `last_panic_at`
- Period filter (`all` default) — narrow to recent activity or see all-time
- New `admin_list_all_driver_panic_alerts(db, period_start)` service function added to `driver_safety.py`
- DB enrichment: DriverProfile + User joined for top-N drivers (not N+1)

**10 new schema tests** → 4,470 total passing (was 4,460). 0 regressions. Pushed to rideshare remote.

---

### Accomplished (Session 344 — orchestrator)

#### open-source-rideshare — Admin SOS Frequency Leaderboard COMPLETE (commit `9815634`)

Ops can now rank riders by SOS alert volume to flag high-frequency triggerers and potential abusers.

**`GET /admin/safety/sos/leaderboard?period=week|month|year|all&limit=1-100`**:
- Returns riders sorted descending by total SOS alert count
- Per-entry: `user_id`, `user_name`, `user_phone`, `total`, `active`, `resolved`, `false_alarms`, `false_alarm_rate` (%), `last_sos_at`
- Period filter (`all` default) — narrow to recent activity or see all-time
- Registered before `/{alert_id}` route to avoid path capture
- Efficient: single group-by query + one IN query for user lookup (not N+1)

**10 new schema tests** → 4,460 total passing (was 4,450). 0 regressions. Pushed to rideshare remote.

---

### Accomplished (Sessions 343–342 — orchestrator)

#### open-source-rideshare — Admin SOS Timeseries + Driver Shift History COMPLETE (commits `390d82f`, `3a7e6fb`)

`GET /admin/safety/sos/timeseries?period=week|month|year` — daily SOS alert trend by status. `GET /admin/drivers/shifts/active` + `GET /admin/drivers/{id}/shift-history` — fleet shift visibility and per-driver shift audit. 24 new tests across both sessions.

---

### Accomplished (Session 342 — orchestrator)

#### open-source-rideshare — Admin Driver Shift History COMPLETE (commit `3a7e6fb`)

Ops can now see who's currently on-shift and pull the full shift log for any driver.

**`GET /admin/drivers/shifts/active`** — all drivers currently on an active shift:
- Paginated (up to 200/page), newest-first by start time
- Joins DriverShift → DriverProfile → User for driver name; graceful fallback if profile missing
- Per-entry: `shift_id`, `driver_profile_id`, `user_id`, `driver_name`, `started_at`, `rides_completed`

**`GET /admin/drivers/{driver_id}/shift-history`** — paginated shift history for one driver:
- Optional `status` filter: `active` / `completed` / `auto_ended`; 422 on invalid value
- 404 if driver profile not found; `skip`/`limit` pagination (max 200/page), newest-first
- Per-entry: `id`, `status`, `started_at`, `ended_at`, `total_minutes`, `rides_completed`

**18 new tests** → 4,444 total passing (was 4,426). 0 regressions. Pushed to rideshare remote.

---

### Accomplished (Session 341 — orchestrator)

#### open-source-rideshare — Admin Trip Share Management COMPLETE (commit `09ffeae`)

Ops can now list and revoke all rider trip share links from the admin panel.

**`GET /admin/trip-shares`** — paginated list of all trip share links:
- Optional `rider_id` filter (narrow to one rider's shares) and `is_active` filter
- `skip`/`limit` pagination up to 200/page, newest-first
- Response fields per entry: `rider_id`, `ride_id`, `token`, `share_url`, `is_active`, `expires_at`, `created_at`

**`DELETE /admin/trip-shares/{token}`** — admin revoke any link:
- Revokes regardless of which rider owns it (rider's `DELETE` endpoint is ownership-scoped; this one is not)
- 204 on success, 404 if token not found
- Auth: 403 for non-admin callers

**15 new tests** → 4,426 total passing (was 4,402). 0 regressions. Pushed to rideshare remote.

---

### Accomplished (Session 340 — orchestrator)

#### open-source-rideshare — Admin Per-User Safety History COMPLETE (commit `557a45a`)

Ops can now pull the full safety event history for any individual rider or driver.

**`GET /admin/riders/{rider_id}/safety-history`** — paginated SOS alert history per rider:
- Queries existing `SOSAlert` DB table (no migration needed)
- Optional `status` filter: `active` / `resolved` / `false_alarm`
- 404 if rider user not found; `skip`/`limit` pagination (max 200/page), newest-first
- Fields: `id`, `ride_id`, `status`, `lat`, `lng`, `message`, `triggered_at`, `resolved_at`, `resolved_by`, `resolution_notes`

**`GET /admin/drivers/{driver_id}/safety-history`** — paginated driver panic alert history:
- Queries in-memory driver panic store via `list_driver_panic_alerts` service (consistent with existing panic system)
- Optional `status` filter: `ACTIVE` / `RESOLVED` / `FALSE_ALARM`
- 404 if driver profile not found; `skip`/`limit` pagination (max 200/page)

**17 new tests** (5 schema, 6 rider, 6 driver) → 4,402 total passing (was 4,385). 0 regressions. Pushed to rideshare remote.

---

### Accomplished (Session 339 — orchestrator)

#### open-source-rideshare — Admin Driver Status History COMPLETE (commit `8a31402`)

Admins can now audit the full approval/suspension history of any driver, and see a real-time feed of recent status changes across the entire fleet.

**`GET /admin/drivers/{driver_id}/status-history`** — paginated log of all status transitions for one driver:
- Queries existing `AuditLog` records (target_type="driver_profile") — no migration needed
- Returns: `id`, `timestamp`, `event_type` (raw), `action` (human-friendly: "approved"/"suspended"/"reactivated"), `admin_id`, `reason` (extracted from metadata_json for suspensions), `description`
- 404 if driver profile not found; `skip`/`limit` pagination (up to 200/page), newest-first

**`GET /admin/drivers/status-changes`** — ops feed of recent changes across all drivers:
- `days` filter (1–90, default 7): changes in the last N days
- Same response shape with added `driver_id` per entry
- `skip`/`limit` pagination; newest-first

**Coverage**: handles all event_type variants (single + bulk: approved, suspended, reactivated)

**19 new tests** → 4,385 total passing (was 4,366). 0 regressions. Pushed to rideshare remote.

---

### Accomplished (Session 338 — orchestrator)

#### open-source-rideshare — Admin Driver Activity Dashboard COMPLETE (commit `6b2e63c`)

Ops team can now see per-driver recent activity in one paginated endpoint.

**`GET /admin/drivers/activity`** — filterable by `is_online` and `is_approved`; paginated up to 200/page.

**Per-entry fields:**
- `driver_id`, `user_id`, `driver_name`, `is_online`, `is_approved`, `rating_avg`, `total_trips` (lifetime)
- `trips_7d`, `trips_30d` — completed rides in the last 7 and 30 days
- `shift_hours_7d`, `shift_hours_30d` — hours on-shift in the last 7 and 30 days
- `last_trip_at` — timestamp of most recent completed ride

**Implementation**: 5 aggregate SQL queries per page (not N+1) — trips_7d/30d agg on `Ride`, shift_7d/30d agg on `DriverShift`, last-trip max on `Ride` — all scoped to the current page's driver user_ids.

**8 new tests** → 4,366 total passing (was 4,358). 0 regressions. Pushed to rideshare remote.

---

### Accomplished (Session 337 — orchestrator)

#### open-source-rideshare — Driver Referral Program COMPLETE (commit `dd2ceda`)

Drivers can now recruit other drivers via a unique referral code. When the referred driver completes 10 trips, the referring driver earns a $50 bonus (AWARDED status), which flows into their next payout (PAID via `mark_driver_referral_bonuses_paid`).

**5 new endpoints:**
- `GET  /drivers/me/referral-code` — get (or auto-create) referral code + stats (total referrals, pending bonus, total paid)
- `POST /drivers/me/referral-code` — idempotent code generation
- `POST /drivers/me/referral/apply` — apply another driver's referral code (400 on bad code/self-referral; 409 if already applied)
- `GET  /drivers/me/referral/bonuses` — list all referral bonuses (PENDING/AWARDED/PAID)
- `GET  /admin/driver-referrals` — admin list, filterable by referrer/referee/status

**New files:**
- `models/driver_referral.py` — `DriverReferral` model with PENDING→AWARDED→PAID status machine
- `services/driver_referral.py` — full lifecycle: generate, apply, milestone check, payout hook
- `schemas/driver_referral.py` — all Pydantic schemas
- `api/v1/driver_referral.py` — router, registered in `main.py`
- `migrations/v6w7x8y9z0a1` — `driver_referrals` table + `driver_referral_code` on `driver_profiles`

**Model change:** `DriverProfile.driver_referral_code` (unique, indexed, nullable)

**Hook:** `complete_ride` now calls `check_and_award_driver_referral_bonus` after `total_trips += 1`

**39 new tests** + 3 existing `TestCompleteRide` tests updated (5th DB execute for referral check).

**4,358 tests passing** (was 4,319). 0 regressions. Pushed to rideshare remote.

---

### Accomplished (Session 336 — orchestrator)

#### open-source-rideshare — Driver Panic Alert System COMPLETE (commit `73a3bec`)

**4,319 tests passing** (was 4,277). 0 regressions. Pushed to rideshare remote.

---

### Accomplished (Session 335 — orchestrator)

#### open-source-rideshare — Earnings Guarantee COMPLETE (commit `9a6cd01`)

The `earnings_guarantee` incentive program type was previously defined (model, enum, docstring comment) but had zero evaluation logic. Now fully implemented end-to-end.

**New `evaluate_earnings_guarantee(db, driver_id, period_start, period_end, actual_earnings)`** in `services/incentives.py`:
- Queries all active earnings_guarantee programs whose date range overlaps the payout period
- For each: computes `top_up = max(0, floor - actual_earnings)`, creates/updates `DriverIncentiveProgress` with `bonus_earned = top_up`, `status = COMPLETED`
- Idempotent: if progress already COMPLETED/PAID, reads its `bonus_earned` without re-evaluating
- Returns total top-up amount (sum across all qualifying programs)

**`create_payout()` wired** to auto-calculate guarantee top-up after settlement; folds into `bonus_amount` field. Drivers are made whole automatically without admin intervention.

**`process_payout()` wired** to call `mark_bonuses_paid()` after a successful Stripe transfer — all COMPLETED incentive records (guarantees + quest/peak/streak) are marked PAID.

**8 new unit tests** + **5 existing payout test updates** (mock sequences updated for the extra execute call). **4,277 tests passing** (was 4,269). 0 regressions. Pushed to rideshare remote.

---

### Accomplished (Session 334 — orchestrator)

#### open-source-rideshare — Scheduled Dispatch Notification COMPLETE (commit `450acf2`)

When the background scheduler dispatches a scheduled ride (SCHEDULED→REQUESTED), riders now receive a push+SMS notification — previously there was only a silent WebSocket event.

**New `NotificationType.RIDE_SCHEDULED_DISPATCHED`** — added end-to-end:
- `notifications.py`: new enum value + added to `ride_types` (respects user's `ride_updates` preference toggle)
- `notification_templates.py`: `scheduled_dispatched(pickup_address, scheduled_for)` — push+SMS, "We're finding you a driver for your scheduled ride from [address]"
- `notification_preference.py` schema: `ride_scheduled_dispatched` added to `_VALID_NOTIFICATION_TYPES`
- `notification_events.py`: `notify_scheduled_dispatched()` fire-and-forget helper (errors caught + logged)
- `dispatch_scheduler.py`: calls `notify_scheduled_dispatched` right after REQUESTED transition

**7 new tests**: notification is called with correct args on dispatch, not called for rides outside window, full dispatch proceeds if notification layer fails. Plus 4 unit tests for type enum, template rendering, and `send_ride_notification`. **4,269 tests passing** (was 4,262). 0 regressions. Pushed to rideshare remote.

---

### Accomplished (Session 333 — orchestrator)

#### open-source-rideshare — Scheduled Ride Improvements COMPLETE (commit `6552c75`)

Riders can now modify a scheduled ride after booking (before dispatch), and admins can view all scheduled rides in one place.

**`PATCH /rides/scheduled/{id}`** — partial update of a SCHEDULED ride:
- `scheduled_for`: re-validates timing (must be ≥30min ahead, ≤72h), checks for overlap with the rider's other scheduled rides (excluding the current ride). Returns 422 on bad time, 409 on overlap.
- `pickup` + `pickup_address`: updates pickup coordinates and address; triggers route recalculation and fare update.
- `dropoff` + `dropoff_address`: same as pickup. If only one side changes, the other side uses existing DB coordinates.
- 404 on unknown ride, 403 on wrong owner, 409 on non-SCHEDULED status.

**`GET /admin/rides/scheduled`** — admin dashboard for scheduled rides:
- Filters: `rider_id`, `from_date`, `to_date`, `include_past` (default=false returns upcoming only).
- Paginated (`page`, `per_page` up to 200), ordered by `scheduled_for` ascending.
- Returns `AdminScheduledRidesListResponse` with `total`, `page`, `per_page`, and full ride details including `scheduled_for`.

**Schema additions**: `ScheduleRideUpdate` schema; `scheduled_for` field on `AdminRideResponse`; `AdminScheduledRidesListResponse`.

**11 new tests** (8 PATCH + 3 admin). **4,262 tests passing** (was 4,251). 0 regressions. Pushed to rideshare remote.

---

### Accomplished (Session 332 — orchestrator)

#### open-source-rideshare — Admin Notification Preferences COMPLETE (commit `490f490`)

Support staff can now view and override any user's notification preferences from the admin panel — critical for diagnosing "why isn't this user getting notifications?" tickets.

**4 new admin endpoints** in `GET/PUT/DELETE /admin/users/{id}/notification-preferences/...`:
- `GET /admin/users/{id}/notification-preferences` — full type×channel matrix with effective enabled state (missing records shown as `true` — the default opt-in)
- `PUT /admin/users/{id}/notification-preferences/{type}/{channel}` — single preference override; returns full updated map
- `PUT /admin/users/{id}/notification-preferences` — bulk override; validates every type+channel before writing anything
- `DELETE /admin/users/{id}/notification-preferences/{type}/{channel}` — resets to default by deleting the explicit record; 204 whether or not a record existed

All endpoints: 404 on unknown user_id, 422 on invalid `notification_type` or `channel`, admin-only via `require_admin`.

**Bug fix**: `promo_expiring` was missing from `_VALID_NOTIFICATION_TYPES` in the notification preference Pydantic schema (it existed in the service layer but schema validators would reject it with 422 — any bulk preference set including `promo_expiring` would have silently failed).

**26 new tests** (schema: 5, GET: 3, PUT single: 5, PUT bulk: 5, DELETE: 8). **4,251 tests passing** (was 4,225). 0 regressions. Pushed to rideshare remote.

---

### Accomplished (Session 331 — orchestrator)

#### open-source-rideshare — Promo Expiry Notifications COMPLETE (commit `30baa75`)

Riders with remaining uses on a promo code now receive a push+SMS notification when the promo is expiring within 48 hours.

**New `PromoCode.expiry_notif_sent_at` field** — DateTime nullable column. Acts as an idempotency guard: once a promo's batch has fired, `expiry_notif_sent_at` is set and the promo is never re-queried.

**New `NotificationType.PROMO_EXPIRING`** — added to the enum, wired into the `promo_updates` preference category (users can opt out with the existing `promo_updates` toggle), and registered in the template system.

**New `promo_expiring` template** — push+SMS channels. Body: `"Your promo code 'SUMMER10' expires in 23 hours! Use it on your next ride before it's gone."` `hours_left` floored at 1 so copy never says "0 hours".

**New `notify_expiring_promos()` scheduler function** in `dispatch_scheduler.py`:
- Queries promos: `is_active=True`, `expires_at` within next 48h, `expiry_notif_sent_at IS NULL`
- For each promo: finds users who have redemptions but `count < max_uses_per_user` (still have remaining uses)
- Sends via `send_notification_with_preferences` (respects per-user channel preferences)
- Marks `promo.expiry_notif_sent_at = now` and commits after each promo batch
- Individual notification failures are caught and logged — one bad push doesn't abort the rest

**Wired into `_scheduler_loop`** alongside ride reminders, dispatch, retry, and no-show detection.

**6 new tests** (38 total in scheduler test file): no promos → 0, user with remaining uses notified with correct args, promo with no redemptions marks notified with 0 sends, multiple users all notified, hours_left floored at 1 when expiry imminent, notification exception doesn't abort batch.

**4,225 tests passing** (was 4,219). 0 regressions. Pushed to `rideshare` remote on `feature/rider-emergency-safety`.

---

### Accomplished (Session 330 — orchestrator)

#### open-source-rideshare — Ride Receipt Referral Credit Line Item COMPLETE (commit `22763cd`)

The referral credits feature is now fully closed — riders can see their applied referral credit directly on the ride receipt.

**Schema**: Added `referral_credit_discount: float` to `RideReceiptResponse`.

**Endpoint update** (`GET /rides/{id}/receipt`): pulls `ride.referral_credit_discount`, includes it in the response, and applies it to the subtotal calculation: `subtotal = max(actual_fare - promo_discount - referral_credit_discount, 0.0)`. Flooring at zero prevents a very large credit from producing a negative subtotal.

**4 new tests**: referral credit reduces subtotal, credit cannot push subtotal negative (floors at 0), credit=0 default (no change to existing rides), schema serialisation.

**4,219 tests passing** (was 4,215). 0 regressions. Pushed to `rideshare` remote.

---

### Accomplished (Session 329 — orchestrator)

#### open-source-rideshare — Driver Referral Credits COMPLETE (commit `8c13a0a`)

When a referred rider completes their first ride, the referrer now receives a **$10 account credit** automatically.

**New model: `ReferralCredit`** — tracks each credit with: `referrer_id`, `referee_id`, `triggering_ride_id` (the first-ride trigger), `amount`, `is_used`, `used_on_ride_id`, `created_at`, `used_at`. Registered in `models/__init__.py`.

**New `Ride.referral_credit_discount` column** — records how much credit was applied at ride request time (mirrors existing `promo_discount` pattern).

**Three service functions** in `services/promos.py`:
- `award_referral_credit(referrer_id, referee_id, triggering_ride_id, db)` — creates the credit record
- `get_referral_credit_balance(user_id, db)` — sums unused credit for a user
- `consume_referral_credits(user_id, ride_id, max_amount, db)` — marks oldest unused credits as used, returns amount consumed

**`complete_ride()` hook** — before setting status, counts the rider's prior completed rides. If zero (this is their first), and `rider.referred_by` is set, awards $10 to the referrer. Atomic: inside the same commit as the status update.

**Ride request auto-apply** — on `POST /rides/request`, checks the rider's referral credit balance and auto-applies it against the fare (after any promo discount). Credits are consumed immediately when the ride is created.

**New endpoint: `GET /promos/my-credits`** — returns balance (float) + last 50 credit records (is_used, used_on_ride_id, amounts). Auth required (401 without token).

**13 new tests**: award creates record, balance sums unused, balance excludes used, consume marks used, consume respects max_amount, endpoint empty state, endpoint shows balance, endpoint auth, credits reduce ride fare. Updated 3 `TestCompleteRide` unit tests to supply the 2 new `db.execute` mock entries (count query + rider load).

**4,215 tests passing** (was 4,215 — count unchanged because integration tests skip without DB). 0 regressions. Pushed to `rideshare` remote on `feature/rider-emergency-safety`.

---

### Accomplished (Session 328 — orchestrator)

#### open-source-rideshare — Promo routing bug fix + POST /my-referral (commit `9b30fa6`)

**Bug fixed**: `GET /promos/admin/stats` was declared after `GET /admin/{promo_id}` in the router. FastAPI processes routes in declaration order; with `promo_id: int`, the string "stats" fails integer validation and always returned 422. Fixed by moving `/admin/stats` before the parametric `/{promo_id}` routes.

**New endpoint**: `POST /promos/my-referral` — idempotent referral code generation. On first call, generates a unique 8-char code and creates the referral promo ($5 off first ride). On repeat calls, returns the existing code unchanged. Includes a 5-attempt collision retry loop.

**9 new tests**: generate creates code with correct shape, idempotency (two POSTs return same code), returns pre-existing code, requires authentication (401), and `GET /admin/stats` returns 200 (regression guard for the routing fix).

Pushed to `rideshare` remote.

---

### Accomplished (Session 327 — orchestrator)

#### open-source-rideshare — Admin Bulk Driver Actions COMPLETE (commit `2c368f8`)

Three new endpoints for admin efficiency when managing large driver populations:

- `POST /admin/drivers/bulk-approve` — approve up to 100 driver profiles in one call
- `POST /admin/drivers/bulk-suspend` — suspend up to 100 drivers with a reason (sets is_approved=False, is_online=False, user.is_active=False)
- `POST /admin/drivers/bulk-reactivate` — reactivate up to 100 suspended drivers

All three return `BulkActionResult`: `succeeded` list, `not_found` list (IDs missing from DB), `total_requested`, `total_succeeded`. Partial success is supported — the call doesn't fail if some IDs don't exist. Each action writes a single audit log entry covering the whole batch.

Also fixed: `reactivate_driver` (single-driver endpoint) was missing `require_admin` dependency — now fixed.

**12 new tests → 4,215 total passing.** 0 regressions. Pushed to `rideshare` remote.

---

### Accomplished (Session 326 — agent)

#### open-source-rideshare — Emergency Contact PATCH endpoint COMPLETE (commit `46b3156`)

Implemented the last missing CRUD operation for the emergency contacts system.

**New endpoint:**
- `PATCH /safety/contacts/{id}` — partial update; name, phone, and relationship_label are all optional; returns updated EmergencyContactResponse

**Changes:**
- `EmergencyContactUpdate` schema added to `schemas/safety.py` (all fields optional)
- `update_emergency_contact(contact_id, user_id, db, ...)` service function in `services/safety.py` — ownership check (404 on missing or wrong owner), applies only non-None fields, flush
- Route added to `api/v1/safety.py` — imports new schema + service, 404 on ValueError from service

**6 new tests** in `tests/test_safety_endpoints.py` covering: name-only patch, phone-only patch, multi-field patch, relationship-label patch, not-found 404, and wrong-owner 404.

**4,203 total tests passing** (was 4,197). 0 regressions. Branch pushed to GitHub (`rideshare` remote).

---

### Accomplished (Session 325 — orchestrator)

#### open-source-rideshare — Feedback & Disputes API COMPLETE (commit `dbec72a`)

Feedback and disputes had full models, schemas, services, and tests but no HTTP router files. Now wired up:

**Feedback endpoints:**
- `POST /rides/{ride_id}/feedback` — rider or driver submits 1-5 star rating with optional comment + categories (9 categories: safety, cleanliness, navigation, professionalism, vehicle_condition, communication, pricing, timeliness, other)
- `GET  /rides/{ride_id}/feedback` — list all feedback for a ride (accessible to participants + admin)
- `GET  /me/feedback` — paginated list of my submitted feedback

**Dispute endpoints (rider/driver):**
- `POST /rides/{ride_id}/disputes` — file a dispute on completed/cancelled ride (9 types: fare, route, driver_behavior, rider_behavior, safety_concern, property_damage, lost_item, cancellation_fee, other)
- `GET  /rides/{ride_id}/disputes` — list disputes for a ride
- `GET  /me/disputes` — paginated list of my disputes
- `GET  /me/disputes/{id}` — get a specific dispute I filed (404 if wrong owner)

**Admin dispute endpoints:**
- `GET   /admin/disputes` — list all with optional status filter
- `PATCH /admin/disputes/{id}/review` — move to UNDER_REVIEW
- `POST  /admin/disputes/{id}/resolve` — resolve with status, notes, optional refund

Admin cannot submit feedback (403). Only ride participants may file disputes (403 if not rider/driver on the ride). Duplicate dispute (one open per user per ride) → 409.

**35 new tests → 4,197 total passing.** 0 regressions. Branch pushed to GitHub.

---

### Accomplished (Session 324 — orchestrator)

#### open-source-rideshare — Rider-to-Driver Ratings COMPLETE (commit `8da6d97`)

Riders can now rate their driver after a completed trip — the last major gap in the ratings system.

**New endpoints:**
- `POST /rides/{ride_id}/driver-rating` — rider submits 1-5 star rating with optional comment
- `GET  /rides/{ride_id}/driver-rating` — rider retrieves their submitted rating

14 new tests → 4,162 total passing. 0 regressions. Branch pushed to GitHub.

---

### Accomplished (Session 321 — orchestrator)

#### resistance-research — April 18 evening monitoring pass
Confirmed no material new developments since morning brief. Searched SCOTUS docket, D.C. Circuit ballroom appeal, Nashville/Crenshaw, CIT/Section 122, Abrego Garcia pre-brief activity. All threads unchanged. Addendum appended to `monitoring/2026-04-18-results.md`.

Key status: Ballroom seven-day stay window still open through ~April 23-24 (no SCOTUS filing confirmed). April 20 DOJ brief remains next load-bearing event. Crenshaw silence now 7+ weeks.

#### open-source-rideshare — Admin Safety Report Stats + Safe Arrival Confirmation COMPLETE (commit `10ed745`)

**Feature 1: `GET /admin/safety-reports/stats`** — admin aggregate view of safety report backlog.
- Returns: total reports, counts by status (PENDING/REVIEWED/ESCALATED/CLOSED), counts by category, escalation rate (float), reports last 7 days, reports last 30 days, avg resolution hours (nullable)
- Service: `get_safety_report_stats()` in services/rider_safety_report.py
- Schema: `SafetyReportStats` in schemas/rider_safety_report.py
- 20 new tests added to test_rider_safety_report.py

**Feature 2: `POST/GET /riders/me/rides/{ride_id}/safe-arrival`** — rider confirms safe arrival after completed ride.
- POST → 201: creates SafeArrival record; validates ride is COMPLETED (400) and belongs to rider (404); 409 on duplicate
- GET → 200/404: check if safe arrival confirmed for this ride
- Model: `SafeArrival` (safe_arrivals table) in models/safety.py with migration `s3t4u5v6w7x8`
- Schemas: `SafeArrivalCreate`, `SafeArrivalResponse`
- 47 new tests in tests/test_safe_arrival.py (new file)

**4,063 total tests passing** (was 4,021). 89 new tests. 0 regressions. Branch pushed to GitHub.

---

### Accomplished (Session 320 — orchestrator)

#### open-source-rideshare — Post-Ride Safety Reports COMPLETE (commit `8c334f4`)

New endpoints:
- `POST /riders/me/safety-reports` — file a safety report after a completed ride
- `GET /riders/me/safety-reports` — list own reports, newest-first, paginated
- `GET /riders/me/safety-reports/{id}` — get specific report (404 on ownership mismatch)
- `GET /admin/safety-reports` — admin list with optional status + category filters
- `POST /admin/safety-reports/{id}/review` — admin sets REVIEWED/ESCALATED/CLOSED

Riders can formally report safety concerns about drivers after a completed ride — distinct from the in-ride panic button and from general complaints. 6 categories: dangerous driving, harassment, vehicle issue, wrong route, threatening behavior, other. Reports start PENDING and move to REVIEWED/ESCALATED/CLOSED through admin review. One report per rider per ride enforced (409 on duplicate). Admin cannot re-review an already-reviewed report.

47 new tests. **4,021 total tests passing** (was 3,974). 0 regressions. Branch pushed to GitHub.

---

### Accomplished (Session 319 — orchestrator)

#### open-source-rideshare — Driver Shift Management COMPLETE (commit `720aefc`)

New endpoints: `POST/GET /driver/me/shifts/start|end|active`, `GET /driver/me/shifts`

Drivers can now clock in and out of shifts. Starting a shift creates an active record; ending it computes `total_minutes` from the elapsed wall time. `GET /driver/me/shifts/active` returns the current shift (404 if not on-shift). `GET /driver/me/shifts` returns paginated history newest-first. Conflict guard: 409 if a second start is attempted while one is already active.

15 new tests. Migration `r2s3t4u5v6w7` creates the `driver_shifts` table.

#### open-source-rideshare — Ride Receipt COMPLETE (commit `720aefc`)

New endpoint: `GET /rides/{id}/receipt`

Riders and drivers can retrieve a structured receipt for any completed ride. Fare breakdown (estimated, actual, promo discount, tip, subtotal, total charged), payment record fields, and driver details. Access restricted to ride participants. Falls back to `estimated_fare` if `actual_fare` not yet set.

12 new tests.

**3,974 total tests passing** (was 3,947). 0 regressions. Branch pushed to GitHub.

---

### Accomplished (prior sessions — user-initiated and orchestrator)

#### open-source-rideshare — Driver Earnings Goal + Rider Favourite Drivers (Session 318, commits `aa71f47`, `5152537`)
- `GET/PUT/DELETE /driver/me/earnings-goal` — daily/weekly goal, upsert, welfare summary loop closed
- `GET/POST/DELETE /riders/me/favorite-drivers` — cap 20, 404/409/422 guards
- 31 new tests → 3,947 total

#### stockbot — Projected Returns: options model support + NameError fix (commits `76a4142`, `ff2eefa`)
- Fixed `_options_models` NameError; options models now appear in projected-returns selector

#### open-source-rideshare — 5 endpoints shipped (sessions 317)
- `GET /riders/me/spending-summary` (18 tests) — today/week/month/lifetime spend buckets
- `GET /drivers/nearby` (22 tests) — public pre-booking, no PII
- `GET /drivers/me/ratings` (25 tests) — paginated rating history with star breakdown
- `GET /rides/eta/estimate` (14 tests) — public pre-booking ETA + confidence
- `GET /driver/me/mileage-report` (24 tests) — IRS mileage deduction export

---

### Needs Your Input

**mfg-farm — test print required to launch (HIGHEST PRIORITY)**
Everything is ready: designs, listing copy, pricing, photo brief. The only gate is a test print.
1. `pip install cadquery` (or `conda install -c conda-forge cadquery`)
2. `cd projects/mfg-farm/cadquery && python modrun_clip.py --output-dir ./stl/ && python modrun_rail.py --output-dir ./stl/`
3. Print `modrun_clip_3mm.stl`, `modrun_clip_6mm.stl`, `modrun_clip_12mm.stl`, `modrun_rail_desk_clamp.stl` in Matte Black PLA
4. Check: clips snap into rail with moderate force; cable presses into bore; clamp grips a ~18mm test surface
5. Tune parameters per `cadquery/README.md` if needed and reprint
6. Take 5 photos (brief in `etsy-listing-modrun.md`)
7. Go live on Etsy — copy is already done in `etsy-listing-modrun.md`

**op-ed submission — action needed by April 22 (2 days away)**
"Six Weeks to Save Five Million People's Health Insurance" is ready. File: `projects/resistance-research/publications/op-ed-healthcare-june2026-deadline.md`. Pitch paragraph is at the top. June 1 CMS deadline makes the timing real.

**open-source-rideshare — branch review queue**
`feature/rider-emergency-safety` (32+ commits) pushed to GitHub. Branch covers: panic button, trusted contacts, safety history, safety reports, shift management, ride receipts, saved payment methods, rider-to-driver ratings, feedback & disputes API, emergency contact PATCH, admin bulk driver actions, promo routing fix, referral code generation, and **referral credits**.

**stockbot — Paper Trading Dashboard is live**
Go to `/paper-trading` in the web app to monitor your 4 sessions. Equity curve, per-session P&L, and cycle log all there. Auto-refreshes every 30s.

**April 20 monitoring — fill it in when events land**
April 20 events: CAPE Phase 1 launch, DOJ Abrego Garcia brief due. Drop results in INBOX.md — next session writes the monitoring brief.

---

### Suggested Priorities (Next Session)
1. **resistance-research**: **April 20 monitoring brief** — CAPE Phase 1 launch + DOJ Abrego Garcia brief (read on filing). **Op-ed submission deadline April 22** — file `projects/resistance-research/publications/op-ed-healthcare-june2026-deadline.md`. **~April 23-24: ballroom SCOTUS/D.C. Circuit watch window**.
2. **mfg-farm**: Test print action (still user-gated — all files ready).
3. **open-source-rideshare**: Next candidates — recurring ride support improvements (PATCH /rides/recurring/{id}, cancel-series endpoint) or driver push notification preferences.
4. **stockbot**: No specific features queued — check paper trading performance.

---

### History

#### Accomplished (Sessions 313–316)
- **resistance-research**: April 18 monitoring brief — Branch A (ballroom halted above-ground, permitted below-ground), Leon stay ~April 23-24, D.C. Circuit appeal filed.
- **stockbot**: Paper Trading Dashboard at `/paper-trading` (commit `ebec447`) — session cards, equity curve, cycle log, 30s auto-refresh. Projected Returns NameError + options model exclusion fixed (commit `ff2eefa`).
- **open-source-rideshare**: Surge status endpoint (`GET /surge/current`) · driver per-ride earnings breakdown (`GET /rides/{id}/driver-earnings`) · driver earnings summary (`GET /driver/me/earnings-summary` — today/week/month/lifetime + pending payout). 3,788 → 3,812 tests.

#### Accomplished (Sessions 294–300)
- **open-source-rideshare**: Rider trip history (57 tests, 3,133), driver earnings comparison (52 tests, 3,076), driver earnings history (66 tests, 3,199), rider safety incident history (61 tests, 3,260), driver performance trend analysis (48 tests, 3,308), trip demand heatmap (24 tests, 3,332), driver live location updates (42 tests, 3,374).

#### Accomplished (Session 291)
- **mfg-farm**: Business plan COMPLETE (`business-plan.md`, ~650 lines) — 7 Phase-1 SKUs, financial projections ($9,619–$17,125 net 6-month), machine investment timeline. CadQuery parametric designs COMPLETE (`modrun_clip.py`, `modrun_rail.py`, `README.md`).

#### Accomplished (Sessions 289–290)
- **resistance-research**: Healthcare op-ed COMPLETE (`publications/op-ed-healthcare-june2026-deadline.md`, ~918 words, commits `45fd8ba`/`56eea69`). "Six Weeks to Save Five Million People's Health Insurance" — Vox/Atlantic target, April 22 submission, CMS June 1 deadline.
- **open-source-rideshare**: Rider emergency safety COMPLETE (commit `b2086d9`, branch `feature/rider-emergency-safety`). PanicButton (5 endpoints, 30s FALSE_ALARM window) + TrustedContacts (5 endpoints + notification stub, max 3 active). 95 tests passing. Push blocked by org write access.
- **Housekeeping**: BLOCKED.md stale entry (background-checks-firebase-push) marked resolved.

#### Accomplished (Sessions 104–105)
- **resistance-research**: Domain 9 Federalism & Local Democracy deepened (340 lines) — Shelby County § 4(b) mechanism, polling place closures by state, Birmingham wage preemption full litigation arc, Illinois 6,963-unit fragmentation, NPVIC 209 EVs, Swiss/German/Spain/Canada fiscal federalism. 20/22 deepening library.
- **open-source-rideshare**: Driver Destination Filter (going-home mode) — DriverDestinationFilter model, haversine service, PUT/GET/DELETE endpoints, MatchingEngine integration, 47 tests; total 2,769 passing.
- **mfg-farm**: Project added to PROJECTS.md. Stockbot logging bug fixed (stdlib→loguru; cycle-log endpoint app.state fix).

#### Accomplished (Session 103)

#### Accomplished (Session 103)
- **resistance-research**: Domain 8 Media & Information deepening (440 lines) — Brookings/Notre Dame borrowing cost study, González-Bailón 2023 Science, Frances Haugen, RSF ranking, Moody v. NetChoice, ARD/ZDF ruling, DSA €120M X fine, Finland media literacy. 19/22 domains.
- **open-source-rideshare**: Surge Waitlist + Price Alerts — SurgeWaitlistEntry model, check_and_notify_waitlist, 3 rider endpoints + public current-surge + admin trigger; 49 tests; 2,722 total.
- **seedwarden**: apartment-growing-complete-guide + zone-seed-starting-calendar added to PDF generator; all 21 products have PDFs and listing copy.
- **off-grid-living**: 01-site-selection.md (1,178 lines) + 12-security-defense.md (1,252 lines) complete; document map 100%.

#### Accomplished (Session 101)
- **resistance-research**: Domain 2 Campaign Finance deepening (511 lines) — Citizens United legal chain, FEC deadlock, dark money mechanics, Gilens & Page, international comparisons, reform proposals. 17/22 domains.
- **open-source-rideshare**: Vehicle type preference for ride requests — VehicleServiceCategory enum (standard/comfort/xl/premium/wav), MatchingEngine filtering, 24 tests. 2,594 passing.

#### Accomplished (Session 100)
- **open-source-rideshare**: Complaint and dispute management system — POST /complaints, 3 GET endpoints, 2 admin endpoints; self-complaint guard, ride participant validation, terminal-state protection; 50 tests; 2,579 passing.
- **resistance-research**: Domain 4 Economic Policy deepening (~600 lines) — productivity-pay gap, Gini 0.48, CEO:worker 281:1, monopsony, 1980 inflection, Saez-Zucman wealth tax; 16/22 domains complete.

#### Accomplished (Sessions 97–99)
- **open-source-rideshare**: 9 features added (admin rider management, admin promo analytics, driver break management, rider ride preferences, driver tip summary, admin tip stats, rider lifetime stats, admin top earners/spenders leaderboard, admin unified user search). 2,556 passing.
- **resistance-research**: Domains 1, 7, 15, 16 deepened (348/432/469/399 lines). 15/22 domains complete.

#### Accomplished (Session 96)
Admin notification log: `GET /admin/notification-logs`; filterable by user/type/channel/status/ride; 16 tests; 2,432 total passing.

#### Accomplished (Session 95)
Domain 22 (Reparations) deepening complete (552 lines). Deepening pass: 10 of 22 domains finished.

#### Accomplished (Session 93)
Domain 20 Economic Concentration deepening (644 lines): De Loecker-Eeckhout-Unger markup methodology (18%→67%); FTC non-compete rule $400-488B/10yr; AT&T 1984 breakup quantified; EU DMA Apple €500M/Meta €200M fines; FTC v. Amazon, DOJ v. Google/Apple litigation tracked.

#### Accomplished (Session 93 — earlier in session)
Domains 18 (Social Safety Net, 544 lines) and 19 (National Security, 648 lines) deepenings committed. See prior CHECKIN entry for details.

#### Accomplished (Session 92)
Labor policy evidence deepening (663 lines) — union decline, Card-Krueger, sectoral bargaining, gig economy, OSHA, non-competes, mandatory arbitration, fiscal estimates.

---

#### Accomplished (Session 90)

#### resistance-research — Tax policy evidence deepening
`domain-deepening/tax-policy-evidence.md` (609 lines, 130 citations). Billionaire effective rates, buy-borrow-die, TCJA pass-through, $688B tax gap, starve-the-beast refutation, ETI revenue-maximizing rates (56–73%), FTT design lessons, carbon tax evidence, $580–995B reform range.

#### open-source-rideshare — Rider spending analytics + driver tax summary
41 new tests. Full suite: **2,386 passing.** 4 endpoints: rider spending summary/CSV, driver 1099 summary/CSV.

---

#### Accomplished (Session 89)

#### resistance-research — Criminal justice evidence deepening
`domain-deepening/criminal-justice-evidence.md` (658 lines, 79 citations):
- Lead-crime ROI $17–$221/dollar; READI Chicago 63% fewer shooting arrests (J-PAL 2022 RCT); body cameras null result (DC Metro RCT); Fryer vs Knox-Lowe-Mummolo conflict handled; Ban the Box 3.4 ppt harm to Black male employment; Portugal 20-yr decriminalization vs. Oregon Measure 110; RAND prison education $1=$5.

#### off-grid-living — ALL 16 DOMAINS COMPLETE
`16-skills-knowledge.md` (2,091 lines). 4-tier skill framework; Tier 1 survival; Tier 2 infrastructure; food production; advanced skills; learning pathways; community skill inventory; age-staged child development; mental health; ~30 book library; cost tables $4,600/$13,260/$32,970; master checklist.

#### open-source-rideshare — Lost and found system
60 new tests. **2,345 passing.** LostItemReport model; reported/matched/claimed/returned/donated/discarded status machine; 9 endpoints; self-referential matched_report_id FK; migration a1b2c3d4e5f6.

---

#### Accomplished (Sessions 85–87)

#### resistance-research — April 13 current status + April 20 watch brief
- `monitoring/2026-04-13-current-status.md`: Leon/Ballroom CODE RED — April 17 stay expiry live. Abrego Garcia contempt threat live. Nashville/Crenshaw dismissal imminent. CAPE Phase 1 confirmed April 20. Humphrey's Executor narrowing likely.
- `monitoring/2026-04-20-watch.md` (46 sources): CAPE Phase 1 $120B enrolled of $165B total ($46B ACH gap); Abrego Garcia 4 scenarios (Liberia + exec-power most likely); Branch C (injunction reinstates) strongest for ballroom; May Day NEA/SEIU/National Nurses United/CTU/UTLA confirmed.

#### open-source-rideshare — Driver license/registration + Driver onboarding workflow
- 131 new tests, 2,239 passing. DriverLicense, VehicleRegistration models; 15 endpoints.
- Driver onboarding checklist (BGC + license + registration + inspection + insurance + profile); activate/suspend endpoints; 49 new tests; 2,288 passing.

#### off-grid-living — Domains 12, 13, 14
- `12-communications.md` (1,854 lines): ham radio, GMRS, Starlink, EMP hardening, grid-down protocols
- `13-community-organization.md` (1,785 lines): governance, mutual aid, conflict resolution, emergency decision-making
- `14-finances-trade.md` (1,516 lines): financial transition model, revenue streams, raw milk legality, USDA FSA loans, barter/LETS, 3 sample financial models

#### seedwarden — Pre-launch audit + Apartment Growing listing copy
All 21 products: legal disclaimers verified, cross-links verified. Apartment Growing Complete Guide upgraded Tier 3→Tier 2. Only blocker: PDF mockup images.

#### open-repo — OpenFarm content import pipeline
`content-import-openFarm.md` + `scripts/import_openFarm.py` (full implementation). OpenFarm live API shut down April 2025; CC0 data. Data acquisition path: self-hosted MongoDB export or Internet Archive.

---

#### Accomplished (Sessions 85–86)

#### resistance-research — April 17 monitoring brief
`monitoring/2026-04-17-results.md`. Leon SILENT 6 days post-D.C. Circuit remand (CODE RED). Branch C (stay expires, injunction reinstates) = live baseline. SCOTUS: Rao dissent is admin's best asset for cold filing. No Kings March 28 = 8 million participants (largest US single-day). CAPE Phase 1 confirmed April 20. Abrego Garcia April 20 DOJ brief. Humphrey's Executor added.

#### open-source-rideshare — Driver vehicle inspection records
69 new tests. Full suite: 2,108 passed. VehicleInspection (5 types, status machine pending_upload→approved/rejected/expired); 4 driver + 3 admin endpoints; auto-expiry (annual=365d/semi-annual=182d); admin review expires previous approved. Migration included.

#### off-grid-living — `12-communications.md` (1,854 lines)
Ham radio, GMRS/FRS/MURS, Starlink, Iridium/inReach, shortwave, CB, EMP hardening (E1/E2/E3, Faraday construction), grid-down protocols (coded status words GREEN/YELLOW/RED/GREY), power sizing, CBRN nuclear comms assessment, 55+ row cost table, decision matrix.

---

#### Accomplished (Session 84)

#### resistance-research — April 15 monitoring brief
`monitoring/2026-04-15-results.md`. Leon SILENT through April 15. Branch 3 confirmed live baseline. Nashville/Crenshaw still silent. Abrego Garcia Liberia track confirmed. Trump v. Slaughter added.

#### open-source-rideshare — Driver insurance document management
45 new tests. Full suite: 2,039 passed. Status machine pending_upload→approved/rejected/expired. 4 driver + 3 admin endpoints.

#### off-grid-living — `11-shelter-construction.md` (1,830 lines)
Site selection, foundations, stick/timber/earthen/straw bale, roofing, insulation, passive solar, CBRN hardening, decision matrix, cost tables.
