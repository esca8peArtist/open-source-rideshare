# Check-in Briefing

> This file is updated by the orchestrator before going idle.
> When you drop in, read this first. It's designed to get you up to speed in under 5 minutes.
> After reviewing, clear the "Since Last Check-in" section and leave notes in "Your Notes" for the orchestrator to pick up.

---

## Since Last Check-in

**Period**: April 15, 2026
**Sessions**: 129–144

### Accomplished (Session 144)

#### open-source-rideshare — Lost and Found System COMPLETE (commit `cb508dd`)
Riders leave items in rideshare vehicles constantly. This is the canonical feature that builds rider trust post-ride.

- **LafLostItemReport** (rider-submitted): ride_id (optional), description, category (electronics/clothing/documents/bags/jewelry/keys/other), date_lost, contact_preference; statuses: open/matched/returned/closed_no_match
- **LafFoundItemReport** (driver-submitted): ride_id (optional), description, category, storage_location; statuses: pending_match/matched/returned_to_owner/discarded
- `Laf` prefix used — pre-existing `lost_found` module was already in the codebase; this is the new, complete system
- Driver found-items at `/drivers/me/found-items-v2` — path conflict with legacy route
- **Admin workflow**: admin matches a lost + found pair → mark-returned (both resolved) or discard (driver held too long, no claim) or close-lost (no match found)
- State-transition guards prevent double-processing; ride-ownership validation when ride_id provided
- Migration: y1z2a3b4c5d6 (laf_lost_item_reports + laf_found_item_reports, 4 enum types, deferred cross-FK)
- **68 new tests** (36 service unit passing + 32 API integration skip — no live DB, consistent with rest of suite); **Total: 4,419 tests passing** (up from 4,383), 0 failing

### Accomplished (Session 143)

#### open-source-rideshare — Driver Minimum Earnings Guarantee COMPLETE (commit `8c7f28a`)
- **67 new tests; Total: 4,383 tests passing** (up from 4,316), 0 failing

### Accomplished (Session 142)

#### open-source-rideshare — Cooperative Member Dividend / Profit-Sharing COMPLETE (commit `b827b33`)
- **63 new tests; Total: 4,316 tests passing** (up from 4,253), 0 failing

### Accomplished (Session 141)

#### open-source-rideshare — Cooperative Governance / Driver Voting System COMPLETE (commit `348e002`)
- **76 new tests; Total: 4,253 tests passing** (up from 4,177), 0 failing

### Needs Your Input

#### open-source-rideshare — PR: Sessions 129–144 (many features)
Branch: `feature/corporate-business-accounts` — **4,419 tests passing**. Features since last push:
- Lost and Found System (cb508dd) ← new
- Driver Minimum Earnings Guarantee (8c7f28a)
- Cooperative Member Dividend / Profit-Sharing (b827b33)
- Cooperative Governance / Driver Voting System (348e002)
- Driver Bonus / Quest Programs (eab25d2)
- Driver Tax Reporting / 1099-NEC (323efef)
- Public Service Coverage API (8600e0e)
- Cooperative Transparency and Member Equity (0d9a8fc)
- Rider Referral Program (61c921e)
- Ride Receipts + Feedback APIs (a254483)
- Driver Vehicle Maintenance Tracking (9352bf6)
- Driver Document Expiry Alerts (1484765)
- Accessibility / WAV Certification (8e20c40)
- Driver Payout / Disbursement (373168d)
- Rider Loyalty Rewards (42b393f)
- Driver Subscription Plans (479219c)
The SSH key (`esca8peArtist`) can't push to `SuperClaude-Org/SuperClaude_Framework`. Push manually when ready.

Note from Session 135: `rides.py` has duplicate receipt/feedback routes superseded by dedicated routers — cleanup after merge.
Note from Session 139: Tax documents reference driver earnings via DriverPayout model. `calculate_annual_earnings` returns 0 for drivers with no completed payouts (correct — no 1099 for $0 earnings).

---

