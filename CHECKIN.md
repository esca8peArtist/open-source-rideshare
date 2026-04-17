# Check-in Briefing

> This file is updated by the orchestrator before going idle.
> When you drop in, read this first. It's designed to get you up to speed in under 5 minutes.
> After reviewing, clear the "Since Last Check-in" section and leave notes in "Your Notes" for the orchestrator to pick up.

---

## Since Last Check-in

**Period**: 2026-04-18
**Sessions run**: 310

### Accomplished (Session 310)

#### open-source-rideshare — Fare preview / surge pricing transparency COMPLETE (commit `c1ca027`)

New public endpoint: `GET /pricing/fare-preview` — no authentication required. Riders see the full pricing breakdown before confirming a trip, with both surge signals disclosed separately.

**What's shown**:
- `surge_zone`: Admin-defined geographic zones (airports, stadiums) — zone name + percentage
- `demand_pricing`: Real-time supply/demand ratio — demand count, driver count, percentage, cap
- `time_of_day_multiplier`: Operator-scheduled adjustments (if any)
- `combined_multiplier`: Product of all signals
- `pricing_summary`: Plain-English explanation ("Fares are 38% higher. Reasons: Downtown Core zone (+20%); high demand (+15%): 8 requests, 1 available driver.")
- `is_surge_active`: Boolean flag for quick UI checks

**Architecture**:
- `fare_preview.py` service: OSRM route lookup with Haversine fallback; graceful Redis/DB degradation (defaults to 1.0× if unavailable)
- Pure helpers `_haversine_km`, `_estimate_duration_min`, `build_pricing_summary` — independently unit-testable
- `FarePreviewResponse` schema with nested `SurgeZoneInfo`, `DemandPricingInfo`, `FareComponentsResponse`

**Why this matters**: Existing `/rides/estimate` requires auth and doesn't check admin surge zones. This is the rider-facing version that works pre-login and shows both surge types — the core cooperative transparency promise.

- 38 new tests — **3,669 total unit-passing**

---

### Accomplished (Sessions 306–309, archived)

#### open-source-rideshare — No-show rate tracking + rider auto-rebooking COMPLETE (commit `f83fa00`)

Two paths for handling driver no-shows:

**Manual report** — `POST /rides/{ride_id}/report-driver-no-show`. Available when ride is in MATCHED, DRIVER_EN_ROUTE, or ARRIVED. One report per ride (409 if already done). Result: cancelled with `DRIVER_NO_SHOW` category, Stripe refund issued on any completed payment, push + SMS to rider, driver returned to available pool.

**Automated detection** — new `detect_driver_no_shows()` in scheduler loop (every 30s). Finds ARRIVED rides where `arrived_at` is older than `driver_no_show_threshold_minutes` (default 15). Same cancel + refund + notify path.

**Bonus**: `arrived_at` timestamp is now set every time a driver marks ARRIVED — was previously untracked. Useful for analytics and required for the automated detector.

- 43 new tests — **3,571 total passing**
- Config: `OPENRIDE_DRIVER_NO_SHOW_THRESHOLD_MINUTES` (default 15)

---

### Accomplished (Session 306)

#### open-source-rideshare — Structured cancellation categories + rider cancel rate tracking COMPLETE (commit `5830c3b`)

Cancellation flow now has three improvements:

**Structured cancellation reasons** — `CancellationCategory` enum (13 values). Riders pick from WRONG_PICKUP, WAIT_TOO_LONG, FOUND_OTHER_RIDE, PLANS_CHANGED, DRIVER_NOT_ACCEPTABLE, PRICE_TOO_HIGH, SAFETY_CONCERN, OTHER. Drivers pick from VEHICLE_ISSUE, RIDER_NO_SHOW, UNABLE_TO_LOCATE, EMERGENCY, DRIVER_OTHER. Free-text `reason` note still accepted alongside. Both stored on the ride row (`cancellation_category`, `cancelled_by`).

**Rider cancel rate tracking** — new `rider_cancellation_stats` table (one row per rider). Tracks `total_rides_requested`, `total_cancellations`, `cancellations_in_grace_period`, `cancellations_with_fee`, `cancellation_rate`. Updated fire-and-forget on every rider cancel — never blocks the response.

**New endpoints**:
- `GET /riders/me/cancel-stats` — rider views own stats (returns zeroed defaults if no rides yet)
- `GET /admin/riders/{rider_id}/cancel-stats` — admin views any rider (404 if no row)

**37 new tests** — **3,528 total unit-passing**

### Accomplished (Session 305)

#### open-source-rideshare — Trip sharing link COMPLETE (commit `57e6f6d`)
Riders can now generate a shareable link (`POST /safety/share`) that lets friends and family track the ride in real-time — no login required to view. The shared view now includes **live driver GPS coordinates** (lat/lng/updated_at) pulled from `DriverProfile.current_location`, so the watcher sees exactly where the driver is as location updates come in.

New functionality over the existing stub:
- `SharedTripView` extended with `driver_lat`, `driver_lng`, `driver_location_updated_at`
- `GET /safety/share` — list caller's active (non-expired) share tokens
- `DELETE /safety/share/{token}` — revoke a token (creator only; 403 for wrong user, 404 if missing)
- `get_shared_trip_detail` service — ride + live driver coords in one DB round-trip
- `revoke_trip_share_token` / `list_trip_share_tokens` service functions
- **18 new tests** — **3,491 total unit-passing**

