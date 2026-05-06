---
title: Governance Model Recommendation — OpenRide Cooperative Platform
project: open-source-rideshare (OpenRide)
date: 2026-05-06
status: research complete — actionable for Phase 2 planning
author: research agent
related_files:
  - phase-2-city-selection-analysis.md
  - cooperative-models-research.md
  - phase-2-engagement-roadmap.md
---

# Governance Model Recommendation

## Most Important Finding

The CoopCycle/Loomio Federation Model is the right governance structure for OpenRide's Phase 2. It is the only model with a live operational track record across multiple cooperatives, it is explicitly designed for platform cooperatives with distributed membership, and it is the fastest to operationalize (4–6 weeks vs. 6–8 weeks for a traditional cooperative structure). The DAO-Cooperative Hybrid is a liability for Phase 2 — regulatory risk, driver alienation, and 8–12 weeks to operationalize are all prohibitive at this stage. The traditional ICA single-cooperative model is structurally adequate but too slow for fast markets and too vulnerable to internal capture at scale.

The specific recommendation: adopt the CoopCycle/Loomio structure as the default governance template for every cooperative that deploys OpenRide, with each cooperative free to adjust within the template. Defer DAO experiments to Phase 3 when governance complexity actually requires it.

---

## 1. Model A: CoopCycle/Loomio Federation Model

### 1.1 Structure

The CoopCycle federation model separates technology infrastructure (the shared platform) from local cooperative operations. This is exactly OpenRide's architecture — the Foundation provides the software; local cooperatives operate rideshare services. The CoopCycle governance template maps directly onto OpenRide's design without modification.

**Federation tier** (OpenRide Foundation):
- Open-source software development and maintenance
- Shared services: insurance pooling, legal templates, background check vendor relationships
- Representation: one vote per affiliated cooperative in annual federation decisions
- Board elected from cooperative representatives at annual assembly
- Geographic and demographic representativeness criteria for board seats (per CoopCycle precedent)
- Decision tool: Loomio for async proposals; full membership vote for major decisions (bylaw changes, fee structure, software licensing terms)

**Local cooperative tier** (each city):
- Independent legal entity (cooperative corporation under state law)
- Driver members: 50% of board seats, operational governance
- Community/rider representatives: up to 30% of board seats (optional — depends on local governance preference)
- Day-to-day operations: staff/management operates under board delegation
- Local pricing, fare structure, and service area decisions
- Loomio workspace per cooperative for internal governance

**Decision architecture (two-level)**:
- Federation-level decisions (software updates, insurance pooling terms, licensing): async Loomio vote with 72-hour window, simple majority
- Local-level operational decisions (fare adjustments, driver deactivation policies, local partnerships): cooperative board or Loomio proposal with 48-hour window
- Emergency operational decisions (safety incident response, regulatory compliance): delegated to management, reported to board within 24 hours

### 1.2 How Loomio Works in Practice

Loomio is a worker-owned cooperative (based in New Zealand) that has operated for 15+ years. It is purpose-built for exactly this governance structure.

**Core features relevant to cooperative rideshare governance**:
- Async voting with defined windows (48–72 hours) — drivers can vote between shifts without attending meetings
- Multiple vote types: show of hands, multiple choice, ranked choice, score voting — different decisions warrant different polling mechanisms
- Quorum requirements configurable per decision type
- Delegated voters (proxy voting) for drivers who are active and can't participate
- Timestamped permanent record of every vote and its outcome — critical for legal defensibility of cooperative decisions
- Inline translation — essential for immigrant driver communities (Somali, Spanish, Amharic, Oromo)
- Integration with Slack, Mattermost, and SMS for notifications — drivers receive vote prompts via text message without needing to be in the app

**Practical governance calendar** under this model:
- Daily: operational decisions by management, no governance required
- Weekly: driver feedback channel on Loomio (comments, concerns, proposals)
- Bi-weekly: board meeting (video call + Loomio agenda), recorded in Loomio
- Monthly: any active proposals resolved (fare adjustments, policy changes)
- Quarterly: financial transparency report posted to Loomio for all members
- Annually: election of board representatives, major strategy decisions, federation representation

**Cost**: Loomio offers cooperative pricing — typically $49–$149/month for small groups. The foundation-level account covering all affiliated cooperatives would be a shared service cost.

### 1.3 Member Composition

**Driver members (primary class)**:
- Eligibility: 30+ trips completed on platform, background check passed, vehicle inspection passed, membership share purchased ($100–$250 recommended)
- Rights: vote on all cooperative decisions, eligible for board election, receive patronage dividends
- Responsibilities: participate in governance, maintain vehicle and driver standards