**mfg-farm — Business plan is ready; next action is your call**
The full business plan is at `projects/mfg-farm/business-plan.md`. To launch:
- **Commission route**: Fiverr/Upwork for cable management parametric family ($200–350, own the STLs). Fastest.
- **Build route**: Fusion 360 learning path (free for hobbyists). Slower but builds long-term design margin.
Drop the direction in INBOX.md.

**Stockbot — paper trading cycle logs (ongoing)**
Paper trading live since April 14. No autonomous path without `STOCKBOT_API_KEY` in env. Share cycle log output in INBOX.md or drop a screenshot path from the Trading page to unblock.

**open-source-rideshare — SSH key**
`esca8peArtist` can't push to `SuperClaude-Org/SuperClaude_Framework`. Push manually or confirm correct credentials.

**resistance-research — what next?**
`democratic-renewal-proposal.md` is publication-ready. Let me know if you want PDF export, sharing, or to file it.

---

### Suggested Priorities (Next Session)
1. **mfg-farm**: User decides commission vs. build route → operational checklist setup
2. **stockbot**: Share cycle logs to unblock model performance assessment
3. **open-source-rideshare**: Next feature TBD (4,419 tests, local commits ready)
4. **resistance-research**: No autonomous work remaining unless user directs a new thread

---

---

### History

#### Accomplished (Session 137)
- **open-source-rideshare**: Cooperative Transparency and Member Equity COMPLETE (commit `0d9a8fc`). Public platform stats, driver equity profile, quarterly transparency reports, admin report generation. 48 unit tests. Total: 4,036 passing.

#### Accomplished (Sessions 135–136)
- **open-source-rideshare**: Rider Referral Program COMPLETE (commit `61c921e`). 4 endpoints; 41 unit tests; 3,988 passing.
- **open-source-rideshare**: Ride Receipts and Feedback APIs COMPLETE (commit `a254483`). 6 endpoints; 51 unit tests; 3,947 passing.

#### Accomplished (Session 134)
- **open-source-rideshare**: Driver Vehicle Maintenance Tracking COMPLETE (commit `9352bf6`). 41 unit tests. 3,896 passing.

#### Accomplished (Session 133)
- **open-source-rideshare**: Driver Document Expiry Alert System COMPLETE (commit `1484765`). 47 unit tests. 3,855 passing.

#### Accomplished (Session 132)
- **open-source-rideshare**: Accessibility / WAV Certification System COMPLETE (commit `8e20c40`). 59 unit tests. 3,808 passing.

#### Accomplished (Session 131)
- **open-source-rideshare**: Driver Payout / Disbursement System COMPLETE (commit `373168d`). 65 unit tests. 3,749 passing.

#### Accomplished (Session 130)
- **open-source-rideshare**: Rider Loyalty Rewards Programme COMPLETE (commit `42b393f`). 58 unit tests. 3,684 passing.

#### Accomplished (Session 129)
- **open-source-rideshare**: Driver Subscription / Flat-Fee Plan COMPLETE (commit `479219c`). Weekly ($49) / monthly ($149) flat-fee; 0% commission while active. 8 endpoints; 49 unit tests. Total: 3,626 passing.

#### Accomplished (Session 128)
- **open-source-rideshare**: Driver/Rider Blocklist System COMPLETE (commit `85834f9`). Either party can block specific counterparties; matching engine checks both directions. 4 endpoints. 34 tests. Total: 3,577 passing.

#### Accomplished (Session 127)
- **open-source-rideshare**: Rider Fare Dispute & Refund System COMPLETE (commit `bd40069`). Riders submit fare disputes on completed rides; admins approve/partial/deny with refund amounts. 8 endpoints (4 rider, 4 admin). 44 unit tests. Total: 3,543 passing.

#### Accomplished (Session 126)
- **open-source-rideshare**: Corporate/Business Accounts COMPLETE (commit `aa9ac92`). Companies create accounts with per-ride/monthly limits, invite employees, employees use corporate billing on rides. 9 admin endpoints + 2 rider endpoints. 75 unit tests. Total: 3,499 passing.

