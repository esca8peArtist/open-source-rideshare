# Check-in Briefing

> This file is updated by the orchestrator before going idle.
> When you drop in, read this first. It's designed to get you up to speed in under 5 minutes.
> After reviewing, clear the "Since Last Check-in" section and leave notes in "Your Notes" for the orchestrator to pick up.

---

## Since Last Check-in

**Period**: 2026-04-18
**Sessions run**: 313–317

### Accomplished (this session — user-initiated)

#### stockbot — Projected Returns: options model support + NameError fix (commits `76a4142`, `ff2eefa`)

The Projected Returns page was already built by an earlier orchestrator session. This session:
- Fixed `_options_models` NameError in `list_all_models` (`/api/models/all` would crash when called)
- Extended projected-returns endpoint to accept string model IDs (UUID or int) — options models now supported
- Frontend switched from `listModels()` to `listAllModels()` so options models appear in the selector dropdown
- Build clean, TypeScript + Vite. All model types (rule-based, ML, MTF, options) now work.

#### open-source-rideshare — 4 endpoints shipped (branch: feature/rider-emergency-safety, pushed to GitHub)

**`GET /riders/me/spending-summary`** (commit `4699fd0`, 18 tests)
Rider-side mirror of driver earnings summary. Today/week/month/lifetime spending buckets, tips given, promo savings, most frequent route.

**`GET /drivers/nearby`** (commit `f10a8fd`, 22 tests)
Public pre-booking endpoint — available drivers within radius, sorted by distance. Bounding-box SQL pre-filter + haversine Python, no PII. Drivers only returned if `is_online=True, is_on_break=False, heartbeat ≤5 min`.

**`GET /drivers/me/ratings`** (commit `2289b7c`, 25 tests)
Paginated driver rating history. Aggregate avg, star breakdown (1–5), recent trend (last 10), paginated list with comment. Rider identity structurally absent from all response types.

**`GET /rides/eta/estimate`** (commit `ec50ef5`, 14 tests)
Public pre-booking ETA before rider commits. Pickup wait time (nearest driver / 30 km/h), trip duration (haversine / 30 km/h, min 2 min), confidence level (high/medium/low by driver count). Reuses nearby-drivers service — no duplication.

**3,891 total tests passing** (was 3,812 at start of session). 0 regressions.

---

### Accomplished (Session 317 — orchestrator)

#### open-source-rideshare — Driver mileage report COMPLETE (commit `9c807d6`)

New endpoint: `GET /driver/me/mileage-report?year=2026[&month=4]`

Drivers can now export their total kilometres/miles driven per year or month, with an IRS standard mileage deduction estimate. Useful for Schedule C tax filings.

24 new tests. **3,812 total passing.** Branch pushed to GitHub.

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
`feature/rider-emergency-safety` (24 commits, 3,812 tests) pushed to GitHub. 4 branches total await PR review.

**stockbot — Paper Trading Dashboard is live**
Go to `/paper-trading` in the web app to monitor your 4 sessions. Equity curve, per-session P&L, and cycle log all there. Auto-refreshes every 30s.

**April 20 monitoring — fill it in when events land**
April 20 events: CAPE Phase 1 launch, DOJ Abrego Garcia brief due. Drop results in INBOX.md — next session writes the monitoring brief.

---

### Suggested Priorities (Next Session)
1. **resistance-research**: April 20 monitoring brief (April 20 evening — CAPE Phase 1 launch + DOJ Abrego Garcia brief). April 22: op-ed submission deadline.
2. **mfg-farm**: Test print action.
3. **open-source-rideshare**: Continue driver features OR start new feature branch.
4. **stockbot**: Check paper trading performance if cycle logs are visible.

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
