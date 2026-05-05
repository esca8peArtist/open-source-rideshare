---
title: Beta Testing Framework — OpenRide Phase 2 Pilot Program Design
project: open-source-rideshare (OpenRide)
date: 2026-05-05
status: research complete — actionable for Phase 2 execution
author: research agent
related_files:
  - phase-2-engagement-roadmap.md
  - phase-2-insurance-framework.md
  - cooperative-models-research.md
  - regulatory-compliance-research.md
---

# Beta Testing Framework: OpenRide Phase 2 Pilot Program Design

## Most Important Finding

Every cooperative rideshare that has survived past year one secured anchor demand before launching to the public. Drivers Cooperative Colorado secured a Denver city government contract for senior/low-income transport. Namma Yatri beta-launched with 100 drivers recruited directly through the Bangalore Auto Union. Green Taxi Denver aggregated enough members (800) to create internal demand before seeking external riders. The failure modes — app instability at Drivers Cooperative NYC, rider-side cold-start at ATX Co-op Taxi — both trace to launching without sufficient anchor demand. OpenRide's beta framework must bake this in from day zero.

---

## 1. Pilot Program Design

### 1.1 Overview

The OpenRide beta pilot should run as a staged 6-month program in one city with a single cooperative operator. This is not a "soft launch" — it is a structured research and validation exercise with defined success gates, a fallback plan, and data collection architecture embedded in the platform from the start.

**Pilot configuration**:
- **Duration**: 6 months, structured in three 2-month phases
- **Target city**: One city (selection criteria in Section 3)
- **Driver count target**: 100 drivers at soft launch, 300-500 by month 4
- **Rider acquisition**: Anchor demand (NEMT/government contract) + organic rider growth. No paid consumer marketing until month 4.
- **Cooperative operator**: A pre-existing or newly formed cooperative entity — not OpenRide Foundation directly. The pilot validates the federation model, not just the software.

### 1.2 Phase 0: Pre-Pilot Setup (Days 1-45)

This phase happens before a single trip is dispatched. Most pilot programs fail because they skip it.

**Legal and compliance**:
- Incorporate the local pilot cooperative (worker cooperative or multistakeholder LCA) under state law
- Execute Platform License Agreement between local cooperative and OpenRide Foundation
- File for TNC operating license in target state (timeline varies: 30 days in Georgia, 60-90 days in California; see regulatory-compliance-research.md)
- Secure $1M commercial auto liability insurance (Periods 2 and 3) — Fare Co-op used Y-Risk specialty insurer; contact them first. Phase-2-insurance-framework.md confirms Y-Risk covers 49 states
- Execute data-sharing agreement with any transit agency or government partner

**Technical setup**:
- Deploy OpenRide stack to production environment (recommendation: AWS or GCP in target city region, not shared dev server)
- Configure Stripe Connect platform account and verify connected account flow with 5 test drivers
- Integrate background check provider (Checkr is standard; integration takes approximately 5 business days)
- Set up driver onboarding document upload and review workflow
- Establish insurance period state machine (Period 1/2/3 tracking) in backend
- Load test the WebSocket real-time tracking system (minimum: 100 concurrent driver connections without degradation)
- Verify 1099-NEC generation flow with Stripe (even if no driver will hit $600 in the pilot, verify the system works)

**Recruitment**:
- Execute peer recruitment via 3-5 paid cooperative ambassadors (see phase-2-engagement-roadmap.md, Section 2.1)
- Target: 100 drivers with completed onboarding (background check passed, insurance period verified, Stripe connected account active) by day 45
- Do not open driver enrollment beyond this group until soft launch gate is passed

### 1.3 Phase 1: Soft Launch (Days 45-105, Months 2-3)

**Objectives**: Validate core technical reliability, driver onboarding flow, and payment routing under live conditions with manageable driver count.

**Operations**:
- Launch with 100 drivers in a defined geographic zone (not whole city — pick 2-3 zip codes with high driver concentration)
- Rider acquisition via: NEMT/government contract (captive demand), word of mouth, university partner program if applicable
- All trips monitored by at least one operations staff member during initial week
- Daily standups with driver ambassadors to capture issues in real-time