#### Accomplished (Session 125)
- **open-source-rideshare**: Scheduled Rides COMPLETE (commit `e956cf2`). POST/GET/DELETE /riders/me/scheduled-rides, driver accept/decline, admin overview. 63 unit tests. Total: 3,424 passing.

#### Accomplished (Session 123)
- **open-source-rideshare**: Surge Price Lock COMPLETE (commit `0dbf3c3`). POST/GET/DELETE /riders/me/surge-lock; riders lock current demand multiplier for 5 min before booking; single-use per rider; lock consumed on ride creation. 36 unit tests. Total: 3,323 passing.

#### Accomplished (Session 122)
- **open-source-rideshare**: Driver Wait Time Billing COMPLETE (commit `a2e894c`). driver_arrived_at stamped on /arrived; GET /rides/{id}/wait-time live status (elapsed, grace remaining, $0.25/min fee, no-show flag); wait_time_fee auto-added to actual_fare on /complete. 30 unit tests. Total: 3,284 passing.

#### Accomplished (Session 121)
- **open-source-rideshare**: Driver Career Tier System COMPLETE (commit `000ffcf`). Bronze/Silver/Gold/Platinum tiers from lifetime rides/rating/acceptance. GET /drivers/me/tier + POST refresh + admin endpoints. 38 unit tests. Total: 3,257 passing.

#### Accomplished (Session 120)
- **open-source-rideshare**: Driver Earnings Goals COMPLETE (commit `ee7ecb2`). GET /drivers/me/earnings-goal returns live progress (current_earnings, percentage, on_track, remaining); PUT upserts goal; DELETE removes. 37 unit tests. Total: 3,219 passing.
- INBOX: User asked to reduce Discord notifications to ~2hr cadence only.

#### Accomplished (Session 119)
- **open-source-rideshare**: Driver Referral Program COMPLETE (commit `424f107`). GET /drivers/me/referral (code + summary), POST /drivers/me/referral/apply, GET /drivers/me/referral/referred, GET /admin/referrals/stats. 38 unit tests. Total: 3,182 passing.

#### Accomplished (Session 118)
- **open-source-rideshare**: Admin Bulk Notifications COMPLETE (commit `d61c5f5`). POST /admin/notifications/broadcast — sends platform-wide notifications to all/riders/drivers; push/sms/email channels; BroadcastRecord persists every broadcast; audit-logged. GET /broadcasts (paginated history) + GET /broadcasts/{id}. 34 unit tests. Total: 3,144 passing.

#### Accomplished (Session 117)
- **open-source-rideshare**: Zone Boundary Suggestions COMPLETE (commit `5ee482a`). GET /admin/surge-zones/suggestions — greedy BFS clustering on trip heatmap; outputs center_lat/lon, radius, multiplier 1.2–2.0, confidence, overlap detection. 49 unit tests. Total: 3,110 passing.

#### Accomplished (Session 116)
- **open-source-rideshare**: Driver Earnings P&L Summary COMPLETE (commit `e8af5e5`). GET /drivers/me/earnings-summary — consolidated P&L combining ride earnings (gross - fees + tips) with expense log. Flexible date range; weekly/monthly breakdown. 45 unit tests. Total: 3,061 passing.

#### Accomplished (Session 115)
- **open-source-rideshare**: Surge Zone Auto-Tuning COMPLETE (commit `908432e`). GET /admin/surge-zones/auto-tune (preview) + POST /admin/surge-zones/auto-tune/apply. Algorithm: demand_ratio >= 2.0 → +0.20, >= 1.5 → +0.10, <= 0.5 → -0.10, else no_change; clamped to [1.0, 10.0]. 50 unit tests. Total: 3,016 passing.

#### Accomplished (Session 114)
- **open-source-rideshare**: Rider Busy Hours Indicator COMPLETE (commit `ae2e408`). `GET /api/v1/rides/busy-hours` — 24 hourly slots with demand_level (low/medium/high/peak), typical_wait_minutes, is_current_hour. Demand classified relative to peak-hour volume. Optional day_of_week filter. 27 unit + 16 integration tests. Total: 2,966 passing.

