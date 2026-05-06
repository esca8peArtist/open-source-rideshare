---
title: Phase 3 MVP — 8-Week Sprint Roadmap
project: open-source-rideshare (OpenRide)
date: 2026-05-06
status: production-ready
author: orchestrator (autonomous execution agent)
related_files:
  - phase-3-tech-architecture.md
  - feature-prioritization-matrix.md
  - ARCHITECTURE.md
  - regulatory-compliance-tech-checklist.md
---

# Phase 3 MVP — 8-Week Sprint Roadmap

## Executive Summary

**Total MVP scope**: 620–805 development hours + 40–60 hours nice-to-have.

**Team structure** (recommended for estimated timeline):
- 1 backend engineer (Python/FastAPI, PostgreSQL)
- 1 mobile engineer (Flutter, driver + rider apps)
- 1 web/admin engineer (React/TypeScript, admin dashboard + public tracking web)
- 0.5 DevOps (CI/CD, Docker, Kubernetes, cloud infra)

**Timeline at full capacity (40 hrs/week per dev)**: 7–10 weeks to MVP ship-readiness.

**Critical path**: Compliance engine (backend) → Checkr integration → Driver go-online gate → Rider booking + payment flow → Rating system → 1099 + tax. No parallel shortcuts; each phase unblocks the next.

**Governance decisions required before sprint kickoff**:
1. Platform fee % (cooperative takes X% of each ride)
2. Surcharge amount (Portland per-trip surcharge for city fees)
3. TNC fee allocation (how much goes to insurance vs. operations)
4. WAV (Wheelchair Accessible Vehicle) driver onboarding strategy
5. Cancellation fee policy (% of estimated fare)
6. SSN tokenization provider (Basis Theory vs. Stripe Identity)

---

## Sprint Structure

Each sprint is **2 weeks** with these ceremonies:
- **Tuesday 09:00 UTC** — Sprint planning (2 hours). Review upcoming work, confirm story estimates, identify blockers
- **Thursday 10:00 UTC** — Sync check-in (30 min). Status updates, blocker triage
- **Friday 16:00 UTC** — Demo / retrospective (90 min). Show working features, discuss process improvements

**Definition of Done** (for all deliverables):
- Code peer-reviewed and merged to feature branch
- Unit tests passing locally (>80% coverage for critical paths)
- Integration tests passing on shared test PostgreSQL
- Documentation updated (API docs, component stories, deploy notes)
- Features tested end-to-end on staging (staging deploy triggered automatically)
- NO merge to master until Phase 3 MVP complete

---

## Sprint Allocations by Phase

### **Sprint 1 (Week 1-2): Compliance Engine & Schema Expansion**

**Goal**: Foundation for all driver verification work. Unblocks driver app onboarding and compliance document upload.

**Backend (90–110 hours)**:

1. **Compliance schema expansion** (12–16 hrs)
   - Add to `driver_profiles` table:
     - `membership_status` (enum: active, suspended, probation, terminated) — default active
     - `license_expiry` (date)
     - `background_check_expiry` (date)
     - `vehicle_inspection_expiry` (date)
     - `insurance_endorsement_expiry` (date)
     - `insurance_endorsement_verified_at` (timestamp)
   - Add `audit_log_entries` table (compliance events)
   - Backfill with dummy data for test drivers
   - Migration scripts for production rollout

2. **Compliance gate logic** (16–20 hrs)
   - New endpoint: `GET /api/v1/compliance/check/{driver_id}` — returns status for each doc type
   - Business logic: all docs current AND membership_status == active → driver eligible to go online
   - Implement 14-day grace period for license, 30-day for background check (automatic hold if expired)
   - Nightly cron job: `compliance_check_cron()` updates all driver statuses at 02:00 UTC
   - Log all status changes to audit_log_entries with reason field

3. **Admin endpoint: set membership status** (8–10 hrs)
   - `POST /api/v1/admin/drivers/{driver_id}/membership_status` (admin-only)
   - Accepts: {new_status: "active|suspended|probation|terminated", reason: string}
   - Stores to audit log
   - Triggers FCM push to driver on suspension/termination (see messaging template in Section 4)