**Community members (optional secondary class)**:
- Eligibility: Riders, local businesses, transit agencies, community organizations who purchase a non-voting or limited-voting support share
- Purpose: Revenue and community buy-in, not governance control — driver members retain majority
- Rights: access to transparency reports, advisory participation in strategic discussions, patronage discounts

**Staff members** (if cooperative employs staff):
- Employed by the cooperative, not member-owners by default
- Some cooperatives give staff a separate board seat with limited voting rights on HR matters

### 1.4 Pros and Cons

**Pros**:
- **Proven operational model**: CoopCycle operates this structure across 50+ cooperatives in 7+ countries. The governance design has been tested, debugged, and refined over multiple years.
- **Modular**: Each city launches its own cooperative with minimal dependency on other cities. Failure in one market does not cascade to others.
- **Minimal central authority**: The foundation provides software and shared services but does not control local operations. This is important for regulatory compliance (each cooperative is an independent legal entity) and for driver trust (no distant headquarters controlling their platform).
- **Union-compatible**: Loomio's async voting model accommodates drivers who drive irregularly. The governance structure is familiar to union members who understand collective bargaining and democratic participation.
- **Fastest to operationalize**: No new legal entity structures need to be invented. Cooperative corporation + Loomio workspace + adoption of the federation template = operational governance in 4–6 weeks.
- **Aligned with Fare Co-op precedent**: Fare Co-op's federated multi-stakeholder structure is a live US example of this model working at scale.
- **Technology integration possible**: OpenRide can embed basic governance features (vote prompts, financial transparency dashboards, member registry) directly into the admin interface, reducing friction for driver participation.

**Cons**:
- **Onboarding complexity**: Drivers joining a cooperative for the first time need education on what cooperative governance means. The first month is heavy on onboarding — governance education materials, orientation sessions, and Loomio walkthrough are required. Budget 5–10 hours of staff time per new member cohort.
- **Coordination overhead across the federation**: When a software change affects all cooperatives, the federation-level vote must happen before deployment. This adds 72-hour minimum latency to platform updates that affect governance-relevant features.
- **Low participation risk**: Research on large cooperative governance consistently shows that participation rates in governance decline over time as the novelty wears off. Loomio quorum requirements prevent this from breaking governance, but building sustained engagement requires active effort. Recommend paid governance participation (hourly rate for attending quarterly driver assemblies) as a best practice.
- **Multi-language governance**: Portland's driver community is predominantly white; Denver and Minneapolis have large East African (Somali, Ethiopian, Eritrean) immigrant driver populations. Governance materials must be translated. Loomio's inline translation helps but is not a substitute for native-language governance meetings.

### 1.5 Timeline to Operationalize

| Step | Duration |
|---|---|
| Cooperative entity incorporated in target state | Days 1–14 |
| Bylaws drafted (using federation template) | Days 7–21 |
| Loomio workspace created and member class structure configured | Days 7–14 |
| Board of directors elected (founding driver cohort, minimum 5 members) | Days 21–35 |
| Governance education materials prepared and delivered | Days 21–42 |
| Federation membership agreement signed | Days 28–42 |
| **Operational governance: 4–6 weeks** | |

---

## 2. Model B: Traditional Cooperative (ICA Model)

### 2.1 Structure

A single cooperative entity incorporating all drivers as member-owners under the International Cooperative Alliance's seven Rochdale Principles. One member, one vote. Annual general meeting as the primary governance event. Board elected annually from the full membership.

**Decision-making**:
- Board of directors handles operational matters between member meetings
- Member meetings (annual or semi-annual) vote on major decisions
- Special member meetings can be called with 10–30% member petition (varies by bylaws)
- No async digital governance — primary governance mechanism is in-person or video general assembly

**Legal basis**: Most states have cooperative corporation statutes (Oregon, Wisconsin, Minnesota, Colorado all have established frameworks). The cooperative incorporates under state law with standard cooperative bylaws.

### 2.2 Pros and Cons

**Pros**:
- **Legal simplicity**: A single cooperative corporation is well-understood by attorneys, regulators, banks, and insurers. No federated structure to explain to a state regulator asking "who is the legal entity responsible for this TNC application?"
- **Strong member protections**: Cooperative corporation statutes provide clear member rights, profit-sharing rules, and governance protections. Harder for a dominant faction to seize control than in an unincorporated structure.
- **Familiar to unions**: Labor unions operate on a similar democratic model — annual elections, board delegation, member votes on major decisions. Union members transitioning to a cooperative understand this governance structure intuitively.
- **No technology dependency for governance**: General meetings can happen in person. For a small initial cohort (50–100 drivers in a single city), in-person governance is feasible.

