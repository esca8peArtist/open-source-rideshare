# Active Projects

> This is the single source of truth for autonomous orchestration.
> The orchestrator reads this file at the start of every session.
> Update priorities, status, and current focus as work progresses.
>
> **Last updated by**: orchestrator on 2026-04-15 (Session 176)

---

## Priority Order
1. stockbot
2. mfg-farm
3. resistance-research
4. open-source-rideshare
5. seedwarden
6. open-repo
7. off-grid-living
8. containerized-agents
9. workout
10. resume

---

## Projects

### mfg-farm
**Goal**: Build a fully automated manufacturing business centered on 3D printing, with a path to a full print farm. Sell products on Etsy, Amazon, and similar platforms. Develop a complete business plan: product selection driven by market demand and unique value proposition, pricing strategy, fulfillment workflow, and a scaling roadmap from single printer to multi-printer farm with multiple colors and material capabilities. Explore adjacent manufacturing (laser cutting, CNC, resin printing) and integrate where demand justifies it. The north star is maximizing income — product and machine decisions should be driven by data: what sells, what margins look like, and where automation creates the highest leverage.
**Priority**: High
**Status**: Active — planning phase
**Visibility**: Private — local only, no GitHub push
**Working dir**: `projects/mfg-farm/`
**Current focus**: Session 107: Market research COMPLETE (861 lines). Business plan COMPLETE (1,002 lines). **Launch-ready** with 5-product sequenced catalog: ModRun cable management (month 1) → Drift flexi animals (month 2) → planters (month 5) → pet memorials (month 6) → GearStation gaming organizer (month 9). Full cost breakdowns, price floors, design strategy (commission first, build in-house by month 5–6), machine milestones with payback periods (P1S at 19 days, xTool S1 2 months, resin as separate model). **Next**: User reviews business plan and decides first action — commission initial cable management designs or start Fusion 360 learning path.
**Blocked on**: —
**Notes**: Automation is the core constraint — products and workflows must be designed for minimal human touchpoints per unit. Physical products mean real fulfillment costs (packaging, shipping, storage) — factor these in from the start. Etsy and Amazon have different fee structures and audiences; may want both. Scaling from 1→N printers requires thinking about file management, queue management, quality control, and packaging throughput — not just the printers themselves.

---

### resistance-research
**Goal**: Identify solutions to a failing democracy — if the current government could be replaced and rebuilt from a clean slate, what would it look like? How could it be structured to ensure justice, life, liberty, and the pursuit of happiness for all citizens? How could it be objectively efficient, equitable, and functional? This project addresses the full scope of government: voting systems, taxation, education, infrastructure, healthcare, law enforcement, housing, and everything in between. The government exists to serve its citizens — so how do we actually achieve that? A secondary goal is tracking and understanding the specific crises the United States is currently facing, finding actionable responses, and building a comprehensive integrated proposal for democratic renewal.
**Priority**: High
**Status**: Active
**Visibility**: Private — local only, no GitHub push
**Working dir**: `projects/resistance-research/`
**Current focus**: Session 109: **Publication-ready formatting pass COMPLETE** (commit `b467e0b`). Removed 1,200+ word internal changelog from header, replaced with clean date line. Added revision history appendix at end. Fixed "Twenty Domains" → "Twenty-Two Domains" in section 5.4. Standardized 113 subheadings to colon format. Document is now clean and shareable externally. **Next**: No further autonomous work identified — document is evidence-dense, coverage-complete, and publication-ready. User may choose to share, convert to PDF, or commission professional layout.
**Blocked on**: —
**Notes**: Ongoing research and monitoring project. Existing files cover ICE detention, litigation tracking, case studies, civic action. When no specific task is queued, extend existing threads, find new angles, and monitor developments. Democratic renewal proposal is comprehensive at 22 domains; remaining work is quality deepening and publication preparation.

---