**Success gate for Phase 2 unlock** (must pass ALL):
- Trip completion rate: 93%+ (trips where driver accepted and completed, not cancelled)
- Payment routing: 100% of completed trips processed without manual intervention
- Driver onboarding: 0 drivers rejected due to system error (only regulatory disqualifications)
- App crash rate: Under 2% of sessions
- Average ETA at match: Under 12 minutes (soft launch geography is small, so this should be achievable)
- Zero Period 2/3 insurance incidents

**Data collected during Phase 1**:
- Every GPS point for every trip (stored, not just streamed — needed for dispute resolution and route verification)
- Time-to-match for every request (from rider submission to driver acceptance)
- Driver acceptance rate (what % of ride requests do drivers accept when pinged?)
- Driver earnings per hour (calculate actual, compare against Uber/Lyft baseline for the same city)
- Support ticket volume and category (what breaks first?)
- Governance portal: Did any drivers use the Loomio interface? What did they discuss?

### 1.4 Phase 2: Expanded Pilot (Days 105-135, Month 4)

**Objectives**: Scale driver count, expand geography, activate rider acquisition, and stress-test the governance system.

**Operations**:
- Open driver enrollment (remove the 100-driver cap)
- Expand service zone to cover full pilot city
- Launch first rider-facing marketing: cooperative branding, "own your ride" messaging, partnership with local credit unions / cooperative grocery stores for co-promotion
- First formal governance event: Membership meeting (hybrid), first policy vote (e.g., pricing policy ratification or service area expansion vote). This validates the governance interface, not just the trip dispatch.
- If NEMT contract is active: expand service hours to match contract requirements

**Driver retention focus**:
- At 90-day mark, conduct structured driver retention survey (10 questions max, in-platform)
- Hold first patronage earnings statement (even if small): show drivers the cooperative's financials, what their equity share looks like, what they'd receive in a dividend if profitable
- Driver ambassador program: pay top-performing early drivers a $500 "founding member" bonus at 90 days — creates visible loyalty incentive for later recruits

### 1.5 Phase 3: Full Pilot Operation and Evaluation (Days 135-180, Months 5-6)

**Objectives**: Operate at full capacity, collect data for phase 2 investment decision, evaluate partner feedback, and make go/no-go call on second city.

**Operations**:
- Full-city operation, open rider enrollment
- Weekly operations review (ops staff + driver ambassador representatives)
- Monthly cooperative board meeting with full financial transparency to members
- Prepare 6-month pilot report for partner organizations (transit agency, university, union)

**End-of-pilot deliverables**:
1. **Technical reliability report**: Trip completion rate, payment error rate, app crash rate, ETA performance over 180 days
2. **Driver economics report**: Median driver earnings vs. Uber/Lyft baseline; 90-day retention rate; governance participation rate
3. **Rider experience report**: NPS scores, ride volume growth, rider retention (% who took a second ride)
4. **Partner satisfaction report**: Did the NEMT contract run without incident? Did the university partner renew interest? What did the transit agency say in their data review?
5. **Go/no-go memo**: Recommendation on second city launch with supporting data

---

## 2. Selection Criteria for Pilot Cities and Partners

### 2.1 City Selection Matrix

Score each candidate city on these dimensions (1-3 scale, 3 = most favorable):