#### Accomplished (Session 113)
- **open-source-rideshare**: Demand-By-Hour Analytics COMPLETE (commit `ef08aa8`). Admin endpoint `GET /api/v1/admin/analytics/demand-by-hour` — 24 hourly slots with total/completed/cancelled rides, avg fare, avg wait. Filters: start_date, end_date, day_of_week. 20 unit + 25 integration tests. Total: 2,939 passing.

#### Accomplished (Session 112)
- **open-source-rideshare**: Platform Admin Config API COMPLETE (commit `aec6101`). Database-backed key/value config store; 6 categories, 5 value types; 21 seeded defaults; 4 admin endpoints with audit trail. 28 unit + 30 integration tests. Total: 2,919 passing.

#### Accomplished (Session 111)
- **open-source-rideshare**: Driver Performance Trends COMPLETE (commit `f3a7125`) — `GET /api/v1/drivers/{driver_id}/performance/trends`; weeks param 1–52; delta fields null on first period, numeric thereafter; oldest-to-newest ordering. 18 unit + 15 integration tests. Total: 2,891 passing.

---

### History

#### Accomplished (Session 110)
- **open-source-rideshare**: Admin Trip Heatmap COMPLETE (commit `93ce85a`) — `GET /api/v1/admin/analytics/trip-heatmap`; precision param (1–4); pickup + dropoff aggregation merged by grid cell; sorted by total_activity descending. 20 unit + 27 integration tests. Total: 2,873 passing.

---

#### Accomplished (Sessions 109)
- **resistance-research**: Publication-ready formatting pass COMPLETE — removed 1,200+ word changelog, added revision history appendix, fixed "Twenty Domains" → "Twenty-Two Domains", standardized 113 subheadings. Commit `b467e0b`.
- **open-source-rideshare**: Admin ride export COMPLETE — `GET /api/v1/admin/rides/export`, 15-column CSV, StreamingResponse, admin-auth gated, 53 tests. Total 2,853 passing. Commit `28a70be`.

---

#### Accomplished (Session 108)
- **resistance-research**: Quality review pass COMPLETE — 9 targeted edits to `democratic-renewal-proposal.md` (Domain 1 registration gap, Domain 2 CPI/tariff-trading, Domain 5 lowest-taxed G7, Domain 6 V-Dem/judge threats, Domain 15 EPA collapse, Domain 17 union density/pay gap, Domain 22 GI Bill/FHA). `executive-summary.md` synced. Commit `ee5aa5b`.
- **open-source-rideshare**: Driver expense tracking COMPLETE — DriverExpense model, 7-category enum, CRUD + summary endpoints, Alembic migration, 52 tests. Total 2,828 passing. Commit `0aad9ea`.

---

#### Accomplished (Session 107)
- **resistance-research**: Domain Deepening Library COMPLETE (22/22). Confirmed `national-security-evidence.md` (648 lines) as Domain 19 deepening. Committed `4045559`.
- **mfg-farm**: Comprehensive Business Plan COMPLETE (1,002 lines) — 5-product launch catalog, full cost model, design strategy, machine milestones, 90-day checklist, 6-risk matrix. Committed `b651e0a`.
- **open-source-rideshare**: Driver Revenue Projections + Earnings Comparison (48 tests; 2,802 total). Committed `61beb3d`.

#### Accomplished (Sessions 105–106)
- **mfg-farm**: Market research COMPLETE (861 lines) — top picks: cable management, flexi animals, planters, pet memorials, gaming organizers. Etsy June 2025 policy (original designs only) documented as existential constraint. Machine sequencing, fee reality, IP risk analysis.
- **resistance-research**: Domain 5 Fiscal Reform COMPLETE (~450 lines) — 400 wealthiest families pay lower effective rate than bottom 50%; buy-borrow-die ($40–50B/yr); corporate offshore shifting ($200–250B/yr); IRS enforcement $200B/yr lost; Direct File killed at 94% satisfaction; Norway wealth tax evidence. 21/22 deepening library.
- **Discord bot stale status fix**: Root cause identified — CHECKIN.md "Since Last Check-in" was not being archived/replaced consistently. Fixed in Session 106.

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