4. **Checkr setup & credential management** (12–16 hrs)
   - Add `CHECKR_API_KEY` and `CHECKR_API_SECRET` to secrets manager
   - Create `checkr_checks` table:
     - candidate_id (Checkr's identifier)
     - driver_id (foreign key)
     - status (created, invited, processing, clear, consider, suspended)
     - result_json (full Checkr response)
     - created_at, completed_at
   - Write integration tests for Checkr API client (don't call API in tests; use mocks)

5. **Jurisdiction config infrastructure** (20–24 hrs)
   - Add `jurisdictions` table (immutable, seeded once at deploy)
   - Portland config (JSON):
     ```json
     {
       "id": "portland_or",
       "name": "Portland, Oregon",
       "background_check_type": "motor_vehicle_record + criminal",
       "per_trip_surcharge": 0.50,
       "per_trip_surcharge_description": "Portland City Fee",
       "license_requirement": "Oregon commercial driver license",
       "insurance_requirement": "$1M commercial auto TNC endorsement",
       "wav_mandate": true,
       "wav_percentage": 0.05
     }
     ```
   - Atlanta config (simpler, no per-trip surcharge):
     ```json
     {
       "id": "atlanta_ga",
       "name": "Atlanta, Georgia",
       "background_check_type": "motor_vehicle_record + criminal",
       "per_trip_surcharge": 0.00,
       "license_requirement": "Georgia commercial driver license",
       "insurance_requirement": "$1M commercial auto TNC endorsement",
       "wav_mandate": false
     }
     ```
   - Seeding script: load from YAML/JSON file at migration time
   - No runtime changes to jurisdiction config (changes require new migration)

**Mobile (Driver app) — Minimal (0 hours)**:
- No driver app work needed this sprint; unblocked by backend schema

**Completion criteria**:
- All compliance endpoints tested and documented in OpenAPI
- Nightly cron validated against staging database
- Jurisdiction configs deployed to staging
- No merge to master yet; feature branch is integration point for Sprint 2

---

### **Sprint 2 (Week 3-4): Checkr Integration & Driver Document Upload**

**Goal**: Enable driver background checks and document uploads. Unblocks go-online gate in Sprint 3.

**Backend (60–75 hours)**:

1. **Checkr API client** (20–25 hrs)
   - Implement Checkr SDK calls:
     - `create_candidate(driver_id, name, dob, email, phone)` → returns candidate_id
     - `request_check(candidate_id, package="COMPREHENSIVE")` → initiates background check workflow
     - Parse webhook handler for check status updates
   - Error handling: Checkr API timeouts, invalid SSN, duplicate candidate
   - Retry logic (exponential backoff for transient failures)
   - Unit tests for all Checkr calls (mock responses)

2. **Checkr webhook handler** (12–15 hrs)
   - New endpoint: `POST /api/webhooks/checkr` (authenticated with Checkr API key)
   - Webhook events: completed_check, adverse_action_initiated, adverse_action_cleared
   - Update driver_profiles.background_check_status and background_check_expiry
   - Log event to audit_log_entries
   - Auto-trigger FCRA adverse action notice if result is "suspended" or "consider"
   - Idempotent: handle duplicate webhooks gracefully

3. **Document storage backend** (12–15 hrs)
   - MinIO or Backblaze B2 bucket configuration (choose one; recommend B2 for cost at startup scale)
   - Backend endpoint: `POST /api/v1/drivers/compliance-documents/upload/{doc_type}` (multipart/form-data)
   - Document types: license, vehicle_registration, vehicle_inspection, insurance_endorsement
   - Validate file type (PDF, JPEG, PNG; reject SVG, executable, etc.)
   - Max file size: 10 MB per document
   - Store with naming convention: `driver_{driver_id}/{doc_type}_{timestamp}_{uuid}.{ext}`
   - Return signed download URL (short-lived, 1-hour expiry)
   - Admin can re-request document; driver gets push notification

4. **Document metadata extraction** (8–10 hrs)
   - For license: extract expiry date from image via OCR or manual reviewer input (depends on doc upload; see notes below)
   - For vehicle inspection: extract expiry date (OCR or manual)
   - For insurance: extract certificate holder name and endorsement date (manual review for TNC endorsement confirmation)
   - Store extracted metadata in document_metadata JSON field
   - Admin dashboard displays extracted values for confirmation (click to override if OCR failed)

5. **FCRA adverse action flow** (8–10 hrs)
   - If Checkr result is "suspended" or "consider": auto-generate FCRA pre-notice (Checkr provides template)
   - Pre-notice tells driver: "We are considering taking action based on the results of a background check. You have 5 business days to dispute."
   - 5-day window: driver can dispute with Checkr directly
   - After 5 days: auto-generate final FCRA notice: "Based on the background check, you are no longer eligible to drive."
   - Driver membership_status set to "terminated" after final notice

**Mobile (Driver app) (50–65 hours)**:

1. **Compliance document upload flow** (30–40 hrs)
   - New screen: `ComplianceDocumentUploadScreen`
   - Displays 4 cards (license, registration, inspection, insurance)
   - Each card has: document type, required fields (expiry date), status indicator (✓ / ⚠ / ✕), "Upload" button
   - On "Upload" tap:
     - Open file picker (device photos or files)
     - User selects image or PDF
     - App shows preview and prompts: "Confirm this is [doc type]?"
     - On confirm: upload via `POST /api/v1/drivers/compliance-documents/upload/{doc_type}`
     - Success: show checkmark, display "Verified" or "Under Review"
   - Failure: show error message with retry button
   - Estimated prints: 20–25
   - Navigation: this screen is part of onboarding flow (before first go-online)
   - Unit tests: file selection, upload success/failure, state management

2. **Expiry alert integration** (10–15 hrs)
   - New background task: check local document metadata cache
   - At app launch: compare expiry dates to today
   - If 30 days away: show amber warning banner ("License expires in 30 days")
   - If 14 days away: show red banner ("License expires in 14 days; upload new license")
   - If expired: show critical banner ("License expired; cannot go online until renewed")
   - Tap banner: navigate to ComplianceDocumentUploadScreen
   - Tests: date logic, banner conditions

3. **App Store / Play Store metadata prep** (10–15 hrs)
   - Write privacy nutrition label for Apple App Store
   - Write data safety section for Google Play Store
   - Prepare screenshots for both stores (English; translators later)
   - Create app description, keywords, support URL
   - Note: do NOT submit yet; store-side prep only (apps submit at end of Sprint 8)

**Web/Admin (0 hours)**: 
- No admin work needed yet; driver app submission prep is minimal

**Testing**:
- E2E test: driver uploads license → backend stores → admin dashboard shows document with extracted metadata
- E2E test: Checkr webhook fires → driver membership_status updates → push notification sent
- Integration test: FCRA adverse action flow (5-day window, final notice, termination)

**Completion criteria**:
- Driver can upload all 4 document types
- Document metadata extracted and displayed to admin
- Checkr integration tested against staging (mock candidate creation)
- FCRA flow implemented and logged
- Feature branch ready for Sprint 3 merge

---

### **Sprint 3 (Week 5-6): Go-Online Gate & Driver App Core Features**

**Goal**: Enable drivers to go online after passing compliance checks. Complete driver app navigation and earnings dashboard.

**Backend (40–50 hours)**:

1. **Go-online compliance check** (12–15 hrs)
   - Modify `POST /api/v1/drivers/{driver_id}/go-online` endpoint (Phase 1 skeleton)
   - Call compliance engine: check all docs current + membership_status == active
   - If any doc expired or membership suspended: return 403 with reason field
   - Log attempt to audit_log_entries (helpful for debugging driver issues)
   - Return error message user-friendly: "Your license expires in 3 days. Please upload a new license to continue."

2. **Earnings API enhancement** (15–18 hrs)
   - Existing `GET /api/v1/drivers/{driver_id}/earnings` endpoint — add new fields:
     - base_fare, platform_fee, stripe_fees, driver_payout (line items, not totals)
     - Cooperative fee: sum of platform_fee across all trips
     - Year-to-date aggregation (all trips this calendar year)
     - Breakdown by date range (today, this week, this month, YTD)
   - All queries use database aggregation (no in-app math)
   - Caching: response cached for 5 minutes (reasonable for earnings display)

3. **1099 tax info collection schema** (8–10 hrs)
   - Add to driver_profiles:
     - legal_name (PII, encrypted)
     - tax_id (SSN or EIN, tokenized via Basis Theory)
     - tax_id_verified_at (timestamp)
     - w9_signed_at (timestamp — when driver accepted W-9 in app)
   - No direct SSN storage; use Basis Theory vault token instead

4. **Background dispatch task queue** (5–7 hrs)
   - If Checkr integration will call external API and webhook may be slow: implement task queue (Celery + Redis)
   - Queue tasks: send_compliance_expiry_push, generate_fcra_notice, send_1099_batch
   - Not critical for Sprint 3, but infrastructure useful for scale; implement low priority

**Mobile (Driver app) (80–100 hours)**:

1. **Go-online gate** (15–20 hrs)
   - Modify toggle: "Go Online" → before it works, check compliance endpoint
   - If 403: show modal with reason and link to ComplianceDocumentUploadScreen
   - If 200: proceed with existing online toggle logic
   - State management: cache compliance status for 5 minutes (reduce API calls)
   - Unit tests: all compliance failure scenarios

2. **Audio alert + haptic on ride offer** (10–15 hrs)
   - When new ride offer arrives via WebSocket: don't just show notification
   - Play audio alert: 1-second alert tone (pre-baked audio file in app, OR use system ringtone)
   - Trigger haptic feedback: strong 200ms vibration
   - If driver has app backgrounded: show foreground notification (FCM)
   - If app is closed: FCM alone (no audio/haptic for now; defer to Phase 4)

3. **Turn-by-turn navigation: pickup route** (30–35 hrs)
   - When ride is matched: fetch route from backend (OSRM)
   - Store route geometry as GeoJSON polyline
   - Render on flutter_map: polyline overlay + current driver position
   - Show turn instruction banner: "Turn left onto Main St" (OSRM provides turn instructions)
   - Recenter map on driver position every 3 seconds (adaptive frequency logic)
   - Tests: polyline rendering, turn instruction updates, map centering

4. **Turn-by-turn navigation: dropoff route** (15–20 hrs)
   - When trip starts (driver at pickup): trigger second navigation segment
   - Hide pickup polyline; show dropoff route
   - Same logic as pickup navigation
   - Tests: segment transition, polyline swap

5. **Adaptive GPS frequency** (15–20 hrs)
   - geolocator package configuration:
     - When moving: 3 seconds (0.3 accuracy: fast updates)
     - When stationary (speed < 1 m/s): 15 seconds
     - When backgrounded: 30 seconds + `isExactLocationRequired: false`
   - Save power: geolocator automatically reduces accuracy in background
   - Monitor battery: if battery < 15%, increase interval to 30 seconds
   - Tests: location callback frequency, battery monitoring

6. **Offline GPS buffering** (20–25 hrs)
   - Use drift (SQLite) to buffer GPS points locally
   - When offline (geolocator works offline, but WebSocket is disconnected):
     - Each location callback: save to local SQLite table buffered_locations
     - Timestamp, lat/lon, accuracy, battery_level
   - When connectivity resumes (detected by connectivity_plus):
     - Batch-upload buffered points: `POST /api/v1/drivers/{driver_id}/locations/batch`
     - Wipe local cache after successful upload
   - Tests: offline scenario, batch upload on reconnect

7. **Earnings dashboard refinements** (8–12 hrs)
   - Existing dashboard (Phase 1) displays total earnings
   - Add breakdowns: today, this week, this month, year-to-date
   - Show platform fee as separate line item (transparency)
   - Add tip total (separate from fare earnings)
   - CSV export button (writes earnings data to device Downloads folder; uses file_picker + csv package)

**Web/Admin (30–40 hours)**:

1. **Admin compliance dashboard** (30–40 hrs)
   - New admin page: `/admin/compliance/drivers`
   - Displays table: driver name, membership_status (color-coded), license_expiry, background_check_expiry, vehicle_inspection_expiry, insurance_endorsement (last verified date)
   - Filters: membership_status, jurisdiction, document status (all current / any expired)
   - Sort: by name, by expiry date, by status
   - Click driver row: see detailed compliance view with document thumbnails + extracted metadata
   - Admin can: update membership_status with reason, mark document as verified (if OCR was wrong), send document re-request push
   - Audit log: each action recorded with timestamp + admin name
   - Estimated effort: React component + GraphQL/REST endpoint + styling

2. **Document management** (in included in above estimate)
   - Admin can view uploaded documents (signed S3/B2 preview links)
   - Admin can flag document as "rejected" (requires driver re-upload)
   - Admin can override OCR metadata if extraction was wrong

**Testing**:
- E2E: driver with expired license clicks "Go Online" → blocked with error → uploads new license → tries again → succeeds
- E2E: during active trip, GPS goes offline for 2 minutes, buffers points, comes back online, syncs
- Integration test: earnings API returns correct line items for multi-trip day

**Completion criteria**:
- Drivers cannot go online without current compliance docs
- Navigation works for pickup and dropoff segments
- GPS buffering validated with offline scenario test
- Admin compliance dashboard fully functional
- App can submit to App/Play Store (no store submission yet, just readiness)

---

### **Sprint 4 (Week 7-8): Rider App MVP & Payment Integration**

**Goal**: Enable riders to book trips, see driver approach, and pay. Complete MVP's main revenue loop.

**Backend (50–65 hours)**:

1. **Fare estimate endpoint enhancement** (10–12 hrs)
   - Existing `/api/v1/rides/estimate` (Phase 1) — add platform fee to response
   - Response structure: {base_fare, distance_km, time_minutes, platform_fee_pct, estimated_total}
   - Include: surcharge amount if Portland jurisdiction
   - Unit tests: fare calculation, surcharge application

2. **Payment split & line items** (15–20 hrs)
   - When ride completes: store to rides table:
     - base_fare (distance + time calculation)
     - stripe_fee (2.9% + $0.30 of base_fare)
     - cooperative_fee (X% of base_fare, as defined in governance decisions)
     - driver_payout (base_fare - stripe_fee - cooperative_fee)
   - Store all four values in database (don't calculate on the fly)
   - Used by earnings API (Sprint 3) and tax reporting (Sprint 6)

3. **Trip cancellation fees** (10–12 hrs)
   - Implement operator-defined cancellation policy
   - If rider cancels after driver departs: charge X% of estimated fare
   - If rider cancels before driver moves: $0 charge (grace period ~2 minutes)
   - Store cancellation_reason and charge_amount in rides record
   - Tests: grace period logic, charge calculation

4. **Ride state machine update** (8–10 hrs)
   - Trip states: REQUESTED → MATCHED → ARRIVED_AT_PICKUP → IN_PROGRESS → COMPLETED
   - Add to Trip enum (if not present from Phase 1): CANCELLED_BY_RIDER, CANCELLED_BY_DRIVER
   - Compliance gate: only active-membership drivers can be offered rides (already added in Sprint 3, re-check wire-up)

5. **WebSocket subscription for rider tracking** (7–10 hrs)
   - Enhance existing WebSocket to broadcast driver location to rider
   - Rider subscribes to ride/{ride_id}/driver_location
   - Backend publishes driver location every 3 seconds (matches GPS update frequency)
   - Unsubscribe when trip completes

**Mobile (Rider app) (120–150 hours):**

1. **Location entry (pickup + dropoff)** (25–30 hrs)
   - Map screen with current GPS pin (flutter_map with MapLibre)
   - Address search: Nominatim geocoding API (free, self-hostable)
   - Autocomplete: as user types, hit Nominatim /search endpoint, show dropdown results
   - Tap result: geocodes to {lat, lon}, shows on map
   - Map pin drag: move pin around map, reverse-geocode to get address
   - Pickup field: pre-filled with current location (allow override)
   - Dropoff field: initially empty, require user entry
   - State management: store both locations in BLoC; debounce geocoding (don't call API on every character)

2. **Fare estimate display** (12–15 hrs)
   - When both locations set: call `/api/v1/rides/estimate`
   - Display card: base_fare, distance, time, platform_fee, total
   - Update live as user adjusts locations
   - Include any jurisdiction-specific surcharges (Portland: show "$0.50 city fee")
   - Format as clear line items, not just a number
   - Caching: re-fetch every 10 seconds if locations change

3. **Request ride / matching status** (20–25 hrs)
   - "Request Ride" button: calls `POST /api/v1/rides` with pickup/dropoff, creates ride record
   - New screen: MatchingStatusScreen
   - Display: "Finding a driver..." (while REQUESTED state)
   - When matched (WebSocket event): show driver card (name, vehicle, photo, rating)
   - Show ETA to pickup (updates live every 3–5 seconds)
   - "Cancel ride" button (charges fee if driver en route)
   - Auto-navigate to next screen when driver arrives (state = ARRIVED_AT_PICKUP)

4. **Live driver tracking on map** (20–25 hrs)
   - Active trip screen: show driver position on map
   - Subscribe to WebSocket: ride/{ride_id}/driver_location
   - Animate driver pin position as updates arrive (animate from old position to new over 3 seconds)
   - Show polyline: current route from driver to rider (if driver is en route to pickup) or current route to dropoff (if in progress)
   - Show ETA banner at top: "Driver arriving in 4 minutes" (updates from OSRM recalc every 30 seconds)
   - "Call driver" button: initiates Twilio masked phone call
   - "Share trip" button: generates public tracking URL, opens share sheet

5. **Stripe card payment** (25–35 hrs)
   - At registration: rider enters card via Stripe CustomerSession (Phase 1 abstraction)
   - Store payment method with Stripe (customer vault)
   - At checkout (after trip completes): call `POST /api/v1/payments/charge` with ride_id
   - Backend calls Stripe `charge(customer_id, payment_method_id, amount)`
   - Stripe webhook: charge succeeded / failed → update rides table payment_status
   - App polls `GET /api/v1/rides/{ride_id}` to check payment_status
   - On success: show receipt, navigate to rating screen
   - On failure: show error, offer retry or cancel
   - Security: never handle raw card data; use Stripe SDK only

6. **Post-trip rating** (25–30 hrs)
   - Rating screen: 1–5 star selector, optional comment text field (max 200 chars)
   - Both rider rating driver AND driver rate rider (mutual)
   - Blinded reveal: neither party sees rating until both submit OR 48-hour window closes
   - Submit button: calls `POST /api/v1/rides/{ride_id}/rating` with stars + comment
   - After submission: show "Rating submitted" message, "Book another ride" button
   - State: if driver hasn't rated yet, show "(Waiting for driver rating)" badge
   - Tests: rating submission, blinded reveal logic, comment validation

7. **Trip history** (8–12 hrs)
   - List of past trips: date, pickup/dropoff, fare, driver name, rating
   - Tap trip: see details (receipt, driver, route map, rating given)
   - "Report issue" button: flags trip for support review

8. **Recent locations cache** (8–10 hrs)
   - Store pickup/dropoff history locally (drift SQLite)
   - Max 10 recent locations
   - On location entry screen: show "Recent" tab with cached locations
   - Tap recent location: auto-fill field, no API call needed

**Web (Public Tracking View) (40–60 hours)**:

1. **Public trip tracking page** (40–60 hrs)
   - URL: `/public/rides/{ride_uuid}/{access_token}` (token-based auth, no login)
   - Shareable link from rider app
   - Display: map (MapLibre GL JS) with driver position + vehicle info
   - Show: driver name, vehicle (make/model/color), rating, ETA
   - Update driver position live via WebSocket (same as rider app)
   - No sensitive data: don't show exact dropoff until after trip (show area/neighborhood instead)
   - Responsive: works on phone browsers
   - React component, stateless (all state from WebSocket)
   - Security: token expires after trip completes or 1 hour (whichever is sooner)

**Testing**:
- E2E: rider enters locations → sees fare estimate → requests ride → matched to driver → sees driver approaching on map → driver arrives → trip ends → rider rates driver → payment processes
- Integration test: payment flow with Stripe test card
- Load test: 100 WebSocket subscribers getting location updates (device impact on backend)

**Completion criteria**:
- Rider can book a trip end-to-end
- Driver and rider can rate each other (blinded reveal working)
- Payment processes without errors
- Public tracking page works (sharable with non-app users)

---

### **Sprint 5 (Week 9-10): Rating System & Dispute Resolution**

**Goal**: Implement mutual rating, dispute handling, and automatic deactivation rules.

**Backend (70–90 hours)**:

1. **Rating schema & blinded reveal** (15–20 hrs)
   - rides table fields: rider_rating, rider_comment, driver_rating, driver_comment, ratings_blinded_until (timestamp)
   - Logic: both ratings stored when submitted, but hidden from each other until both rated OR 48 hours pass
   - Endpoint: `GET /api/v1/rides/{ride_id}` only returns rider/driver ratings to the rated party (not to the other party before window closes)
   - Query logic: if (current_time < ratings_blinded_until AND requester != rated_party): omit rating fields

2. **Rolling 500-trip average rating** (10–12 hrs)
   - New table: driver_profile.rating_avg (cached aggregate)
   - Nightly cron: calculate 500-trip rolling average for each driver
   - Query: most recent 500 complete trips, average driver_rating, round to 1 decimal
   - Used by: matching engine (filter drivers below 4.0), admin dashboard

3. **Rating dispute system** (20–25 hrs)
   - Endpoint: `POST /api/v1/rides/{ride_id}/rating-dispute`
   - Driver can dispute a low rating (1–3 stars) within 7 days of completion
   - Dispute reason (dropdown): "unfair", "false accusation", "driver error", "other"
   - Creates dispute_tickets record (id, ride_id, driver_id, reason, status: open, resolved)
   - Auto-exclude rule: if single-star rating from rider (no comment) AND driver_rating_avg > 4.0, auto-exclude this rating from average (retain in history)

4. **Human review queue** (18–22 hrs)
   - Admin endpoint: `GET /api/v1/admin/disputes/queue` (paginated)
   - Show: driver name, trip details (route, timestamp, fare), rider comment, driver dispute reason
   - Admin actions: "dismiss dispute" (rating stays), "uphold dispute" (rating excluded from average, logged)
   - Safety committee override: if driver has 3+ disputes in 30 days, auto-escalate to safety committee review (new status: escalated)
   - Audit log: all admin decisions with reason + timestamp

5. **Automatic compliance deactivation** (12–16 hrs)
   - Nightly cron: check all drivers' document expiry dates
   - 14-day grace for license: send push notification 14/7/1 day before expiry
   - On expiry: auto-set membership_status = compliance_hold (can't go online)
   - 30-day grace for background check: push at 30/14/1 day before expiry
   - On expiry: send automated FCRA final notice, set membership_status = terminated
   - Audit log: each auto-deactivation with expiry date + reason

6. **Rating threshold monitoring** (10–12 hrs)
   - If driver rating < 4.0: 30-day improvement notice (push + email)
   - Message: "Your rating has fallen below 4.0 stars. Here are resources to improve..." (link to coaching doc)
   - If still < 4.0 after 30 days: escalate to safety committee review (status: under_review)
   - Committee has 5-day SLA to make decision

7. **Safety committee workflow** (15–18 hrs)
   - New admin role: safety_committee_member (distinct from admin)
   - Committee can see: dispute queue, under_review drivers, deactivation appeals
   - Action: "sustain deactivation" or "overturn" with written decision
   - Decision logged to audit_log_entries with committee member signature + date
   - Overturned: set membership_status = active, send notification to driver with appeal decision

8. **Appeal workflow for deactivated drivers** (10–12 hrs)
   - Endpoint: `POST /api/v1/drivers/{driver_id}/appeal`
   - Driver can appeal termination within 30 days
   - Requires: written explanation + evidence (uploaded documents)
   - Creates appeal record, auto-notifies safety committee
   - Committee review: 5-day SLA, decision logged, driver notified

**Mobile (Driver app) (15–20 hours)**:

1. **Dispute flag on ride history** (8–12 hrs)
   - In trip history detail view: if driver_rating is 1–3 stars, show "Flag for review" button
   - On tap: show dispute reason options (unfair, false accusation, etc.)
   - Submit: calls `POST /api/v1/rides/{ride_id}/rating-dispute`
   - Confirm: show "Thanks for your feedback. Our team will review this."

2. **Rating threshold alert** (5–8 hrs)
   - If driver rating < 4.0: show persistent banner on home screen
   - Message: "Your rating is at [3.8]. Here's how to improve..." (link to resources)
   - Banner dismissible (can hide until tomorrow)

**Web/Admin (20–25 hours)**:

1. **Dispute queue dashboard** (12–15 hrs)
   - Show pending disputes with driver/trip context
   - Admin filter: by reason, by driver, by status
   - Bulk actions: "dismiss 5 disputes as group" (if similar reason)
   - Click dispute: modal with full trip context, rating comment, driver response
   - Decision: "uphold" or "dismiss" button + reason text field

2. **Safety committee dashboard** (8–10 hrs)
   - Separate view for safety committee role
   - Show: under_review drivers, escalated disputes, appeals
   - SLA tracking: days since escalation + warning if exceeding 5-day SLA
   - Decision form: checkboxes for decision + text field for reasoning + signature approval

**Testing**:
- E2E: driver flags a low rating dispute → admin reviews → dismisses → driver can see decision in app
- E2E: driver rating drops below 4.0 → push notification sent → stays low for 30 days → auto-escalates to committee
- Integration test: rolling average calculation correct after 500+ trips

**Completion criteria**:
- Rating system working (mutual, blinded reveal)
- Disputes reviewable by admin
- Auto-deactivation rules enforced (cron jobs running correctly)
- Safety committee can review and appeal cases

---

### **Sprint 6 (Week 11-12): Tax & Regulatory Compliance**

**Goal**: Implement 1099 generation, surcharge remittance, and compliance automation.

**Backend (60–75 hours)**:

1. **1099 tax info collection at onboarding** (12–15 hrs)
   - New endpoint: `POST /api/v1/drivers/tax-info`
   - Input: legal_name, tax_id (SSN/EIN), street_address, city, state, zip
   - Use Basis Theory for SSN tokenization (never store raw SSN)
   - Validate: legal name matches ID, tax_id is valid format (9 digits for SSN)
   - Return: tax_info_id (for use in 1099 generation)
   - Driver must accept W-9 terms before submission (stored as w9_accepted_at timestamp)

2. **1099-NEC generation (annual batch)** (20–25 hrs)
   - New admin endpoint: `POST /api/v1/admin/tax/generate-1099-batch`
   - Requires: tax_year (int, e.g., 2026), jurisdiction (optional)
   - Logic: for each driver_id with total_earnings > $600 in year:
     - Aggregate rides from Jan 1 – Dec 31 of tax_year
     - Sum driver_payout (not including tips, which are 1099-MISC, not NEC)
     - If total >= $600: generate 1099-NEC PDF with driver tax info + earnings total
     - Store pdf_path in tax_1099_documents table
   - Output: CSV report + PDF directory for manual S-corp adjustment if needed
   - Testing: mock driver earnings across jurisdiction, verify PDF generation

3. **IRS e-filing via Tax1099 API** (15–20 hrs)
   - Integrate Tax1099 SDK (or equivalent e-filing service)
   - New endpoint: `POST /api/v1/admin/tax/e-file-1099-batch`
   - Takes generated 1099-NEC PDFs, submits batch to IRS electronically
   - Receive: confirmation numbers, filing date, receipt for records
   - Error handling: if IRS validation fails (bad FEIN, duplicate SSN), return error with detail
   - Audit log: e-filing timestamp + number of 1099s submitted

4. **Surcharge remittance (Portland)** (10–12 hrs)
   - Portland per-trip surcharge: 0.50 per ride
   - New endpoint: `GET /api/v1/admin/surcharge-report?jurisdiction=portland_or&date_from=2026-05-01&date_to=2026-05-31`
   - Response: CSV with ride_id, trip_date, surcharge_amount
   - Admin downloads CSV, sums total, remits to PBOT by end of month
   - Audit log: remittance record with check number + date
   - Note: Portland may eventually automate this via API (future phase); for MVP, manual CSV is acceptable

5. **Quarterly tax reminder (nice-to-have)** (5–7 hrs)
   - Nightly cron: check calendar for end of Q1/Q2/Q3/Q4
   - 1 day before quarter end: send FCM push to all active drivers
   - Message: "Tax deadline tomorrow: remember to set aside 25% of earnings."
   - Not a legal requirement, but a member service

6. **W-9 re-signature (annual)** (8–10 hrs)
   - Nightly cron: check w9_accepted_at, look for anniversaries
   - 365 days after original: send push + in-app prompt: "Please re-sign W-9 for tax year 2027"
   - Driver must accept again to continue driving (soft gate, not hard stop; can drive for 7 days grace period)

**Mobile (Driver app) (20–30 hours)**:

1. **Tax info collection flow** (15–20 hrs)
   - New onboarding screen: "Tax Information"
   - Required fields: legal name, tax ID (SSN), address
   - Explain: "We need this to file 1099-NEC for your earnings" + link to tax FAQ
   - Validate: SSN format (9 digits), legal name (min 2 words or name + suffix)
   - Checkbox: "I accept the W-9 declaration" (required)
   - Submit: calls `POST /api/v1/drivers/tax-info`
   - Success: show confirmation screen + link to FAQ

2. **W-9 annual re-signature** (5–10 hrs)
   - When W-9 expires (365 days): show modal on app launch
   - Can't dismiss; must re-accept W-9 to proceed
   - After re-accept: can go online again
   - Tap "See original": open webview with original W-9 document

**Web/Admin (15–20 hours)**:

1. **1099 generation & filing dashboard** (15–20 hrs)
   - New admin page: `/admin/tax/1099-generation`
   - Button: "Generate 1099-NEC Batch"
   - Input: tax year (dropdown: 2025, 2026, 2027, etc.)
   - On click: run batch generation, show progress + summary
   - Display: "Generated 247 1099-NEC PDFs, $XX total reported earnings"
   - List of generated files with download link
   - Button: "E-file to IRS" (calls Tax1099 API)
   - Status: shows IRS confirmation number + receipt
   - Audit log: visible below (date, user, action, count)

2. **Surcharge remittance report** (5–8 hrs)
   - Page: `/admin/surcharge-remittance`
   - Filter: jurisdiction (Portland, Atlanta, etc.), date range
   - Download CSV button
   - Shows: total surcharge collected in period, per-driver breakdown (for verification)
   - Admin checks off "remitted to [jurisdiction]" with date + check number
   - Audit log: remittance records

**Testing**:
- Unit test: 1099-NEC PDF generation with mock driver earnings
- Integration test: IRS e-filing mock (validate payload format)
- E2E: driver enters tax info → 1 year passes → W-9 re-signature prompt appears

**Completion criteria**:
- 1099-NEC PDFs generated correctly for all drivers over $600 earnings
- IRS e-filing tested (mock or sandbox)
- Surcharge report accurate (manual verification with test data)
- W-9 re-signature flow working

---

### **Sprint 7 (Week 13): Integration Testing & Staging Hardening**

**Goal**: Run end-to-end scenarios, stress test backend, validate all integrations.

**Backend (30–40 hours)**:

1. **API contract testing** (10–12 hrs)
   - Ensure all endpoints have OpenAPI docs + schema validation
   - Use contract testing library (Pact or similar) to validate mobile/web requests match schema
   - Run against staging: mobile app hits real backend endpoints, confirms response shapes

2. **Integration test suite** (12–15 hrs)
   - End-to-end test: driver onboarding → go online → ride matched → trip completed → rating → payment
   - Integration test: Checkr webhook flow, 1099 generation, surcharge report
   - Load test: 50 concurrent drivers, 10 concurrent riders, WebSocket subscription stress
   - Database: use test database, reset after each test

3. **Error scenarios** (8–13 hrs)
   - Test failure paths: payment declined, Checkr integration timeout, WebSocket disconnect/reconnect
   - Verify error messages are user-friendly, not exposing internal errors

**Mobile (both apps) (20–30 hours)**:

1. **E2E test scenarios** (15–20 hrs)
   - Automated E2E tests (Patrol or similar Flutter test framework)
   - Scenario 1: driver onboarding → go online → receive offer → navigate → complete trip
   - Scenario 2: rider book trip → see driver → cancel → pay cancellation fee
   - Scenario 3: offline GPS buffering → trip continues → reconnect → data syncs
   - Run on iOS + Android emulators

2. **Manual testing** (5–10 hrs)
   - Smoke test: all screens load, navigation works, no crashes
   - Device matrix: iOS 15+, Android 11+
   - Network conditions: 4G, 3G, WiFi, airplane mode transitions

**Web/Admin (10–15 hours)**:

1. **Admin portal smoke test** (10–15 hrs)
   - Load all admin pages (compliance, disputes, 1099 generation, surcharge)
   - Verify data displays correctly
   - Click all admin actions (update status, override metadata, approve/deny disputes)
   - Check audit logs are written

**Testing**:
- Integration test suite passes 100% (no flaky tests)
- Load test: backend handles 50 drivers + 10 riders without latency spikes
- E2E passes on iOS + Android

**Completion criteria**:
- All integration tests passing
- Load test validates backend can handle launch day traffic
- No crashes on both mobile platforms
- Admin portal fully functional

---

### **Sprint 8 (Week 14-15): Documentation, Store Submission, Launch Prep**

**Goal**: Finalize documentation, submit apps to stores, prepare for user launch.

**Backend (5–10 hours)**:

1. **API documentation** (5–10 hrs)
   - OpenAPI/Swagger spec complete for all endpoints
   - Deployment guide: how to set environment variables, run migrations, configure Stripe/Checkr/Tax1099
   - Troubleshooting guide: common errors + solutions

**Mobile (both apps) (40–50 hours)**:

1. **App Store iOS submission** (20–25 hrs)
   - Build for App Store (archive in Xcode, submit via App Store Connect)
   - Privacy Nutrition Label: declare location, identifiers, financial info
   - Review notes: explain TNC driver/rider model, background location justification
   - TestFlight internal track for user testing (first 48 hours)
   - Wait for Apple review (typically 24–48 hours)
   - Fix any rejections (usually rare for rideshare apps; most issues flagged in pre-review)

2. **Google Play submission** (15–20 hrs)
   - Build for Play Store (APK or App Bundle via Flutter build)
   - Play Store console: complete Data Safety section
   - Store listing: write description, keywords, screenshots, privacy policy URL
   - Internal test track first (5 days)
   - Staged rollout: 5% → 25% → 100% over 5 days (safe launch)
   - Expect review time: 2–4 hours for Google (faster than Apple)

3. **App Store onboarding assets** (5–5 hrs)
   - In-app tutorial: first-time user onboarding
   - Screenshots: 4 per platform (registration, home, active trip, earning)
   - Translations: defer to Phase 4 (English only for MVP)

**Web/Admin (5–10 hours)**:

1. **Admin onboarding guide** (5–10 hrs)
   - How to configure jurisdiction (add Portland/Atlanta)
   - How to approve drivers (compliance, background check workflow)
   - How to monitor/resolve disputes
   - How to generate + file 1099s
   - Video walkthrough (10 min per workflow)

2. **Privacy Policy + Terms of Service** (included in legal outside orchestration scope)
   - Ensure app stores have links to privacy policy + ToS
   - ToS should include: mutual rating agreement, dispute resolution, deactivation policies

**Operations (10–15 hours)**:

1. **Runbook: launch day** (5–8 hrs)
   - Monitoring: what metrics to watch (API latency, error rate, WebSocket connections)
   - On-call schedule: who responds to outages during launch week
   - Rollback plan: if critical bug found, how to revert app submission

2. **Monitoring/alerting setup** (5–7 hrs)
   - Log aggregation: Datadog or similar, store all request/response logs
   - Alerts: if error rate > 5%, if API latency > 500ms, if WebSocket connections drop 50%+
   - Dashboard: live trip count, active drivers, payment success rate

**Testing**:
- Final E2E: launch day scenario (100+ concurrent riders, 50+ drivers)
- App Store + Play Store submission validation (no rejected builds)
- Admin portal fully documented + tested

**Completion criteria**:
- Both apps submitted to stores (in review)
- Admin documentation complete + tested
- Monitoring + alerting deployed to production
- Runbook approved by cooperative leadership

---

## Schedule Summary

| Sprint | Weeks | Focus | Deliverables |
|---|---|---|---|
| 1 | 1–2 | Compliance engine | Schema, Checkr setup, jurisdiction config |
| 2 | 3–4 | Checkr integration & document upload | Document storage, OCR, FCRA flow, driver upload UI |
| 3 | 5–6 | Go-online gate & driver features | Navigation, GPS offline, earnings dashboard, compliance gate |
| 4 | 7–8 | Rider app & payments | Booking, matching, live tracking, payment, rating |
| 5 | 9–10 | Rating & disputes | Mutual rating, dispute queue, auto-deactivation, appeals |
| 6 | 11–12 | Tax compliance | 1099 generation, e-filing, surcharge remittance, W-9 |
| 7 | 13 | Integration testing | Contract tests, E2E scenarios, load testing |
| 8 | 14–15 | Launch prep | Store submission, documentation, monitoring |

**Total**: 14–15 weeks at 3-person team (1 backend, 1 mobile, 1 web + admin + 0.5 DevOps).

---

## Resource Allocation by Role

### Backend Engineer (Python/FastAPI, PostgreSQL)

**Sprints 1–2**: Compliance + Checkr (~150 hours)
**Sprints 3–4**: Go-online gate, earnings API, payment split (~90 hours)
**Sprints 5–6**: Rating system, 1099 generation (~130 hours)
**Sprint 7**: Integration testing, error scenarios (~35 hours)
**Sprint 8**: Documentation, monitoring setup (~10 hours)

**Total**: ~415 hours (10–11 weeks at 40 hours/week)

### Mobile Engineer (Flutter, driver + rider apps)

**Sprint 1**: Minimal (0 hours)
**Sprint 2**: Document upload UI (~50 hours)
**Sprint 3**: Navigation, GPS, earnings dashboard (~100 hours)
**Sprint 4**: Rider app MVP (~150 hours)
**Sprint 5**: Rating + dispute flag (~20 hours)
**Sprint 6**: Tax info collection (~25 hours)
**Sprint 7**: E2E testing (~25 hours)
**Sprint 8**: Store submission (~40 hours)

**Total**: ~410 hours (10–11 weeks at 40 hours/week)

### Web/Admin Engineer (React/TypeScript)

**Sprint 1**: Minimal (0 hours)
**Sprint 2**: App Store / Play Store prep (~15 hours)
**Sprint 3**: Compliance dashboard (~40 hours)
**Sprint 4**: Public tracking web (~50 hours)
**Sprint 5**: Dispute + committee dashboards (~25 hours)
**Sprint 6**: 1099 + surcharge dashboards (~20 hours)
**Sprint 7**: Admin smoke test (~15 hours)
**Sprint 8**: Onboarding guide, final docs (~10 hours)

**Total**: ~175 hours (4–5 weeks at 40 hours/week)

### DevOps Engineer (0.5 FTE)

**Throughout**: CI/CD pipeline, Docker, Kubernetes, monitoring (~80–100 hours total)

**Grand Total**: ~680–800 hours (19–22 engineer-weeks)

---

## Governance Decisions Checklist

Before Sprint 1 kickoff, the cooperative must decide:

- [ ] **Platform fee %** (recommended: 20–25% for cooperative operations + fleet insurance)
- [ ] **Surcharge amount** (Portland only: recommend $0.50 per trip for PBOT regulatory fee)
- [ ] **TNC fee allocation** (of platform fee: X% to insurance, Y% to operations, Z% to member dividend fund)
- [ ] **WAV driver strategy** (mandatory? recommended? financial incentives? Portland: 5% min required)
- [ ] **Cancellation fee policy** (recommended: 50% of estimated fare if driver en route, $0 if within 2-min grace)
- [ ] **SSN tokenization provider** (Basis Theory vs. Stripe Identity; recommend Basis Theory for cost)

---

## Nice-to-Have Features (Post-Launch)

If timeline allows before launch, consider adding (in priority order):

1. **Destination filter** (2 uses per shift) — ~12–18 hours
2. **Guest payment** (card entry each trip) — ~10–15 hours
3. **Recent locations autocomplete** — ~8–10 hours
4. **Quarterly tax reminder push** — ~4–6 hours
5. **CSV export for driver earnings** — ~8–12 hours

Each of these is independently shippable as a hotfix after Day 1 launch without affecting core functionality.

---

## Known Risks & Mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Checkr integration delays | Blocks Sprint 2; Checkr API may be slow/unreliable | Start Checkr API integration in Sprint 1 (parallel work); use mock responses for testing |
| Payment processing errors | Lost revenue, customer complaints | Stripe has 99.9% uptime SLA; test payment failures extensively in Sprint 7 |
| WebSocket stability under load | Live driver tracking fails at scale | Load test in Sprint 7 with 50+ concurrent subscribers; auto-reconnect logic in mobile apps |
| iOS App Store review rejection | 1-week delay to launch | Include clear TNC model explanation in review notes; expect 24–48 hour review time |
| Database query performance | API latency spikes as data grows | Add indexes to driver_profiles (membership_status, license_expiry), rides (trip_state, driver_id) |
| Regulatory compliance gaps | Fail to launch in target city | Engage with Portland/Atlanta regulators early (Sprints 1–2); compliance_tech_checklist.md covers known gaps |

---

## Post-Launch Roadmap (Phase 4)

Phase 4 features deferred from MVP (estimated 150–200 hours, 4–5 weeks at 3-person team):

1. **Scheduled rides** — advance booking, driver acceptance window
2. **Ride pooling** — match multiple passengers, resequence pickups/dropoffs
3. **In-app wallet / prepaid balance** — requires money transmitter license (legal step first)
4. **Multi-language support** (i18n infrastructure ready in Phase 3; translations Phase 4)
5. **Batch dispatch optimization** — VRP solver for 100+ concurrent riders
6. **Demand prediction** — surge pricing, zone heat maps
7. **Driver cooperative governance voting** — in-app voting on fees, policies
8. **Accessibility: WAV vehicle filtering** — if needed for Portland/Atlanta compliance

---

## Success Metrics for MVP Launch

- **Day 1**: Zero critical bugs (payment failures, app crashes)
- **Week 1**: 50+ completed trips, 90%+ payment success rate
- **Week 2**: 200+ completed trips, 95% payment success rate, avg Sharpe ratio = 1.0 (earnings = time invested)
- **Month 1**: 1,000+ completed trips, positive member feedback on governance + transparency

---

## Conclusion

This roadmap provides a concrete execution plan for Phase 3 MVP: 14–15 weeks at 3 engineers, broken into 2-week sprints respecting dependencies, with clear deliverables per sprint. The path is critical (compliance → dispatch → booking → payment → rating → tax) and each sprint unblocks the next.

**Ready for developer assignment and sprint planning kickoff upon cooperative governance decisions (5 governance decisions required, ~1 week lead time for legal/policy alignment).**

Key success factor: strict adherence to dependency order. Attempting to parallelize rating + payment before dispatch/matching is complete will create rework and delays.