| Criterion | Weight | What to Look For |
|---|---|---|
| TNC regulatory environment | 25% | Has state TNC framework (all 50 states do), but look for states without NYC-style TLC overlay. Georgia, Oregon, Colorado, Minnesota score highest. |
| Insurance market | 20% | Y-Risk (Fare Co-op's insurer) covers 49 states. Check if specialty market exists for cooperative operators specifically. Non-NYC markets have 50-70% lower insurance costs. |
| Existing cooperative ecosystem | 15% | Presence of worker cooperative support organizations (USFWC affiliates, state cooperative development centers). Colorado, Wisconsin, Massachusetts, Oregon have strong ecosystems. |
| Driver supply concentration | 15% | Cities with existing rideshare driver communities, immigrant worker concentrations, or taxi cooperative history. Denver, Portland, Madison, Minneapolis score well. |
| Anchor demand availability | 15% | Government NEMT contracts, university partnership, transit agency first/last mile program. Cities with cooperative-friendly government procurement score higher. |
| Market competition intensity | 10% | Avoid NYC (entrenched TLC, rising insurance costs, market saturation) and San Francisco (regulatory complexity, high cost). Mid-size cities (200K-1M population) are optimal. |

**Recommended pilot cities based on this matrix** (in priority order):

1. **Portland, OR**: Phase-2-insurance-framework.md confirms Oregon is cooperative-friendly, PBOT has an active shared mobility program, TriMet has documented first/last mile gaps, existing Green Taxi analogue in Denver provides operational playbook
2. **Denver, CO**: Green Taxi Cooperative and Drivers Cooperative Colorado already operate here — OpenRide positions as technology partner, not new entrant. Network effects are pre-built.
3. **Madison, WI**: University of Wisconsin cooperative infrastructure, Union Cab worker-owned taxi cooperative, progressive city government, smaller population makes early iteration faster
4. **Minneapolis, MN**: Strong immigrant driver community (Somali, East African), existing cooperative ecosystem (Seward Co-op, others), transit-oriented city with documented first/last mile gaps

### 2.2 Partner Organization Selection Criteria

**For transit agency partners**, require:
- Written commitment to data sharing (pickup/drop-off, trip volume, rider demographics)
- Designated staff liaison who attends monthly review meetings
- Pre-agreed definition of "first/last mile" — what routes are they trying to supplement?
- Budget authority confirmed — who can sign the MOU?

**For university partners**, require:
- Student government buy-in (not just sustainability office)
- ADA-accessible vehicle requirement met (at least 10% of fleet must be WAV-capable in Year 1)
- Campus branding approval (universities will want co-branding, not full OpenRide branding)
- IT security review completed before app deployment on campus networks

**For union partners** (ATU, CWA, SEIU), require:
- Formal board resolution endorsing the cooperative pilot (not just staff enthusiasm)
- Agreement on driver representation in cooperative governance (typically: union members who join the cooperative retain union representation rights during a transition period)
- Non-compete clarity: the union must confirm that cooperative membership does not create a conflict with existing collective bargaining agreements for members who are also public transit employees

**For government/NEMT contract partners**, require:
- Contract with defined service requirements (geographic coverage, hours, vehicle standards)
- Payment terms: net-30 or better (cooperatives cannot absorb 60+ day payment delays in early operation)
- Performance bond waiver or small business exemption (cooperative may not have balance sheet to support a bond)

### 2.3 Partner Disqualifiers

Do not pursue partnerships with organizations that:
- Require exclusive data licensing (cooperative platform's data belongs to members, not partners)
- Require proprietary technology integration that creates vendor lock-in
- Have signed exclusive agreements with Uber or Lyft that restrict working with competitors
- Demand equity or profit-sharing in exchange for partnership (cooperative equity is for driver-members, not institutional partners)

---

## 3. Risk Mitigation Strategies

### 3.1 Technical Risk

**Risk**: App instability destroys driver trust before rider base is established (this is how Drivers Cooperative NYC failed).

**Mitigation**:
- Load testing before any live trip: simulate 200 concurrent drivers and 50 simultaneous ride requests before soft launch
- Staged rollout: 10 drivers in week 1, 25 in week 2, 50 in week 3, 100 in week 4 — this surfaces bugs at each scale threshold
- On-call engineering rotation during Phase 1 (someone reachable 24/7 for the first 60 days)
- Offline mode for driver app: if the driver app loses connectivity, the trip does not orphan — it continues with locally cached navigation and syncs when connectivity returns
- Automatic payment reconciliation: any payment that fails to process triggers an automatic retry queue, then manual review alert. No driver goes unpaid.

### 3.2 Regulatory Risk

**Risk**: TNC license delayed or denied in target state, blocking launch.

**Mitigation**:
- File in two states simultaneously (target state + one backup state) during Phase 0
- Begin filing 120 days before intended soft launch, not 30 days
- Engage a transportation attorney with specific TNC licensing experience in target state (general cooperative attorneys do not know TNC licensing; this requires a specialist)
- If license delayed: structure the soft launch as NEMT-only (NEMT licensing is separate from TNC licensing in most states and can be obtained faster)

### 3.3 Insurance Risk

**Risk**: Insurance carrier declines to cover a new cooperative operator, or coverage is unaffordable.

**Mitigation**:
- Contact Y-Risk (Fare Co-op's insurer) first — they have already underwritten a cooperative rideshare platform, which dramatically reduces underwriting uncertainty
- Have Drivers Cooperative Colorado or Fare Co-op provide a reference letter to Y-Risk on OpenRide's behalf (warm introduction to an insurer is worth months of cold outreach)
- Budget $4,000-$8,000/month for insurance in the first year (Phase-2-insurance-framework.md has detailed benchmarks)
- If commercial auto coverage is delayed: structure Phase 1 as a carpooling/ridesharing arrangement (not TNC) which falls under different insurance categories in most states

### 3.4 Driver Retention Risk

**Risk**: Drivers join the pilot but return to Uber/Lyft within 60 days because trip volume is insufficient.

**Mitigation**:
- NEMT/government contract is the single most effective mitigation — it provides guaranteed trips regardless of consumer rideshare demand
- Set realistic income expectations during recruitment: "This is a part-time income supplement for the first 3 months; full-time viable by month 4-5 as rider base grows"
- Do not over-promise hourly earnings during recruitment (Drivers Cooperative NYC promised $30/hour in 2021 and couldn't deliver reliably — this destroyed trust)
- 90-day retention bonus ($500 founding member bonus) creates a financial anchor that prevents early churn

### 3.5 Governance Risk

**Risk**: Member participation is so low that governance is captured by a small, unrepresentative group.

**Mitigation**:
- Set a minimum participation threshold for all binding votes: any proposal that receives votes from fewer than 25% of active driver-members is non-binding and must be re-sent with additional outreach before counting
- Governance engagement is an onboarding step — every driver who completes onboarding is walked through the governance portal and encouraged to vote on one existing proposal as a tutorial
- Loomio's async voting model accommodates gig workers who cannot attend fixed-time meetings — this is essential for a driver community

---

## 4. Measurement and Feedback Loop

### 4.1 Quantitative Metrics (Tracked Weekly)

**Platform reliability**:
- Trip completion rate (target: 95%+ by month 2)
- Payment error rate (target: <0.1%)
- App session crash rate (target: <1% by month 3)
- WebSocket connection stability (target: <0.5% dropped connections causing trip orphan)

**Driver economics**:
- Median driver earnings per hour (compare monthly against Uber/Lyft reported median for target city)
- Driver 30-day retention rate (% who drove at least one trip in their 2nd month)
- Driver 90-day retention rate (% who are still active at day 90) — industry target: 60%+ vs. Uber/Lyft's ~30%
- Average trips per active driver per week

**Rider experience**:
- Rider 7-day return rate (% who take a second ride within 7 days of first ride)
- Rider NPS survey (monthly, in-app, 10-question max)
- Average time from request to match (target: under 5 minutes in city core, under 12 minutes city-wide)

**Cooperative governance**:
- % of active driver-members who voted in at least one proposal per month (target: 40%+ by month 4)
- Number of member-submitted proposals per month (measures member engagement quality, not just consumption)
- Meeting attendance rate (% of members who attended at least one cooperative meeting in the quarter)

### 4.2 Qualitative Feedback Loop

**Weekly driver interviews (Months 1-3)**: 30-minute structured interviews with 3-5 randomly selected drivers per week. Topics: app reliability, earnings expectations vs. reality, governance participation experience, what would make them recruit other drivers. This is the most valuable signal.

**Monthly rider survey**: 5-question email survey to all riders who completed at least one trip that month. Net Promoter Score + two open-ended questions. Track NPS trend over time.

**Partner check-ins**: Monthly 30-minute call with designated liaison at each partner organization. Structured agenda: (1) what's working, (2) what's not, (3) what data do you need for your quarterly report, (4) what would make you renew/expand the partnership.

**Governance sentiment survey** (quarterly): Anonymous survey to all driver-members. Are they satisfied with decision-making processes? Do they feel their voice matters? Do they understand how profits are distributed? This is a leading indicator of cooperative health — dissatisfied members who feel unheard are likely to exit.

### 4.3 Iteration and Response Protocol

**Weekly**: Operations team reviews crash reports, payment errors, support tickets. Any issue affecting more than 5% of trips or any payment processing failure triggers immediate engineering escalation.

**Monthly**: Platform metrics report shared with all partner organizations and posted in member governance portal (full transparency). Driver ambassador team reviews earnings data and prepares feedback summary for engineering team.

**At Phase Gates (Day 45 → Phase 1, Day 105 → Phase 2, Day 135 → Phase 3)**: Formal review against all success criteria. Go/no-go decision for next phase made by cooperative board (driver-member vote, simple majority). This is governance in practice, not just policy.

**6-Month Final Evaluation**: External evaluator (recommended: ICA Group, USFWC, or academic partner from a cooperative studies program) reviews pilot data and produces independent assessment. This is critical for fundraising and second-city expansion — partners and funders want independent validation, not self-reported success.

---

## Sources

- [A National Rideshare Cooperative Takes Aim at Uber and Lyft — Jacobin, Dec 2024](https://jacobin.com/2024/12/a-national-rideshare-cooperative-takes-aim-at-uber-and-lyft)
- [Drivers Cooperative-Colorado: Building a Social Co-op — Nonprofit Quarterly](https://nonprofitquarterly.org/drivers-cooperative-colorado-building-a-social-co-op-for-rideshare-drivers/)
- [Fare Co-op Rises to America's 3rd Largest Fully Licensed Rideshare](https://fare.coop/news/from-vision-to-reality-fare-co-op-rises-to-become-americas-3rd-largest-fully-licensed-rideshare-in-less-than-12-months/)
- [Fare Co-op Expands in California — PR Newswire, Jan 2025](https://www.prnewswire.com/news-releases/driver-owned-ride-hailing-platform-fare-co-op-expands-in-california-with-over-5-000-registered-drivers-and-increased-investments-302355893.html)
- [The Rise and Fall of NYC's Driver-Owned Ride-Share — Documented NY, Oct 2024](https://documentedny.com/2024/10/07/forman-nyc-driver-cooperative-taxi-ride-share/)
- [Innovator Update: The Drivers Cooperative — Workers Lab](https://www.theworkerslab.com/updates/innovator-drivers-cooperative)
- [Namma Yatri — Story Part 1 (India Notes)](https://newsletter.theindianotes.com/p/story-of-namma-yatri-part-1)
- [Namma Yatri Launch and Driver Onboarding — Internet Katta](https://www.internetkatta.com/beyond-the-ride-unveiling-the-secrets-of-namma-yatris-success)
- [CWA Local 7777 Builds Green Taxi Coop in Denver — CWA](https://cwa-union.org/news/entry/cwa_local_7777_builds_green_taxi_coop_in_denver)
- [Transit and TNC Partnerships — APTA](https://www.apta.com/research-technical-resources/mobility-innovation-hub/transit-and-tnc-partnerships/)
- [One Year In, Access Pilot Program — RTA Chicago, Feb 2025](https://www.rtachicago.org/blog/2025/02/20/one-year-in-access-pilot-program-makes-transit-more-affordable-encourages-ridership-growth)
- [How Can Ride-Sharing Companies Partner with Public Transit? — GovTech](https://www.govtech.com/transportation/how-can-ride-sharing-companies-partner-with-public-transit.html)
- [Microtransit Trends — EY, 2024](https://www.ey.com/en_us/insights/government-public-sector/microtransit-trends-and-strategies-shaping-the-future)
- [CoopCycle Federation Governance — Platform Cooperativism Consortium](https://platform.coop/blog/coopcycle-navigating-political-democratic-and-economic-realities/)
- [CoopCycle in Argentina — International Review of Applied Economics, 2024](https://www.tandfonline.com/doi/abs/10.1080/02692171.2024.2433443)
- [Loomio — How It Works](https://www.loomio.com/how-it-works/)
- [Empowering Communities with Platform Cooperatives — OECD, 2023](https://www.oecd.org/content/dam/oecd/en/publications/reports/2023/09/empowering-communities-with-platform-cooperatives_63d716b6/c2ddfc9f-en.pdf)
- [Via TransitTech for Universities](https://ridewithvia.com/audience/universities)
- [Unveiling and Mitigating Bias in Ride-Hailing Pricing — AI and Ethics / Springer, 2024](https://link.springer.com/article/10.1007/s43681-024-00498-3)
- [Best Instant Payouts for Ride-Share — Dots, 2026](https://usedots.com/blog/best-instant-payout-solutions-ride-sharing-delivery/)
- [Stripe Connect Tax Reporting Documentation](https://docs.stripe.com/connect/tax-reporting)
