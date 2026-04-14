# Active Projects

> This is the single source of truth for autonomous orchestration.
> The orchestrator reads this file at the start of every session.
> Update priorities, status, and current focus as work progresses.
>
> **Last updated by**: orchestrator on 2026-04-13 (Session 104)

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
**Current focus**: Session 107: **All 22 domains deepened** — `national-security-evidence.md` (648 lines) confirmed as Domain 19 deepening (committed before domain-XX naming convention, content matches). **Domain-deepening library: 22/22 COMPLETE.** Full library: Domain 1 (Electoral), Domain 2 (Campaign Finance), Domain 3 (Anti-Corruption), Domain 4 (Economic Concentration), Domain 5 (Fiscal Reform), Domain 6 (Labor), Domain 7 (Housing), Domain 8 (Media/Information), Domain 9 (Federalism), Domain 10 (Criminal Justice), Domain 11 (Judicial Independence), Domain 12 (Immigration), Domain 13 (Healthcare/Education), Domain 14 (Environment/Climate), Domain 15 (Social Safety Net), Domain 16 (Data Privacy/Surveillance), Domain 17 (Reparations), Domain 18 (Rights Protection), Domain 19 (National Security), Domain 20 (Tax Policy), Domain 21 (Racial/Economic Justice), Domain 22 (Democratic Institutions). Next: quality review pass, synthesis, or publication-ready formatting of the democratic-renewal-proposal.md.
**Blocked on**: —
**Notes**: Ongoing research and monitoring project. Existing files cover ICE detention, litigation tracking, case studies, civic action. When no specific task is queued, extend existing threads, find new angles, and monitor developments. Democratic renewal proposal is comprehensive at 22 domains; remaining work is quality deepening and publication preparation.

---

### stockbot
**Goal**: Build a full-stack model building and automated trading platform with both a web app and iOS app integration. The platform should allow creation, backtesting, and optimization of trading models across multiple model types (stock, options, rule-based, ensemble, multi-timeframe). The end goal is fully automated live trading — but only after models are rigorously vetted and confidence is established through paper trading. Model training and optimization costs must stay under $20/month. Once a model is sufficiently validated through paper trading performance, it graduates to live trading. Profit maximization is the north star, but capital preservation and risk management are non-negotiable constraints.
**Priority**: High
**Status**: Active
**Visibility**: Private — local only, no GitHub push
**Working dir**: `projects/stockbot/`
**Current focus**: Paper trading LIVE. 3 sessions running: momentum (SPY/QQQ/MSFT), rsi_mean_reversion (AAPL/NVDA), sma_crossover (AMZN/SPY). First market open was April 14. Monitor via `http://127.0.0.1:8000` Trading page or `curl -H "Authorization: Bearer $STOCKBOT_API_KEY" http://127.0.0.1:8000/api/paper-trading/cycle-log?limit=20`. Orchestrator cannot pull cycle logs without API key in env. iOS app deferred until paper trading stable. **Next**: User needs to share cycle logs or Trading page screenshot — then orchestrator can assess model performance and suggest improvements.
**Blocked on**: —
**Notes**: Web app is in good shape. Model creation and most optimisation is operational. Paper trading has just started but has had issues — this is the current priority. iOS app is out of scope until paper trading is solid. All features must work across ALL model types (stock, options, rule-based, ensemble, MTF) — do not implement something for one type only.

---