### stockbot
**Goal**: Build a full-stack model building and automated trading platform with both a web app and iOS app integration. The platform should allow creation, backtesting, and optimization of trading models across multiple model types (stock, options, rule-based, ensemble, multi-timeframe). The end goal is fully automated live trading — but only after models are rigorously vetted and confidence is established through paper trading. Model training and optimization costs must stay under $20/month. Once a model is sufficiently validated through paper trading performance, it graduates to live trading. Profit maximization is the north star, but capital preservation and risk management are non-negotiable constraints.
**Priority**: High
**Status**: Active
**Visibility**: Private — local only, no GitHub push
**Working dir**: `projects/stockbot/`
**Current focus**: Paper trading LIVE since April 14. 3 sessions: momentum (SPY/QQQ/MSFT), rsi_mean_reversion (AAPL/NVDA), sma_crossover (AMZN/SPY). Orchestrator cannot pull cycle logs without STOCKBOT_API_KEY in env. **Next**: User shares cycle logs or Trading page screenshot to unblock model assessment.
**Blocked on**: —
**Notes**: Web app is in good shape. Model creation and most optimisation is operational. Paper trading has just started but has had issues — this is the current priority. iOS app is out of scope until paper trading is solid. All features must work across ALL model types (stock, options, rule-based, ensemble, MTF) — do not implement something for one type only.

---

