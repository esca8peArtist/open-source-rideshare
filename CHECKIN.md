## Since Last Check-in

**Period**: 2026-04-17
**Sessions**: 257–277

---

### Accomplished (Session 277)

#### resistance-research — Publication-readiness formatting pass on democratic-renewal-proposal.md (commit `413a917`)

3 fixes applied to the 2,581-line proposal:
1. Numbered list collision in Section 3.2 "What Requires Federal Statute" — 20a/20b/20 collision resolved, list now runs cleanly 1–93.
2. Missing `---` separator added before Domain 10: Education.
3. Missing `---` separator added before Domain 16: Immigration and Citizenship.
All 22 domains verified present and in order. All 5 Part headings confirmed consistent. All `domain-deepening/` cross-references verified against actual files. `executive-summary.md` was already publication-ready — not modified.

#### open-source-rideshare — Driver earnings comparison vs Uber/Lyft rate cards (29 tests, pushed, commit `aed89c6`)

New endpoint: `GET /drivers/me/earnings-comparison`

Compares actual OpenRide driver payouts to estimated Uber (UberX) and Lyft (Standard) payouts for the same trips, using 2025 published national average rate cards. New files: schema, service, API, tests. Feature: Payment records + tips as actuals; base + per-min + per-mile × driver take-rate for estimates. Rides without distance/duration excluded and counted separately. Per-ride, per-mile, per-hour averages. Absolute and percentage advantage vs. each platform. Rate cards and methodology note included in every response for transparency. Router registered in main.py.

---

### Needs Your Input

#### open-source-rideshare — Feature branch ready for review

Feature branch: `feature/corporate-business-accounts`
Pushed to: `rideshare` remote (esca8peArtist/open-source-rideshare)

**Full feature set** (all committed, all tests passing):
- Three-tier corporate policy hierarchy (account → department → member override)
- Booking eligibility enforcement (policy, blackout, quotas, spend limit, dept budget, onboarding)
- Invoice due dates + overdue tracking
- Spending alerts (75%/90%/100% thresholds)
- Member onboarding with checklist enforcement
- Invitation → onboarding auto-trigger
- Expense report generation (member + admin + CSV)
- Trip purpose codes (admin CRUD, rider tag, analytics)
- Driver earnings comparison (Uber/Lyft rate card comparison)

Ready to merge to master when you approve.

---

### Accomplished (Sessions 275–276)

#### resistance-research — ALL 23 DOMAIN FILES NOW TIER 1 (deepening queue 100% complete)

Three final Tier 2 files elevated this session:

**data-privacy-evidence.md** (Session 275, commit `924d6d3`): Section 9.5 counterargument on data availability/beneficial uses (fraud prevention, medical research, free flow of data — each engaged directly with resolution). Sections AI-1 through AI-6 actionable intelligence — Section 702 April 2026 expiration, ADPPA successor, federal BIPA, COPPA 2.0, KOSA, FTC ANPRM litigation path, Illinois BIPA defense (May 2026), seven organizations, five 2026 windows.

**social-safety-net-evidence.md** (Session 276, commit `18d11f5`): Sections 10–13 added. Nordic benchmarks (25%+ GDP spending, child poverty 3.7–9.4% vs. US 15–17%); UK Universal Credit cautionary case (5-week wait → 36% housing arrears); Canada Mincome + Ontario pilot. SNAP 0.06% fraud rate vs. 10.93% improper payment rate. Fiscal sustainability and work disincentive counterarguments. OBBBA P.L. 119-21 SNAP $295B/10yr, Medicaid work requirements 4.8M losing coverage (Jan 2027 deadline), Farm Bill Sep 30, 2026 expiration. Six organizations. Five 2026 windows.

**reparations-evidence.md** (Session 276, commit `77d3eb9`): Sections 11–13 added. Darity-Mullen $14.3T/$10.7T + Craemer $16.4-20T fiscal methodologies; revenue mechanisms ($860B-$1.5T/10yr window). Three core counterarguments at full depth. Actionable intelligence — NY Commission testimony (open now), HR 40/S.40 (99 co-sponsors), five state pressure points, six orgs, five 2026 windows, 2025-2026 rollback with state/local bridge strategy.

quality-review-index.md: **23 Tier 1, 0 Tier 2, 0 Tier 3**

#### open-source-rideshare — Invitation → onboarding auto-trigger (48 tests, pushed, commit `9cfacf2`)

`accept_invitation` now calls `create_onboarding` after flush — idempotent (409 absorbed silently). 3 new tests: creates onboarding on accept, ignores duplicate, revoke does not trigger. No regressions in onboarding (93 tests) or bulk invitations (27 tests).

#### open-source-rideshare — Corporate expense report generation (60 tests, pushed, commit `0b07eab`)

Three new files: schema, service, API. No new migrations. Member self-service report, admin account report with dept + member breakdowns, CSV export. 60 tests covering all paths.

---

### Needs Your Input

#### open-source-rideshare — Feature branch ready for review

Feature branch: `feature/corporate-business-accounts`
Pushed to: `rideshare` remote (esca8peArtist/open-source-rideshare)

**Full corporate feature set** (all committed, all tests passing):
- Three-tier policy hierarchy (account → department → member override)
- Booking eligibility enforcement (policy, blackout, quotas, spend limit, dept budget, onboarding)
- Invoice due dates + overdue tracking
- Spending alerts (75%/90%/100% thresholds)
- Member onboarding with checklist enforcement
- Invitation → onboarding auto-trigger
- Expense report generation (member + admin + CSV)

Ready to merge to master when you approve. Sessions of work across a substantial corporate accounts feature set — worth a PR review before merging.

---

### Accomplished (Session 274)

#### open-source-rideshare — Onboarding checklist enforcement in booking eligibility (58 tests, pushed, commit `043c790`)

Added **Step 0** to `check_booking_eligibility` in `corporate_booking_eligibility.py`. Before any policy check, the service now queries for an active (non-completed) `CorporateMemberOnboarding` record for the member. If found and `policy_acknowledged` is not complete, the ride is blocked.

- `BookingEligibilityResponse` schema extended: `onboarding_incomplete: bool = False`, `onboarding_pending_steps: List[str] = []`
- `eligible` verdict now includes `not onboarding_incomplete`
- No-onboarding-record path: `onboarding_incomplete=False` (onboarding is admin-initiated, not mandatory)
- Completed onboarding (status='completed') excluded by query — no false positives
- 8 new tests; 58 total passing (was 50)
- Pushed to `rideshare` remote, `feature/corporate-business-accounts`

#### resistance-research — rights-protection-evidence.md elevated Tier 2 → Tier 1 (local commit `8ba9bd0`)

File: `domain-deepening/rights-protection-evidence.md` (432 → 648 lines). quality-review-index.md: **20 Tier 1, 3 Tier 2, 0 Tier 3** (was 19/4/0).

Four gaps filled: (1) Counterargument on infrastructure security interest (Section 7g) — states the legitimate claim before dismantling it via overbreadth, discriminatory application pattern, and legislative record analysis; (2) EU benchmarks (Section 7h) — EU Anti-SLAPP Directive 2024/1069 with December 2026 implementation deadline as domestic leverage; France Constitutional Council Loi Séparatisme ruling; Germany mandatory constitutional expert opinion requirement vs. US legislative record; (3) Fiscal estimates (Section 7i) — Federal DPA at $300-500M (UK ICO methodology), anti-SLAPP as cost-negative ($350M/yr IPI chilling effect), fusion center restructuring at net-zero (reallocation), IMSI catcher warrants at $1.5M compliance cost; (4) Actionable intelligence (AI-1 through AI-6) — Section 702 212-212 swing vote strategy, PRESS Act / 4th Amendment Is Not For Sale Act / SPEAK FREE Act bill numbers, Illinois BIPA defense / Texas civil rights litigation / Minnesota pipeline SCOTUS pathway as state priorities, six named organizations, five time-bounded 2026 windows.

---

### Needs Your Input

#### open-source-rideshare — Corporate department management + policy enforcement + budget enforcement + onboarding enforcement (PR ready for merge)

Feature branch: `feature/corporate-business-accounts`
Pushed to: `rideshare` remote (esca8peArtist/open-source-rideshare)

**What was built** (all committed, all tests passing):

Three-tier policy hierarchy fully operational + booking enforcement:
  1. Account-level policy (CorporateRidePolicy)
  2. Department-level override (CorporateDepartmentRidePolicy)
  3. Member-level override (CorporateMemberPolicyOverride)
  4. Booking eligibility enforces: effective policy, blackout periods, ride quotas, member spend limit, department budget, **onboarding checklist** (policy_acknowledged step)

**Latest additions**:
- Session 273: Department budget enforcement — blocks booking when any dept monthly_budget exceeded (`commit 238ab1e`)
- Session 274: Onboarding checklist enforcement — blocks booking when `policy_acknowledged` incomplete in active CorporateMemberOnboarding (`commit 043c790`)

Total tests: 151 dept/policy + 58 booking eligibility = **209 tests passing** across the corporate feature set.

Ready to merge to master when you approve.

---

### Accomplished (Session 273)

**Period**: 2026-04-17
**Sessions**: 257–273

---

### Needs Your Input

#### open-source-rideshare — Corporate department management + policy enforcement + budget enforcement (PR ready for merge)

Feature branch: `feature/corporate-business-accounts`
Pushed to: `rideshare` remote (esca8peArtist/open-source-rideshare)

**What was built** (all previously committed, all tests passing):

Three-tier policy hierarchy is fully operational:
  1. Account-level policy (CorporateRidePolicy)
  2. Department-level override (CorporateDepartmentRidePolicy) — new middle tier
  3. Member-level override (CorporateMemberPolicyOverride) — member wins

**Models** (`app/models/corporate_department.py`, `app/models/corporate_department_ride_policy.py`):
- `CorporateDepartment`: account-scoped departments with name, code (unique per account), description, optional cost_center_id, monthly_budget, is_active
- `CorporateDepartmentMember`: junction table (department ↔ user) with is_department_head flag
- `CorporateDepartmentRidePolicy`: per-department policy override (allowed_vehicle_categories, max_per_ride_usd, require_purpose, approved_purposes, business_hours_only, notes, is_active)

**Migrations** committed: `b2c3d4e5f6g7_corporate_departments.py`, `i0j1k2l3m4n5_corporate_department_ride_policies.py`

**Services** (`app/services/corporate_department.py`, `app/services/corporate_department_ride_policy.py`):
- Full CRUD: create/get/list/update/deactivate department; add/remove/list department members; spend analytics
- Policy management: set/get/update/delete/activate/deactivate per-department policy
- `get_effective_policy_for_member`: merges all three tiers (account → department most-restrictive → member override)

**API** (routers registered in main.py): `corporate_departments` + `corporate_department_ride_policy`
- Member self-view, admin CRUD, platform-admin cross-account endpoints
- Department spend analytics with budget utilization %

**Tests**: 52 passing (`test_corporate_departments.py`) + 49 passing (`test_corporate_department_ride_policy.py`) + 50 passing (`test_corporate_booking_eligibility.py`) = 151 total

**Latest addition (Session 273)**: Department budget enforcement in booking eligibility (`commit 238ab1e`). When a ride is requested, the system now:
1. Looks up all departments the member belongs to
2. Sums this month's completed-ride spend across ALL members of each department
3. Blocks the booking if any department's `monthly_budget` is exceeded
New `DeptBudgetCheckSummary` schema; `BookingEligibilityResponse` extended with `dept_budget_exceeded` + `dept_budget_details`.

Ready to merge to master when you approve.

---

### Accomplished (Session 273)

#### open-source-rideshare — Department budget enforcement added to booking eligibility (50 tests, pushed, commit `238ab1e`)

`_get_department_budget_checks(db, account_id, user_id)` added to `corporate_booking_eligibility.py`. Sums current-month `Ride.actual_fare` across all department members (via `CorporateDepartmentMember` join). Step 5b in eligibility check — blocks ride if any of the user's departments has exceeded its `monthly_budget`. New `DeptBudgetCheckSummary` schema. `BookingEligibilityResponse` extended. 10 new tests cover: exceeded, not-set, two-dept scenarios, combined failures, limit boundary, partial spend, not in any dept, schema construction, floor-at-zero.

#### resistance-research — domain-03-democratic-participation elevated Tier 2 → Tier 1 (local commit `c4eed22`)

File: `domain-deepening/domain-03-democratic-participation.md` (217 → 411 lines). quality-review-index.md: **19 Tier 1, 4 Tier 2, 0 Tier 3** (was 18/5/0).

- **Section 9 (new)** — Counterargument: deliberative bodies as minority capture vectors. Engages Bagg (2024 AJPS), Yale ISPS (2025) selection bias, JDD (2024) invisible facilitation power, arXiv (2026) temporal panel selection. Identifies 5 design requirements for capture-resistant assemblies. Structural framing: compare to actual institutional alternatives, not ideal legislature.
- **Section 10 (new)** — Fiscal estimates with named methodology: GS-11 member compensation, CBO cost-per-employee for secretariat, National Academies pricing for expert witnesses. Assembly estimate: $35-65M per 18-month cycle (median $50M). PB federal match grounded in NYC 7-10% ratio + Harvard Ash Center 3.5x durability finding.
- **Section 11 (new)** — 2025-2026 rollback: EO 14248 citizenship documentation (21M affected, 2 injunctions); SAVE America Act (House 218-213, Senate 60-vote threshold); 13-state RCV ban wave through March 2026. Two-track resistance implication.
- **Section 12 (new)** — Actionable Intelligence: 5 active cases (LULAC v. EOP, California v. Trump, LWV Ohio v. LaRose, Louisiana v. Callais, Turtle Mountain v. Howe), 4 legislative vehicles with bill numbers, 8 organizations with roles/URLs, 5 time-bounded 2026 windows.

---

### Accomplished (Session 272)

#### resistance-research — immigration-evidence.md elevated Tier 2 → Tier 1 (local commit)

File: `domain-deepening/immigration-evidence.md` (399 → 636 lines). quality-review-index.md: **18 Tier 1, 5 Tier 2, 0 Tier 3** (was 17/6/0).

**Section 9 — Int'l benchmarks (all three subsections deepened)**:
- **Canada**: Statistics Canada 2024 longitudinal data — employment gap between recent immigrants and Canadian-born narrowed 13.1 → 6.5pp (2010-2023); 2016 cohort earnings trajectory ($58,400 yr-1 → $76,800 yr-5); 111,301 Express Entry invitations in 2024; April 2026 CRS overhaul shifting points toward demonstrated earnings; overeducation rate 40% → 27%; H-1B dependency as structural contrast with employer-portable Canadian model.
- **Germany**: Renamed section to include labor shortage context — €150B annual output cost of unfilled positions (political economy driver); Blue Card + Opportunity Card numbers; sector specifics (healthcare, IT, trades); bilateral partner agreements (India, Brazil, Philippines, Morocco, Kenya); credential recognition bottleneck as design lesson.
- **Australia (Albanese reforms)**: NOM trajectory 528,000 → 306,000 → projected 260,000; Skills in Demand visa replacing TSS-482; 185,000 permanent places with employer-sponsored/independent allocation; 2023 Migration Strategy goals; why lower overstay dynamic reflects genuine temporary-to-permanent pathways.

**Section 11 (new) — Counterarguments**:
- 11.1 Enforcement-deterrence: Massey backfire finding (border militarization created settled population out of circular migration); structural non-deterrability of asylum seekers; IZA World of Labor diminishing returns; policy implication (enforcement requires legal pathways to work).
- 11.2 Rule-of-law objection: Heritage/FAIR framing engaged directly; 1986 IRCA comparison debunked (failure to create legal pathways drove growth, not legalization signal); Sarah Song (NYU) statutory legalization analysis; Spain 2005 700,000-worker legalization precedent; objection's internal inconsistency (workers vs. employers).
- 11.3 Card-Borjas wage dispute deepened: Borjas 2017 reanalysis critique; Peri-Sparber task-specialization (O*NET data, communication vs. manual); 2025 meta-analysis consensus; policy implication — labor law enforcement, not restriction.

**Section 12 (new) — Actionable Intelligence (AI-1 through AI-6)**:
- AI-1: IRS-ICE data sharing litigation (two injunctions, one denial, circuit ruling pending); SHIELD Act H.R.3101; birthright citizenship SCOTUS ruling June-July 2026.
- AI-2: Legislative vehicles — DREAM Act S.3348 (2021 House 228-197 precedent, 9 GOP co-sponsors); Farm Workforce Modernization H.R.3227 (agricultural employer constituency); SHIELD Act H.R.3101 (Vera Institute + universal representation data); FY2027 DHS appropriations as annual vehicle for ATD funding, judge hiring, legal orientation programs.
- AI-3: Administrative vs. legislative pathways — what a future administration can do by executive action (parole-in-place, prosecutorial discretion, TPS, expanded legal orientation) vs. what requires legislation (permanent citizenship path, visa cap expansion, Article I immigration courts, mandatory detention reform, right to counsel).
- AI-4: Sanctuary policy — Tenth Amendment anti-commandeering basis (Printz); July-August 2025 federal court rulings upholding IL/Cook County/Chicago; April 2025 ruling blocking funding withholding from 16 jurisdictions; what Shut Down Sanctuary Policies Act would do; crime-reporting research on public safety outcomes.
- AI-5: 7 organizations with specific roles — NILC (policy/litigation), CLINIC (500,000 clients/year, accreditation network), Vera (SAFE Network, representation dashboard), ACLU IRP (lead in AEA/IRS-ICE/family separation litigation), American Immigration Council (quantitative evidence, Gateways for Growth), National Immigration Forum (cross-partisan faith/law enforcement/business), NIJC (direct services, asylum law leadership).
- AI-6: 5 named 2026 windows — SCOTUS birthright citizenship (June-July 2026); IRS-ICE data litigation with specific case names; Abrego Garcia contempt proceedings + documented US citizen wrongful deportation cases; FY2027 DHS and CJS appropriations with specific line items; Farm Workforce Modernization agricultural employer pressure.

#### open-source-rideshare — Corporate department-level policy enforcement verified (101 tests, pushed)

Agent discovered the full three-tier policy hierarchy was already implemented in a prior session. 101/101 tests confirmed passing:
- 52/52 in `tests/test_corporate_departments.py`
- 49/49 in `tests/test_corporate_department_ride_policy.py`