**Cons**:
- **Slow decisions**: Annual meetings as the primary governance event mean a fare change proposal submitted in February may not be voted on until November. With a board delegation of operational authority, the board can act faster — but the board itself has limited meeting frequency.
- **Susceptible to capture**: When a cooperative has low average governance participation, a small motivated faction (15–20% of members who always show up) can effectively control the board and shape policy. This is a documented failure mode in established cooperatives.
- **No built-in async mechanism**: Drivers who work irregular hours, or who work multiple jobs, cannot meaningfully participate in governance timed around meetings. A rideshare cooperative with 100+ members drawn from diverse time zones, languages, and schedules needs async governance.
- **Legal setup required before operations**: The cooperative corporation must be incorporated, bylaws approved by the founding members, initial board elected, and basic governance structures established before the first driver onboards. This takes 6–8 weeks minimum.
- **Doesn't scale across cities**: If OpenRide wants to support multiple city cooperatives, each one needs to be a separate legal entity with separate governance. The traditional model provides no shared governance infrastructure between cooperatives.
- **Not designed for platform cooperatives**: Traditional cooperative law was designed for grocery stores, farms, and credit unions — not app-based platforms with real-time member interactions. The governance cadence doesn't match the operational reality of rideshare.

### 2.3 Timeline to Operationalize

| Step | Duration |
|---|---|
| Cooperative entity incorporated | Days 1–14 |
| Founding member meeting to adopt bylaws | Days 14–28 |
| Initial board elected | Days 21–35 |
| Governance calendar established | Days 28–42 |
| Member education on governance rights | Days 28–56 |
| **Operational governance: 6–8 weeks** | |

---

## 3. Model C: Hybrid DAO-Cooperative (Blockchain Governance)

### 3.1 Structure

A hybrid entity combining a cooperative legal charter (cooperative corporation under state law) with token-based on-chain voting for a defined subset of decisions — primarily the economic parameters that matter most to drivers: commission rate, fare pricing floors/ceilings, and insurance cost allocation.

**Decision architecture**:
- On-chain: fee structure, commission splits, insurance cost distribution, token issuance rules
- Off-chain (Loomio or equivalent): policy decisions, member conduct standards, partnership agreements, board elections
- Tokens: issued to driver-members based on tenure and contribution (trips completed, governance participation)
- Token-weighted voting for economic parameters (not pure one-member-one-vote — weighting rewards long-tenure drivers)

**Technical stack**: Most likely implementation uses a layer-2 Ethereum solution (Polygon, Optimism) or a purpose-built governance framework (Aragon, Snapshot) to minimize transaction costs and energy use.

### 3.2 Pros and Cons

**Pros**:
- **Transparent and auditable**: Every vote is on-chain and publicly verifiable. Fare structure decisions cannot be manipulated by a management team — the smart contract enforces the member vote outcome.
- **Fast execution for economic parameters**: Once a fare change is voted on, it executes automatically in the platform. No implementation lag.
- **Tenure recognition**: Token weighting can reward long-term driver-owners who have built the cooperative, without violating the one-member-one-vote principle for other governance questions.

**Cons**:
- **Regulatory uncertainty**: DAOs and token-based governance are not well-understood by TNC regulators, insurers, or cooperative attorneys. When filing for a PBOT permit in Portland, the applicant is a legal entity — a DAO is not a recognized legal entity. The cooperative charter handles legal status, but token governance adds a layer that regulators will not know what to do with.
- **Driver alienation**: The driver population for a cooperative rideshare platform — immigrant drivers, working-class gig workers, people who drive because they need income — is not the demographic that has broad familiarity with blockchain wallets, gas fees, or token mechanics. Designing governance around technology that most members cannot use effectively undermines the democratic mandate.
- **Security risk**: Smart contract exploits have drained hundreds of millions of dollars from DAOs. A bug in a governance contract that allows a token holder to seize the fare structure could be existential for the cooperative.
- **Overkill for MVP**: Phase 2 will have 50–200 drivers in 1–2 cities. At that scale, a Google Form or Loomio vote accomplishes everything a DAO accomplishes, without the complexity, cost, or risk. DAO governance adds value when the cooperative has thousands of geographically distributed members making decisions about complex multi-market economic parameters — that is a Phase 4 or Phase 5 problem.
- **Legal gray zone for cooperative taxation**: If tokens are considered securities, the Subchapter T cooperative tax advantages may be complicated. IRS guidance on tokenized cooperative governance is nonexistent as of 2026.
- **8–12 weeks to operationalize**: Building and auditing a governance smart contract, setting up a multisig wallet for cooperative treasury, and onboarding drivers into a token-based system takes significantly longer than setting up a Loomio workspace.