### open-source-rideshare
**Goal**: Build a free, open-source alternative to Uber and Lyft that stops price-gouging both riders and drivers. The platform should be a web and mobile app that minimises deployment and maintenance costs, ideally using a model where the platform itself is non-profit or cooperative — the margin extracted by Uber/Lyft goes back to drivers and riders instead. Solve the real problems: regulatory compliance in different jurisdictions, driver and rider safety and security, insurance, payment processing, and trust. Also build a plan for bootstrapping the user and driver base — a rideshare app with no users is worthless, so growth strategy is part of the scope.
**Priority**: Medium
**Status**: Active — early stage
**Visibility**: Public — push to feature branches on GitHub freely. Hold on main push for user approval.
**Working dir**: `projects/open-source-rideshare/`
**Current focus**: Session 176: **Corporate Budget Alerts COMPLETE** (commit `3f5027f`). Admins configure percentage-based thresholds on cost centers and the overall account; the evaluation engine computes monthly utilisation and triggers alerts when spend crosses a threshold, recording spend/budget snapshots. Triggered alerts can be acknowledged by any account admin. `CorporateBudgetAlert` model (unique per account+scope+cost_center+threshold_pct, BudgetAlertScope/Status enums, trigger+acknowledge audit fields), 7 service functions, 9 endpoints (member CRUD + evaluate + acknowledge + 2 platform-admin), migration x2y3z4a5b6c7, 48 tests. **Total: 5,489 passing**. **Next**: Next feature TBD; PR push when user ready. Previous: **Corporate Data Export COMPLETE** (commit `8147a9d`). CSV exports for corporate accounts — `export_corporate_rides_csv` (admin-only, filterable by date range/cost center/trip purpose, 19 columns incl. rider/driver names, fares, distance, trip tags) and `export_invoice_csv` (member-level, per-ride line items for a specific invoice with metadata on every row). 2 service functions; 4 endpoints; 25 tests. **Total: 5,441 passing**. Previous: **Corporate Employee Spend Limits COMPLETE** (commit `0daed0a`). Surfaces the existing `monthly_spend_limit` field on `BusinessAccountMember` with a full self-service and admin API — no new model or migration. Employees see current-month spend vs personal cap, utilization %, YTD totals, and monthly history. Admins set/update/remove per-employee limits and view a live member overview (bulk query). 6 service functions; 7 endpoints (2 employee self-service + 4 admin + 1 platform-admin); 43 tests. **Total: 5,417 passing**. Previous: **Corporate Guest Passes COMPLETE** (commit `ee0e029`). Employees issue limited-use UUID booking tokens to non-employees (clients, candidates, visitors). Guest submits token to book a ride billed to corporate account — no corporate login required. CorporateGuestPass model (UUID token unique, label, max_uses/uses_remaining, per-ride budget cap, optional trip_purpose + cost_center FKs, valid_from/valid_until window, GuestPassStatus enum, revocation audit); guest_pass_id FK added to rides; 8 service functions; 7 endpoints (employee CRUD + public validate + platform-admin list/account); migration w2x3y4z5a6b7; 44 tests. **Total: 5,374 passing**. Previous: **Corporate Trip Purpose Codes COMPLETE** (commit `564a580`). Employees tag rides with admin-defined purpose codes (CLIENT_MEETING, CONFERENCE, AIRPORT_TRANSFER, etc.); analytics break down spend per purpose with untagged bucket. CorporateTripPurpose model (code normalised uppercase, unique per account, soft-deactivate), 2 columns added to Ride (trip_purpose_id FK + trip_notes), 8 service functions, 9 endpoints (member/admin/rider/platform-admin), migration v2w3x4y5z6a7, 40 tests. **Total: 5,330 passing**. Previous: **Corporate Batch/Group Booking COMPLETE** (commit `1f86eb9`). Admins create a named batch booking (DRAFT), add up to 50 individual ride requests (passenger info, pickup/dropoff, time), then submit for fulfilment. Feature not in Uber for Business. 2 models (CorporateBatchBooking + CorporateBatchRideRequest), 9 service functions, 13 endpoints (member/admin/platform-admin), migration u2v3w4x5y6z7, 38 tests. **Total: 5,290 passing**. Previous: **Corporate Spending Analytics COMPLETE** (commit `88addd1`). Read-only analytics layer for corporate accounts — 4 service functions (spending overview with budget utilisation, monthly trend, employee breakdown, ride patterns by hour/DOW), 8 endpoints (4 member + 4 platform-admin), 35 tests. **Total: 5,252 passing**. Previous: **Corporate Monthly Invoices COMPLETE** (commit `4da54cd`). Formal billing/invoice lifecycle for corporate accounts — draft → finalized → paid (or void). CorporateInvoice model (corporate_invoices_v2 table; auto-generated invoice_number, 4-state enum, total_rides, subtotal_usd, per-transition timestamps), 8 service functions (generate/get/list/finalize/mark-paid/void/line-items/regenerate), 11 member + 3 admin endpoints, migration t2u3v4w5x6y7, 39 tests. **Total: 5,217 passing**. Previous: **Corporate Cost Centers COMPLETE** (commit `cfb33a0`). CorporateCostCenter model (account_id FK, code unique/account, is_active soft-delete, monthly_budget cap), nullable cost_center_id FK on rides, 7 service functions (create/get/list/update/deactivate/spend/breakdown), 10 endpoints, migration s2t3u4v5w6x7, 40 tests. Previous: **Corporate Ride Approval Workflow COMPLETE** (commit `f8658d7`). Pre-booking expense approval — employees request approval, admins approve/deny, unique code verified at booking time. CorporateRideApproval model, 7 service functions, 8 endpoints, migrations q2r3s4t5u6v7 (backfill) + r2s3t4u5v6w7, 38 tests. Previous: **Corporate Ride Policy COMPLETE** (commit `18d5a18`). CorporateRidePolicy model (unique per account_id), 4 service functions (get/set/delete/check_ride_allowed), 5 endpoints (member/admin), 31 tests. Previous: **Driver Work Preferences COMPLETE** (commit `57b8707`). DriverWorkPreference model (unique per driver), 3 service functions (get/update/reset), 4 endpoints, 22 tests. Previous: **Driver Language Skills & Rider Language Preferences COMPLETE** (commit `ebbf097`). 2 models (DriverLanguage + RiderLanguagePreference), 8 service functions, 9 endpoints, migration o2p3q4r5s6t7, 40 tests. Previous: **Driver Certification Badges COMPLETE** (commit `44c7037`). Cooperative recognition system — drivers earn 8 badge types (safe_driver, five_star, accessibility_specialist, pet_friendly, long_distance_expert, mentor, eco_driver, veteran) surfaced to riders at match time; DriverCertification model with audit trail; 6 service functions (award/revoke/get/eligibility check/auto-award/stats); 6 endpoints (public, driver self-view, 4 admin); migration n1o2p3q4r5s6; 38 new tests + **Total: 5,007 passing** (4,969 before). Branch: `feature/corporate-business-accounts`. **Next**: Next feature TBD; PR push when user ready. Features included: matching engine, payments (Stripe), dynamic pricing, geocoding, auth, safety (SOS), notifications (Twilio/SendGrid/FCM), driver tools (insurance, inspection, license, onboarding, performance + trends, destination filter, revenue projections, expense tracking, tips, earnings P&L summary, referral program, earnings goals, career tier, wait time billing, subscription plan, payout/disbursement, document expiry alerts, vehicle maintenance tracking, tax reporting 1099-NEC, bonus/quest programs, cooperative governance + voting, member dividends + profit-sharing, minimum earnings guarantee, cancellation fees, rating appeals, incident reporting, shift + hours tracking, live location tracking, airport queue, driver emergency assistance fund, driver mentorship program), rider tools (rating system, spending analytics, saved locations, fare splits, recurring rides, waypoints, busy hours indicator, surge price lock, membership plans, scheduled rides, corporate billing, fare disputes, user blocklist, loyalty rewards, accessibility profile, ride receipts, ride feedback, referral program, cancellation + fee visibility, trusted contacts + trip sharing, cooperative membership + voting + dividends, community partner credits, carbon footprint + voluntary offset, **GDPR/CCPA privacy compliance**), admin tools (financial reconciliation, ride export, notification log, rider management, promo analytics, user search, leaderboard, complaints/disputes, trip heatmap, demand-by-hour heatmap, platform config, surge zone auto-tuning, zone boundary suggestions, bulk broadcast notifications, referral stats, tier distribution, membership stats, scheduled ride summary, fare dispute review, blocklist review, driver subscription stats, rewards stats + manual adjust, payout queue + processing, WAV coverage stats + certification review, expiring document cross-fleet view + bulk expiry scan, fleet maintenance summary, all-feedback view, rider referral stats, cooperative transparency, public service coverage, quest/bonus management + leaderboard, proposal management + ballot records, dividend management + per-driver breakdown, earnings guarantee policy + weekly record management, lost and found report management, cancellation policy + waive + summary, rating appeal review + summary, trusted contact platform summary, corporate business accounts management, live driver map, rider cooperative member management + rider dividend generation, partner org management + credit issuance + usage reporting, airport zone management + FIFO dispatch, hardship fund balance + contributions + application review, mentorship program management + platform stats, platform carbon sustainability metrics, **privacy consent audit + data export + account deletion**), surge zones + waitlist, vehicle preferences, pooling, in-app chat, audit logging, background checks, incentives, cooperative transparency, lost and found, cancellation policies. Both Flutter apps have full user flows. **Note**: GitHub push blocked — SSH key `esca8peArtist` lacks access to `SuperClaude-Org`; commit is local.
**Blocked on**: —
**Notes**: This is the only public project. Higher standards for documentation, test coverage, and code quality since it's community-facing. Regulatory/safety/security solutions and growth strategy are in scope alongside the technical build.