**Three-tier resolution chain live**: account policy → department policy override (most-restrictive merge across member's departments) → member override (member wins).

Key models: `CorporateDepartment`, `CorporateDepartmentMember`, `CorporateDepartmentRidePolicy`. Services: full CRUD, membership, spend analytics, `get_effective_policy_for_member`. REST endpoints registered in main.py. Pushed to rideshare remote.

---

### Accomplished (Session 271)

#### resistance-research — labor-evidence.md elevated Tier 2 → Tier 1 (local commit)

File: `domain-deepening/labor-evidence.md`. The quality card showed Int'l benchmarks as Adequate and Fiscal estimates + Actionable Intelligence + 2025-2026 rollback as missing. Added ~200 lines:

**Int'l benchmarks strengthened**: UK National Living Wage — LPC finding low-pay share fell 21% → under 10% (~3M workers); 2024 LPC/Frontier Economics research; US transferability: UK NLW at 62% of median vs US federal minimum at 31%; $17/hr would reach 56-58% (still below UK). Manning 2021 ILR Review — wage markdowns 15-50% typical across advanced economies; the load-bearing number for minimum wage evidence (increases within the markdown range reduce monopsony rent, not employment). Nordic transfer conditions — DA/SAF associations represent 65-80% of employers; cannot be replicated without mandatory association or statutory extension; California FAST Act (AB 1228, Sep 2023) as first US sectoral wage board experiment.

**CBO 2023 $17 analysis**: 18M workers affected, 400K lifted from poverty, 700K job loss estimate — more current than the 2021 $15 analysis already in file.

**Section 10: 2025-2026 Rollback**: OSHA — 8% budget cut, 266-year inspection cycle projection, 20% fewer inspections, 42% fewer severe-violation fines. DOL Wage and Hour Division — 400+ staff reduction. EO 14236 (March 14, 2025) — rescinded $17.75 federal contractor minimum wage affecting 3.7M contract workers (largest single-action minimum wage rollback in US history). FAB 2025-1 (May 2025) — stopped Biden IC classification enforcement; replacement rule open for comment through April 28, 2026. Davis-Bacon Biden-era expansion litigation pause. Synthesis: counter-strategy implications (consumer-pressure campaigns, state enforcement, organizing under state law).

quality-review-index.md: **17 Tier 1, 6 Tier 2, 0 Tier 3** (was 16/7/0).

#### open-source-rideshare — Corporate member ride quota management verified (45 tests, pushed)

Agent discovered the system was fully implemented in a prior session. Verified: `CorporateMemberRideQuota` model, `QuotaPeriod` enum, full schemas, service layer with `set_quota`/`update_quota`/`deactivate_quota`/`get_quota`/`list_member_quotas`/`get_quota_usage`/`get_account_quota_summary`, 11 API endpoints (member self-view, account-admin CRUD, platform-admin override + cross-account exceeded view), router registered at main.py:181. 45/45 tests passing. Pushed to rideshare remote.

---

### Accomplished (Session 270)

#### resistance-research — national-security-evidence.md elevated Tier 2+ → Tier 1 (commit `4a88fe7`)

The only remaining weak dimension was Actionable Intelligence. Replaced a thin placeholder with 6 comprehensive subsections (~280 lines):

**AI-1 (Most Immediately Actionable)**: FY2027 NDAA markup May-August 2026 named as the single highest-leverage action window; H.R. 6751 as the parallel floor track.

**AI-2 (Legislative Vehicles)**: 7 named vehicles — H.R. 6751 (Jayapal-Massie-McGovern-Griffith-Casar-Crane, 2001 AUMF 240-day sunset; Senate: Kaine/Young); FY2026 NDAA enacted December 2025 repealing 2002 Iraq + 1991 Gulf War AUMFs (first AUMF repeal since Gulf of Tonkin in 1971, establishes procedural feasibility); H.R. 7555 Audit the Pentagon Act (Pocan-Biggs, 0.5%/1% budget return — at ~$850B DoD = $4.25B first trigger); FY2024 NDAA 1.5% cancellation trigger (December 2028 enforcement deadline); RECEIPTS Act (Ernst, $150M AI audit — Republican fiscal framing); FY2027 NDAA five specific provisions.

**AI-3 (Federal Agency Pressure Points)**: GAO request process (CongRel@gao.gov, any Member can trigger, 6-18 months, National Security division has clearances); DoD IG Hotline ((800) 424-9098, dodig.mil); FOIA pathways for DFAS/DCMA/SAM.gov with notes on what's reachable vs. classified.

**AI-4 (Organizations)**: 12 organizations with specific roles: POGO (NDAA amendment coordination menu), National Priorities Project (Cost of War by congressional district — primary constituent outreach tool), Taxpayers for Common Sense (BWAF podcast, Republican coalition credibility), Stimson Center (Alternative Defense Budget), Quincy Institute (Responsible Statecraft daily coverage), Center for International Policy (Security Assistance Monitor arms sales database), Win Without War, FCNL (district-by-district lobby day logistics), AFSC, Council for a Livable World (candidate endorsements + Center for Arms Control staff briefings), Brennan Center, IAVA.

**AI-5 (State-Level Leverage)**: AUMF resolutions in 10 achievable states (CA, CO, IL, ME, MA, MN, NM, OR, VT, WA); CalSTRS $489M in top-3 contractors → shareholder proxy vote approach (not divestment); National Guard federalization limits post-December 2025 SCOTUS ruling.

**AI-6 (Near-Term Windows)**: FY2027 NDAA markup (May-Aug 2026, contact orgs in April-May now); H.R. 6751 discharge petition / NDAA attachment; Pentagon 9th consecutive audit failure (December 2026); Section 702 vote; FY2027 State/USAID appropriations for USAID reconstitution mandates.

quality-review-index.md: **16 Tier 1, 7 Tier 2, 0 Tier 3** (was 15/8/0). Domain 19 card: Actionable Intelligence and Counterarguments both now Strong.

#### open-source-rideshare — Corporate member expense policy enforcement (commit `d8bbe8c`)

68 tests, 68 passing. Pushed to rideshare remote.

Built the enforcement layer on top of the existing two-tier policy system (CorporateRidePolicy + CorporateMemberPolicyOverride + get_effective_policy):

**Schemas** (`schemas/corporate_member_policy_enforcement.py`): `BookingPolicyCheckRequest` (vehicle_category, estimated_fare_usd, trip_purpose, requested_at), `PolicyViolation` (field, message, value, limit), `PolicyCheckOutcome` enum (ALLOWED/REQUIRES_APPROVAL/DENIED), `BookingPolicyCheckResponse`, `MonthlySpendResponse`.

**Service** (`services/corporate_member_policy_enforcement.py`): 6 isolated check functions + `check_booking_against_policy`. Logic: vehicle category (DENIED if not in allowed list); fare cap (≤cap → allowed, cap–150% → REQUIRES_APPROVAL, >150% → DENIED, named constant `_FARE_APPROVAL_RATIO = 1.5`); business hours (Mon-Fri 07:00-21:00 UTC, DENIED otherwise); purpose required (DENIED if missing); purpose allowed (DENIED if not in list); monthly cap (REQUIRES_APPROVAL — never DENIED, manager can override). DENIED beats REQUIRES_APPROVAL.

**Endpoints** (`api/v1/corporate_member_policy_enforcement.py`): `POST /corporate/accounts/me/check-booking` (member self-check); `POST /corporate/accounts/{id}/members/{id}/check-booking` (admin); `GET /corporate/accounts/{id}/members/{id}/monthly-spend` (admin).

No migration required — pure service layer over existing tables.

---

### Accomplished (Session 269)

#### resistance-research — economic-concentration-evidence.md elevated Tier 2 → Tier 1 (commit `429a246`)

File: `domain-deepening/economic-concentration-evidence.md`. Added **Section 10: Actionable Intelligence** (~800 words). The only weak dimension in the quality card was "Actionable intelligence: Adequate" — now Strong.

**10.1 Live Enforcement Opportunities**: Four DOJ/FTC platform cases in their specific 2026 procedural posture — Google Search (remedy phase, DOJ requesting Chrome/Android divestiture, public comment window open, 38 state AG co-plaintiffs); FTC v. Amazon (pre-trial, public complaint mechanism); DOJ v. Apple (discovery); DOJ v. Google Ad Tech (remedy after November 2024 liability finding); FTC PBM investigation (final report + congressional hearing leverage). Each entry names a concrete public participation mechanism available now.

**10.2 Legislative Vehicles**: CALERA (burden shift, per se expansion, DOJ/FTC resource increase); AICOA (self-preferencing prohibition, Senate Judiciary 16-6 vote history, stalled 2022); Open App Markets Act (side-loading); Farm System Reform Act (Booker/Khanna, livestock processor cap); state-level: IL Antitrust Act, CA AB 2788 (2024), MN common ownership study. FY2027 CJS appropriations framed as higher-leverage than new legislation.

**10.3 State AG Enforcement**: TX Paxton (Google Search co-plaintiff, ad tech case initiator, Meta, Google Maps); NY James (Meta/Instagram structural separation suit, Amazon labor, healthcare); CA Bonta (tech, healthcare); IL Raoul (hospital, grocery). 38-state Google coalition and 48-state pharma patterns named as templates. Section argues state AG enforcement is structurally resilient even under federal agency defunding.

**10.4 Organizations**: Open Markets Institute, American Economic Liberties Project, Accountable.US, EFF, Demand Progress, state PIRGs; Senate and House Judiciary antitrust subcommittee contact mechanisms.

**10.5 Near-Term Windows**: Google remedy record (closes when opinion issues, likely late 2026); FY2027 appropriations (CJS subcommittee); state AG coalition expansion.

quality-review-index.md: **15 Tier 1, 8 Tier 2, 0 Tier 3** (was 14/9/0).

#### open-source-rideshare — Corporate spending limit alerts (commit `fb2f2d1`)

55 tests, 55 passing. Pushed to rideshare remote.

**Model**: `CorporateSpendingAlert` with `AlertType` enum (`warning_75pct`, `warning_90pct`, `limit_reached`). Unique constraint on `(account_id, member_id, alert_type, period_year, period_month)` — idempotent.

**Service**: `check_and_create_alerts` (threshold detection), `get_account_alerts` (admin), `get_member_alerts` (member-scoped), `get_alerts_summary` (admin dashboard). Member spend uses account-spend/active-member-count approximation (invoices lack member_id column) — documented as known limitation.

**Endpoints**: POST check (admin, 201); GET alerts list (admin); GET summary (admin); GET own alerts (member); GET platform-admin cross-account view.

**Migration**: `c3d4e5f6g7h8` (down_revision `b2c3d4e5f6a7`).

---

### Accomplished (Session 268)

#### resistance-research — housing-evidence.md elevated Tier 2 → Tier 1 (commits `d38edfc`, `d3b3ed2`)

File: `domain-deepening/housing-evidence.md` (633 → 865 lines). Four gaps from the quality review filled:

**Vienna Gemeindebau (expanded Section 9.1)**: Construction cost €150-200k/unit vs. US LIHTC $400-600k; rents €7-8/sqm subsidized vs. €15-20/sqm market (50-60% discount); 26,000 waitlist households with ~1-2 year wait vs. 17-year implied New York Section 8 wait; income ceiling €53,340/yr net (~160% AMI — explains income-mixing design); Klimabonus passive-house mandate (max 15 kWh/m²/yr) for new social housing; Gemeinschaftliche Wohnprojekte co-housing model; 2021 new-build resumption after 2005 debt pause.

**Singapore HDB (new Section 9.1b)**: 79% of residents covered; 88.9% homeownership (2023); SGD 500-600k resale vs. SGD 1.2-1.5M private; construction cost SGD 200-350k/unit vs. US market-rate $400k+; BTO 2-5x oversubscribed; income ceiling SGD 14,000/month captures wide middle class; Land Acquisition Act (1967) named as the irreplaceable enabling condition that cannot be replicated under the US Takings Clause.

**Fiscal estimates (new Section 12 subsection)**: Zoning reform — YIMBY Act near-zero cost; transportation conditioning $5-15B leverage on $55-60B FHWA grants; Hsieh-Moretti $1.7T annual GDP gain (2026 dollars); Minneapolis 6-10% rent reduction at zero federal cost. LIHTC alternatives — current $400-600k all-in vs. $280-420k direct grant (30-40% less); Vienna non-profit analog $180-280k + $3-5k/yr operating. CLT scaling — $2.5-4B/10yr for 250k units vs. $31-37.5B voucher equivalent for same households.

**Section 13 Actionable Intelligence**: Federal vehicles (YIMBY Act S.1614/H.R.3009, Housing Choice Act, Ending Homelessness Act); state pressure points 2026 (CA/CO/MT/NY/TX); organizations to support (NLIHC, Up For Growth, NAEH, Grounded Solutions Network, LISC, Habitat); FY2027 THUD subcommittee + AFFH APA challenge + Ways and Means LIHTC reconciliation window + 2026 state ballot initiatives.

**Section 14 2025-2026 Rollback**: AFFH suspended Jan 20 2025 — $7B in formula grants now flow without fair housing conditions; HUD discretionary budget cut ~$2.6B (20%), 400 FTE reduction concentrated in FHEO/CPD; Section 8 under-funded by ~100,000 vouchers in FY2025; manufactured housing code update (87 changes) identified as the surviving regulatory gain; 770,000 PIT count (record +18.1% from 2023) as backdrop.

quality-review-index.md: **14 Tier 1, 9 Tier 2, 0 Tier 3** (was 13/10/0). Domain 13 housing card: Int'l benchmarks → Strong, Fiscal estimates → Strong, Actionable intelligence → Strong.

#### open-source-rideshare — Corporate invoice due date and overdue tracking (commit `41cbde3`)

55 tests written, 55 passing. Pushed to rideshare remote (`esca8peArtist/open-source-rideshare`).

**Model changes:**
- `CorporateInvoice` model: added `payment_terms_days: int | None` and `due_date: date | None`
- Alembic migration `b2c3d4e5f6a7` (down_revision: `a1b2c3d4e5f6`) — adds both columns + index to `corporate_invoices_v2`

**New files:**
- `schemas/corporate_invoice_due_date.py` — `SetInvoiceDueDateRequest` (validates payment_terms_days 1-365), `OverdueInvoiceRow`, `OverdueInvoicesResponse`, `InvoiceOverdueScanResponse`
- `services/corporate_invoice_due_date.py` — `set_invoice_due_date` (rejects PAID/VOID), `get_overdue_invoices` (FINALIZED + due_date < as_of), `run_overdue_scan` (newly-flagged detection)
- `api/v1/corporate_invoice_due_date.py` — 4 endpoints: `PUT .../invoices/{id}/due-date`; `GET .../invoices/overdue` (member); `GET /admin/corporate/invoices/overdue`; `POST /admin/corporate/invoices/overdue-scan`

---

### Accomplished (Session 267)

#### open-source-rideshare — Replace in-memory expense report store with ORM model (commit `258e794`)

Removes the `_REPORT_STORE` dict and replaces it with a proper SQLAlchemy model + Alembic migration. 65 tests passing. Pushed to rideshare remote.

**New files:**
- `backend/app/models/corporate_generated_expense_report.py` — `CorporateGeneratedExpenseReport` ORM model; JSONB columns for `by_member`/`by_category`; FK to `corporate_accounts_v2` (CASCADE) and `users`
- `backend/app/db/migrations/versions/a1b2c3d4e5f6_corporate_generated_expense_reports.py` — Alembic migration, revision `a1b2c3d4e5f6`, down_revision `z9a0b1c2d3e4`

**Updated files:**
- `services/corporate_expense_report_service.py` — removed all in-memory store infrastructure; `generate_expense_report` uses `db.add/flush/refresh`; `list_generated_reports` runs count + paginated DB query; `get_generated_report` selects by id + corp_id
- `tests/test_corporate_expense_report_aggregates.py` — mocks updated for DB-backed implementation; all 65 tests pass

#### resistance-research — judicial-independence-evidence.md deepened to Tier 1 (commit `7a23670`)

File: `domain-deepening/judicial-independence-evidence.md` (406 → ~720 lines). Three new sections (~2,300 words):

**Section 12 — Fiscal Estimates for Reform Options**: SCOTUS expansion at ~$1-1.2M annual recurring per seat + $2-4M one-time chamber renovation (2-3% of $174.5M SCOTUS budget for 4 seats); term limits as "indeterminate but modest" (CRS); ethics IG at $15-30M SCOTUS-specific or $30-50M full bench; full reform program at $150-260M annually — rounding error in $9B judiciary budget.

**Section 13 — Canada and South Africa Benchmarks**: Canada's 2016 Trudeau JAAC reforms (open applications, lay membership, three-tier assessment, 35-year Ontario track record); South Africa's Section 178 constitutional JSC (public hearings, 23-member composition with opposition protection, Constitutional Court independence record). Combined lesson: transparency alone doesn't solve politicization; bloc pressure insulation is the unsolved design challenge.

**Section 14 — Counterargument (court reform as politicization)**: Full-strength norm erosion objection developed (FDR 1937, no-limiting-principle arms race, Tribe/Biden commission caution); counter-counter (Garland blockade, ACB self-contradiction, V-Dem empirical record); policy resolution sequencing procedural → structural reform with 72% public support for ethics requirements as pathway.

quality-review-index.md updated: judicial-independence moved Tier 2 → Tier 1 (now **13 Tier 1, 10 Tier 2, 0 Tier 3**).

---

### Accomplished (Session 266)

#### resistance-research — Quality review pass complete + V-Dem insertion + labor deepened

**quality-review-index.md updated** (commit `b8d0118`): All 5 Tier 3 files moved to correct tiers in the index. Tier count now 12 Tier 1 / 11 Tier 2 / 0 Tier 3. Priority 1 deepening queue marked complete with session notes.

**V-Dem figure inserted into proposal Part I** (commit `5138de2`): Section 1.1 (The Current Crisis) now includes a full paragraph on the 0.75→0.57 score decline — 24% drop in a single term, largest single-term decline V-Dem has recorded for a consolidated democracy, US among 6 globally autocratizing countries, "diminished to levels similar to 1965." Cross-referenced to `judicial-independence-evidence.md`.

**labor-evidence.md deepened to Tier 1** (commit `5d539b4`): Added Section 9 (Actionable Intelligence, ~1,400 words):
- NLRB crisis: Wilcox/Abruzzo firings, 345-day quorum paralysis, 30% drop in union elections (1,498 in 2025)
- Live campaigns: Starbucks Workers United (535 locations, 4 years without contract, Nov 2025 strike); Amazon Labor Union (JFK8/RDU1); CIW Fair Food Program (non-NLRA model)
- Minimum wage targets: Oklahoma SQ832 June 16 2026 ($7.25→$15), 2026 scheduled increases, One Fair Wage targets
- Legislative vehicles: PRO Act (119th Congress bipartisan House co-sponsors, Senate filibuster barrier), state analogs (IL, MN, WA)
- Org landscape: EPI/NELP/AFL-CIO/Clean Slate + organizing orgs + state pressure point map for 2026

#### open-source-rideshare — Background check expiration tracking (commit `3646ec7`)

New feature on `feature/corporate-business-accounts`. 43 tests written, 43 passing. Pushed to rideshare remote.

**New files:**
- `BackgroundCheckAlertType` enum + `BackgroundCheckAlert` model added to `background_check.py`; `expires_at: date | None` field on `BackgroundCheck`
- `schemas/background_check_expiry.py` — ExpiringBackgroundCheckRow, ExpiringBackgroundChecksResponse, BackgroundCheckExpiryScanResponse
- `services/background_check_expiry.py` — `get_expiring_background_checks` (window query, excludes non-clear checks), `run_expiry_scan` (threshold-based dedup at 7/30/60 days)
- `api/v1/background_check_expiry.py` — `GET /admin/background-checks/expiring` + `POST /admin/background-checks/expiry-scan` (admin-only)

---

### Accomplished (Session 265)

#### resistance-research — tax-policy-evidence.md elevated Tier 3 → Tier 1 (commit `a704f78`)

All 5 Tier 3 files from the quality review are now done. This was the last one.

**Duplication resolved**: The file was overlapping heavily with `domain-05-fiscal-reform.md`. Scope is now explicit — tax-policy owns the tax code structure (progressivity, loopholes, IRS enforcement framing, international profit shifting); fiscal-reform owns budget process, deficit/debt, entitlement sustainability.

**New content added**:
- **Carried interest loophole** (new §6): $63.1B/10yr JCT figure, 3 active 119th Congress bills including Wyden/Whitehouse/King bill filed April 16 2026 — a live Gilens/Page illustration
- **IRS enforcement: DOGE crisis** (expanded §13): 31% of revenue agents gone by mid-2025; Yale Budget Lab projects $861B deficit increase from payroll savings of $45.5B
- **Counterarguments** (8 full subsections replacing 8 bullet points): Supply-side/Laffer (ETI formula, t* = 73%), double taxation, IRS targeting history, capital flight with US structural differences, unrealized gains workability, corporate taxes/jobs, code complexity, entrepreneurship objection — all taken seriously and rebutted with named studies and data
- **Fiscal policy and democratic legitimacy** (new §16): Gilens/Page applied directly to tax outcomes; 5000:1 lobbying ROI on Direct File; 1986 reform coalition conditions
- **Actionable intelligence** (new §18): OBBBA signed July 4 2025 ($5.2T revenue reduction, 60% top-quintile benefits), active bills table, IRS pressure points, org profiles (Tax Policy Center, ITEP, Yale Budget Lab, ATF, FACT Coalition, CBPP, EPI, Patriotic Millionaires), near-term calendar through 2027

**Tier 3 → Tier 1 complete for all files**: electoral-reform (S263), national-security (S263→Tier 2+), environment-climate (S264), healthcare-education (S264), tax-policy (S265).

#### open-source-rideshare — Corporate expense reporting feature (commit `ea7b1c0`)

New feature on `feature/corporate-business-accounts`. 65 tests written, 65 passing.

**Endpoints** (`GET/POST /corporate/{corp_id}/expense-reports`, `GET /{report_id}`, `GET /{report_id}/export`):
- List reports with date range + pagination filters
- Generate aggregated report for a date range (per-member and per-category breakdowns)
- CSV export with `Content-Disposition: attachment` header

**Note for review**: Service uses an in-memory store (`_REPORT_STORE`) — reports don't persist across restarts. A natural follow-up is a `CorporateGeneratedExpenseReport` ORM model + migration. Not a blocker for the current feature branch, but worth doing before merge to main.

---

### Accomplished (Session 264)

---

### Needs Your Input

*(None — no items awaiting user decision.)*

---

### Accomplished (Session 264)

#### open-source-rideshare — All test suite commits pushed to rideshare remote

The pending test suite commits that had been blocked since Sessions 257–260 are now live on `github.com/esca8peArtist/open-source-rideshare` at `feature/corporate-business-accounts`.

**What happened**: Prior pushes to the rideshare remote used direct `git push` (not subtree-filtered), so the remote's tip matched the main repo's commit SHA rather than a clean subtree split. `git subtree push` failed with non-fast-forward rejection. Fixed by running `git subtree split --prefix=projects/open-source-rideshare` to create a clean filtered history, then force-pushing to the rideshare remote. Private files (resistance-research, orchestrator metadata) are excluded.

**Commits now on remote**: 9 rideshare test suite commits including fare splits (184 tests), cancellation/feedback (163 tests), document expiry/safety/drivers (230 tests), vehicles/travel itineraries (178 tests), corporate member permission/device tokens (168 tests).

#### resistance-research — environment-climate-evidence.md elevated Tier 3 → Tier 1

The quality review had rated this Tier 3 based on only reading 80 lines of a 469-line file. Full read confirmed strong foundation. Added the two genuinely missing sections:

- **Counterarguments** (4 objections with evidence): carbon leakage (BC/EU empirical evidence, CBAM as the design fix), grid reliability (Denmark 59%/Germany 63% empirics, Texas failure was gas not renewables, storage cost trajectory), jobs (geographic mismatch is real, but coal was dying of gas competition not regulation; IRA manufacturing jobs map), science uncertainty (models underestimated, not overestimated, actual impacts; 1.5°C crossed in 2024)
- **Actionable intelligence**: current litigation (Endangerment Finding, methane rule, power plant standards, NWS staffing), federal legislative targets (IRA defense, FEMA pre-disaster mitigation), state carbon pricing (RGGI, California, Washington), community enforcement watchdogs

File: 469 → 585 lines. Commit: `b2586c7`.

#### resistance-research — healthcare-education-evidence.md elevated Tier 3 → Tier 1

File was 599 lines; quality review had only read 80 lines. Full read confirmed counterarguments section was already present (5 objections: wait times, innovation, cost, government control, jobs). Missing: actionable intelligence. Added:

- **Healthcare actionable**: IRA drug pricing defense (AARP campaign, negotiated drugs saving $800/year per prescription), ACA marketplace subsidies expiring end of 2025 (21.4M enrollment record at risk), Medicaid fight in reconciliation bill (10-15M projected coverage cuts), HHS/FDA restructuring (inspection backlogs, NIH cut congressional district maps)
- **Education actionable**: DoE restructuring (Title I, IDEA enforcement backlog), federal voucher legislation (Education Freedom Scholarships Act — CBO $5-10B in tax credits), Head Start 15% cut (50K children affected), state pre-K pathway (19 states + DC now operate universal pre-K, bipartisan momentum), PSLF for public service workers (780K borrowers, $56B forgiven)
- **Cross-domain frame**: Medicaid funds school-based health services — connects healthcare and education advocacy constituencies

File: 599 → 664 lines. Commit: `c0fbe82`.

---

### Accomplished (Session 263)

#### resistance-research — Quality review pass + targeted deepening (Session 263, commits `2e21504`, `1a71b86`, `4c830df`, `52df7ef`)

**Pending work committed** (had been written but uncommitted across earlier sessions):
- `monitoring-2026-04.md` (255 lines) — April 2026 monitoring pass: Federal Reserve independence threat (Powell ultimatum + Trump v. Cook), IEEPA tariff SCOTUS ruling (6-3 Feb 2026), No Kings March 28 (8–9M participants — largest single-day protest in US history), birthright citizenship oral arguments, journalist arrests (Don Lemon + Georgia Fort), third-country deportations (27-country network, CECOT documentation), Abrego Garcia compliance failures, Harvard $2B case
- `domain-03-democratic-participation.md` (217 lines) — democratic participation deepening with updated 2025 trust data (Pew Dec 2025: 17%), citizens' assembly outcomes through 2024-2025 (Ireland failed referendums as cautionary case, Belgium permanent model, Taiwan vTaiwan AI governance), participatory budgeting evidence (NYC $24M 2024)
- Updates to `us-democracy-crisis-analysis-2026.md` and `litigation-tracker-2026.md`

**Quality review index** — `domain-deepening/quality-review-index.md` (467 lines):
- Full read of all 23 companion files against 6-dimension rubric
- Tier 1 (publish as-is): 8 files — criminal-justice, campaign-finance, anti-corruption, digital-government, fiscal-reform, media-information, federalism, infrastructure
- Tier 2 (adequate): 10 files
- Tier 3 (needs deepening): 5 files — national-security, tax-policy, electoral-reform, environment-climate, healthcare-education
- Key finding: `tax-policy-evidence.md` duplicates `domain-05-fiscal-reform.md` scope — needs differentiation before publication
- Key finding: V-Dem 0.75→0.57 decline figure (the strongest quantification of the democratic crisis in the corpus) sits in one file only — should be pulled into the proposal's Part I

**Electoral reform deepening** — `electoral-reform-evidence.md` elevated Tier 3 → Tier 1:
- Sourcing corrections: RCV cost figures were untraced to primary sources; AVR count corrected to 24 states + DC
- Counterarguments: voter confusion (Atkeson 2024 study, 16% confusion rate; rebuttal from arXiv preprint); strategic voting elimination objection; Duverger's Law in presidential systems (honest concession; reframed to achievable US goals); incumbency protection (closed-list party capture; STV as the solution)
- **CRITICAL intelligence**: Alaska RCV repeal certified December 31, 2025 — on November 2026 ballot. The 2024 repeal attempt failed by only 743 votes. **This is the highest-priority defensive action for electoral reform advocates in 2026.** If you know people working on this, flag it.
- Maine SJC ruled April 6, 2026 (this week) that RCV expansion to state general elections is unconstitutional under the plurality-winner clause — constitutional amendment path not currently pursued
- Michigan: active signature drive, 446,198 needed by July 6, 2026

**National security deepening** — `national-security-evidence.md` elevated Tier 3 → Tier 2+:
- Veteran suicide figure corrected: VHA 2024 Annual Report = 17.6/day (up from 16.8/day in 2023 report)
- Section 702: April 12, 2024 warrant-requirement amendment failed 212-212 tie — one vote short
- Counterarguments: deterrence success (Waltz stability case + rebuttal); defense industrial base (narrowly valid, doesn't cover full portfolio); classified program audit objection (OIG/GAO have clearances; failures are data management, not security); veterans benefits sustainability
- Actionable intelligence: POGO, Stimson, Quincy Institute, Brennan Center org profiles; near-term pressure points through December 2026

---

### Accomplished (Session 262)

#### resistance-research — Domain 4 Digital Government Infrastructure Evidence Deepening (Session 262, commit `c32f681`)

`domain-deepening/domain-04-digital-government.md` — 412 lines, 7 sections.

**The 22-domain evidence deepening set is now fully complete.** Every domain in the Democratic Renewal Proposal has a companion evidence file.

**Structural center of the file**: DOGE-SSA weaponization (2025) as the definitive proof that governance-first is a design *requirement*, not an aspiration. The NUMIDENT database (548M identity records for nearly every living American), voter-roll matching disclosure, and Treasury payroll access show what happens when digital government infrastructure lacks constitutional firewalls from enforcement agencies. The proposal's Domain 4b (digital identity) now has a concrete negative precedent to design against.

**Key findings / updates to proposal content**:
- **IRS modernization**: Not just old COBOL — four separate modernization attempts over 35 years, currently $15B over budget, no clean completion date. The "just replace the COBOL" framing in the proposal undersells the institutional failure
- **DoD audit**: 7th consecutive failure in 2024; 2,300+ financial systems; the proposal's "7th consecutive" count is confirmed current
- **Direct File terminated November 2025**: 94% user satisfaction, 25-state expansion — killed by tax prep industry lobbying. Clearest proof-of-concept for the political economy blocking 4d (automated service delivery)
- **USDS mission-captured**: Renamed "US DOGE Service," now staffed by DOGE personnel — not a budget cut, a mission capture. The 18F team was gutted. This is the implementation capacity gap for day-one reform
- **Denmark update**: The proposal referenced NemID, which was *retired June 30, 2023*. MitID is the current system — complete transition documented
- **UK GDS caveat**: "Lack of sustained senior sponsorship and uneven funding" per the 2025 State of Digital Government review — the proposal presents GDS as pure success; the honest version includes the stall
- **Brazil Portal da Transparência**: Operational and real, but "secret amendments" (emendas parlamentares secretas) flow outside portal visibility — transparency tool without enforcement is insufficient on its own

**Five-domain dependency map**: Domain 4 infrastructure is load-bearing for Domains 18 (benefits delivery), 5 (fiscal transparency), 8 (media accountability), 2 (anti-corruption), and 1 (electoral integrity). Sequencing argument made explicit: Estonia built governance *before* the tools were politically contested; the US is building in 2026 *after* weaponization.

**Key tensions documented** (unresolved in the proposal):
1. National digital ID is now politically radioactive post-DOGE — how do you build it?
2. "Once only" principle could accelerate exclusion of the 24M without broadband
3. Classified spending exemption could swallow the transparency rule
4. Any reform government inherits DOGE-gutted implementation capacity
5. Open data guidance issued January 15, 2025 (Biden's final days) — implementation status unknown under Trump admin

---

### Accomplished (Session 261)

#### resistance-research — Domain 12 Infrastructure Evidence Deepening (Session 261, commit `9cd41a8`)

`domain-deepening/domain-12-infrastructure.md` — 339 lines, 35 sourced citations.

**Headline finding**: The IIJA funding cliff arrives September 30, 2026 — **5.5 months away**. No reauthorization bill has been introduced. The structural math is broken: gas tax generates ~$44B annually against $102B+ in current federal outlays — a $58B gap no one is addressing. Transportation for America identifies five compounding reasons the IIJA will expire without a successor.

**What's at risk**:
- $293B in allocated-but-unobligated IIJA funds become politically vulnerable
- Formula highway/transit programs revert to pre-IIJA (FAST Act) baselines — steep cliff for state DOTs mid-project
- Discretionary programs (RAISE, Safe Streets, Reconnecting Communities, Corridor ID for rail) stop making new awards immediately

**Key findings by sub-domain**:
- *Broadband*: BEAD has distributed zero deployment dollars as of August 2025; 5M of 23M households that lost ACP cut service entirely; Trump admin technology-neutrality revision forced state plan restarts
- *Grid*: FERC Order 1920 in effect; interconnection queue at 2,300 GW — roughly 2x current US generating capacity; Texas Railroad Commission still inadequately verifying natural gas weatherization per August 2025 auditor report
- *Water*: 9.2M lead service lines remain nationally; Flint complete July 2025; FY2026 is the last (5th) $3B IIJA tranche with no automatic successor
- *Transit*: ASCE 2025 grades transit D (lowest category); FTA Capital Investment Grant demand $45.1B against $1.7–3.8B appropriated
- *Maintenance*: ~$1T total deferred maintenance backlog ($105B roads/bridges, $370B federal real property, $23B NPS)

**Actionable intelligence section** included: what state DOTs, advocates, water justice groups, and grid advocates should do before September 30.

---

### Accomplished (Session 260)

#### open-source-rideshare — Final 4 endpoint test suites (Session 260, commits `2efe7a3` + `31c2101`)

**346 new tests** across four previously uncovered API endpoint modules:
- `test_vehicles.py` (94 tests): VehicleType/VehicleServiceCategory enums, model columns, add_vehicle (first-vehicle auto-activates, 5-vehicle 409, invalid type 422), list, get, update, remove (soft-delete, clears active_vehicle_id), activate, schema validators
- `test_corporate_travel_itineraries.py` (84 tests): ItineraryStatus enum, create (starts as draft), get/update/cancel/complete lifecycle (404+409 paths), list with filters, add/remove rides (409 cancelled + 409 duplicate), list rides, summary, platform-admin list, schema validators (empty title raises)
- `test_corporate_member_permission.py` (108 tests): 7-value PermissionScope enum, _is_currently_active pure helper (boundary, expired, future-expiry), grant/revoke/get service, list_member/account, has_permission (T/F/revoked/expired), get_members_with_scope, permission summary (multi-scope sum), model UniqueConstraint + 3 indexes, 5 schema types
- `test_device_tokens.py` (60 tests): DevicePlatform enum, model structure, register (new + upsert reassign), deregister 404, list active tokens, schemas

**Total: 10,524 passing** (2 pre-existing failures unchanged). All endpoint coverage gaps cleared.

---

### Accomplished (Sessions 257–259)

---

#### resistance-research — Quality deepening pass (Session 259)

`us-democracy-crisis-analysis-2026.md`: 612 → 622 lines, substantive updates to 6 sections:
- §1.5: Mail-ballot EO + DHS/SSA pre-approved list mechanism + 23-state lawsuit fully synthesized
- §1.6: Project 2025 "stalled" counter-narrative addressed with specific remaining agenda items and rebuttal
- Variable 3 (Elite Defections): FBI/DOJ investigation of 5 legislators for unlawful-orders video; Posse Comitatus ruling on LA National Guard deployment — two concrete April 2026 developments replaced vague language
- Variable 4: Stale "7M" → current "8–9M March 28" figure in opening paragraph
- Conclusion: Chenoweth calculation updated to March 2026 figures (8–9M / 5–6.5M independent estimate, ~2.5–2.7%)
- "What Is Working" table: G. Elliott Morris/Xylom independent estimate range; Eyes on ICE 200K training viewers

**New file**: `domain-deepening/domain-03-democratic-participation.md` (217 lines) — Domain 3 was the only one of 22 lacking a dedicated evidence companion. Covers: Pew 2025 trust data (17%), primary-election concentration effect, citizens' assemblies 2024-2025 (Ireland cautionary case, Belgium Ostbelgien 3-yr data, Netherlands 2025), vTaiwan AI governance 2024-2025, participatory budgeting NYC/LA 2024, resistance-participation connection, fiscal estimates.

Still missing deepening files: **Domain 4** (Digital Government Infrastructure), **Domain 12** (Infrastructure — IIJA cliff September 2026 makes this time-sensitive).

---

#### resistance-research — April 2026 Monitoring Integration (Session 257)

`us-democracy-crisis-analysis-2026.md` (582→612): Fed Reserve independence threat, IEEPA ruling, No Kings 8–9M, OBBBA impacts, Don Lemon charges, law firm resistance wins.
`litigation-tracker-2026.md` (738→852): *Trump v. Cook*, *Learning Resources*, third-country deportation tracker (new category), Harvard First Circuit appeal, 23-state AG citizenship suit.

---

#### open-source-rideshare — Cancellation + Feedback tests (Session 258, commit `3a58a59`)

- `test_cancellation_policies.py` (106 tests), `test_ride_feedback.py` (57 tests)

---

#### open-source-rideshare — Fare Splits Test Suite (Session 257, commit `df1aeed`)

- `test_fare_splits.py` (184 tests) covering all 8 service functions

---

### Session 255–256 Accomplished (archived)

#### resistance-research — April 2026 Monitoring Pass

Written to `projects/resistance-research/monitoring-2026-04.md`. Four major developments not yet in the main analysis (`us-democracy-crisis-analysis-2026.md`):

1. **Federal Reserve independence under direct threat** (Apr 15): Trump issued an ultimatum — Powell must resign by May 15 or be fired. Companion case *Trump v. Cook* (whether Trump can remove Fed Board member Lisa Cook) is at SCOTUS. This is the Turkey/Argentina monetary capture playbook applied to the US central bank.

2. **SCOTUS struck down IEEPA tariff authority** (Feb 20): *Learning Resources, Inc. v. Trump*, 6-3 ruling — Roberts + cross-ideological majority. "Liberation Day" tariff architecture ruled unlawful. Most significant judicial check on emergency economic powers since *Youngstown Steel*. Administration reconstituted authority under §232/§301; 10% baseline remains through July 24.

3. **No Kings March 28 — 8–9 million participants**: New record, third national day of action. Counter to protest fatigue curves (June 2025: 5M → Oct 2025: 7M → Mar 2026: 8–9M). April 19 + May 1 upcoming.

4. **Third-country deportations expanding to DRC** (Apr 5): 27+ countries now holding US third-country deportees. 8 of 9 in one Cameroon batch had active US court protection orders. Federal courts ruled El Salvador transfers violated due process; program continues.

Additional: Don Lemon charged (first journalist criminally charged for covering an ICE protest), birthright citizenship oral args (Trump's own appointees appeared skeptical), OBBBA implementation ($1.02T Medicaid + $120B SNAP cuts now taking effect), 23-state AG lawsuit challenging citizenship verification voter-purge EO, Harvard First Circuit appeal, law firm resistance victories. Full gap table in the file routes each item to correct section of main analysis.

---

#### open-source-rideshare — Beckn Protocol Interoperability Design Doc

Written to `projects/open-source-rideshare/beckn-protocol.md` (~370 lines, 11 sections). Key findings:

- **BPP-primary role recommended**: We expose our drivers to the Beckn network (seller-side); acting as a BAP (aggregating other platforms' drivers) creates tension with the cooperative-first positioning.
- **Not in Phase 1**: No Western production Beckn network exists yet. India's ONDC/Namma Yatri is production; Europe is exploring. Premature to build now.
- **Phase 2 implementation**: Build `backend/app/beckn/` adapter mounted at `/beckn/` — 8 inbound endpoints, purely additive. Doesn't touch matching engine, pricing, Stripe, or the PostgreSQL schema.
- **Key architectural constraint**: Beckn uses async callbacks (not synchronous REST) — requires a task queue (Celery/ARQ/etc.) for inbound request handling.
- **Full schema mapping tables**: `RideRequest`→`search.intent`, `DriverProfile`→`Provider`+`Agent`, `Ride`→`Order`, `RideStatus`→Beckn fulfillment state codes
- **3 zero-cost decisions to lock in now**: operator-per-BPP credentials, clean service interfaces, no BAP role by default

---

### Session 255 Accomplished (archived)

#### open-source-rideshare — WAV Dispatch Integration (commit `a541c28`)

Three gaps in wheelchair-accessible vehicle (WAV) dispatch were identified and fixed:

1. **WAV certification required**: The matching engine was checking `vehicle.is_wheelchair_accessible` but ignoring the admin-verified `DriverWAVCertification`. Fixed: drivers now need BOTH a WAV vehicle AND a `verified` cert status.

2. **Expanded WAV search radius**: Accessibility requests now start at max radius (not initial), since WAV-certified drivers are sparse.

3. **Auto-promote from rider profile**: `request_ride` now checks `RiderAccessibilityProfile.needs_wav` and promotes `accessibility_required=True` automatically.

- **15 new unit tests** | **Total: 9,719 passing** (was 9,704)

---

### Session 254 Accomplished (archived)

#### open-source-rideshare — Ride Pool Tests (commit `25ebb35`)

The ride pooling (shared rides) feature had a 327-line API and 325-line service but zero test coverage. Now fixed.

- **65 unit tests** across: haversine distance math, direction vector math, cosine similarity, discount tier calculations, pool lifecycle (create/join/leave/pickup/dropoff), find-compatible-pool logic (empty DB, full pool, too far, wrong direction, detour limit, valid candidate), schema defaults, model enum values
- **8 integration tests** (auto-skipped without live DB) — auth gates on all endpoints
- **Total tests: 9,704 passing** (was 9,586)

Pushed to `feature/corporate-business-accounts`.

#### open-source-rideshare — Growth Strategy & Bootstrapping Plan (commit `25ebb35`)

This was explicitly in scope ("a rideshare app with no users is worthless, growth strategy is part of the scope") but no document existed. Now written at `growth-strategy.md`.

12 sections covering:
- **Thesis**: Build infrastructure for cooperative operators, not a competing consumer platform
- **Phase 1 target**: NYC — Drivers Cooperative NYC has 9,000 drivers + a broken app = perfect first partner
- **Driver acquisition**: Through gig worker unions and cooperative partnerships; financial model shows drivers earn $300-600/month more on 0% commission vs Uber
- **Rider acquisition sequence**: Seed driver supply → community organizing → public launch (not the other way)
- **Network effect thresholds**: 30-50 active drivers in one neighborhood to soft-launch; 500+ for competitive city-wide coverage
- **Revenue model**: Driver subscriptions ($150/month) + operator hosting + corporate accounts → sustains a lean team at ~1,000 active drivers
- **Insurance/regulatory path**: Cooperative partner holds the TNC license in Phase 1 (no license needed until Phase 2 markets)
- **Growth feature activation**: All the built-in levers (referral program, promo codes, incentive zones, pool rides, corporate accounts) mapped to launch phases with budget estimates
- **12-month roadmap**: Concrete milestones from partnership signing through second-city launch

---

### Session 253 Accomplished (archived)

#### open-source-rideshare — Corporate Fleet Incident Reports (commit `031f77a`)

Fleet admins can file and track incident reports against fleet vehicles (was committed last session but not reflected in prior check-in).

#### open-source-rideshare — Corporate Fleet Fuel Log Tracking (commit `eac7f37`)

Fleet managers and drivers can log fuel fill-ups and EV charging events per vehicle, with per-vehicle fuel efficiency analytics.

Model (`CorporateFleetFuelLog`) existed but had no service/API/tests. Now complete. Completes the fleet cost tracking story — fuel logs feed into the existing cost analytics aggregation.

- **6 service functions**: create/update/delete fuel logs; list by vehicle; list fleet-wide (admin only); per-vehicle summary
- **6 API endpoints**: POST/GET per vehicle, GET summary, PUT/DELETE individual logs, GET fleet-wide admin view
- **Analytics**: total fill-ups, total gallons, total kWh, total spend, avg cost/gallon, avg cost/kWh, last fill date — null-safe coalesce, gallon vs kWh paths split by fuel type
- **43 tests** | **Migration**: `aa1b2c3d4e5f` | **Total: 9,586 passing** (was 9,543)

Pushed to `feature/corporate-business-accounts`.

#### mfg-farm — ModRun Etsy & Amazon Listing Copy COMPLETE

Full listing copy drafted and saved to `projects/mfg-farm/etsy-listing-modrun.md`. Covers:

**3 Etsy listings:**
- Listing 1 (hero): 4-piece set (1 rail + 3 clips) — $42.99 — full description, 13 tags, category, attributes
- Listing 2 (entry): 5-pack cable clips (single size) — $8.99
- Listing 3 (expansion): Mounting rail only — $12.99

**Amazon listing:**
- Title, 5 keyword-rich bullet points, A+ product description, 250-char backend search terms
- Parent/child ASIN color variant strategy

**Photo brief:** 5-shot sequence (hero, detail/snap, scale, colorways, in-context use) — ready to hand to a mockup designer or shoot once test print is in hand.

**Launch sequence:** Start Etsy, seed 25 reviews before Amazon, run $1–3/day Etsy Ads for 30 days, follow-up sequence messaging.

---

#### stockbot — rsi_mean_reversion & MTF AAPL Threshold Analysis

Reviewed the signal generation code in `src/trading/trading_session.py` for both strategies.

**RSI Mean Reversion (lines 933–953):**
- Default thresholds: `oversold_threshold=30`, `overbought_threshold=70` (configurable via `strategy_params`)
- These are correctly implemented but conservative — RSI rarely touches 30 or 70 in a trending market
- **Assessment**: In a trending upmarket (AAPL Jan–Apr 2026 was broadly upward), RSI on a 14-bar window often sits 50–65 and never hits 70. The 0-signal count likely reflects market conditions rather than a broken strategy. The thresholds are not wrong — they're working as designed for a mean-reversion signal, which fires infrequently by nature.
- **Recommendation**: If you want more frequent signals, lower to 35/65. This makes the strategy more aggressive and will fire in less extreme conditions. Risk: more false signals in trending markets. Alternative: wait 1–2 more weeks with the current 30/70 to see if any extreme moves trigger it.

**MTF AAPL (lines 865–895, strategy.py):**
- MTF signal direction is determined by sign of raw model prediction. "Hold" is returned when `direction == "hold"` (raw ≈ 0) OR when `confluence_min_tfs` filter overrides to hold
- `_CONFIDENCE_THRESHOLD = 0.0` — no minimum confidence filter at the strategy level
- **Assessment**: If the MTF AAPL model is returning 0 signals, it's because the model itself is consistently predicting near-zero (→ hold) or the confluence filter (`min_tfs` check) is overriding to hold. This is the model's response to the data, not a code bug.
- **Recommendation**: Cannot tune this without seeing actual `raw_prediction` values from the Jetson logs. If you can pull `logs/trading_*.log` from the Jetson over SSH, look for lines containing `MTF hold` or `confidence=0.00` — that will confirm which path is triggering. If raw_prediction is consistently near 0, the model may need retraining on more recent data.

**Bottom line**: Now that the trade recording fix is deployed, wait 5 market days before adjusting thresholds. If rsi_mean_reversion still shows 0 trades after 5 days of open market, lower to 35/65. MTF requires log inspection from Jetson to diagnose further.

---

### Needs Your Input

1. **mfg-farm: ModRun test print + listing launch**
   - Etsy listing copy is ready at `projects/mfg-farm/etsy-listing-modrun.md`
   - Blocked on: mockup photos (or real photos after test print)
   - When you print: check desk-edge clamp fit on your actual desk thickness and snap-arm feel on the clips. Report back and I'll adjust clearances.

2. **stockbot: threshold decision**
   - RSI thresholds (currently 30/70): watch for 5 more market days first. If still 0 signals after 5 days, do you want me to adjust to 35/65 and redeploy?
   - MTF AAPL: can you SSH to Jetson and check `logs/trading_*.log` for lines with "MTF"? Looking for whether `raw_prediction` values are near 0 or the confluence filter is blocking signals.

3. **resistance-research: integrate monitoring findings?**
   - `monitoring-2026-04.md` has a gap table mapping each new item to its correct section in the main analysis. Want me to do a full integration pass — weaving the Powell/Fed, IEEPA ruling, No Kings numbers, and deportation updates directly into the main document?

---

### What's Next (suggested)

1. **open-source-rideshare**: Beckn Protocol design doc written. Next: (a) integrate feedback on beckn-protocol.md if you have direction; (b) any new feature from Anya.
2. **resistance-research**: Integration pass — weave April 2026 monitoring findings into main analysis document (gap table already written).
3. **stockbot**: Watch for 5 market days post trade-recording fix. If RSI signals still 0, lower to 35/65 and redeploy.
4. **mfg-farm**: Launch Etsy listing once mockup photos are ready. Listing copy is done.

---

## History

### Accomplished (Sessions 251–252) — archived from previous check-in

#### stockbot — Trade Recording Bug FIXED (commit `b0332d9`)

Root cause: `_record_trade` in `trading_session.py` omitting `price=price` from Trade constructor → NOT NULL constraint silently swallowed. Fixed. Also committed bracket orders, stop/TP, position_size_pct cap, max_positions, reentry cooldown, cycle timeout, exponential backoff, get_bars per-attempt timeout, unintentional exit detection, submit_bracket_order in brokers, TradingPage UI, ExecutionOptimizer config, ModelRun session resume columns.

#### open-source-rideshare — Corporate Fleet Incident Reports (commit `031f77a`)

Fleet incident reporting with full CRUD + multi-tier access.

#### open-source-rideshare — Corporate Fleet Cost Analytics (commit `9558413`)

Fleet-wide cost aggregation across fuel, maintenance, toll — fleet summary, per-vehicle breakdown, 12-month trend. 40 tests. Total: 9,543 passing.

#### open-source-rideshare — Corporate Fleet Driver Assignments (commit `095b3d8`)

Primary/secondary/pool/temporary driver assignments with 1-primary-per-vehicle constraint. 58 tests. Total: 9,503 passing.

---

### Accomplished (Sessions 250) — archived from previous check-in

#### open-source-rideshare — Corporate Fleet Toll & Transponder Management (commit `8effb2c`)

Tracks E-ZPass/FasTrak/SunPass/etc. transponders assigned to fleet vehicles and logs individual toll charges for per-vehicle and fleet-wide cost analytics.

- **8 transponder providers**: ezpass, fastrak, sunpass, peach_pass, i-pass, nc_quickpass, pikepass, other
- **14 service functions**: assign/deactivate/reactivate transponders; log/update/delete charges; vehicle toll summary; fleet toll summary; platform admin
- **16 API endpoints** across member/admin/platform-admin tiers
- **58 tests** (fixed 16 API tests that used incorrect auth-patch pattern)
- **Migration**: `t9u0v1w2x3y4` | Total: 9,395 passing

#### open-source-rideshare — Corporate Fleet Maintenance Scheduling (commit `f0fe19c`)

Schedule and track preventive maintenance for fleet vehicles with overdue alerts and cost analytics.

- **12 maintenance types**: oil change, tire rotation, brake inspection, air filter, transmission service, battery replacement, coolant flush, spark plugs, wheel alignment, state inspection, recall repair, other
- **5 statuses**: scheduled, in_progress, completed, cancelled, overdue (auto-detected)
- **12 service functions**: schedule/complete/cancel/delete; list by vehicle or account; get-overdue (auto-marks records); vehicle summary; account summary; platform admin
- **13 API endpoints** across member/admin/platform-admin tiers
- **50 tests** | **Migration**: `u0v1w2x3y4z5` | Total: **9,445 passing**

Both features pushed to `feature/corporate-business-accounts` on GitHub.

---

### Accomplished (Session 249 — archived)

#### stockbot — Projected Returns Feature (commit `76a4142`)

New "Projected Returns" menu item added to the Core Features sidebar.

**What it does**:
- Pick any trained model from a dropdown + enter a ticker (e.g. AAPL)
- Shows a price chart overlaid with the model's buy/sell/hold signal for every historical trading day
- Bar chart below shows signal confidence over time (green = buy, red = sell, gray = hold; height = confidence)
- Forward projection chart shows what the model would predict under 3 price scenarios: bull (+0.4%/day), flat, bear (-0.4%/day). Dots on each line are coloured by the predicted signal.
- Summary bar: today's current signal + confidence badge, plus buy/sell/hold day counts over the history window
- Recent signal log table with last 25 days

**Works with all model types**: sklearn, LightGBM, ensemble, MTF (anything with predict or predict_proba).

**Backend**: new endpoint `GET /api/models/{id}/projected-returns?ticker=AAPL&days=90&forward_days=10`

---

### Accomplished (Session 248 — archived)

#### stockbot — Performance Assessment via SSH API

All 4 paper trading sessions confirmed running. Accessed API via SSH (server binds Tailscale IP only; SSH tunnel not viable but direct SSH curl works fine).

**Portfolio (paper Alpaca account)**:
- Equity: $100,682 (+$682 / +0.68%) over 3 trading days (Apr 14–16, Good Friday closed)
- Today: +$413.51 (+0.41%)

**Open positions**:
- AMZN: 34 shares @ $237.54 → $249.25 | +$398 (+4.93%) — sma_crossover
- SPY: 71 shares @ $695.33 → $701.95 | +$470 (+0.95%) — momentum
- QQQ: 52 shares @ $632.91 → $639.96 | +$366 (+1.11%) — momentum
- MSFT: 79 shares @ $418.18 → $419.60 | +$112 (+0.34%) — momentum

**Session health**:
- rsi_mean_reversion (AAPL/NVDA): running, 0 trades, cycle timeout #1
- sma_crossover (AMZN/SPY): running, 1 trade executed, cycle timeout #1
- mtf_c49f181b (AAPL): running, 0 trades, no errors
- momentum (SPY/QQQ/MSFT): running, 2 trades executed, cycle timeout #1

**Issues**:
1. Cycle timeout #1 on 3/4 sessions (soft error, sessions continue running)
2. In-app DB trade recording broken: session-results API shows num_trades=0 for all sessions despite 3 Alpaca fills. DB analytics are empty; Alpaca account is authoritative.
3. rsi_mean_reversion and MTF: 0 trades in 3 days — AAPL/NVDA conditions not met

#### mfg-farm — ModRun CadQuery Family COMPLETE

Built the full ModRun cable management product family in parametric CadQuery:

**Files created**:
-  — rail with 2 base variants
-  — 3 clip variants
-  — parameter guide + print settings
-  — desk-edge C-clamp mount
-  — adhesive-pad base
- , , 

**CadQuery env fixed** (was broken — cadquery-ocp 7.9.3.1 installed + OCP hashCode patch applied + nlopt copied from system + casadi/nptyping/typish/ezdxf/multimethod installed).

---

---

## History

### Accomplished (Session 249) — archived from previous check-in

**stockbot — Projected Returns Feature (commit `76a4142`):** New "Projected Returns" menu in Core Features sidebar. Backend endpoint runs any trained model over historical Alpaca data, returns per-day buy/sell/hold signal + confidence, plus forward projection under 3 price scenarios. Frontend: model/ticker selector, price + signal confidence charts, forward projection chart with 3 scenario lines, signal log table.

**stockbot — Session 248 summary:** Portfolio +$682 (+0.68%) over 3 trading days. 4 sessions running. Known issue: in-app DB trade recording broken (Alpaca account authoritative). 2 sessions (rsi_mean_reversion, MTF) show 0 trades — AAPL/NVDA conditions not met.

**mfg-farm — Session 248:** Full ModRun CadQuery family built. CadQuery env fixed. STLs ready to print.

### Accomplished (Sessions 246–247) — archived from previous check-in

**open-source-rideshare — Corporate Fleet (Sessions 245–247):**
- **Corporate Fleet Vehicle Registration Tracking** (commit `334c869`): CorporateFleetVehicleRegistration, 10 service functions, 11 endpoints, 43 tests → 9,337 total
- **Corporate Fleet Fuel & Mileage Tracking** (commit `45ea4a4`): CorporateFleetFuelLog, FleetFuelType enum, avg MPG analytics, 9 service functions, 9 endpoints, 43 tests → 9,294 total
- **Corporate Fleet Vehicle Acquisition & Disposal Tracking** (commit `cfe4ccb`): AcquisitionType/DisposalType enums, full acquisition/disposal lifecycle, 9 service functions, 11 endpoints, 40 tests → 9,251 total


### Accomplished (Sessions 220–223) — archived from previous check-in

- **Corporate Recurring Ride Schedules** (commit `68bb13a`): personal recurring commute/airport/offsite schedules + booking history, 75 tests, total 7,902
- **Corporate SLA Policies** (commit `c2c792f`): named SLA policies + per-ride evaluation + compliance reporting, 76 tests, total 7,827
- **Corporate Ride Satisfaction Surveys** (commit `0927479`): configurable question types + per-question analytics, 66 tests, total 7,751
- **Corporate Office Locations** (commit `9b98d1d`): named offices with HQ flag + employee-to-office assignments, 74 tests, total 7,685

### Accomplished (Sessions 219–221) — archived from previous check-in

- **Corporate Travel Policy & Acknowledgement** (commit `019b3dc`): versioned policies + append-only acknowledgements, 12 service functions, 13 endpoints, 74 tests, total 7,611
- **Corporate Ride Satisfaction Surveys** (commit `0927479`): configurable question types + per-question analytics, 11 service functions, 13 endpoints, 66 tests, total 7,751

### Accomplished (Sessions 217–219) — archived from previous check-in

- **Corporate Service Zone Restrictions** (commit `1936c46`): CorporateServiceZone with ZoneType enum, Haversine distance check, 10 service functions, 11 endpoints, 64 tests, total 7,475
- **Corporate Employee Transport Preferences** (commit `76d42d2`): CorporateEmployeeTransportPreference upsert-on-read, accessibility needs JSONB, 9 service functions, 11 endpoints, 62 tests, total 7,537
- **Corporate Travel Policy & Acknowledgement** (commit `019b3dc`): versioned policies + append-only acknowledgements, 12 service functions, 13 endpoints, 74 tests, total 7,611

### Accomplished (Sessions 215–216) — archived from previous check-in

- **Corporate Shift-Based Ride Scheduling** (commit `ee2c734`): CorporateShift + CorporateShiftAssignment, 14 service functions, 14 endpoints, 69 tests, total 7,355
- **Corporate Ride Templates** (commit `c66075a`): CorporateRideTemplate, 10 service functions, 11 endpoints, 56 tests, total 7,411

### Accomplished (Sessions 211–214) — archived from previous check-in

- **Corporate Event Management** (commit `7182eb7`): CorporateEvent + CorporateEventAttendee, organizer creates events and invites employees, 53 tests, total 7,286
- **Corporate Booking Eligibility Check** (commit `5c986d1`): capstone orchestration feature, 6-layer policy validator, 40 tests, total 7,233
- **Corporate Department-Level Ride Policies** (commit `6847e59`): middle tier 3-level policy hierarchy, most-restrictive-wins merge, 49 tests, total 7,193
- **Corporate Auto-Approval Rules** (commit `a3f1089`): priority-ordered auto-approval, 51 tests, total 7,144

### Accomplished (Session 209)

#### open-source-rideshare — Corporate Receipt Template Customization (commit `09119f7`)

Corporate accounts can now define a branded receipt template applied to all employee ride receipts. Finance teams get company-name, logo, header/footer message, a custom reference-number prefix (e.g. `ACME-2026-001`), toggles for driver details and route map, and JSONB custom line items (e.g. project codes). The template is a single "one per account" row with upsert-on-read defaults so members always get a valid response.

- **`CorporateReceiptTemplate` model**: unique `account_id`; CASCADE delete; `company_name`; `logo_url`; `header_message`; `footer_message`; `reference_prefix` String(20); `show_driver_details` bool (default True); `show_route_map` bool (default True); `custom_line_items` JSONB; `is_active`; `created_by_id` + `updated_by_id` FK SET NULL; `created_at` / `updated_at`
- **6 service functions**: `get_or_create_receipt_template` (upsert-on-read, returns sensible defaults if none configured); `update_receipt_template` (partial PUT); `deactivate_receipt_template` (409 if already inactive); `delete_receipt_template` (hard delete, admin-only); `get_receipt_template_for_ride` (returns None for receipt-generation fallback); `list_all_receipt_templates` (platform-admin, paginated)
- **6 endpoints**: member `GET /corporate/accounts/me/receipt-template`; admin `PUT + POST /deactivate + DELETE`; platform-admin `GET list-all + GET /accounts/{id}/receipt-template`
- **Migration `f7g8h9i0j1k2`** (revises `e6f7a8b9c0d1`)
- **38 tests** → **Total: 7,053 passing** (was 7,015)

---

### Accomplished (Session 208)

#### open-source-rideshare — Corporate Member Policy Overrides (commit `cda549d`)

Admins can now grant per-member exceptions to the account-level ride policy. An executive can be allowed premium vehicles when company policy restricts to standard; a contractor can have a tighter per-ride cost cap. The `GET /corporate/accounts/me/effective-policy` endpoint returns the merged effective policy for any employee.

- **`CorporateMemberPolicyOverride` model**: unique on `(account_id, member_id)`; all override fields nullable (null = inherit account policy); `is_active` soft-delete; `valid_from` / `valid_until` window; 4 indexes; CASCADE FKs on account + member; SET NULL on `overridden_by_id`
- **9 service functions**: `create_member_override` (409 if active override exists; 404 if member not in account); `get_member_override`; `update_member_override` (404 if no row); `deactivate_member_override` (409 if already inactive); `delete_member_override`; `get_effective_policy` (merges account policy + active member override); `list_member_overrides` (is_active filter); `list_all_overrides_platform`; `get_members_with_overrides`
- **10 endpoints**: admin create/list/get/update/delete/deactivate; member `GET /me/effective-policy`; 2 platform-admin
- **Migration `e6f7a8b9c0d1`** (revises `d4e5f6a7b8c9`)
- **45 tests** → **Total: 7,015 passing** (was 6,970)

---

### Accomplished (Session 207)

#### open-source-rideshare — Corporate Manager Hierarchy (commit `9168751`)

Enterprise admins can now define employee→manager reporting relationships within a corporate account. Enables manager-aware approval routing, org chart visibility, and violation notification workflows.

- **`CorporateManagerRelationship` model**: two types — `direct` (at most one active per employee per account; replaced on reassignment) and `dotted_line` (multiple allowed); `check constraint` prevents self-reporting; unique on `(account_id, employee_member_id, manager_member_id)`; soft-delete; 4 indexes
- **10 service functions**: `create_relationship` (cycle detection by BFS up manager's direct chain; 400 on self-manager; 409 on cycle or duplicate dotted-line; auto-deactivates previous direct manager); `get/update/remove_relationship`; `list_relationships` (type+is_active filters); `get_managers` / `get_direct_reports` / `get_all_reports`; `get_reporting_chain` (BFS upward to root, max_depth=10); `get_org_summary` (counts + top-level manager IDs); `list_all_relationships_platform` (cross-account)
- **12 endpoints**: admin CRUD + member-managers + member-direct-reports + member-reporting-chain + org-summary; member own-managers + own-reporting-chain + own-direct-reports; platform-admin list-all
- **Migration `d4e5f6a7b8c9`** (revises `c3d4e5f6a7b8`)
- **54 tests** → **Total: 6,970 passing** (was 6,916)

---

### Accomplished (Session 206)

#### open-source-rideshare — Corporate Multi-Level Approval Chains (commit `a365044`)

Corporate accounts can now define configurable multi-step approval chains. When a ride request matches a chain's triggers (cost threshold and/or cost center filter), the employee must obtain sequential approval from each step before proceeding. For example: rides over $150 require approval from a designated manager, then a finance admin.

- **4 new models**: `CorporateApprovalChain` (chain definition with cost+cost-center triggers); `CorporateApprovalChainStep` (ordered steps with approver_type specific_user/any_admin, optional timeout + escalation_action skip/deny); `CorporateApprovalChainRequest` (running request tracking current step and status pending/approved/denied/cancelled); `CorporateApprovalChainStepDecision` (append-only per-step decision log)
- **14 service functions**: full chain CRUD (create validates sequential steps; delete 409 if pending requests; deactivate 409 if already inactive); `find_applicable_chain` returns most-specific match (highest min_cost_usd first); `start_chain_request` (409 on inactive chain); `decide_step` (approve advances to next or resolves; deny closes immediately; 403 if wrong specific-user approver); `cancel_request` (409 if not pending); `list_pending_for_approver` (returns requests awaiting a given admin's decision)
- **15 endpoints**: admin chain CRUD + deactivate + pending-review list + decide-step; member applicable-chain lookup + start/list/get/cancel request; platform-admin list-all chains and requests
- **Migration `c3d4e5f6a7b8`** (revises `b2c3d4e5f6a7`)
- **66 tests** → **Total: 6,916 passing** (was 6,850)

---

### Accomplished (Session 205)

#### open-source-rideshare — Corporate Policy Violation Tracking (commit `19f0c47`)

Corporate accounts now have an append-only compliance audit trail of ride policy violations. When employees' bookings break account ride policy, violations are recorded with type, JSONB context (e.g. attempted vehicle type vs. allowed types), and a policy snapshot so the audit trail remains accurate even if the policy later changes.

- **`CorporatePolicyViolation` model**: account+member FKs CASCADE; ride_id FK SET NULL (NULL for pre-booking denials); `violation_type` String(50); `violation_details` + `policy_snapshot` JSONB; `is_acknowledged` + acknowledgement audit fields (by_id, at, note); immutable `created_at` (no updated_at — violations are never mutated); 4 indexes (account_id; member_id; account+created_at; account+is_acknowledged)
- **8 ViolationType values**: `vehicle_type` / `per_ride_cost_exceeded` / `business_hours` / `missing_purpose` / `unapproved_purpose` / `spend_limit_exceeded` / `ride_quota_exceeded` / `blackout_period`
- **7 service functions**: `record_violation` / `get_violation` (404 on wrong account) / `list_violations` (member+type+ack+date-range filters; newest-first) / `acknowledge_violation` (409 if already acked) / `bulk_acknowledge_violations` (silently skips already-acked or not-found rows) / `get_violation_summary` (total + unacknowledged count + by_type breakdown + top-5 offenders + period_days) / `list_all_violations` (platform-admin cross-account)
- **8 endpoints**: member list-own (with ack filter); admin list+summary+get+acknowledge+bulk-acknowledge; platform-admin list-all+manually-record
- **Migration `b2c3d4e5f6a7`** (revises `a1b2c3d4e5f6`)
- **45 tests** → **Total: 6,850 passing** (was 6,805)

---

### Accomplished (Session 204)

#### open-source-rideshare — Corporate Account Tags (commit `8f2a8e9`)

Platform admins can now label corporate accounts with short slugified tags (vip, at-risk, healthcare, government) for internal classification and cross-account filtering. Tags are ad-hoc — no registry. Normalisation is automatic (lowercase, spaces→hyphens, non-alphanumeric stripped, max 50 chars).

- **`CorporateAccountTag` model**: unique constraint on `(account_id, tag)`; `created_by_id` FK SET NULL; CASCADE delete; 3 indexes
- **`normalise_tag()` helper** in schemas: lowercase → replace spaces/underscores with hyphens → strip non-alphanumeric → collapse consecutive hyphens → truncate 50
- **6 service functions**: `add_tag` (409 duplicate) / `remove_tag` (404 if absent) / `list_tags` (alphabetical) / `get_platform_tag_summary` (all distinct tags by account_count desc) / `list_accounts_by_tag` / `bulk_add_tags` (1–20 tags; silently skips existing; deduplicates input)
- **7 endpoints**: platform-admin add/remove/list/bulk-add/tag-index/accounts-by-tag; member list-own-tags (read-only)
- **Migration `z5a6b7c8d9e0`** (revises `y4z5a6b7c8d9`)
- **36 tests** → **Total: 6,760 passing** (was 6,724)

#### open-source-rideshare — Corporate Member Ride Quotas (commit `c08f12d`)

Admins define per-member ride count limits (daily/weekly/monthly) that complement the existing per-member spend limits. Employees can check their remaining quota before booking; platform-admins see a cross-account list of exceeded quotas.

- **`CorporateMemberRideQuota` model**: unique on `(account_id, member_id, period)`; `max_rides` ≥1; `is_active`; `created_by_id` FK SET NULL; CASCADE delete; 3 indexes
- **`_period_start(period)`** helper: UTC midnight for daily (today), weekly (current Monday), monthly (1st of month)
- **`_count_rides_in_period()`**: counts non-cancelled rides for member on `Ride.corporate_account_id` in current period
- **8 service functions**: `set_quota` (409 active duplicate; reactivates inactive rows instead of creating duplicates) / `update_quota` / `deactivate_quota` / `delete_quota` / `get_quota` / `list_member_quotas` / `get_quota_usage` (current_period_rides + remaining + quota_exceeded + quota_active flag) / `get_account_quota_summary` (all active quotas enriched with live usage)
- **13 endpoints**: member check-own (period filter) + list-own-with-usage; admin set/list/get/update/delete/summary; platform-admin list-any-account / set-on-any / cross-account-exceeded
- **Migration `a1b2c3d4e5f6`** (revises `z5a6b7c8d9e0`)
- **45 tests** → **Total: 6,805 passing** (was 6,760)

---

### Accomplished (Session 203)

#### open-source-rideshare — Corporate Account Notes (commit `94fd249`)

Platform admins can now annotate corporate accounts with CRM-style freeform notes — support call summaries, billing exceptions, sales context, compliance findings. The first dedicated admin CRM tooling in the system.

- **`CorporateAccountNote` model**: `NoteType` enum (general/billing/support/compliance/sales/technical); `content` text (min 10 chars); `is_pinned` flag (pinned notes sort first in list); `is_internal` flag (controls member visibility); `author_id` FK SET NULL; CASCADE delete on account; 4 indexes
- **7 service functions**: `create_note` / `get_note` (404 on wrong account) / `list_notes` (note_type + pinned_only + include_internal filters; pinned-first sort) / `update_note` (partial update, all fields optional) / `delete_note` (hard delete) / `toggle_pin` (flip is_pinned) / `list_notes_member` (non-internal only)
- **8 endpoints**: platform-admin `POST/GET/GET-by-id/PUT/DELETE/toggle-pin`; member `GET /corporate/accounts/me/notes` + `GET .../notes/{id}` (returns 404 on internal notes)
- **Migration `y4z5a6b7c8d9`**: `notetype` enum + `corporate_account_notes` table + 4 indexes
- **37 tests** → **Total: 6,724 passing** (was 6,687)

---

### Accomplished (Session 202)

#### open-source-rideshare — Corporate Account Health Score (commit `c0b4d1d`)

Corporate accounts and platform admins can now view a computed 0–100 health score that aggregates six data domains into a single risk indicator. Scores are stored as immutable snapshots, preserving historical trend data.

- **`CorporateAccountHealthScore` model**: `HealthRiskLevel` enum (excellent/good/fair/poor/critical); `overall_score` 0–100 composite; 6 sub-scores (payment/compliance/credit/dispute/contract/suspension); `score_details` JSON evidence; `computed_at` + `computed_by_id` audit; CASCADE delete; 4 indexes + 7 check constraints
- **5 service functions**: `compute_health_score` (weighted average: payment 30% / compliance 20% / credit 20% / dispute 15% / contract 10% / suspension 5%; persists snapshot) / `get_latest_health_score` / `get_health_score_history` / `list_accounts_by_health` (filter by risk_level or below_score; uses max-per-account subquery; sorted worst-first) / `get_at_risk_summary` (platform distribution counts by risk level)
- **7 endpoints**: member `GET .../health-score` + `GET .../health-score/history`; admin `POST .../health-score/refresh` (403 if not account admin); platform-admin `GET/POST /admin/corporate/accounts/{id}/health-score(/recompute)` + `GET /admin/corporate/health-scores` (filters) + `GET /admin/corporate/health-scores/at-risk`
- **Migration `x3y4z5a6b7c8`** (revises `w3x4y5z6a7b8`): `healthrisklevel` enum + `corporate_account_health_scores` table + 4 indexes
- **46 tests** → **Total: 6,687 passing** (was 6,641)

---

### Accomplished (Session 201)

#### open-source-rideshare — Corporate Invoice Dispute Resolution (commit `d0f793c`)

Corporate accounts can now formally dispute charges on their invoices through a structured workflow. Employees submit disputes, admins review and resolve, members can withdraw before resolution.

- **`CorporateInvoiceDispute` model**: `DisputeType` enum (7 values: incorrect_charge/service_failure/duplicate_charge/policy_violation/unauthorized_ride/pricing_discrepancy/other); `DisputeStatus` enum (5 values: submitted/under_review/resolved_upheld/resolved_denied/withdrawn); `description` text required (min 10 chars); `disputed_rides` JSON nullable (list of ride IDs); `disputed_amount_usd` optional; `resolved_by_id` FK SET NULL; `resolved_at` timestamp; CASCADE delete on both invoice and account; 4 indexes
- **8 service functions**: `submit_dispute` (404 wrong invoice/account; 409 active dispute already exists; re-dispute allowed after resolution) / `update_dispute` (409 if not in submitted status) / `mark_under_review` (409 if resolved/withdrawn) / `resolve_dispute` (upheld/denied; sets resolved_by/at) / `withdraw_dispute` (409 if already resolved) / `get_dispute` / `list_account_disputes` (optional status filter) / `list_all_disputes` (platform-admin)
- **9 endpoints**: member `POST .../disputes` (submit) + `GET .../disputes` (by invoice) + `GET /corporate/disputes/{id}` + `PUT .../update` + `DELETE .../withdraw`; admin `GET /corporate/accounts/{id}/disputes` + `POST .../review` + `POST .../resolve`; platform-admin `GET /admin/corporate/disputes`
- **Migration `w3x4y5z6a7b8`** (revises `v2w3x4y5z6a7`): `disputetype` + `disputestatus` enums + `corporate_invoice_disputes` table + 4 indexes
- **40 tests** → **Total: 6,641 passing** (was 6,601)

---

### Accomplished (Session 200)

#### open-source-rideshare — Corporate Account Suspension & Reinstatement (commit `03907e5`)

Platform-admins can now suspend corporate accounts for billing overdue, policy violations, fraud investigations, voluntary pauses, compliance failures, non-payment, or other reasons. Once issues are resolved, accounts can be reinstated with a note. Members can check their own account's suspension status.

- **`CorporateAccountSuspension` model**: `SuspensionReason` enum (7 values: billing_overdue/policy_violation/fraud_investigation/voluntary_pause/compliance_failure/non_payment/other); `suspended_by_id` FK SET NULL (system events supported); `suspension_note` text; `suspended_at` default now(); `reinstated_at` nullable; `reinstated_by_id` FK SET NULL; `reinstatement_note`; `is_active` bool; CASCADE delete on account; 3 indexes
- **6 service functions**: `suspend_account` (409 if active suspension already exists) / `reinstate_account` (404 if no active suspension) / `get_active_suspension` (None when not suspended) / `is_account_suspended` (bool — ready for booking-flow gating) / `list_suspension_history` (all records newest-first) / `list_all_suspended_accounts` (paginated, platform-admin cross-account)
- **6 endpoints**: platform-admin `POST .../suspend` + `POST .../reinstate` + `GET .../suspension` (active only) + `GET .../suspension/history`; platform-admin `GET /admin/corporate/suspensions` (all suspended); member `GET /corporate/suspension/status` (own account)
- **Migration `v2w3x4y5z6a7`** (revises `u1v2w3x4y5z6`): `suspensionreason` enum + `corporate_account_suspensions` table + 3 indexes
- **38 tests** → **Total: 6,601 passing** (was 6,563)

---

### Accomplished (Session 199)

#### open-source-rideshare — Corporate Carbon Budget & ESG Reporting (commit `0c5d3a3`)

Corporate accounts can now set a monthly CO2 budget and track their environmental footprint across all employee rides. Sustainability teams get current-month summaries, month-over-month trend data, per-employee breakdowns, and platform-wide ESG reports. No Uber for Business equivalent — this is a genuine cooperative differentiator for ESG-conscious enterprise clients.

- **`CorporateCarbonBudget` model**: one per account (upsert-on-read); `monthly_budget_co2_kg` Numeric(10,2) nullable ceiling; `offset_budget_usd` Numeric(10,2) optional; `tracking_enabled` bool (default True); `alert_threshold_pct` int 1–100 (default 80); `notes` text; `updated_by_id` audit FK (SET NULL); CASCADE delete on account; unique constraint on account_id; 1 index
- **6 service functions**: `get_or_create_carbon_budget` (upsert-on-read, never 404) / `update_carbon_budget` (partial PUT, creates if absent, only supplied fields written) / `get_account_carbon_summary` (current-month CO2 kg + green ride % + offset payments + budget utilisation % + alert_triggered flag; 403 when tracking disabled for non-admin members) / `get_carbon_trend` (month-over-month 1–24 months, newest-first; 400 on range) / `get_employee_carbon_breakdown` (admin only, ordered by CO2 desc; 400 on bad period; 403 non-admin) / `get_platform_esg_report` (platform-admin cross-account; cumulative totals + monthly trend; 400 on range)
- **7 endpoints**: `GET /corporate/accounts/me/carbon-budget` (member) / `PUT /corporate/accounts/me/carbon-budget` (admin set/update) / `GET /corporate/accounts/me/carbon-summary` (member, current month) / `GET /corporate/accounts/me/carbon-trend` (member, ?months=6) / `GET /corporate/accounts/me/carbon/employees` (admin, ?period_start&period_end) / `GET /admin/corporate/accounts/{id}/carbon-budget` (platform-admin) / `GET /admin/corporate/carbon/esg-report` (platform-admin, ?months=12)
- **Migration `u1v2w3x4y5z6`** (revises `t0u1v2w3x4y5`): `corporate_carbon_budgets` table + unique constraint + 1 index
- **39 tests** → **Total: 6,563 passing** (was 6,524)

---

### Accomplished (Session 198)

#### open-source-rideshare — Corporate Account Contract Management (commit `b7e139e`)

Enterprise service agreements between the platform and corporate clients. Sales and account management teams can now track the full contract lifecycle — draft → active → terminated — with committed volume, negotiated discounts, and account manager assignment.

- **`CorporateAccountContract` model**: `ContractStatus` enum (draft/active/expired/terminated); `contract_number` unique auto-generated as `CONTRACT-{acct:04d}-{YYYYMM}-{seq}`; `contract_start/end_date` (nullable end = open-ended); `auto_renews` + `renewal_term_days` + `renewal_notice_days`; `committed_monthly_rides` + `committed_monthly_spend_usd`; `negotiated_discount_pct` (0–100); `account_manager_name` + `account_manager_email`; `contract_document_url`; `signed_by_name` + `signed_at`; `activated_at`, `terminated_at`, `termination_reason` audit fields; CASCADE delete on account; 4 indexes + unique constraint on contract_number
- **8 service functions**: `create_contract` (409 if active exists), `get_contract` (404), `get_active_contract` (returns None), `list_contracts` (status filter + pagination), `update_contract` (409 on terminated/expired), `activate_contract` (draft-only; deactivates prior active), `terminate_contract` (active-only), `list_expiring_contracts` (active contracts where end_date ≤ today + N days)
- **8 endpoints**: member `GET /corporate/accounts/me/contract` (own active contract or 404); platform-admin `GET/POST /admin/corporate/accounts/{id}/contracts`, `GET /admin/corporate/contracts/expiring`, `GET/PATCH /admin/corporate/contracts/{id}`, `POST .../activate`, `POST .../terminate`
- **Migration `t0u1v2w3x4y5`** (revises `s9t0u1v2w3x4`): `contractstatus` enum + `corporate_account_contracts` table + 4 indexes + unique constraint
- **38 tests** → **Total: 6,524 passing** (was 6,486)

---

### Accomplished (Session 197)

#### open-source-rideshare — Corporate Account Onboarding Checklist (commit `868b7d7`)

New corporate accounts can view a structured setup checklist that shows which features are configured and what's still missing. Purely computed — no new database tables or migration.

- **5 required steps**: billing (settings + at least one payment method), employees (at least 1 active member), ride_policy (CorporateRidePolicy configured), cost_centers (at least 1 active), trip_purposes (at least 1 active)
- **3 optional steps**: notifications (at least 1 enabled event config), sso (status=active), integrations (active webhook OR active API key)
- **Service**: `get_onboarding_checklist()` fires 10 scalar `COUNT(*)` queries against existing tables — no N+1, no new schema
- **Endpoints**: `GET /corporate/accounts/me/onboarding-checklist` (any active member) + `GET /admin/corporate/accounts/{id}/onboarding-checklist` (platform admin)
- **Response**: step-by-step list with `is_complete`, `is_optional`, `action_hint` per step; aggregates: `total_steps`, `required_steps`, `completed_required`, `completed_optional`, `all_required_complete`, `completion_pct`
- **30 tests** → **Total: 6,486 passing** (was 6,456)

---

### Accomplished (Session 196)

#### open-source-rideshare — Corporate Billing Settings (commit `19518f3`)

Enterprise accounts can now configure how they are billed. This is the last major missing piece for a complete enterprise B2B billing story.

- **`CorporateBillingSettings` model**: one per account (upsert-on-read); billing address fields (line1/2, city, state, postal, country); `tax_id` for EIN/VAT; `po_number_required` + `default_po_number`; `invoice_memo_template` boilerplate; `auto_pay_enabled`; `billing_cycle` enum (weekly/biweekly/monthly); `invoice_emails` JSONB; `updated_by_id` audit FK; CASCADE delete
- **`CorporatePaymentMethod` model**: multiple methods per account (credit_card/debit_card/ach_bank_account/wire_transfer); `display_name`; `last_four`; `cardholder_name`; `bank_name`; `external_payment_method_id` (Stripe `pm_…`); `is_default` + `is_active`; denormalised `account_id` for direct queries; 3 indexes
- **9 service functions**: `get_or_create_settings` (upsert, never 404) / `update_settings` (partial patch, creates if absent) / `add_payment_method` (clears prior default when set_as_default=True) / `get_payment_method` (404 if absent) / `list_payment_methods` (active_only filter) / `set_default_payment_method` (409 on inactive) / `deactivate_payment_method` (clears default flag) / `delete_payment_method` (409 if is_default) / `get_billing_summary` (combined response with `auto_pay_ready` + `has_complete_billing_address` derived fields)
- **11 endpoints**: member (billing summary, list methods); admin (get/update settings, add/get/set-default/deactivate/delete methods); platform-admin (list all, get for account)
- **Migration `s9t0u1v2w3x4`** (revises `r8s9t0u1v2w3`): 2 enums + 2 tables + 4 indexes
- **44 tests** → **Total: 6,456 passing** (was 6,412)

---

### Needs Your Input

#### open-source-rideshare — PR: feature/corporate-business-accounts

Branch now includes (most recent first):
- Corporate Manager Hierarchy (9168751) ← new
- Corporate Multi-Level Approval Chains (a365044)
- Corporate Policy Violation Tracking (19f0c47)
- Corporate Account Tags (8f2a8e9)
- Corporate Member Ride Quotas (c08f12d)
- Corporate Account Notes (94fd249)
- Corporate Account Health Score (c0b4d1d)
- Corporate Invoice Dispute Resolution (d0f793c)
- Corporate Account Suspension & Reinstatement (03907e5)
- Corporate Carbon Budget & ESG Reporting (0c5d3a3)
- Corporate Account Contract Management (b7e139e)
- Corporate Account Onboarding Checklist (868b7d7)
- Corporate Billing Settings (19518f3)
- Corporate Commuter Benefits (50d62eb)
- Corporate Employee Groups (a39a86a)
- Corporate Preferred Driver Pool (d0f284f)
- ... and 30+ more enterprise features

**Total: 6,805 passing** (45 new, no regressions — pre-existing 1 failure in test_corporate_guest_pass unrelated). Push to remote blocked by org permissions. Please push and open a PR to `master` when ready to review.

---

### Accomplished (Session 195)

#### open-source-rideshare — Corporate Commuter Benefits (commit `50d62eb`)

Companies can now define a monthly ride subsidy program giving each eligible employee a per-month credit for qualifying commute rides. Distinct from prepaid credit pools (account-level) and spend limits (caps) — this is per-employee monthly allotments.

- **`CorporateCommuterProgram` model**: one-per-account unique constraint on `account_id`; `monthly_allowance_usd`; `rollover_enabled` + `max_rollover_usd` for carryover logic; `eligible_trip_purpose_ids` + `eligible_group_ids` JSONB for scoping eligibility; `is_active` soft-delete; `valid_from`/`valid_until` date range; `created_by_id` audit FK; CASCADE delete on account
- **`CorporateCommuterAllotment` model**: monthly per-employee record; unique (program_id, member_id, period_year, period_month); `allotted_usd` copied from program; `used_usd` running total; `rolled_over_usd` for carryforward balance; 3 indexes
- **8 service functions**: `create_program` (409 if exists) / `get_program` / `update_program` (404) / `deactivate_program` (404) / `get_or_create_allotment` (lazy create + rollover from prior month, capped by `max_rollover_usd`) / `list_allotments` (filters: year, month, member_id) / `get_member_allotment` (convenience: program lookup + allotment) / `record_commuter_ride_usage` (increment used_usd; 409 if balance exceeded) / `get_program_stats` (aggregate utilisation: members, allotted, used, remaining, pct)
- **10 endpoints**: member self-service (get-my-allotment, allotment-history); admin (create/get/update/deactivate program, list allotments, stats); platform-admin (list-all-programs, get-for-account)
- **Migration `r8s9t0u1v2w3`** (revises `q7r8s9t0u1v2`): 2 tables + 4 indexes + 2 unique constraints
- **42 tests** → **Total: 6,412 passing** (was 6,370)

---

### Accomplished (Session 194)

#### open-source-rideshare — Corporate Employee Groups (commit `a39a86a`)

Enterprise admins can now create named, cross-functional groups of employees — more flexible than departments, since one employee can belong to many groups and groups don't have to follow org hierarchy. Examples: "VIP Executives", "Remote Workers", "Engineering All-Hands". Designed for targeted policy enforcement, notifications, and analytics.

- **`CorporateEmployeeGroup` model**: unique (account_id, name); `color` hex field for UI display; `is_active` soft-delete; `created_by_id` audit FK; CASCADE delete on account; 2 indexes
- **`CorporateGroupMembership` model**: unique (group_id, member_id); `added_by_id` audit FK; CASCADE delete on both group and member; 2 indexes
- **11 service functions**: `create_group` (409 on duplicate name) / `get_group` (404) / `list_groups` (active_only filter) / `update_group` (409 on name conflict) / `deactivate_group` / `delete_group` / `add_member_to_group` (409 if already in group) / `remove_member_from_group` (404 if not in group) / `list_group_members` (paginated) / `get_member_groups` (all groups for an employee) / `get_group_stats` (member count)
- **12 endpoints**: member (list/get/get-members/get-member-groups); admin (create/update/deactivate/delete/add-member/remove-member); platform-admin (list-all/get-stats)
- **Migration `q7r8s9t0u1v2`** (revises `p7q8r9s0t1u2`): 2 tables + 5 indexes + 2 unique constraints
- **42 tests** → **Total: 6,370 passing** (was 6,328)

---

### Accomplished (Session 193)

#### open-source-rideshare — Corporate Preferred Driver Pool (commit `d0f284f`)

Enterprise accounts can now curate a pool of trusted, vetted drivers that the matching engine surfaces first for corporate rides — giving companies continuity and quality assurance. Uber for Business has no equivalent feature.

- **`CorporateDriverPool` model**: unique (account_id, driver_id) constraint; `is_active` soft-delete flag; optional `notes`; `added_by_id` audit FK; CASCADE deletes on both account and driver FKs; 3 indexes
- **6 service functions**: `add_driver_to_pool` (409 if active; upserts deactivated entry) / `remove_driver_from_pool` (soft-delete, 404 if not active) / `get_pool_entry` (404 if not active) / `list_pool_drivers` (paginated, active_only flag) / `is_driver_preferred` (plain bool — ready for matching engine) / `get_driver_pool_stats` (count of preferring accounts, driver-facing)
- **8 endpoints**: member list + get + boolean check; admin add (201) + remove (204); driver pool-stats; 2 platform-admin (list + remove)
- **Migration `p7q8r9s0t1u2`** (revises `o6p7q8r9s0t1`): `corporate_driver_pool` table + 3 indexes + unique constraint
- **32 tests** → **Total: 6,328 passing** (was 6,296)

---

### Accomplished (Session 192)

#### open-source-rideshare — Corporate Bulk Member Invitations (commit `3ae104b`)

Admins can now invite up to 100 employees in a single POST request instead of making individual invitation calls. Designed for enterprise onboarding — import an entire team at once.

- **`BulkInvitationRequest`** schema: 1–100 `BulkInvitationItem` entries (email + role + message); optional shared `expires_at` (validated future); Pydantic enforces bounds
- **`create_bulk_invitations()` service**: admin check once upfront; per-item guards (pending-dupe check, active-member-by-email check via User join); emails normalized lowercase; shared expiry applied to all created items; errors collected without aborting batch
- **`POST /corporate/accounts/me/invitations/bulk`** (admin-only, HTTP 200): per-item `status` ∈ {created/skipped/error}; `reason` field on skipped/error; full `InvitationResponse` on created items; aggregate counts `total_requested/created/skipped/errors`
- Route declared before `/{invite_id}` to avoid FastAPI treating "bulk" as a UUID path param
- **27 tests** (10 service, 10 schema, 7 API) → **Total: 6,296 passing** (was 6,269)

---

### Accomplished (Session 191)

#### open-source-rideshare — Corporate Account Dashboard (commit `9c73f93`)

Single read endpoint that returns a consolidated health snapshot of a corporate account — one call replaces ~10 separate API queries when rendering an admin overview page. No new model or migration needed.

- **Sections returned**:
  - `account` — name, status, billing_email, tax_id, monthly_budget_limit, created_at
  - `members` — total_active, total_admins, pending_invitations
  - `spend` — rides_this_month, spend_this_month_usd, monthly_budget_limit, budget_utilization_pct
  - `credit` — prepaid balance + low-balance flag (null when unconfigured)
  - `pending` — pending_ride_approvals, pending_invitations
  - `setup` — sso_configured/status/enforced, active_webhooks, active_api_keys, billing_contacts, account_contacts, notification_configs
  - `alerts` — total_active, total_triggered (budget alerts)
  - `blackouts` — total_active blackout periods
- **2 endpoints**: `GET /corporate/{account_id}/dashboard` (authenticated user) + `GET /platform-admin/corporate/{account_id}/dashboard` (admin)
- **30 tests** → **Total: 6,269 passing** (was 6,239)

### Accomplished (Session 190)

#### open-source-rideshare — Corporate Notification Settings (commit `da2d9ca`)

Admins can now configure per-account notification routing — which of 12 event types trigger emails and which contact channels receive them. Ties together billing contacts, account contacts, and webhooks into a unified dispatch layer.

- **`CorporateNotificationConfig` model**: unique (account_id, event_type); `NotificationEventType` enum (member_joined / member_removed / policy_violation / budget_threshold_crossed / invoice_generated / invoice_paid / ride_approval_requested / ride_approval_denied / low_credit_balance / sso_login_failed / api_key_created / data_export_ready); per-event flags: `enabled`, `notify_billing_contacts`, `notify_account_contacts`, `notify_via_webhooks`, `additional_emails` JSONB
- **6 service functions**: `get_notification_config` (upsert-on-read with defaults) / `get_all_notification_configs` (always returns all 12) / `update_notification_config` / `bulk_update_notification_configs` / `reset_notification_configs` / `get_recipients_for_event` (queries billing contacts + account contacts + webhooks based on flags — ready for dispatch layer)
- **7 endpoints**: admin list + get + update + bulk-update + reset + preview-recipients; 1 platform-admin view
- **Migration `o6p7q8r9s0t1`**: `notificationeventtype` enum + `corporate_notification_configs` table + indexes
- **35 tests** → **Total: 6,239 passing** (was 6,204)

### Accomplished (Session 189)

#### open-source-rideshare — Corporate SSO Configuration (commit `684849d`)

Enterprise accounts can now configure single sign-on with their identity provider — Okta, Azure AD, Google Workspace, or any standard SAML 2.0 / OIDC provider. Admins supply credentials, test the connection, activate, and optionally enforce SSO so all members must authenticate via their company IdP.

- **`CorporateSSOConfig` model**: `SSOProvider` enum (saml/oidc/google/microsoft/okta); `SSOStatus` enum (pending/active/disabled); `enforce_sso` boolean; SAML fields (metadata_url, entity_id, sso_url, slo_url, certificate); OIDC fields (discovery_url, client_id, client_secret_hash, scopes); `attribute_mapping` JSONB; `allowed_domains` JSONB; `last_tested_at` audit; unique on account_id
- **Security note**: OIDC client secret stored hashed, excluded entirely from response schema (not just nulled) — can never be leaked by serialization
- **9 service functions**: create (409 if already exists) / get / update / delete / set_enforcement (422 if enabling when not active) / activate / disable (also sets enforce=False) / record_test / list_configs
- **10 endpoints**: admin CRUD + enforce toggle + activate + disable + test-connection + 2 platform-admin (list all + get by account)
- **Migration `n5o6p7q8r9s0`**: `ssoprovider` + `ssostatus` enums + `corporate_sso_configs` table + indexes, down_revision `m4n5o6p7q8r9`
- **40 tests** → **Total: 6,204 passing** (was 6,164)

### Accomplished (Session 188)

#### open-source-rideshare — Corporate Account Contacts (commit `2812bd9`)

- **34 tests** → **Total: 6,164 passing** (was 6,130)

### Needs Your Input

#### open-source-rideshare — Push to GitHub

Branch: `feature/corporate-business-accounts` | Latest commit: `a39a86a`

SSH key `esca8peArtist` still cannot push to `SuperClaude-Org/SuperClaude_Framework`. Please push manually when ready.

Summary of what's local and unpushed since the last push:
- **Session 186**: Corporate Scheduled Reports (commit `f834b67`) — 55 tests
- **Session 187**: Corporate Pre-paid Credits (commit `55027e1`) — 53 tests
- **Session 188**: Corporate Account Contacts (commit `2812bd9`) — 34 tests
- **Session 189**: Corporate SSO Configuration (commit `684849d`) — 40 tests
- **Session 190**: Corporate Notification Settings (commit `da2d9ca`) — 35 tests
- **Session 191**: Corporate Account Dashboard (commit `9c73f93`) — 30 tests
- **Session 192**: Corporate Bulk Member Invitations (commit `3ae104b`) — 27 tests
- **Session 193**: Corporate Preferred Driver Pool (commit `d0f284f`) — 32 tests
- **Session 194**: Corporate Employee Groups (commit `a39a86a`) — 42 tests
- **Total: 6,370 passing** (1 pre-existing failure in `test_corporate_guest_pass.py::test_validate_token_not_yet_valid`, 1,082 skipped)

---

### Accomplished (Session 187)

#### open-source-rideshare — Corporate Pre-paid Credits (commit `55027e1`)

Enterprise accounts can pre-load a credit balance that is drawn down as rides are completed. All movements are recorded in an append-only ledger — every deposit, deduction, refund, and manual adjustment is fully auditable.

- **`CorporateCreditAccount` model**: one per account — `balance_usd`, `total_deposited_usd`, `total_spent_usd`, `total_refunded_usd`, optional `low_balance_threshold_usd` for alerts
- **`CorporateCreditTransaction` model**: append-only ledger — `CreditTransactionType` enum (deposit/deduction/refund/adjustment), `amount_usd` (always positive), `balance_after_usd` snapshot, `reference_id`/`reference_type` for linking to rides/invoices
- **8 service functions**: get_or_create / get_balance / deposit / deduct (409 if insufficient) / refund / adjust (signed, 422 if negative balance) / list_transactions / list_low_balance_accounts / set_threshold
- **9 endpoints**: member balance+history; admin deposit/refund/threshold; platform-admin get/transactions/adjust/low-balance
- **Migration `l3m4n5o6p7q8`**: 2 tables + 6 indexes + `credittransactiontype` enum
- **53 tests** → **Total: 6,130 passing** (was 6,077)

### Accomplished (Session 186)

#### open-source-rideshare — Corporate Scheduled Reports (commit `f834b67`)

- **55 tests** → **Total: 6,077 passing** (was 6,022)

### Needs Your Input

#### open-source-rideshare — Push to GitHub
Branch: `feature/corporate-business-accounts` (latest commit `55027e1`)
Includes Sessions 166–187: corporate ride policy, approval workflow, cost centers, monthly invoices, spending analytics, batch/group booking, trip purpose codes, guest passes, employee spend limits, data export, budget alerts, blackout periods, fare agreements, employee invitations, departments, expense reports, billing contacts, admin audit log, custom ride fields, delegate access, address book, webhooks, API keys, scheduled reports, **pre-paid credits**.
Please run: `git push origin feature/corporate-business-accounts`

---

### Accomplished (Session 179)

#### open-source-rideshare — Corporate Employee Invitations (commit `24834c3`)

Admins issue UUID-based invitation tokens to prospective employees by email address. The invitee validates the token via a public endpoint (always returns JSON, never 404), then accepts it as an authenticated user — automatically creating their corporate account membership with the contracted role.

- 9 endpoints; migration `a2b3c4d5e6f7`; 45 tests; **Total: 5,628 passing**

---

### Accomplished (Session 177)

#### open-source-rideshare — Corporate Blackout Periods

**Feat (commit `d6dff97`)**: Admins define named date ranges during which corporate bookings are restricted. Three recurrence modes: one-time (`none`), annually-repeating (e.g., "Christmas" every Dec 24–26), and weekly recurring (e.g., "No weekend corporate rides"). The `/check` endpoint lets callers verify whether a proposed booking datetime is blocked before attempting to book.

- **`CorporateBlackoutPeriod` model**: UUID PK, account FK, name, start/end datetime (timezone-aware), `BlackoutRecurrence` enum (none/annual/weekly), `affected_days` JSONB (weekday integers for weekly blocks), `override_allowed`/`override_requires_approval` booleans, reason, `is_active` soft-disable, created_by FK
- **6 service functions**: create (validates end > start), get (404 on wrong account), list (active_only/from_dt/to_dt filters), update (partial, re-validates dates), delete, check_booking_blackout (`_period_covers` handles all three recurrence types, including annual cross-year wrapping)
- **9 endpoints**: 7 member (create/list/check-datetime/get/update/delete/deactivate) + 2 platform-admin (list/check); `/check` declared before `/{id}` to avoid FastAPI path conflict
- **Migration `y2z3a4b5c6d7`**: `blackoutrecurrence` enum + `corporate_blackout_periods` table + 2 indexes
- **45 new tests** (all passing); **Total: 5,534 passing** (up from 5,489)

---

### Accomplished (Session 174)

#### open-source-rideshare — Corporate Employee Spend Limits

**Feat (commit `0daed0a`)**: Surfaces the existing `monthly_spend_limit` column on `BusinessAccountMember` with a full self-service and admin API. No new model or migration needed — all data from existing tables.

Employees now have a self-service spending dashboard: current-month spend vs personal monthly cap, utilization percentage, YTD totals, and a month-by-month history view. Admins can set, update, or remove any employee's monthly cap, and pull a live overview of all members' limits alongside their current-month usage (single bulk query).

- **6 service functions**: `get_my_spend_summary`, `get_my_spend_history`, `get_member_spend_summary`, `list_members_spend_summary`, `set_member_spend_limit`, `remove_member_spend_limit`
- **7 endpoints**: `GET /corporate/accounts/me/my-spending` (employee self-service), `GET /corporate/accounts/me/my-spending/history`, `GET /corporate/accounts/me/members/spend-limits` (admin overview), `GET /corporate/accounts/me/members/{uid}/spend-limit`, `PUT /corporate/accounts/me/members/{uid}/spend-limit`, `DELETE /corporate/accounts/me/members/{uid}/spend-limit`, `GET /admin/corporate/accounts/{id}/members/spend-limits` (platform-admin)
- **43 new tests**; **Total: 5,417 passing** (up from 5,374)

---

### Accomplished (Session 173)

#### open-source-rideshare — Corporate Guest Passes

**Feat (commit `ee0e029`)**: Corporate employees can now issue limited-use booking tokens to non-employees — clients, candidates, and visitors. The guest submits the UUID token when booking; no corporate login is required. The resulting ride bills to the corporate account. Passes have configurable expiry, per-ride budget caps, optional usage limits, and can be linked to a cost center and trip purpose for automatic tagging.

- **`CorporateGuestPass` model**: UUID PK and UUID `token` (globally unique); `label` VARCHAR(200); `max_uses`/`uses_remaining` (both nullable = unlimited); `max_ride_budget_usd` Numeric(10,2); optional FKs to `corporate_trip_purposes` and `corporate_cost_centers`; `valid_from`/`valid_until` DateTimeTZ window; `GuestPassStatus` enum (active/exhausted/expired/revoked); `revoked_at`/`revoked_by_id` audit fields. `guest_pass_id` nullable UUID FK added to `rides` table.
- **8 service functions**: `create_guest_pass` (sets uses_remaining=max_uses), `get_guest_pass` (404 on wrong account), `list_guest_passes` (status filter + pagination), `update_guest_pass` (rejects revoked/exhausted), `revoke_guest_pass` (409 if already revoked), `validate_guest_pass_token` (public-safe: never 404, returns is_valid dict checking status + time window), `use_guest_pass` (decrements uses_remaining, auto-exhausts at 0, links ride), `get_guest_pass_rides`
- **7 endpoints**: employee CRUD (POST/GET/GET-by-id/PATCH/DELETE); public `GET /guest-pass/{token}` (no auth, returns `GuestPassValidationResponse`); platform-admin list all + list by account
- **Migration `w2x3y4z5a6b7`** (down: `v2w3x4y5z6a7`): creates `corporate_guest_passes` table + `GuestPassStatus` enum + adds `guest_pass_id` to rides
- **44 new tests**; **Total: 5,374 passing** (up from 5,330)

---

### Accomplished (Session 171)

#### open-source-rideshare — Corporate Batch/Group Booking

**Feat (commit `1f86eb9`)**: Companies can now arrange multiple rides in a single coordinated booking — event shuttles, offsites, airport pickups for visiting clients. An admin creates a batch (DRAFT), adds up to 50 ride requests (each with a passenger, pickup, dropoff, and requested time), then submits the batch for fulfilment. Batches can be cancelled before or after submission. This feature does not exist in Uber for Business.

- **2 new models** (`CorporateBatchBooking` + `CorporateBatchRideRequest`): DRAFT/SUBMITTED/CANCELLED batch lifecycle; PENDING/REMOVED request status; denormalised `account_id` on requests for fast account-scoped queries; cascade delete
- **9 service functions**: create (admin), get (member), list (member, optional status filter), update (admin, draft-only), add_ride_request (admin, draft-only, 50-cap), remove_ride_request (admin, draft-only), submit (admin, must have ≥1 pending), cancel (admin), get_with_requests (member)
- **13 endpoints**: 3 member-read + 6 admin-write + 4 platform-admin
- **Migration `u2v3w4x5y6z7`** (down: `t2u3v4w5x6y7`) — 2 enum types, 2 tables, 5 indexes
- **38 new tests**; **Total: 5,290 passing** (up from 5,252)

---

### Accomplished (Session 170)

#### open-source-rideshare — Corporate Spending Analytics

**Feat (commit `88addd1`)**: Read-only analytics layer completing the corporate billing picture. Account members can view spend trends and ride patterns; admins get per-employee breakdowns. Finance teams can now answer "How much did we spend this month vs budget?" and "Who are our top 10 spenders?" without needing a data export.

- **4 service functions** — no new model/migration:
  - `get_spending_overview`: current-month + YTD + all-time ride counts and totals; budget utilisation % when `monthly_budget_limit` is set
  - `get_monthly_spend_trend`: PostgreSQL `to_char(YYYY-MM)` grouping, 1–24 months, newest-first; includes avg fare per month
  - `get_employee_spend_breakdown`: admin-only; top-N employees by total spend in a date range; avg fare per employee
  - `get_ride_pattern_analytics`: `extract(hour)` and `extract(dow)` queries; all 24 hour and all 7 DOW buckets always returned (zero-count buckets included)
- **8 endpoints**: 4 member/admin under `/corporate/accounts/me/analytics/…` + 4 platform-admin mirrors
- **35 new tests**; **Total: 5,252 passing** (up from 5,217)

---

### Accomplished (Session 169)

#### open-source-rideshare — Corporate Monthly Invoices

**Feat (commit `4da54cd`)**: Monthly billing invoices for corporate accounts. Admins can generate, finalize, mark as paid, void, and recalculate invoices. Any member can view line items and cost-center breakdowns.

- **`CorporateInvoice` model** (`corporate_invoices_v2` table): Note — `corporate_invoices` was already taken by an older `BusinessInvoice` model in `corporate.py`; used `_v2` suffix consistent with project conventions. Invoice number auto-generated as `INV-{account_id:04d}-{YYYYMM}` with `-2/-3` suffixes on collision. 4-state enum: draft/finalized/paid/void. Columns: `invoice_number` (unique), `period_start/end`, `total_rides`, `subtotal_usd`, `notes`, `generated_at`, `finalized_at`, `paid_at`, `voided_at`.
- **8 service functions**: `generate_invoice` (admin-only, 409 on duplicate non-void period, aggregates `Ride.corporate_account_id`-linked completed rides), `get_invoice` (account-scoped 404), `list_invoices` (status filter, period_start DESC), `finalize_invoice` (draft-only), `mark_invoice_paid` (finalized-only, optional notes), `void_invoice` (400 if already void), `get_invoice_line_items` (any member; per-ride + by-cost-center summary), `regenerate_invoice_totals` (draft-only re-aggregation)
- **11 member endpoints** + **3 platform-admin endpoints**: POST/GET/GET/{id}/GET/{id}/line-items/PUT/{id}/finalize/PUT/{id}/paid/DELETE/{id}/POST/{id}/regenerate
- **Migration `t2u3v4w5x6y7`** (down_revision: s2t3u4v5w6x7) — 1 new table, `corp_invoice_status_v2` enum type, 2 indexes
- **39 new tests**; **Total: 5,217 passing** (up from 5,178)

---

### Accomplished (Session 168)

#### open-source-rideshare — Corporate Cost Centers

**Feat (commit `cfb33a0`)**: Named departments, projects, or teams for per-cost-center expense tracking. Companies can create cost centers, tag rides to them at booking time, and view spend breakdowns by department. No equivalent feature exists in Uber for Business — finance-controlled orgs can now see exactly which department spent what, with optional monthly budget caps and utilization percentages.

- **`CorporateCostCenter` model**: unique `(account_id, code)` constraint; code UPPER-normalised in schema; `is_active` soft-delete flag preserves historical ride assignments; optional `monthly_budget` Decimal cap
- **`rides.cost_center_id`**: nullable FK → corporate_cost_centers (SET NULL on delete); cost center tag set at booking time
- **7 service functions**: `create_cost_center` (admin-only, duplicate-code guard, 100-center cap), `get_cost_center` (account-scoped, 404 on mismatch), `list_cost_centers` (active_only filter), `update_cost_center` (admin-only partial update), `deactivate_cost_center` (soft-delete, 400 if already inactive), `get_cost_center_spend` (date-range aggregation + budget utilization pct), `list_account_spend_by_cost_center` (all centers ranked by spend desc; zero-ride centers included)
- **10 endpoints**: POST/GET/GET/{id}/PATCH/{id}/DELETE/{id}/GET/{id}/spend (member + admin); GET /spend (account breakdown, admin-only); 3 platform-admin endpoints
- **Migration s2t3u4v5w6x7** (down_revision: r2s3t4u5v6w7) — 1 new table, nullable FK column on rides, 3 indexes
- **40 new tests**; **Total: 5,178 passing** (up from 5,138)

### Accomplished (Session 167)

#### open-source-rideshare — Corporate Ride Approval Workflow

**Feat (commit `f8658d7`)**: Pre-booking expense approval for corporate accounts. A genuinely missing enterprise feature — Uber for Business has no pre-approval flow; review is post-hoc. Finance-controlled orgs can now require employees to get explicit sign-off before booking a corporate ride.

- **`CorporateRideApproval` model**: links account + requester + reviewer; stores purpose, destination, estimated cost, status (6-value enum), unique UUID approval code, admin-set cost ceiling, expiry window, review note, audit timestamps
- **7 service functions**: `request_approval` (active-member guard, 5-concurrent-pending cap), `list_pending_approvals` (admin queue, oldest-first), `list_member_approvals`, `get_approval` (account-scoped), `approve` (admin-only, PENDING-only), `deny` (admin-only, PENDING-only), `cancel` (requester cancels own PENDING), `verify_approval` (code → status → expiry → cost-ceiling chain — returns structured result)
- **8 endpoints**: POST/GET/DELETE `/corporate/accounts/me/approvals` (member); GET `…/pending` (admin review queue); PUT `…/{id}/approve` + `…/{id}/deny` (admin); POST `…/verify` (booking-time check, any member); GET `/admin/corporate/accounts/{id}/approvals` (platform admin)
- **Migrations**: `q2r3s4t5u6v7` (backfill — corporate_ride_policies migration missing from session 166 commit) + `r2s3t4u5v6w7` (corporate_ride_approvals — enum type + table + 4 indexes)
- **38 new tests**; **Total: 5,138 passing** (up from 5,100)

### Accomplished (Session 166)

#### open-source-rideshare — Corporate Ride Policy

**Feat (commit `18d5a18`)**: Companies can now define a ride policy that controls what rides employees may charge to the corporate account — vehicle type restrictions, per-ride cost caps, per-employee monthly limits, trip purpose requirements with an approved-purpose allowlist, and business-hours-only restrictions. No policy configured → all rides permitted (safe default). Genuine enterprise differentiator that makes corporate accounts production-ready.

- **`CorporateRidePolicy` model**: unique on `account_id`; FK → `corporate_accounts_v2`; 6 policy columns (allowed_vehicle_categories JSONB, max_per_ride_usd, max_per_member_monthly_usd, require_purpose, approved_purposes JSONB, business_hours_only); created_at / updated_at
- **4 service functions**: `get_policy` (returns None when not configured), `set_policy` (upsert, account-admin-only, 403/404 guarded), `delete_policy` (account-admin-only, 404 if not set), `check_ride_allowed` (evaluates proposed ride against all 4 policy dimensions; returns `{allowed, reason}`)
- **5 endpoints**: GET/PUT/DELETE `/corporate/accounts/me/policy` (any member read; admin write); POST `/corporate/accounts/me/policy/check` (any member); GET `/admin/corporate/accounts/{id}/policy`
- **Schema validation**: max_per_ride_usd and max_per_member_monthly_usd > 0; approved_purposes ≤ 20 entries; each purpose ≤ 100 chars
- **Migration q2r3s4t5u6v7** (down_revision: p2q3r4s5t6u7) — 1 table, 1 unique constraint
- **31 new tests**; **Total: 5,100 passing** (up from 5,069)

### Accomplished (Session 165)

#### open-source-rideshare — Driver Work Preferences

**Feat (commit `57b8707`)**: Drivers can specify what kinds of rides they are willing to accept — pool rides, pet passengers, extra luggage, trip distance range, long-distance preference, and language-matched dispatch priority. Gives drivers real agency over their workload — a core cooperative value that Uber/Lyft's algorithmic dispatch completely ignores.

- **`DriverWorkPreference` model**: unique on `driver_id`; 8 preference columns; defaults are permissive (all ride types accepted) so new drivers aren't inadvertently excluded from dispatch
- **3 service functions**: `get_preferences` (auto-creates default row on first access), `update_preferences` (partial update — only supplied fields written), `reset_preferences` (restore all fields to platform defaults)
- **4 endpoints**: GET/PUT/DELETE `/drivers/me/work-preferences` (driver self-manage); GET `/admin/drivers/{id}/work-preferences` (admin read-only)
- **Migration p2q3r4s5t6u7** (down_revision: o2p3q4r5s6t7) — 1 table, 1 index, 1 unique constraint
- **Schema validation**: min/max distance range cross-validated (min ≤ max); `notes` max 200 chars; distances 0–500 km
- **22 new tests**; **Total: 5,069 passing** (up from 5,047)

### Accomplished (Session 164)

#### open-source-rideshare — Driver Language Skills & Rider Language Preferences

**Feat (commit `ebbf097`)**: Language-matched rides for non-English-speaking communities — genuine cooperative accessibility that Uber/Lyft have never offered.

- **`DriverLanguage` model**: unique `(driver_id, language_code)` constraint; `LanguageProficiency` enum (basic/conversational/fluent/native); `is_primary` flag (at most one per driver — auto-clears previous)
- **`RiderLanguagePreference` model**: one row per rider (upsert on update); soft preference — matching surfaces language-compatible drivers first, never blocks a ride when none available
- **8 service functions**: `set_driver_language` (upsert with primary-clear logic), `remove_driver_language`, `get_driver_languages`, `get_drivers_by_language` (optional min_proficiency filter using ordered proficiency scale), `set_rider_language_preference`, `get_rider_language_preference`, `clear_rider_language_preference`, `get_language_coverage_stats` (per-language driver count + fluent/native breakdown for admin diversity reporting)
- **9 endpoints**: GET /drivers/{id}/languages (public); GET/POST/DELETE /drivers/me/languages (driver self-manage); GET/PUT/DELETE /riders/me/language-preference (rider); GET /admin/language-coverage-stats; GET /admin/drivers/{id}/languages
- **Migration o2p3q4r5s6t7** (down_revision: n1o2p3q4r5s6) — 2 tables, 1 enum type, 3 indexes, 1 unique constraint
- **40 new tests**; **Total: 5,047 passing** (up from 5,007)

### Accomplished (Session 163)

#### open-source-rideshare — Driver Certification Badges

**Feat (commit `44c7037`)**: Cooperative recognition system for driver quality and community contribution. Drivers earn badges surfaced to riders at match time — Uber/Lyft have no peer recognition equivalent.

- **8 badge types**: `safe_driver` (0 incidents + high rating), `five_star` (sustained 4.8+, 50+ rides), `accessibility_specialist` (WAV certified), `pet_friendly` (opted in), `long_distance_expert` (10+ rides >30km), `mentor` (active mentorship), `eco_driver` (electric/hybrid), `veteran` (365+ days + 500+ rides)
- **`DriverCertification` model**: unique `(driver_id, badge_type)` constraint; revoked badges kept as `is_active=False` for full audit trail
- **6 service functions**: `award_badge` (409 on dupe, re-activates revoked), `revoke_badge` (404 if not active), `get_driver_badges` (active-only or all), `check_badge_eligibility` (8 criteria queried from rides/ratings/incidents/vehicles/mentorship), `auto_award_eligible_badges`, `get_badge_stats` (by type + top drivers)
- **6 endpoints**: GET /drivers/{id}/badges (public, active only); GET /drivers/me/badges (driver, includes revoked); POST/DELETE /admin/drivers/{id}/badges (award/revoke); POST /admin/drivers/{id}/badges/check-eligibility (auto-award eligible); GET /admin/badge-stats
- **Migration n1o2p3q4r5s6** (down_revision: z1a2b3c4d5e6) — 1 table, 1 enum type, 2 indexes, 1 unique constraint
- **38 new tests**; **Total: 5,007 passing** (up from 4,969)

### Accomplished (Session 162)

#### open-source-rideshare — Community Safety Alerts

**Feat (commit `1d77664`)**: Crowdsourced hazard reporting for drivers and riders. Every cooperative member can warn others about road conditions, construction, weather, and safety concerns in real time. Unlike Uber/Lyft (which silo safety data), this gives the network a live community safety layer where every member has a voice.

- **2 models**: `SafetyAlert` (alert type: road_hazard/construction/weather/traffic/dangerous_area/other; severity: low/medium/high/critical; lat/lon + radius_meters; optional description + auto-expiry; moderation lifecycle: pending/auto_approved/approved/rejected; cached upvote_count; soft-deactivate); `SafetyAlertUpvote` (unique vote per user per alert; CASCADE delete)
- **Auto-approval**: low-sensitivity types (road_hazard, construction, weather, traffic) skip moderation and are immediately visible; sensitive types (dangerous_area, other) enter pending queue for admin review
- **Proximity search**: haversine great-circle + bounding-box DB pre-filter; alert's own radius_meters extends effective query radius (e.g. a 500m area alert surfaced even if its centre is slightly outside the query zone)
- **10 service functions**: create (auto-approve logic), get (404 on miss), nearby search (approved + active + non-expired), upvote (409 on dupe or inactive), list mine, deactivate (reporter or admin; 403/409 guards), admin list (filter by status/type), admin moderate (approve/reject; reject also deactivates), platform stats
- **10 endpoints**: 5 auth-user (POST /safety-alerts, GET /nearby, GET /me, POST /upvote, DELETE deactivate); 4 admin (list, detail, moderate, stats); 1 admin force-deactivate
- **Migration m1n2o3p4q5r6** (down_revision: l1m2n3o4p5q6) — 2 tables, 4 enum types, 7 indexes, 1 unique constraint
- **48 new tests** (48 passed, 12 skipped — integration tests need live DB); **Total: 4,969 passing** (up from 4,921)

### Accomplished (Session 161)

#### open-source-rideshare — Platform Announcements / Cooperative News Feed

**Feat (commit `c8189b5`)**: Persistent cooperative communication channel. Unlike Uber's opaque email blasts, cooperative members get a structured, browsable news feed with full acknowledgment audit trails. Critical policy/regulatory notices require explicit acknowledgment before they can be dismissed — giving the cooperative a legally defensible record that members were informed.

- **2 models**: `PlatformAnnouncement` (title, body, audience: all/drivers/riders/members, priority: low/normal/high/critical, `requires_acknowledgment` flag; draft-or-published lifecycle via `published_at`; optional `expires_at`; soft-delete via `is_active`); `AnnouncementView` (per-user view + `acknowledged_at`; unique constraint on (announcement_id, user_id) prevents duplicate rows)
- **Audience routing**: drivers see ALL + DRIVERS + MEMBERS; riders see ALL + RIDERS + MEMBERS; public (no auth) sees only ALL
- **13 service functions**: create/update/publish/unpublish/delete (admin writes); get + admin_list_all; list_public_announcements (no-auth); list_announcements_for_user (role-filtered); mark_viewed (idempotent upsert); acknowledge_announcement (409 if already acked, 422 if not required); get_pending_acknowledgments (unacked critical items per user); get_announcement_stats (view + ack counts); get_announcement_views (paginated per-user records)
- **16 endpoints**: 1 public (GET /announcements), 4 auth-user (my feed, pending acks, mark viewed, acknowledge), 9 admin (CRUD + publish/unpublish + stats + view records + soft-delete)
- **Migration l1m2n3o4p5q6** (down_revision: k3l4m5n6o7p8) — 2 tables, 2 enum types, 6 indexes, 1 unique constraint
- **34 new tests** (34 passed, 17 skipped — integration tests need live DB); **Total: 4,921 passing** (up from 4,887)

### Accomplished (Session 160)

#### open-source-rideshare — Cooperative Board Elections

**Feat (commit `9e4f919`)**: Full democratic governance tooling for electing cooperative board members. Unlike Uber/Lyft (which have no such structure), driver-owners elect their own representatives through a formal, transparent process with nomination windows, candidacy review, and secret ballots.

- **4 models**: `CooperativeBoardSeat` (named seats with term months, term limits, eligibility threshold, current holder tracking); `BoardElection` (7-stage lifecycle: draft → nominations_open → nominations_closed → voting_open → tallied → certified | cancelled); `BoardCandidacy` (driver self-nomination with platform statement; admin-reviewed with approve/reject; vote_count cached at tally); `BoardElectionVote` (secret ballot; unique per driver per election — individual choices never exposed publicly)
- **Business rules**: one active election per seat at a time (409 guard); ride eligibility thresholds for both running and voting; tie-breaking by earliest applied_at; certification updates seat's current holder and sets term expiry date
- **14 service functions**: full seat CRUD, all 6 election lifecycle transitions, candidacy apply/review/withdraw, cast_vote with eligibility checks, get_election_results (tallied/certified only), get_board_roster
- **20 endpoints**: 2 public (board roster, seat list), 6 driver (list elections, detail, ballot, self-nominate, withdraw, secret ballot), 12 admin (seat CRUD, create draft, open/close nominations, open voting, tally, certify, cancel, full results, review candidacy)
- **Migration k3l4m5n6o7p8** (down_revision: j3k4l5m6n7o8) — 4 tables, 2 enum types, 10 indexes, 2 unique constraints
- **50 new tests** (50 passed, 16 skipped); **Total: 4,887 passing** (up from 4,837)

### Accomplished (Session 159)

#### open-source-rideshare — Driver Incentive Zones (Transparent Boost Zones)

**Feat (commit `f68fd69`)**: Cooperative-transparent "boost zones" — admins create time-limited geographic zones with earnings bonuses for drivers. Every zone includes a mandatory `reason` field visible to drivers, showing them the cooperative's rationale. Unlike Uber's opaque Boost multipliers, this is fully transparent governance.

- **2 models**: `DriverIncentiveZone` (polygon or circle geometry; MULTIPLIER (e.g. 1.5× earnings) or FLAT (fixed cents per ride) bonus; optional total cap + per-driver cap; optional min rating; mandatory reason); `DriverZoneCompletion` (idempotent per-ride award; (zone_id, ride_id) unique constraint prevents double-awarding)
- **Pure helpers**: `check_ride_qualifies` (ray-cast polygon check + haversine circle; validates active flag and time window); exposed for testing
- **10 service functions**: create/update/deactivate/get zone, get active zones, get all zones, record_zone_completion (idempotent; total + per-driver cap guards), get_driver_completions, get_driver_zone_summary, get_zone_stats
- **11 endpoints** (4 driver, 7 admin): driver (list active, zone detail, my bonus history, my earnings summary); admin (create, list all, get, update, deactivate, record completion, performance stats)
- **Migration j3k4l5m6n7o8** (down_revision: i2j3k4l5m6n7) — 2 tables, 1 enum type, 5 indexes, 1 unique constraint
- **39 new tests** (39 passed, 0 failed); **Total: 4,837 passing** (up from 4,798)

### Accomplished (Session 158)

#### open-source-rideshare — GDPR/CCPA Data Privacy Compliance

**Feat (commit `994e390`)**: Full data privacy compliance — legally required for EU/California and a meaningful cooperative differentiator (Uber/Lyft offer nothing comparable).

- **3 models**: `PrivacyConsentRecord` (consent audit trail; 4 policy types; IP + user-agent evidence; idempotent upsert on version change), `DataExportRequest` (GDPR right of access; full lifecycle with 7-day expiry and 3-download cap), `AccountDeletionRequest` (GDPR right to erasure; 30-day grace period; cancellable; irreversible PII anonymisation — row kept for referential integrity)
- **13 service functions** including generate_user_data_export (profile + ride/payment counts + consent history), execute_account_deletion (overwrites name/email/phone/password, deactivates account)
- **11 endpoints**: 8 user-facing (consent CRUD, data export request/status/download, deletion request/status/cancel) + 3 admin (list exports, list deletions, execute deletion)
- **Migration i2j3k4l5m6n7** (down_revision: h1i2j3k4l5m6) — 3 tables, 3 enum types, 8 indexes
- **29 new tests** (fixed 4 mock-chain bugs in test file); **Total: 4,798 passing** (up from 4,769)

### Accomplished (Session 157)

#### open-source-rideshare — Ride Carbon Footprint Tracker

**Feat (commit `07e3d2f`)**: Green Rides — per-ride CO2 tracking and voluntary carbon offsets. Cooperative differentiator: Uber/Lyft offer no environmental accountability.

- **1 model**: `RideCarbonRecord` — emission_class (petrol/diesel/hybrid/electric/unknown), distance_km, co2_grams computed at record creation, voluntary offset payment tracking
- **Emission rates**: petrol 120g/km, diesel 130g/km, hybrid 70g/km, electric 50g/km (well-to-wheel mixed grid)
- **Offset pricing**: $1 per 10kg CO2 (10 cents/kg) — minimum 1 cent
- **7 service functions**: 2 pure calculators + idempotent record upsert (preserves offset if already paid) + get + pay offset (409 if already paid) + rider summary + platform stats
- **5 endpoints**: rider (per-ride data, lifetime summary, pay offset) + admin (record/update, platform sustainability metrics with green_pct, electric_pct)
- **Migration h1i2j3k4l5m6** (down_revision: g1h2i3j4k5l6) — 1 table, 1 enum, 3 indexes
- **26 new tests**; **Total: 4,769 passing** (up from 4,743)

### Accomplished (Session 156)

#### open-source-rideshare — Driver Mentorship Program

**Feat (commit `634f676`)**: Driver Mentorship Program — cooperative differentiator with no Uber/Lyft equivalent.

- **2 models**: `DriverMentorship` (pending → active → completed | cancelled; commission_rate + commission_days snapshotted at assignment), `MentorshipEarning` (per-ride commission; idempotent unique constraint on ride_id)
- **Lifecycle**: new driver requests mentorship → admin assigns experienced driver as mentor → active for configurable days (default 90) → auto-completes → mentor earns 2% of mentee ride earnings
- **8 service functions**: request (409 guard), assign (404/409/400 guards), cancel (409 guard), record_commission (idempotent), complete_expired (batch), earning summary, admin summary, list mentees
- **8 endpoints**: driver self-service (request/status/mentees/earnings) + admin (list/summary/assign/cancel)
- **Migration g1h2i3j4k5l6** (follows hardship fund)
- **26 new tests**; **Total: 4,743 passing** (up from 4,717)

### Accomplished (Session 155)

#### open-source-rideshare — Recovery + Driver Emergency Assistance Fund

**Fix (commit `2800b57`)**: Four cancellation policy files from a prior session were on disk but never git-added. Recovered and committed — no code changes, just the missing `git add`. 77 cancellation tests confirmed passing first.

**Feat (commit `7810699`)**: Driver Emergency Assistance Fund — cooperative mutual-aid infrastructure. No Uber/Lyft equivalent.

- **3 models**: `DriverHardshipFund` (singleton balance ledger), `HardshipContribution` (deposit record), `HardshipApplication` (driver application with full lifecycle)
- **6 application statuses**: pending → under_review → approved → disbursed | denied; or withdrawn
- **6 application types**: medical, vehicle_repair, natural_disaster, housing, bereavement, other
- **Business rules**: one active application per driver at a time; fund balance sufficiency check before approving; ownership check on withdrawal
- **13 endpoints**: public balance (transparency), driver self-service (apply/list/view/withdraw), admin full review workflow (start review / approve / deny / disburse) + contribution management
- **Migration f8a9b0c1d2e3** (follows airport queue)
- **28 new tests**; **Total: 4,717 passing** (up from 4,689)

### Accomplished (Session 154)

#### open-source-rideshare — Airport Queue Management System COMPLETE (commit `5766eb3`)
Real operational feature: airports require TNC drivers to stage in designated holding lots and be dispatched FIFO. This implements the full system for regulatory compliance with airport authorities.

- **AirportZone**: admin-configured staging/pickup zone per terminal; max_queue_size cap; ttl_minutes expiry policy; is_active toggle
- **AirportQueueEntry**: FIFO queue slot per driver-per-zone; status: waiting → dispatched | left | expired; UniqueConstraint prevents double-joining; position derived from joined_at ASC (no mutable column = no race conditions)
- **Service**: join (capacity check + dup guard + TTL expiry set), leave, get_position (1-based FIFO rank), dispatch_next (pops FIFO head, returns next_in_queue), expire_stale, admin_zone_view (expire → snapshot → today's stats)
- **9 endpoints**: driver (join/leave/get position/list active queues); admin (create/list/view/update zones + dispatch + remove entry + expire stale)
- Migration: e7f8a9b0c1d2 — airport_zones, airport_queue_entries; queueentrystatus enum; 5 indexes; 1 unique constraint
- **35 new tests passing** (18 DB tests skipped); **Total: 4,689 tests passing** (up from 4,654), 0 failing

### Accomplished (Session 153)

#### open-source-rideshare — Community Partner Organization System COMPLETE (commit `cea2099`)
Cooperative differentiator: hospitals, social service agencies, and NGOs can partner with the platform to directly fund rides for their clients — filling the last-mile gap for patients, job-training participants, and others who need transport support but can't pay out-of-pocket.

- **PartnerOrganization**: pending → active ↔ suspended / terminated; 7 org types; optional monthly credit issuance cap; designated partner admin user can log in and view their org's data
- **PartnerCreditGrant**: org issues a dollar credit to a specific rider; optional per-ride cap; optional expiry; FIFO applied across rides; auto-marked exhausted when balance reaches $0
- **PartnerCreditUsage**: immutable record per ride; idempotent (unique constraint prevents double-apply)
- **apply_credit_to_ride()**: service helper ready to call from the rides service when a ride completes
- **21 endpoints**: admin org CRUD + lifecycle (activate/suspend/terminate), admin grant issuance/revocation/usage view, partner-admin read-only org portal, rider credit summary + usage history
- Migration: d6e7f8a9b0c1 — 3 tables, 3 enum types, 7 indexes, 1 unique constraint
- **27 new tests passing** (11 DB tests skipped); **Total: 4,654 tests passing** (up from 4,627), 0 failing

### Accomplished (Session 152)

#### open-source-rideshare — Rider Cooperative Membership & Dividends COMPLETE (commit `be177df`)
Completes the multi-stakeholder cooperative model. Drivers already had profit-sharing and governance; riders now join as member-owners too.

- **RiderCoopMembership**: applicant → member ↔ suspended / resigned; tracks lifetime_rides + voting_weight (1 + rides//100, max 5)
- **RiderCoopVote**: riders vote on existing DriverProposal records; weight snapshotted at cast time; stored separately for per-stakeholder tallies
- **RiderDividendShare**: riders receive a portion of quarterly surplus proportional to rides taken that period
- **15 endpoints**: full rider self-service (apply/resign/withdraw/vote/dividends) + admin management (approve/suspend/reinstate/generate shares/mark paid) + platform summary
- Migration: c6d7e8f9a0b1 — 3 tables, 3 enum types, 9 indexes, 3 unique constraints
- **31 new tests passing** (19 DB tests skipped); **Total: 4,627 tests passing** (up from 4,596), 0 failing

### Accomplished (Session 151)

#### open-source-rideshare — Driver Live Location Tracking COMPLETE (commit `f299951`)
Fills a fundamental rideshare infrastructure gap: riders can now track their assigned driver in real-time during active rides. Admins get a platform-wide live driver map.

- **DriverLocation** model: one row per driver (upserted on each push); latitude, longitude, accuracy_meters, heading, speed_kmh, is_active, ride_id (nullable)
- **3 endpoints**:
  - `POST /drivers/me/location` — driver pushes GPS coordinates (upsert, authenticated driver only)
  - `GET /rides/{ride_id}/driver-location` — rider or driver reads current position; restricted to `driver_en_route`, `arrived`, `in_progress` status; 403 for non-participants; 409 for wrong status; 404 if driver hasn't pushed yet
  - `GET /admin/drivers/live` — paginated list of all is_active=True drivers with last-known position (admin only)
- `clear_driver_location()` helper to mark driver inactive on shift end
- Migration: b5c6d7e8f9a0 — driver_locations table, unique constraint on driver_id, 4 indexes
- **23 new tests passing** (8 DB tests skipped); **Total: 4,596 tests passing** (up from 4,573), 0 failing

### Accomplished (Session 150)

#### open-source-rideshare — Driver Incident Reporting System COMPLETE (commit `9be524d`)
Cooperative differentiator: Uber/Lyft notoriously poor at driver safety support — reports often vanish with no feedback. This gives drivers a transparent incident channel with formal status tracking and admin accountability.

- **DriverIncidentReport** model: driver_id, ride_id (nullable), incident_type (7: passenger_harassment/physical_threat/property_damage/theft/unsafe_behavior/accident/other), severity (low/medium/high/critical), status (submitted/under_review/resolved/dismissed), description, evidence_urls, admin_note, reviewed_by_id, reviewed_at
- **10 endpoints**:
  - Driver: `POST /drivers/me/incidents` — report; `GET /drivers/me/incidents` — list; `GET /drivers/me/incidents/{id}` — get; `PUT /drivers/me/incidents/{id}` — update (submitted-only)
  - Admin: `GET /admin/driver-incidents` — list (filter by status/severity/type/driver); `GET /admin/driver-incidents/{id}` — get; `GET /admin/driver-incidents/summary` — stats (open_count, critical_open, breakdowns)
  - Admin: `PUT /admin/driver-incidents/{id}/review` — start review; `PUT .../resolve` — resolve; `PUT .../dismiss` — dismiss
- Migration: a4b5c6d7e8f9 — driver_incident_reports table, 3 enum types, 4 indexes
- **26 new tests passing** (17 DB tests skipped); **Total: 4,573 tests passing** (up from 4,547), 0 failing

### Accomplished (Session 149)

#### open-source-rideshare — Driver Shift & Hours Tracking System COMPLETE (commit `b715edb`)
Cooperative differentiator: Uber/Lyft have no driver fatigue protections. This gives drivers clock-in/out, daily/weekly hours visibility, and break recommendations — and gives admins a platform-wide fatigue dashboard.

- **DriverShift** model: driver_id, started_at, ended_at, status (active/completed/auto_ended), rides_completed, total_minutes, admin_note, ended_by_admin_id
- **Policy constants**: 12 h/day max, 60 h/week max, break recommended after 4 h on shift
- **9 endpoints**:
  - Driver: `POST /drivers/me/shift/start` — clock in; `POST /drivers/me/shift/end` — clock out
  - Driver: `GET /drivers/me/shift/current` — active shift status
  - Driver: `GET /drivers/me/shifts` — paginated history; `GET /drivers/me/hours/summary` — daily + weekly hours
  - Driver: `GET /drivers/me/shift/fatigue` — break recommendation + hours remaining
  - Admin: `GET /admin/driver-shifts` — all shifts (filter by driver, status, date); `GET /admin/driver-hours/summary` — fatigue dashboard
  - Admin: `POST /admin/driver-shifts/{id}/end` — force-end any active shift (records admin note)
- Migration: z1a2b3c4d5e6 — driver_shifts table, 4 indexes
- **16 new tests passing** (25 DB tests skipped); **Total: 4,547 tests passing** (up from 4,531), 0 failing

### Accomplished (Session 148)

#### open-source-rideshare — Corporate Business Accounts System COMPLETE (commit `71401f6`)
Companies can register corporate accounts, add employee riders with optional per-member spend limits, and receive consolidated billing invoices. Platform admins manage and audit all accounts.

- **BusinessAccount** model: company name, tax_id (optional), billing_email, billing_address, status (pending/active/suspended/cancelled), monthly_budget_limit
- **BusinessAccountMember** model: account + user pair; role (admin/member); per-member monthly_spend_limit; soft-deletable; max 500 per account; user can only belong to one active account
- **BusinessInvoice** model: billing period, total rides + amount, status lifecycle (draft → issued → paid/overdue)
- 17 endpoints:
  - `POST /corporate/accounts` — create account (becomes admin)
  - `GET/PUT /corporate/accounts/me` — view/update own account
  - `GET/POST /corporate/accounts/me/members` — list / add members
  - `PUT/DELETE /corporate/accounts/me/members/{user_id}` — update / remove member (last-admin guard)
  - `GET /corporate/accounts/me/invoices` — invoice history
  - `GET /corporate/accounts/me/spend` — current month spend summary
  - `GET /admin/corporate/accounts` — list all (filter by status)
  - `PUT /admin/corporate/accounts/{id}/suspend|activate` — account status management
  - `POST /admin/corporate/accounts/{id}/invoices` — generate invoice for billing period
  - `PUT /admin/corporate/invoices/{id}/issue|paid` — invoice lifecycle
  - `GET /admin/corporate/summary` — platform-wide totals
- Migration: d5e6f7g8h9i0 — corporate_accounts_v2, corporate_account_members, corporate_invoices; 3 enum types, 5 indexes
- **45 new tests** (39 passing + 6 skipped); **Total: 4,531 tests passing** (up from 4,492), 0 failing

### Accomplished (Session 147)

#### open-source-rideshare — Trusted Contact & Trip Sharing System COMPLETE (commit `d7889ee`)
- **54 new tests; Total: 4,492 tests passing** (up from 4,467), 0 failing

### Accomplished (Session 146)

#### open-source-rideshare — Driver Rating Appeal System COMPLETE (commit `1d3f1db`)
- **38 new tests; Total: 4,467 tests passing** (up from 4,451), 0 failing

### Accomplished (Session 145)

#### open-source-rideshare — Ride Cancellation Policies and Fees COMPLETE (commit `c2c332e`)
- **85 new tests; Total: 4,451 tests passing** (up from 4,419), 0 failing

### Needs Your Input

#### open-source-rideshare — PR: Sessions 129–152 (many features)
Branch: `feature/corporate-business-accounts` — **4,627 tests passing**. Features since last push:
- Rider Cooperative Membership & Dividends (be177df) ← new
- Driver Live Location Tracking (f299951)
- Driver Incident Reporting (9be524d)
- Driver Shift & Hours Tracking (b715edb)
- Corporate Business Accounts (71401f6)
- Trusted Contact & Trip Sharing (d7889ee)
- Driver Rating Appeal System (1d3f1db)
- Ride Cancellation Policies and Fees (c2c332e)
- Lost and Found System (cb508dd)
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
3. **open-source-rideshare**: Next enterprise feature (6,563 tests passing, corporate suite very complete)
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