### 3.3 Timeline to Operationalize

| Step | Duration |
|---|---|
| Cooperative entity incorporated | Days 1–14 |
| Governance token design and legal review | Days 14–56 |
| Smart contract development and audit | Days 28–70 |
| Token distribution to founding members | Days 56–84 |
| Driver onboarding to blockchain wallet | Days 70–90 |
| **Operational governance: 8–12 weeks** | |

---

## 4. Recommendation and Rationale

### 4.1 Primary Recommendation: CoopCycle/Loomio Federation Model

Adopt the CoopCycle/Loomio Federation Model as the default governance template for all Phase 2 OpenRide deployments.

**The decisive arguments**:

1. **Proved by the most operationally successful cooperative rideshare platform in the US**: Fare Co-op is operating in Oregon under a federated multi-stakeholder structure. It is America's third-largest fully licensed rideshare. Its governance model is not theoretical — it is the reason Fare Co-op can operate across California, Georgia, Florida, and Oregon without a single central TNC license.

2. **Loomio solves the async governance problem**: Rideshare drivers work irregular shifts and cannot consistently attend in-person governance meetings. Loomio's 48–72 hour async vote windows allow drivers to vote between trips. This is not a convenience feature — it is the structural requirement for legitimate democratic governance of a rideshare cooperative. A governance model that relies on in-person attendance will have low participation, which means low legitimacy, which means the board governs without real mandate.

3. **Cooperative corporation + Loomio is legally clean**: The cooperative is a cooperative corporation under state law. Regulators, insurers, and attorneys understand what this is. The Loomio layer is the governance tool, not the legal entity. PBOT in Portland, Colorado PUC in Denver, and DSPS in Wisconsin all interface with the cooperative corporation — they do not need to understand Loomio.

4. **Union-compatible**: SEIU Local 26 in Minneapolis, CWA Local 7777 in Denver, SEIU Local 49 in Portland are the primary driver recruitment channels. Union members understand democratic governance, election of representatives, and collective decision-making. The federation model's governance structure is directly analogous to how unions operate — local chapters with federation-level shared governance. Union organizers can explain this model to drivers in five minutes.

5. **Fastest to operational governance**: 4–6 weeks vs. 6–8 weeks for the traditional ICA model and 8–12 weeks for the DAO-Cooperative hybrid. In a market where the first cooperative to sign drivers and launch wins the driver recruitment window, this matters.

### 4.2 Phase Sequencing for Governance Complexity

| Phase | Governance Tool | When to Add |
|---|---|---|
| Phase 2 (pilot) | CoopCycle/Loomio Federation | Immediately — use at launch |
| Phase 3 (2–4 cities) | Strengthen federation layer, add inter-cooperative governance forum | When second city launches |
| Phase 3+ (scale) | Consider Risk Retention Group formation (requires federation-level financial governance) | When 500+ total drivers across federation |
| Phase 4+ (if governance complexity grows) | Evaluate DAO tools for specific economic parameter decisions only | If member count exceeds 2,000+ and async Loomio votes feel insufficient |

The DAO-Cooperative hybrid should be reconsidered only if two conditions are both true: (1) the federation has more than 2,000 driver-members across multiple cities with diverse economic interests that are in genuine tension, and (2) the federation's legal counsel determines that on-chain governance can be implemented without securities law risk. Neither condition applies to Phase 2.

### 4.3 Governance Configuration Checklist (Phase 2 Launch)

The following governance elements should be operational before the first driver onboards:

**Legal structure**:
- [ ] Cooperative corporation incorporated in target state under appropriate cooperative statute
- [ ] Bylaws drafted and adopted by founding member cohort (use federation template from OpenRide Foundation)
- [ ] Federation membership agreement signed between local cooperative and OpenRide Foundation
- [ ] Member share structure defined (price $100–$250; payment plan for drivers who cannot pay upfront)
- [ ] Board of directors elected (founding cohort; minimum 5; majority driver-members)
- [ ] Cooperative attorney reviewed bylaws in target state