---

### seedwarden
**Goal**: Build a profitable Etsy store and digital brand focused on farming, homesteading, and survival-related digital products, with the ability to expand into physical small products and seed packets. The business needs a full foundation: high-quality digital products that genuinely help people, a consistent social media presence across relevant platforms, and a reputation for real value. The goal is profit and a loyal customer base — not just a store. Grow the business systematically, identify what sells, double down on winners, and build a media presence that drives traffic organically.
**Priority**: Medium
**Status**: Active
**Visibility**: Private — local only, no GitHub push
**Working dir**: `projects/seedwarden/`
**Current focus**: Session 103 (last updated): **21 products, all PDFs generated, all listing copy complete.** Added Zone-by-Zone Seed Starting Calendar (1,635 lines, 82pp PDF, $7–$18) to product catalog — was missing from PDF generator and audit. Apartment Growing Complete Guide PDF now generated (146pp). Southwest region in Native Plants guide expanded (was 19 entries, target 30+; agent running). **Biggest blocker**: PDF mockup images needed for all listings — #1 conversion factor on Etsy, requires Canva or mockup generator. All content is ready; launch is blocked only on mockup images.
**Blocked on**: —
**Notes**: Etsy store exists with some products started but not yet quality to sell. Social media has plans but nothing executed. Need to fix quality before promoting. Plant images: all 120 native-plants images already downloaded and cached (verified Session 74) — "0/18" note in prior session was stale.