### Accomplished (Session 304)

#### open-source-rideshare — Driver pickup verification COMPLETE (commit `f4a7a80`)
Rider can now confirm the driver's photo and vehicle plate match before entering the vehicle. Only available when the driver has marked the ride ARRIVED. A mismatch is logged and flagged for ops review — but the rider retains full autonomy over whether to enter. Subsequent calls overwrite the previous result (last-write-wins) so the rider can correct a mistaken tap.

- `app/models/ride.py` — `pickup_verification_at`, `driver_photo_confirmed`, `plate_confirmed` columns
- `app/db/migrations/versions/i3j4k5l6m7n8_add_pickup_verification.py` — migration
- `app/schemas/ride.py` — `PickupVerificationRequest`, `PickupVerificationResponse`
- `app/services/pickup_verification.py` — `verify_pickup()` service
- `app/api/v1/rides.py` — `POST /rides/{ride_id}/verify-pickup`
- **18 new tests** — **3,473 total unit-passing**

### Accomplished (Session 303)

#### open-source-rideshare — TRIP_END trusted contact notification COMPLETE (commit `a1ac332`)
Closed the last gap in trusted contact lifecycle coverage. `complete_ride` now calls `send_trusted_contact_notifications(TRIP_END)` — fire-and-forget, never blocks ride completion.

- `app/api/v1/rides.py` — TRIP_END wired into `complete_ride` after audit, same pattern as TRIP_START
- **2 new tests** — **3,455 total unit-passing**

All three trusted contact notification types are now wired: PANIC_ALERT (panic endpoint), TRIP_START (start_ride), TRIP_END (complete_ride).

### Accomplished (Session 302)

#### open-source-rideshare — Route deviation detection COMPLETE (commit `3125230`)
When a driver submits a location update during an IN_PROGRESS ride, the platform now checks cross-track distance (perpendicular distance from driver's position to the pickup→dropoff line). If deviation exceeds 1 km and the ride hasn't already been flagged, the rider receives a push+SMS alert and the flag is set (idempotent — fires once per ride).

- `route_deviation.py`: cross-track geometry + `check_and_notify_deviation` fire-and-forget
- `Ride.route_deviation_flagged_at` column + migration
- `GET /{ride_id}/route-deviation-status` — rider/driver-scoped deviation check endpoint
- `ROUTE_DEVIATION` NotificationType in ride_types (respects rider preferences)
- `notify_route_deviation` dispatcher + `route_deviation` template (push+SMS)
- `beckn-protocol.md`: Beckn/ONDC interoperability research (design notes for community)
- **30 new tests** — **3,449 total unit-passing**

#### open-source-rideshare — Trusted contact notification wiring COMPLETE (commit `ede14a4`)
`send_trusted_contact_notifications` existed but was never called. Closed two gaps:

- Panic button (`POST /riders/me/panic`) → now fires `PANIC_ALERT` to contacts with `notify_on_panic=True` — fire-and-forget, failure logged but never blocks the alert
- Trip start (`POST /rides/{id}/start`) → now fires `TRIP_START` to contacts with `notify_on_trip_start=True` — fire-and-forget, silent failure so ride is never blocked

**4 new tests** — **3,453 total unit-passing**

### Accomplished (Sessions 300–301)

#### open-source-rideshare — Driver live location + ride status notifications COMPLETE
- Driver location: `PUT/GET /drivers/me/location`, `GET /riders/nearby-drivers`, admin views (42 tests)
- Ride status notifications: 3 new types (RIDE_IN_PROGRESS, RIDE_ASSIGNED, RIDE_COMPLETED_DRIVER), 3 templates, 3 dispatchers, hooks in start/accept/complete endpoints (45 tests)

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

**op-ed submission — action needed by April 22 (5 days away)**
"Six Weeks to Save Five Million People's Health Insurance" is ready. File: `projects/resistance-research/publications/op-ed-healthcare-june2026-deadline.md`. Pitch paragraph is at the top. June 1 CMS deadline makes the timing real.

**open-source-rideshare — GitHub push permission**
`feature/rider-emergency-safety` now has 13 sessions of work locally (3,453 tests). Push via: (a) grant Pi GitHub write access, or (b) `git push origin feature/rider-emergency-safety` from a terminal where you have auth.

**Stockbot — paper trading cycle logs (ongoing)**
Paper trading live since April 14. Drop cycle logs or a Trading page screenshot in INBOX.md to unblock model performance assessment.

**April 20 results framework**
`projects/resistance-research/monitoring/2026-04-20-results-framework.md` is pre-drafted. After April 20 events land (CAPE Phase 1, Abrego Garcia DOJ brief), drop outcomes in INBOX.md — next session fills the framework.

---

### Suggested Priorities (Next Session)
1. **mfg-farm**: User runs test print + photographs → Etsy listing goes live.
2. **resistance-research**: Fill April 20 results framework (Apr 20 evening — CAPE Phase 1 + Abrego Garcia DOJ brief results).
3. **open-source-rideshare**: Next feature — driver live location polling (rider sees driver moving on map pre-pickup) OR admin surge analytics (when/where surge fired, correlation with ride volume).
4. **stockbot**: Share cycle logs to unblock model performance assessment.

---

### History

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