### open-source-rideshare
**Goal**: Build a free, open-source alternative to Uber and Lyft that stops price-gouging both riders and drivers. The platform should be a web and mobile app that minimises deployment and maintenance costs, ideally using a model where the platform itself is non-profit or cooperative — the margin extracted by Uber/Lyft goes back to drivers and riders instead. Solve the real problems: regulatory compliance in different jurisdictions, driver and rider safety and security, insurance, payment processing, and trust. Also build a plan for bootstrapping the user and driver base — a rideshare app with no users is worthless, so growth strategy is part of the scope.
**Priority**: Medium
**Status**: Active — early stage
**Visibility**: Public — push to feature branches on GitHub freely. Hold on main push for user approval.
**Working dir**: `projects/open-source-rideshare/`
**Current focus**: Backend comprehensive — 2,769 tests passing. Features include: matching engine, WebSocket, payments (Stripe, cancellation fees), pricing (demand-aware, time-of-day), geocoding, auth, admin API, Alembic migrations, ride history, profile endpoints, safety service (SOS, trip sharing, emergency contacts), admin SOS monitoring, cancellation policy, notification service (Twilio SMS + SendGrid email + Firebase FCM push), driver rating aggregation, rate limiting, admin SOS WebSocket, scheduled rides, dispatch scheduler + retry logic, admin cancellation stats, driver earnings, promo codes & referral system, ride receipts, service areas/geofencing, admin feedback & disputes, ride & driver metrics dashboard, ride pooling/shared rides, vehicle management & WAV matching, in-app chat, transparent demand pricing, driver ETA estimation, saved locations, admin document verification, recurring rides/commute scheduling, multi-stop rides/waypoints, fare splitting, driver payout & settlement (Stripe Connect), SMS/email notification integration, audit logging & compliance reporting, background check integration (Checkr API), device token management (FCM), driver incentive/bonus programs (quest, peak-hours, streak, earnings guarantee), rider rating system (drivers rating riders, low-rated flag, admin monitoring), per-user push notification preferences (opt-in/out by type + channel, SOS bypass, full CRUD API), driver availability and scheduling (weekly schedule slots, online/offline toggle, heartbeat, admin monitoring), driver availability dispatch integration (MatchingEngine filters online+heartbeat+schedule-window drivers), driver insurance document management (status machine; 45 tests), driver vehicle inspection records (5 types; auto-expiry; 69 tests), driver license + vehicle registration document management (expiry tracking + alerts; 71 tests), driver onboarding status and activation workflow (checklist aggregates BGC+license+registration+inspection+insurance+profile; activate/suspend; 49 tests), driver performance scoring and scorecards (DriverPerformanceSnapshot; composite score 0–100; tiers bronze/silver/gold/platinum; 7 endpoints; 56 tests), lost and found system (LostItemReport; 9 endpoints; ~60 tests; migration a1b2c3d4e5f6), rider spending analytics + driver tax summary (4 endpoints; 41 tests; `services/analytics.py`), **admin financial reconciliation** (3 admin endpoints — summary+CSV+payout-status; gross/net revenue, daily breakdown, payout filtering; admin-auth gated; 54 tests; `services/admin_financials.py`), **admin notification log** (GET /admin/notification-logs; filterable by user/type/channel/status/ride; 16 tests; `api/v1/admin.py`), **admin rider management** (list/get/suspend/reactivate riders; 409 on duplicate action; bulk ride stats + rating; 20 tests; `api/v1/admin.py`), **admin promo analytics** (GET /promos/admin/stats; period filter week/month/year/all; top promos by usage+discount; referral breakdown; 11 tests; `api/v1/promos.py`), **driver tip summary** (GET /drivers/me/tips/summary; period filter; status breakdown; 36 tests; `api/v1/tips.py`), **admin tip stats** (GET /admin/tips/stats; platform-wide total/avg/unique drivers+riders/top-10 tipped drivers; 36 tests total with driver tip summary), **rider lifetime stats** (GET /analytics/rider/stats; total/completed/cancelled rides, completion rate, spend, distance, avg rating given, tips; 24 tests; `api/v1/analytics.py`), **admin top earners/spenders leaderboard** (GET /admin/stats/top-earners?role=driver|rider; period filter; 17 tests; `api/v1/admin.py`), **admin unified user search** (GET /admin/users/search?q=&role=all|driver|rider; full-text search across name/phone/email; driver stats included; 15 tests; `api/v1/admin.py`), **complaint and dispute management** (POST /complaints; GET filed/received; admin list/get/update; self-complaint guard; ride participant validation; terminal-state protection; 50 tests; `api/v1/complaints.py`), **vehicle type preference for ride requests** (VehicleServiceCategory enum: standard/comfort/xl/premium/wav; optional field on RideRequest schema + Ride model + RideResponse; MatchingEngine filters candidates by service_category when preference set; 15 unit tests + 9 integration tests; `models/vehicle.py`, `models/ride.py`, `schemas/ride.py`, `services/matching.py`), **surge pricing zone management** (SurgePricingZone model; polygon/circle geo zones; haversine + ray-casting pure Python; admin CRUD + toggle 6 endpoints; public active-zones map endpoint; FareBreakdown gains surge_multiplier + surge_label for transparency; overlapping zones → highest multiplier wins; time/day-restricted zones; 79 tests; `models/surge.py`, `services/surge_zones.py`, `api/v1/surge_zones.py`), **surge waitlist + price alerts** (SurgeWaitlistEntry model; riders join waitlist with max_multiplier threshold + expiry; check_and_notify_waitlist polling function marks notified/expired; public current-surge endpoint; admin trigger endpoint; 49 tests; `models/surge_waitlist.py`, `services/surge_waitlist.py`, `api/v1/surge_waitlist.py`), **driver destination filter / going-home mode** (DriverDestinationFilter model; drivers set a destination + radius so MatchingEngine only offers rides whose dropoff is within range; upsert set/clear/get service; PUT/GET/DELETE /drivers/me/destination-filter; optional expires_at; pure-Python haversine; 47 tests; `models/driver_destination.py`, `services/driver_destination.py`, `api/v1/driver_destination.py`). Push to GitHub blocked pending SSH key/credentials setup. Both Flutter apps have full user flows. **Total: 2,769 tests passing.**
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