---

### open-repo
**Goal**: An open-source library for all things under the sun — a distributed, free, one-stop shop to find and share information that benefits all of humanity. Link to Wikipedia for general information, schematics, building plans, 3D models, recipes/instructions, services to share, and more. The core principle: no single person or organization controls any of it. Everything is distributed and open source. This is about leveling the playing field — giving all people the best chance to not only survive but thrive.
**Priority**: Medium
**Status**: Active — research phase
**Visibility**: Public — push to feature branches on GitHub freely. Hold on main push for user approval.
**Working dir**: `projects/open-repo/`
**Current focus**: Landscape research COMPLETE. Architecture notes COMPLETE. MVP protocol design COMPLETE (Session 78) — `mvp-protocol-design.md` (711 lines): 5 JSON-LD content type schemas, endorsement schema, ActivityPub federation protocol, 5-phase bootstrapping plan, MVP stack decisions (FastAPI/PostgreSQL/Meilisearch/Kubo/Next.js). Content import pipeline research COMPLETE — `content-import-openFarm.md`: OpenFarm API/schema/license documented, field mapping + sample transformation + 5-step implementation plan. Extraction script scaffolded: `scripts/import_openFarm.py` — `fetch_crops()`, `transform_crop()` (implemented), `validate_schema()`, `export_jsonl()`, `compute_cid_placeholder()`, CLI entry point. Key finding: OpenFarm live API shut down April 2025; data acquisition via self-hosted MongoDB export or Internet Archive snapshot. Next: acquire data (clone OpenFarm + mongoexport OR Internet Archive crawl), run import_openFarm.py, review output sample.
**Blocked on**: —
**Notes**: Start with landscape research before any building. The goal is ambitious — don't reinvent what already exists well. Identify the missing layer that ties it all together or fills the gaps nobody else is filling.

---

### off-grid-living
**Goal**: A comprehensive plan for off-grid, sustainable living. Define full plans for construction, implementation, operation, maintenance, and repair. Cover the complete operational architecture: food production, shelter, medicine, electricity generation, food preparation and storage, water, and general survival necessities. Include disaster scenarios up to and including nuclear disaster. Also cover community building, organization, and mutual support.
**Priority**: Medium
**Status**: Active — research phase
**Visibility**: Private — local only, no GitHub push
**Working dir**: `projects/off-grid-living/`
**Current focus**: **ALL 16 DOMAIN FILES NOW COMPLETE.** Session 103: `01-site-selection.md` (1,178 lines — 32-criterion parcel evaluation checklist; weighted scoring matrix; prior appropriation vs. riparian doctrine; state-by-state water/zoning/off-grid legality; regional comparison table with Mid-South/Appalachian/Pacific NW/Mountain West/Southwest detail; due diligence guide with minerals/easements/perc test/flood plain; 3-phase transition model with budget tables) and `12-security-defense.md` (1,252 lines — 13-threat probability×consequence matrix; fencing/camera/dog systems; livestock predator table 14 species; firearms loadout + storage + training; community defense protocols; 12 threat-specific response protocols; quarterly audit checklist; regional profiles; 50+ product reference list with 2026 prices). Both domains were the only ones listed as "Planned" in master-outline.md. **Document map now 100% complete.** **Next**: Quality review pass OR publish-ready formatting pass across all 16 domains.
**Blocked on**: —
**Notes**: This is a planning and research project, not a software build. Practical and actionable plans over theory. Include real costs, sourcing, and skill requirements where possible. Nuclear disaster scenario is in scope — treat it seriously.