**Loomio configuration**:
- [ ] Loomio workspace created for the cooperative
- [ ] All board members and founding driver cohort added as members
- [ ] Decision types configured: operational votes (48h window), bylaw changes (7-day window), emergency decisions (delegated to board)
- [ ] Governance calendar published (board meetings bi-weekly; quarterly financial report; annual board election)
- [ ] Onboarding document prepared: "How to participate in your cooperative's governance" (max 2 pages, translated into primary driver community languages)
- [ ] Notification preferences configured: SMS or push notifications for active vote prompts

**Economic transparency**:
- [ ] Monthly revenue/expense report format agreed
- [ ] Patronage dividend calculation methodology written and ratified
- [ ] Reserve fund policy adopted (what percentage of surplus is retained vs. distributed)
- [ ] Insurance cost allocation to members disclosed (transparent as a per-driver line item)

**Federation-level participation**:
- [ ] Local cooperative representative designated for annual federation assembly
- [ ] OpenRide Foundation federation governance participation rights established
- [ ] Software update proposal pathway defined (Foundation proposes, local cooperative votes on adoption)

---

## 5. Governance Model Comparison Summary

| Dimension | CoopCycle/Loomio | Traditional ICA | DAO-Cooperative |
|---|---|---|---|
| **Time to operationalize** | 4–6 weeks | 6–8 weeks | 8–12 weeks |
| **Legal clarity** | High | Very high | Low-medium |
| **Regulatory acceptance** | High (cooperative corp) | Very high | Low |
| **Driver accessibility** | High (async, mobile) | Medium (meeting-dependent) | Low (blockchain required) |
| **Union compatibility** | Very high | High | Low |
| **Scale across cities** | Designed for it | Difficult (separate entities, no shared governance) | Theoretically designed for it but untested |
| **Live US precedent** | Yes (Fare Co-op) | Yes (Green Taxi Coop, Drivers Cooperative NYC) | No (no live US rideshare DAO) |
| **Insurance/lender acceptance** | High | Very high | Unknown/risky |
| **Governance participation rate (expected)** | Medium-high (async lowers barrier) | Medium (meeting-dependent) | Low (technical barrier) |
| **Phase 2 recommendation** | **ADOPT** | Consider for single-city pilots that want simpler legal | **DEFER to Phase 4+** |

---

## Sources

- [CoopCycle Federation Structure](https://legacy.coopcycle.org/en/federation/)
- [CoopCycle: Navigating Political and Democratic Realities (Platform Cooperativism Consortium)](https://platform.coop/blog/coopcycle-navigating-political-democratic-and-economic-realities/)
- [Loomio — How It Works](https://www.loomio.com/how-it-works/)
- [Loomio Cooperative Handbook — Governance](https://www.loomio.coop/governance.html)
- [Fare Co-op — The Rideshare You Own](https://fare.coop/)
- [Fare Co-op's Rapid Rise to America's 3rd Largest Rideshare (Highways Today, Sept 2025)](https://highways.today/2025/09/07/fare-co-op/)
- [Drivers Cooperative Colorado — Cooperative Models Research (this project)](cooperative-models-research.md)
- [Cooperative Models Research: Multi-Stakeholder Structures (this project)](cooperative-models-research.md)
- [Phase 2 Stakeholder Engagement Roadmap (this project)](phase-2-engagement-roadmap.md)
- [International Cooperative Alliance — Rochdale Principles](https://www.ica.coop/)
- [Minnesota Cooperative Statutes — Chapter 308A and 308B](https://www.revisor.mn.gov/statutes/cite/308A)
- [Oregon Cooperative Corporation Act (2019 update)](https://oregon.public.law/statutes/ors_62.005)
- [Wisconsin Chapter 185 — Cooperative Corporations](https://docs.legis.wisconsin.gov/statutes/statutes/185)
- [MAIF / CoopCycle Insurance Partnership (ICMIF)](https://www.icmif.org/news_story/maif-launches-an-insurance-offer-in-partnership-with-coopcycle-for-users-of-delivery-bicycles/)

---

*Confidence levels: CoopCycle federation model operational track record HIGH (50+ cooperatives documented); Loomio features HIGH (direct product documentation); DAO-Cooperative regulatory risk HIGH (no existing regulatory guidance on tokenized cooperative governance for TNC context); timeline estimates MEDIUM (derived from cooperative formation case studies, not OpenRide-specific timelines). All governance design elements should be reviewed by a cooperative attorney in the specific target state before adoption.*