---

### containerized-agents
**Goal**: Archived — goal TBD if reactivated.
**Priority**: Low
**Status**: Archived
**Visibility**: Private — local only, no GitHub push
**Working dir**: `projects/containerized-agents/`
**Current focus**: —
**Blocked on**: —
**Notes**: Archived per user direction on 2026-04-12.

---

### workout
**Goal**: Create comprehensive workout plans that blend athleticism, strength training, mobility, and calisthenics into unified programs. Produce plans for three equipment tiers: no equipment, resistance bands only, and full gym. Provide proposals for different training frequencies (days/week), exercise variety, and formats to build the best all-in-one plan maximizing strength growth while addressing athleticism, mobility, and bodyweight mastery.
**Priority**: Low
**Status**: Active
**Visibility**: Private — local only, no GitHub push
**Working dir**: `projects/workout/`
**Current focus**: `comprehensive-plan.md` (1,053 lines) complete — covers all 3 equipment tiers (no equipment, bands, full gym) × multiple frequencies (3/4/5/6 days), with full exercise libraries, progression systems, calisthenics skill ladders, and mobility protocols. Awaiting user review and selection.
**Blocked on**: —
**Notes**: Content/planning project, not a software build. Goal defined by user on 2026-04-12. Existing `proposals_v2.md` covers the 6-day gym PPL in detail (referenced from comprehensive plan). `requirements.md` has baseline info and calisthenics skill levels.

---

### resume
**Goal**: Maintain and improve Anya's professional resume and any associated portfolio materials.
**Priority**: Low
**Status**: Paused
**Visibility**: Private — local only, no GitHub push
**Working dir**: `projects/resume/`
**Current focus**: —
**Blocked on**: —
**Notes**: Only gets attention when explicitly requested.

---

## Exploration Queue

Topics fair game when no higher-priority task is active. Log findings to the relevant project or resistance-research.

- ~~Cryptographic voting systems and democratic resistance — extend the remote-voting research into the democratic renewal proposal~~ — **Done** (Session 24: Section 4 expanded to 8 subsections covering E2E-V protocols, deployed systems, coercion resistance, RLAs, post-quantum crypto, formal verification, maturity spectrum; Domain 1e updated with three-layer verification model)
- ~~Legal landscape of algorithmic decision-making in ICE detention — recent case law, civil rights angles~~ — **Done** (Session 24: `algorithmic-decision-making-immigration.md`, 270 lines — ICM/FALCON/ImmigrationOS systems, NIST bias data, Gonzalez v. ICE, EU AI Act/Canada AIA models, 6 reform recommendations; Domain 16d expanded)
- ~~Cooperative/platform cooperative business models — relevant to rideshare's ownership structure~~ — **Done** (Session 22: `cooperative-models-research.md`, 744 lines in open-source-rideshare/)
- ~~Regulatory landscape for rideshare in major US cities~~ — **Done** (Session 23: `regulatory-compliance-research.md`, 1,002 lines)
- ~~Etsy SEO and digital product market research — what sells in the homesteading/survival niche?~~ — **Done** (Session 24: `etsy-seo-market-research.md` in seedwarden/, 402 lines — Etsy algorithm mechanics, keyword strategy, competitive landscape, price positioning, title optimization, growth strategy, seasonal planning, bundle strategy, social media, metrics)

---

## Completed (Archive)

<!-- Move completed projects here with a completion date -->
