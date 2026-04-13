# Platform Cooperative Business Models for Rideshare
**Date**: 2026-04-11
**Purpose**: Inform OpenRide's ownership structure, revenue model, and cooperative deployment strategy
**Companion to**: [research-report.md](research-report.md) (tech landscape), [ARCHITECTURE.md](ARCHITECTURE.md) (technical design)

---

## Executive Summary

Platform cooperativism offers the most credible alternative to the extractive Uber/Lyft model. Real cooperatives already operate in rideshare — The Drivers Cooperative in NYC has ~8,000-9,000 driver members, Eva runs in Montreal at 8% commission, and several taxi co-ops predate app-based ride-hailing entirely. The model works. What doesn't work yet is the technology: every existing rideshare co-op either built fragile custom tech, licensed expensive third-party platforms, or relies on phone dispatch.

OpenRide's opportunity is not to be a cooperative itself, but to be the **open source infrastructure that cooperatives deploy**. This document covers the business models, ownership structures, revenue approaches, legal landscape, and failure modes — and ends with concrete recommendations for how OpenRide should position itself.

---

## 1. What Is a Platform Cooperative?

### 1.1 Definition

A platform cooperative is a digital platform — app, marketplace, or service — that is **owned and governed by the people who use it** (workers, customers, or both). It applies traditional cooperative principles to internet-era platform businesses.

The term was popularized by **Trebor Scholz** (The New School, New York) in his 2014 essay "Platform Cooperativism vs. the Sharing Economy" and subsequent book *Platform Cooperativism: Challenging the Corporate Sharing Economy* (2016). **Nathan Schneider** (University of Colorado Boulder) extended this with *Everything for Everyone: The Radical Tradition That Is Shaping the Next Economy* (2018), focusing on governance and democratic ownership.

### 1.2 Core Principles

Platform cooperatives inherit the **Rochdale Principles** (International Cooperative Alliance, established 1844, last revised 1995):

1. **Voluntary and open membership** — anyone who meets criteria can join
2. **Democratic member control** — one member, one vote (not one dollar, one vote)
3. **Member economic participation** — members contribute to and democratically control capital
4. **Autonomy and independence** — the cooperative is self-governing
5. **Education, training, information** — members are educated about cooperativism
6. **Cooperation among cooperatives** — co-ops work together
7. **Concern for community** — sustainable development of communities

### 1.3 How It Differs from Traditional Platforms

| Dimension | Traditional Platform (Uber) | Platform Cooperative |
|---|---|---|
| Ownership | Shareholders / VC investors | Workers, users, or multi-stakeholder |
| Governance | Board appointed by investors | Democratic (1 member = 1 vote) |
| Profit distribution | Dividends to shareholders | Surplus returned to members or reinvested |
| Commission | 25-40% of fare | 0-15% or flat fee |
| Data ownership | Platform owns all data | Members/cooperative owns data |
| Pricing | Algorithmic surge pricing | Transparent, stable pricing |
| Worker status | Independent contractor (contested) | Owner-operator or employee |
| Exit strategy | IPO or acquisition | No exit — perpetual community asset |

### 1.4 How It Differs from Traditional Co-ops

Traditional cooperatives (credit unions, agricultural co-ops, REI) operate in physical space with local membership. Platform cooperatives face unique challenges:

- **Scale**: A rideshare co-op might have 8,000 voting members across a city. A rural credit union might have 500.
- **Governance complexity**: Democratic decision-making is harder when members are geographically dispersed and interact primarily through an app.
- **Technology dependency**: The platform IS the business. A grocery co-op can operate with pen and paper; a rideshare co-op cannot.
- **Network effects**: The value of the platform depends on having enough participants on both sides (drivers and riders). Traditional co-ops don't face this chicken-and-egg problem.
- **Capital intensity**: Building and maintaining a mobile app + backend + real-time infrastructure costs real money. Traditional co-ops have lower tech overhead.

---

## 2. Existing Rideshare Cooperatives

### 2.1 The Drivers Cooperative (NYC)

- **Founded**: 2021
- **Location**: New York City
- **Status**: Operating. Pivoting toward paratransit/NEMT [non-emergency medical transport].
- **Structure**: Worker-owned cooperative. Incorporated as a cooperative corporation under New York Cooperative Corporations Law.
- **Membership**: ~8,000-9,000 driver members as of 2024 [approximate — various sources report different numbers]. This represents roughly 10-15% of NYC's licensed TLC drivers.
- **Membership buy-in**: Drivers purchase a membership share. Reports indicate $1 initial fee with $2.50/week deducted from earnings until a $500 share is paid off [unverified — terms may have changed].
- **Commission**: ~15% of fare, compared to Uber's ~25-30% and Lyft's similar range. The Drivers Cooperative has stated this is meant to decrease as the cooperative scales.
- **Revenue (2022)**: $5.9M gross revenue, 162,000 trips, $5.2M paid to drivers.
- **Technology**: Custom-built app. Chronically unstable — driver and rider reviews consistently cite crashes, GPS issues, and matching failures. This is the cooperative's biggest operational weakness.
- **Key pivot**: Moving toward paratransit and NEMT contracts, which provide guaranteed demand (government contracts) and don't require consumer rider acquisition. This is smart survival strategy but moves away from direct Uber/Lyft competition.
- **Governance**: Board of directors elected by driver members. Annual general meeting. One member, one vote.
- **Funding**: Raised via member shares, grants, and community investment. Notably received support from the Cooperative Development Foundation and local NYC programs. Cannot raise traditional VC (no equity to sell).
- **Key lesson**: Proves that drivers will join a cooperative for better economics. Proves that without solid technology, the cooperative stalls. The 15% commission, while better than Uber, is still significant — driven by technology and insurance costs.

### 2.2 Eva (Montreal)

- **Founded**: 2019
- **Location**: Montreal, Quebec, Canada
- **Status**: Operating [as of last verified reports, though scale is limited]
- **Structure**: Nonprofit cooperative (solidarity cooperative under Quebec law)
- **Commission**: 8% — among the lowest of any rideshare platform globally
- **Model**: Quebec's cooperative legislation is more favorable than most US states. Eva is structured as a "solidarity cooperative" which allows multiple stakeholder classes (drivers, riders, community supporters) under Quebec's *Cooperatives Act*.
- **Technology**: Custom-built mobile app
- **Geographic scope**: Focused almost exclusively on Quebec. Canadian regulatory environment is somewhat different from US.
- **Key differentiator**: The solidarity cooperative model means riders and community members can also be voting members, not just drivers. This creates a multi-stakeholder governance structure.
- **Key lesson**: Low commission is possible when you're a nonprofit without investor returns to generate. Quebec's cooperative-friendly legal framework matters — not all jurisdictions make this easy.

### 2.3 Green Taxi Cooperative (Denver)

- **Founded**: 2015
- **Location**: Denver, Colorado
- **Status**: Operating
- **Structure**: Worker-owned cooperative. Drivers are owner-operators.
- **Membership**: 150+ owner-operator members [approximate]
- **Model**: Taxi cooperative, not technically a TNC/rideshare. Operates under taxi regulations rather than TNC regulations. Drivers own their own vehicles and medallions/permits.
- **Membership buy-in**: ~$2,000 [unverified — may have changed]
- **Revenue model**: Members pay a flat monthly fee for dispatch, insurance access, and cooperative membership. No per-ride commission.
- **Dispatch**: Phone dispatch + app. Not a sophisticated tech platform.
- **History**: Founded by immigrant and refugee drivers who were being exploited by lease arrangements with traditional taxi companies. Strong community and cultural cohesion among membership.
- **Key lesson**: Community identity and shared grievance are powerful drivers of cooperative formation. The flat-fee model works when drivers have predictable demand. Taxi co-ops have existed for decades — the "platform cooperative" framing is new but the cooperative model for transportation is not.

### 2.4 ATX Co-op Taxi (Austin)

- **Founded**: 2016
- **Location**: Austin, Texas
- **Status**: Operating [reduced scale since Uber/Lyft returned to Austin in 2017]
- **Structure**: Worker-owned cooperative
- **History**: Formed after Uber and Lyft left Austin in May 2016 over a fingerprint-based background check requirement. Several cooperative and alternative rideshare platforms launched in the vacuum: Ride Austin (nonprofit), Fasten, Fare, and ATX Co-op Taxi.
- **What happened when Uber returned**: When Austin reversed the fingerprinting requirement in 2017, Uber and Lyft returned. Most alternatives (Ride Austin, Fasten, Fare) shut down or shrank dramatically. ATX Co-op Taxi survived because it had an existing taxi cooperative structure, not just a rideshare app.
- **Key lesson**: Regulatory disruption can create a window for cooperatives, but if the regulatory pressure is removed, the incumbents return with overwhelming market power. Cooperatives that survive long-term need a structural advantage beyond "Uber isn't here right now."

### 2.5 Other Notable Examples

**Cotabo (Bologna, Italy)**: One of Italy's largest taxi cooperatives, operating since 1968. ~800 drivers [approximate]. Uses modern dispatch technology including an app. Demonstrates that taxi cooperatives can operate at meaningful scale for decades.

**Ride Austin (Austin, Texas, 2016-2020)**: Nonprofit, not a cooperative. Launched during the Austin Uber/Lyft vacuum. 100% of fares went to drivers — the nonprofit operated on donations and sponsorships. Shut down during COVID-19 in 2020. Proves the nonprofit rideshare model is fragile without diversified revenue.

**Liftango / various carpooling co-ops**: Several smaller carpooling cooperatives exist globally but operate at a scale too small to draw meaningful lessons for urban rideshare.

**Namma Yatri (India)**: Covered in [research-report.md](research-report.md). Not a cooperative in formal structure — it's a company (Juspay subsidiary) — but operates on cooperative-like principles: zero commission, flat subscription, open source. 100M+ rides. The most important proof point that the economic model works at scale, even if the governance model is corporate.

---

## 3. Ownership Structures

### 3.1 Worker-Owned (Driver Cooperative)

**How it works**: Drivers are the sole member class. Each driver buys a membership share and gets one vote. The cooperative's board is elected by drivers. Surplus revenue (after operating costs) is returned to drivers as patronage dividends or reinvested by vote.

**Pros**:
- Alignment is clean: the people doing the work own the platform
- Strong driver recruitment pitch ("own your platform")
- Simplest governance — one stakeholder class
- The Drivers Cooperative and Green Taxi Cooperative use this model

**Cons**:
- Riders have no voice. If drivers vote to raise fares, riders have no recourse.
- Driver turnover in rideshare is extremely high (50-80% annual churn in traditional platforms). High turnover + democratic governance = unstable membership.
- Scaling governance beyond a few hundred members is hard. The Drivers Cooperative has 8,000+ members — meaningful democratic participation at that scale is a real challenge.

**Membership buy-in (typical range)**: $100-$2,000. Must be low enough not to exclude drivers (who are often capital-constrained) but high enough to create commitment.

**Best for**: Single-city deployments with a strong existing driver community.

### 3.2 Multi-Stakeholder (Drivers + Riders + Community)

**How it works**: Multiple classes of membership, each with defined voting rights. Example structure:
- **Driver members**: 50% of board seats, vote on operational matters
- **Rider members**: 30% of board seats, vote on pricing and service standards
- **Community/supporter members**: 20% of board seats, vote on mission alignment

Quebec's solidarity cooperative law explicitly supports this model. In the US, it requires more creative legal structuring.

**Pros**:
- Balances driver and rider interests
- Rider membership creates a committed user base (skin in the game)
- Community members can include local businesses, transit agencies, advocacy groups
- Eva (Montreal) uses a version of this model

**Cons**:
- Governance is more complex — three stakeholder classes means more meetings, more disputes, more politics
- Rider membership is harder to sell than driver membership (riders just want a ride, not governance participation)
- Voting weight allocation is inherently political — who decides drivers get 50% vs. 40%?
- Slower decision-making

**Best for**: Markets where community buy-in is critical and there's an existing multi-stakeholder coalition (e.g., a city transit authority + a driver union + a community organization all want to collaborate).

### 3.3 Municipal / Public Utility

**How it works**: A city or municipal transit authority operates the rideshare platform as a public service, similar to a public bus system. Funded by taxes, fees, or transit budgets. May be operated directly by a city agency or contracted to a cooperative or nonprofit.

**Pros**:
- Solves the capital problem (city budgets are large)
- Solves the regulatory problem (the city IS the regulator)
- Can integrate with existing public transit (first/last mile)
- Can mandate use by city employees, subsidize rides for equity populations
- No chicken-and-egg problem if the city subsidizes both sides initially

**Cons**:
- Political risk — changes with elections, subject to budget cuts
- Government IT procurement is notoriously slow and expensive
- Municipal unions may resist or demand concessions
- Drivers are likely employees (with benefits, pensions), which dramatically increases costs
- Limited to one city — no scaling across jurisdictions
- Innovation typically slower than private sector

**Real-world precedent**: No major US city has launched a municipal rideshare platform. Some cities (e.g., Los Angeles) have explored "public option" transit apps but none are operational at rideshare scale [as of early 2026]. Helsinki's Whim (MaaS Global) was a private attempt at municipal-scale mobility-as-a-service that struggled financially.

**Best for**: Cities with progressive governance, existing transit infrastructure, and a mandate to reduce dependence on Uber/Lyft. Most realistic as a pilot in a mid-size city (200K-1M population) where a single city government can act decisively.

### 3.4 Nonprofit

**How it works**: A 501(c)(3) or 501(c)(4) nonprofit corporation operates the platform. No owners, no equity, no dividends. All surplus is reinvested in the mission. Funded by grants, donations, and operating revenue.

**Pros**:
- Eligible for foundation grants and charitable donations
- Tax-exempt status reduces operating costs
- Clear mission alignment — "we exist to serve drivers and riders, not shareholders"
- Ride Austin used this model

**Cons**:
- No equity means no investor funding and limited access to debt capital
- Ride Austin's failure demonstrates fragility: when donations and sponsorships dried up (COVID), the nonprofit died
- 501(c)(3) restrictions limit political activity and lobbying, which may be needed for regulatory fights
- No member ownership means no built-in loyalty mechanism
- Board is self-appointing (not elected by users), which reduces accountability

**Best for**: Initial launch phase where grant funding is available and the goal is proving the model before transitioning to a cooperative structure.

### 3.5 Hybrid: Nonprofit Shell + Worker-Owned Operating Co-op

**How it works**: A nonprofit entity owns the technology and brand. It licenses (for free or at cost) to local worker-owned cooperatives that operate the platform in their markets. The nonprofit handles technology development, updates, and shared services. Each local cooperative handles driver recruitment, rider acquisition, regulatory compliance, insurance, and operations.

**Example structure**:
```
OpenRide Foundation (501(c)(3) nonprofit)
├── Develops and maintains the software platform
├── Provides shared services (payment processing, insurance pooling, legal templates)
├── Funded by grants, technology licensing fees, cooperative dues
│
├── Denver Drivers Co-op (worker-owned cooperative)
│   ├── Operates OpenRide in Denver
│   ├── Drivers are owner-members
│   ├── Handles local regulatory compliance
│   └── Pays monthly platform fee to Foundation
│
├── Austin Riders & Drivers Co-op (multi-stakeholder cooperative)
│   ├── Operates OpenRide in Austin
│   └── (same as above, different governance)
│
└── Portland Municipal Transit (city agency)
    ├── Deploys OpenRide as municipal service
    └── Pays annual licensing fee to Foundation
```

**Pros**:
- Separates technology (nonprofit, grant-funded) from operations (local, self-sustaining)
- Each local co-op can choose its own governance model, pricing, and market strategy
- The nonprofit can accept grants, donations, and foundation funding for tech development
- Local co-ops benefit from shared technology without each needing to build their own
- Scales naturally — adding a new city means adding a new local co-op, not scaling one organization
- **This is exactly what OpenRide should be.**

**Cons**:
- Coordination between the foundation and local co-ops requires clear agreements
- Technology decisions affect all co-ops — governance of the foundation itself matters
- If the foundation fails, all local co-ops lose their technology provider
- More legal complexity (multiple entities, inter-organization agreements)

**Best for**: A project like OpenRide that wants to serve multiple communities with shared technology.

---

## 4. Revenue Models for Zero/Low-Commission Platforms

The fundamental question: if you're not taking 25-30% of every fare, how do you pay for technology, insurance, support, and operations?

### 4.1 Flat Monthly Driver Subscription

**How it works**: Drivers pay a fixed monthly fee (e.g., $50-$200/month) for access to the platform. They keep 100% of fares.

**Real-world examples**:
- Namma Yatri charges drivers ~₹50-100/day (~$1-2/day, or ~$30-60/month) [approximate, varies by city]
- Green Taxi Cooperative charges a flat monthly fee [exact amount unverified]

**Pros**:
- Predictable revenue for the cooperative
- Drivers keep 100% of fares — strongest possible recruitment pitch
- Aligns incentives: the cooperative earns the same whether a ride is $5 or $50
- Simple to understand and administer

**Cons**:
- Part-time drivers subsidize nothing or need a lower tier
- If a driver has a bad month (few rides), they still owe the subscription
- Requires enough active drivers to generate meaningful subscription revenue
- Doesn't scale with ride volume — if usage doubles, revenue stays flat

**Suggested range for US market**: $50-150/month for full-time drivers, $25-50/month for part-time (fewer than 20 hours/week). Tiered pricing matters — a driver doing 5 rides/week shouldn't pay the same as one doing 50.

### 4.2 Per-Ride Flat Fee

**How it works**: Instead of a percentage commission, a fixed dollar amount is charged per completed ride (e.g., $0.50-$1.50/ride).

**Pros**:
- Scales with ride volume (more rides = more revenue)
- Fair to drivers: $0.75 on a $50 ride is 1.5%; $0.75 on a $8 ride is 9.4%. Still much less than Uber's 25%.
- Drivers can predict their costs per ride easily
- Hybrid fairness: cheaper than commission for expensive rides, somewhat more for cheap rides but still very low

**Cons**:
- Low revenue per ride means you need high volume to sustain operations
- Short rides generate the same platform revenue as long rides, which may not cover matching costs equally

**Suggested range**: $0.50-$1.50 per completed ride. At $1.00/ride and 10,000 rides/month (a small cooperative), that's $10,000/month in platform revenue. At 100,000 rides/month (a mid-size co-op), that's $100,000/month.

### 4.3 Low Percentage Commission (5-15%)

**How it works**: A traditional commission model, but at a much lower rate than Uber/Lyft.

**Real-world examples**:
- The Drivers Cooperative: ~15%
- Eva: 8%

**Pros**:
- Revenue scales naturally with ride volume and fare amounts
- Familiar model — drivers understand what a commission means
- 8-15% is dramatically better than 25-30% and is a strong recruitment message

**Cons**:
- Still feels like "taking from drivers" even if the rate is low
- Undermines the "keep 100% of your fares" narrative that Namma Yatri uses so effectively
- Creates the same misaligned incentive as Uber (platform benefits from higher fares) — just at a lower degree

**Assessment**: This is the pragmatic choice for cooperatives that need immediate revenue and can't afford to wait for subscription scale. The Drivers Cooperative uses 15% because they need to — technology and insurance costs are real. As those costs decrease (e.g., by switching to OpenRide from expensive custom tech), the commission can decrease.

### 4.4 Rider Membership / Annual Fee

**How it works**: Riders pay an annual or monthly membership fee for access to the platform, reduced fares, or priority matching.

**Pros**:
- Creates committed riders (invested in the platform's success)
- Revenue not tied to driver economics at all
- Can offer tiers: free (basic access), $5/month (no booking fee), $10/month (priority + discounts)

**Cons**:
- Hard sell: riders are used to free signup with Uber/Lyft
- Chicken-and-egg: riders won't pay to join a platform with no drivers
- Works better as a supplemental revenue stream than a primary one

**Assessment**: Don't require rider membership. Offer it as an optional tier for frequent riders who want perks. The base platform should be free for riders.

### 4.5 Municipal Subsidy

**How it works**: A city subsidizes the cooperative as a public transit complement. Common models:
- Direct operating subsidy (city pays $X/month to the cooperative)
- Per-ride subsidy (city pays $Y per ride to/from underserved areas)
- Infrastructure subsidy (city provides server hosting, office space, insurance pooling)

**Pros**:
- Solves the capital problem
- City gets a policy tool (subsidize rides to transit deserts, medical appointments, job centers)
- Can replace expensive paratransit contracts — many cities pay $30-60/ride for paratransit; a subsidized cooperative ride might cost $15-20 [approximate]

**Cons**:
- Political dependency — a new mayor can cut funding
- Procurement and compliance overhead
- May require the cooperative to meet municipal requirements (accessibility, geographic coverage)

**Assessment**: Extremely promising, especially for the paratransit/NEMT niche that The Drivers Cooperative is already pursuing. Cities already spend heavily on paratransit. A cooperative using OpenRide could bid on those contracts at lower cost than existing paratransit providers.

### 4.6 Grant Funding

**How it works**: Foundations, government programs, and impact investors provide grants for cooperative development.

**Relevant funders**:
- **USDA Rural Development** — has cooperative development grants
- **National Cooperative Bank** — provides financing to cooperatives
- **Cooperative Development Foundation** — funded The Drivers Cooperative
- **Robert Wood Johnson Foundation** — funds transportation equity projects
- **Ford Foundation** — has funded platform cooperativism research (via Trebor Scholz's Platform Cooperativism Consortium at The New School)
- **State cooperative development centers** — most states have one, funded by USDA
- **SBA (Small Business Administration)** — cooperatives are eligible for some SBA programs [verify eligibility for specific programs]

**Assessment**: Good for startup phase. Not sustainable long-term — grants are competitive, time-limited, and come with reporting overhead. Use grants to build the technology and launch pilots; transition to operational revenue (subscriptions + per-ride fees + municipal contracts) for sustainability.

### 4.7 Technology Licensing

**How it works**: The OpenRide Foundation (or equivalent nonprofit) licenses the platform to cooperatives, municipalities, or organizations in other cities/countries. Licensing can be:
- Free (open source, no restrictions)
- Free for cooperatives, paid for commercial entities
- Paid support/hosting tiers (like Red Hat's model with Linux)

**Pros**:
- Scales without the Foundation needing to operate in every city
- Creates a sustainable revenue stream for ongoing development
- "Open core" model is well-proven in software (WordPress, GitLab, etc.)

**Cons**:
- If the software is fully open source (which it should be), anyone can fork it and not pay
- Licensing revenue requires enough adopters to be meaningful
- Must avoid making the free version intentionally crippled — that undermines the mission

**Recommended approach**: OpenRide's source code is fully open source (AGPL or similar). The Foundation offers optional paid services:
- **Managed hosting**: $500-2,000/month per cooperative [estimated] for a fully hosted, maintained instance
- **Configuration and onboarding**: One-time setup fee ($5,000-20,000) for a new cooperative deployment
- **Custom development**: Hourly/project rates for cooperative-specific features
- **Insurance pooling coordination**: Administrative fee for managing group insurance procurement
- **Support contracts**: Annual support agreement for guaranteed response times

### 4.8 What They Actually Charge (Summary)

| Platform | Model | Rate | Notes |
|---|---|---|---|
| Uber | % commission | 25-30% | Plus booking fees, surge multipliers |
| Lyft | % commission | 25-30% | Similar to Uber |
| The Drivers Cooperative | % commission | ~15% | Aiming to reduce as they scale |
| Eva | % commission | 8% | Nonprofit, Quebec |
| Namma Yatri | Flat subscription | ~$1-2/day | Drivers keep 100% of fares |
| Green Taxi Co-op | Flat monthly fee | [unverified] | Plus membership buy-in |

### 4.9 Recommended Revenue Model for OpenRide Cooperatives

A blended model is most resilient. Suggested default (each local cooperative can adjust):

| Revenue Stream | Amount | Purpose |
|---|---|---|
| Per-ride flat fee | $0.75/completed ride | Core operating revenue |
| Driver subscription (optional premium tier) | $30-75/month | Priority matching, analytics dashboard, tax tools |
| Rider booking fee | $1.00-1.50/ride | Passed to cooperative for insurance and support |
| Municipal/paratransit contracts | Varies | Guaranteed demand and revenue |
| Foundation platform fee | $500-1,500/month | Paid to OpenRide Foundation for hosting/updates |

At 50,000 rides/month (a mid-size city cooperative):
- Per-ride fees: $37,500/month
- Rider booking fees: $50,000-$75,000/month
- Foundation fee: -$1,000/month
- **Net cooperative revenue**: ~$86,500-$111,500/month before insurance and operating costs

This is enough to fund a small operations team (3-5 people), insurance, and support — without taking a percentage of driver earnings.

---

## 5. Legal and Regulatory Considerations

### 5.1 Cooperative Incorporation in the US

Cooperative law in the US is fragmented. There is no federal cooperative incorporation statute for general cooperatives (agricultural co-ops have specific federal provisions under the Capper-Volstead Act of 1922).

**States with specific cooperative corporation statutes**:
- **New York**: Cooperative Corporations Law — used by The Drivers Cooperative. Relatively well-developed.
- **California**: Cooperative Corporation statute (Cal. Corp. Code §§ 12200-12656). Strong protections.
- **Minnesota**: Chapter 308A and 308B — Minnesota has among the most developed cooperative law in the US. Both traditional and worker cooperative statutes exist.
- **Wisconsin**: Chapter 185 — strong cooperative tradition (home of many agricultural and utility co-ops).
- **Colorado**: Cooperative statute exists. Green Taxi Cooperative incorporated under Colorado law.
- **Massachusetts**: Worker Cooperative Corporation act (2019) — relatively new, specifically designed for worker cooperatives.
- **Oregon**: Oregon Cooperative Corporation Act — updated in 2019 to explicitly support worker cooperatives.

**States with weak or no specific cooperative statutes**: Some states (particularly in the South) have limited cooperative legislation. In these states, cooperatives typically incorporate as LLCs with cooperative operating agreements, which works but provides less legal clarity.

**Recommended approach**: Incorporate each local cooperative in its own state under the best available cooperative statute. The OpenRide Foundation itself should incorporate as a 501(c)(3) nonprofit in a state with strong nonprofit law (Delaware or New York are common choices).

### 5.2 TNC Licensing Requirements

In the US, rideshare platforms operate as **Transportation Network Companies (TNCs)**, a regulatory category created after 2010 (California was first in 2013).

**Key requirements (vary by state)**:
- **TNC license/permit**: Application, background check on company officers, insurance filings, fee ($1,000-$100,000+ depending on state) [wide range — California's fee is substantial, smaller states may be less]
- **Driver background checks**: Usually required through an approved vendor (e.g., Checkr). Some states require fingerprint-based checks (which Uber/Lyft fought aggressively).
- **Vehicle inspections**: Annual or biannual inspection requirements.
- **Driver licensing**: Some states require specific endorsements or commercial license elements.
- **Data reporting**: Many states require trip data reporting (anonymized) for congestion and equity analysis.
- **Accessibility requirements**: Some jurisdictions require wheelchair-accessible vehicle (WAV) availability.

**Who holds the TNC license**: The cooperative or the Foundation could hold the TNC license, depending on the structure. If each local cooperative holds its own TNC license, they have full operational autonomy but bear the regulatory burden individually. If the Foundation holds a multi-state TNC license [where possible — not all states allow this], it reduces duplication but creates dependency.

**Recommendation**: Each local cooperative holds its own TNC license. The Foundation provides templates, legal guidance, and connects cooperatives with TNC-experienced attorneys. This keeps regulatory risk local.

### 5.3 Insurance Requirements

This is covered in detail in [research-report.md](research-report.md) Section 3.2. Key points for cooperative context:

- **Period 1/2/3 coverage** is required in most TNC-regulated states
- Commercial TNC insurance policies are expensive — typically $3,000-$8,000 per driver per year [approximate, varies wildly by market and claims history]
- **Group purchasing power**: A cooperative with 500+ drivers can negotiate better insurance rates than individual drivers. This is one of the strongest practical benefits of the cooperative model.
- **Insurance pooling**: The OpenRide Foundation could coordinate group insurance procurement across multiple cooperatives, creating even more buying power.
- **Self-insurance**: Larger cooperatives (500+ drivers) may eventually be able to self-insure for Period 1 coverage, reducing costs further. This requires significant reserves and actuarial analysis.

**Companies that insure TNCs**: James River Insurance Group has been a major TNC insurer (they were Uber's primary insurer for years). Progressive, State Farm's commercial division, and several specialty insurers also operate in this space. Cooperatives should approach insurance brokers who specialize in commercial transportation.

### 5.4 Worker Classification

This is the thorniest legal question for a rideshare cooperative.

**The options**:

1. **Independent contractors**: Drivers are self-employed, use the cooperative's platform as a tool. This is the Uber/Lyft model and the simplest legally. Co-op members who are independent contractors maintain flexibility (set own hours, use multiple platforms) but lack benefits.

2. **Employees**: Drivers are W-2 employees of the cooperative. This provides benefits (health insurance, workers' comp, unemployment insurance) but dramatically increases costs and reduces driver flexibility. California's AB5 (2019) and similar laws in other states push toward employee classification for gig workers — but cooperatives may have a stronger argument that drivers are genuinely independent because they OWN the platform.

3. **Owner-operators**: This is the cooperative-specific answer. Co-op member-drivers are neither employees nor independent contractors — they are **owner-operators** of their own cooperative business. This is analogous to a partner in a law firm or a member of a farming cooperative. The legal viability of this classification varies by state and hasn't been fully tested for rideshare cooperatives specifically.

**The cooperative advantage**: The core argument against Uber's "independent contractor" classification is that Uber controls the work (sets prices, controls matching, can deactivate). In a cooperative, the drivers collectively control the work — they vote on prices, they govern matching rules, they can't be unilaterally deactivated. This genuinely different power dynamic may support an owner-operator classification that would not hold up for Uber.

**Recommendation**: Default to owner-operator/independent contractor hybrid until case law clarifies. Each cooperative should get legal counsel on this in their specific jurisdiction. This is an area where platform cooperatives have a genuine legal advantage over extractive platforms, but it hasn't been fully litigated yet.

### 5.5 Beckn Protocol

**What it is**: An open, decentralized protocol for commerce and mobility, developed in India. It's the underlying protocol for India's ONDC (Open Network for Digital Commerce) and is the protocol layer under Namma Yatri.

**How it works**: Instead of a single monolithic platform (Uber) controlling both supply and demand, Beckn defines a protocol where:
- **BPPs** (Beckn Provider Platforms) represent supply (drivers)
- **BAPs** (Beckn Application Platforms) represent demand (rider apps)
- A **gateway/registry** connects them

Any BAP can discover any BPP through the protocol. Multiple rider apps can access the same pool of drivers. Multiple driver apps can receive ride requests from any rider app. It's like HTTP for mobility — a shared protocol layer that prevents lock-in.

**Relevance to OpenRide**: High, in theory. If OpenRide implemented Beckn-compatible APIs, any local cooperative could plug into a shared driver/rider network. A driver registered with the Denver co-op could theoretically be discoverable by a rider using the Austin co-op's app (if they were in the same city). This solves the network effects problem: instead of each cooperative building its own network, they share one.

**Practical reality**: Beckn is currently India-specific. There is no Western Beckn registry, no Western regulatory framework for Beckn-style interoperability, and no Western adoption. Implementing Beckn support in OpenRide would be forward-looking but not immediately useful.

**Recommendation**: Design OpenRide's API layer to be Beckn-compatible in structure (separate discovery, matching, and fulfillment layers) even if full Beckn implementation is deferred. If a Western open mobility network emerges, OpenRide should be ready to plug in.

---

## 6. Challenges and Failure Modes

### 6.1 Capital Raising

**The problem**: Cooperatives cannot sell equity. A VC fund can't buy 20% of a cooperative — there's no equity to buy. This eliminates the primary funding mechanism that Uber ($25B+ raised pre-IPO) and Lyft ($5B+) used to subsidize growth.

**What cooperatives can do**:
- **Member shares**: Each member buys in. At $500/member and 1,000 members, that's $500,000. Meaningful but modest.
- **Cooperative loans**: The National Cooperative Bank, Shared Capital Cooperative, and some CDFIs (Community Development Financial Institutions) lend specifically to cooperatives.
- **Community investment**: Some states allow cooperatives to sell "investment shares" or "preferred shares" to non-members. These provide a return but no voting rights. New York's Cooperative Corporations Law allows this. [Verify specific provisions before relying on this]
- **Grants**: See Section 4.6.
- **Revenue**: The old-fashioned way — generate more money than you spend. This requires a viable revenue model from day one.

**What cooperatives cannot do**:
- Sell equity to investors
- Promise exponential returns
- Use stock options to recruit engineers
- Run at a massive loss for years while building network effects

**Implication for OpenRide**: The software must be free or very cheap. Cooperatives cannot afford $500K in custom software development. OpenRide's open source model directly solves this — the technology cost drops from "build from scratch" to "deploy and configure."

### 6.2 Driver Recruitment Without Marketing Budget

**The problem**: Uber spent billions on driver recruitment (sign-up bonuses, guaranteed earnings, referral bonuses). A cooperative has none of that.

**What works instead**:
- **Economics**: "Keep 100% of your fares" (or "pay 8% instead of 30%") is a compelling pitch that doesn't require a marketing budget. Drivers talk to each other. Word of mouth is powerful when the deal is genuinely better.
- **Community organizing**: The Drivers Cooperative recruited 8,000 members primarily through community organizing — driver meetups, WhatsApp groups, word of mouth, partnerships with driver advocacy organizations. This is labor-intensive but free.
- **Existing organizations**: Partner with taxi driver unions, immigrant driver associations, and driver advocacy groups (e.g., New York Taxi Workers Alliance, which has 28,000 members). These organizations have existing trust and communication channels.
- **Regulatory moments**: When cities pass new regulations that hurt drivers on traditional platforms (e.g., Minneapolis minimum wage law in 2024, NYC TLC driver pay rules), cooperatives get free media attention and a receptive audience.

### 6.3 Rider Acquisition (Chicken-and-Egg)

**The problem**: Riders care about one thing: can I get a ride within 5 minutes? If the answer is no, they open Uber. You can't have fast pickup times without driver density. You can't have driver density without rider demand.

**Strategies that have worked**:
- **Namma Yatri**: Offered zero-commission to drivers in a market where drivers hated commissions. Drivers flooded in. The driver density naturally attracted riders. The key was that the driver value proposition was SO much better that supply came first.
- **The Drivers Cooperative**: Pivoted to paratransit/NEMT where demand is guaranteed (government contracts). You don't need rider acquisition if the government is paying for rides.
- **Geographic focus**: Don't try to cover a whole city. Start with one neighborhood, one corridor, or one use case (airport rides, hospital trips, university campus). Dense coverage in a small area is better than sparse coverage everywhere.
- **Events and partnerships**: Partner with venues, employers, and organizations for guaranteed ride volume. "This concert venue uses [local co-op] for all ride-home services" creates a starting base.

### 6.4 Technology Costs

**Building the app from scratch**: $500K-$2M for a basic but functional rider + driver app + backend, if built by contractors or a small team. The Drivers Cooperative reportedly spent significant sums on technology that still doesn't work reliably.

**OpenRide's value proposition**: The software is free. Deploy it, configure it, run it. This turns a $500K-$2M cost into a $5,000-$20,000 setup cost (server infrastructure, configuration, app store deployment). This is the single most impactful thing OpenRide can do for the cooperative movement.

**Ongoing costs** (for a small cooperative, 100-500 drivers):
- Cloud hosting (backend, database, Redis): $200-$500/month
- OSRM/routing server: $50-$100/month
- SMS/push notifications: $50-$200/month
- App store fees (Apple + Google): $125/year
- Domain, SSL, misc: $50/month
- **Total**: ~$400-$900/month, or $5,000-$11,000/year

This is sustainable even for a small cooperative.

### 6.5 Scaling Across Jurisdictions

**The problem**: Every city and state has different TNC regulations, insurance requirements, background check rules, and vehicle standards. Uber employs hundreds of lawyers and lobbyists to manage this. A cooperative has none of that.

**OpenRide's answer**: Don't scale one cooperative across jurisdictions. Scale the software across multiple independent cooperatives. Each cooperative handles its own local regulatory compliance. The Foundation provides templates and connects cooperatives with legal resources, but each cooperative is an independent legal entity in its own jurisdiction.

This is fundamentally different from the Uber model. Uber is one company operating everywhere. OpenRide enables many cooperatives, each operating locally but sharing technology.

### 6.6 Democratic Governance at Scale

**The problem**: Democratic governance works well with 20 members around a table. It works badly with 8,000 members, most of whom are driving right now and don't have time for governance.

**Real challenges**:
- **Voter participation**: The Drivers Cooperative's annual meetings likely have very low attendance as a percentage of membership [unverified, but this is consistent with large cooperative governance generally]
- **Information asymmetry**: Board members and staff understand the business; most driver-members do not. This creates a knowledge gap that can lead to rubber-stamp governance.
- **Factionalism**: In a diverse membership (different languages, different driving patterns, different neighborhoods), coalitions form and conflict.
- **Speed**: Democratic process is slow. When a competitor drops prices or a regulatory deadline hits, the cooperative can't wait for a vote.

**Mitigations**:
- **Delegate model**: Instead of direct democracy on everything, elect regional representatives. Drivers in each zone elect a delegate; delegates form a council that votes on operational matters. The full membership votes only on major decisions (pricing changes, bylaw amendments, board elections).
- **Digital governance tools**: Use the platform itself for voting. Push notifications for votes. Transparent dashboards showing cooperative finances.
- **Clear decision rights**: Document what the board can decide, what staff can decide, and what requires member vote. Don't put everything to a vote — that's not effective democracy, it's governance paralysis.
- **Term limits**: Prevent entrenchment on the board.
- **Paid governance time**: Some cooperatives compensate members for attending governance meetings (e.g., an hourly rate for attending the annual meeting). This increases participation.

---

## 7. Recommendations for OpenRide

### 7.1 Suggested Default Ownership Structure

**Recommended: Hybrid model (Section 3.5)**

The OpenRide project should consist of two types of entities:

**A. OpenRide Foundation** (501(c)(3) nonprofit)
- Owns and maintains the open source codebase
- Provides shared services to cooperatives (hosting, insurance pooling, legal templates, onboarding)
- Governed by a board that includes representatives from affiliated cooperatives, technology contributors, and independent directors
- Funded by platform fees from cooperatives, grants, and donations
- Does NOT operate rideshare services directly

**B. Local cooperatives** (independent, locally incorporated)
- Deploy OpenRide in their city/region
- Choose their own governance model (worker-owned, multi-stakeholder, etc.)
- Handle local regulatory compliance, insurance, and driver/rider relationships
- Pay a platform fee to the Foundation for hosting and shared services
- Are independent legal entities — the Foundation doesn't control them

This is similar to how WordPress Foundation relates to individual WordPress sites, or how the Linux Foundation relates to companies using Linux.

### 7.2 Suggested Revenue Model

For local cooperatives (default configuration — each co-op can adjust):

| Stream | Rate | Notes |
|---|---|---|
| Rider booking fee | $1.25/ride | Covers insurance, support, platform fee |
| Driver subscription (optional) | $0/month (basic), $50/month (premium) | Premium tier: analytics, tax tools, priority |
| Per-ride fee (alternative to booking fee) | $0.75/ride from driver side | Some co-ops may prefer this to rider-side fee |
| Municipal contracts | Varies | Paratransit, NEMT, transit-first/last-mile |

For the OpenRide Foundation:

| Stream | Rate | Notes |
|---|---|---|
| Managed hosting | $500-$1,500/month per cooperative | Scales with ride volume |
| Onboarding/setup | $5,000-$15,000 one-time | Deployment, configuration, training |
| Support contracts | $200-$500/month | Guaranteed response times |
| Grants | Varies | Startup funding, not long-term reliance |
| Custom development | Hourly/project | Cooperative-specific features |

### 7.3 How the Open Source Platform Serves Multiple Co-ops

OpenRide should follow a **"WordPress for rideshare"** model:

**What OpenRide provides (the software)**:
- Rider mobile app (Flutter, white-label ready)
- Driver mobile app (Flutter, white-label ready)
- Backend (FastAPI, fully deployable)
- Admin dashboard (React, cooperative management tools)
- Matching engine (PostGIS + Redis)
- Routing (OSRM integration)
- Payment processing (Stripe Connect integration)
- Real-time communication (WebSocket)
- Docker Compose deployment
- Comprehensive documentation for deployment and operations

**What OpenRide provides (shared services via Foundation)**:
- Managed hosting option (for co-ops that don't want to run servers)
- Legal templates (cooperative bylaws, membership agreements, TNC application guides)
- Insurance broker relationships (group purchasing power)
- Onboarding support (help a new co-op go from zero to operational)
- Software updates and security patches
- Community forum / knowledge sharing between cooperatives

**What each local cooperative handles**:
- Driver recruitment and onboarding
- Rider acquisition and marketing
- TNC licensing in their jurisdiction
- Insurance procurement (with Foundation's help)
- Local pricing decisions (fares, fees, subscription rates)
- Customer support (with shared tooling from Foundation)
- Governance (board, elections, meetings)
- Community relationships (city government, transit agencies, advocacy groups)
- Branding (each co-op can brand the app for their market — "Denver Ride Co-op," "Austin Community Rides," etc.)

### 7.4 Configuration, Not Forking

OpenRide should be designed so that local cooperatives configure it, not fork it. Key configuration points:

- **Branding**: App name, colors, logo — environment variables or admin dashboard settings
- **Pricing**: Fare calculation formula, booking fees, surge rules (or no surge) — admin dashboard
- **Commission/fees**: What the co-op charges drivers/riders — admin dashboard
- **Service area**: Geographic boundaries — admin dashboard with map interface
- **Payment**: Stripe Connect credentials — environment config
- **Regulatory**: Background check provider, vehicle requirements — admin config
- **Governance tools**: Voting, member communication — built into admin dashboard

This means a new cooperative can launch OpenRide in a new city by:
1. Creating a cooperative entity (legal)
2. Obtaining TNC license (regulatory)
3. Securing insurance (insurance broker)
4. Deploying OpenRide (Docker Compose or managed hosting)
5. Configuring branding, pricing, and service area (admin dashboard)
6. Publishing to app stores (with co-op's branding)
7. Recruiting drivers and riders (community organizing)

Steps 4-6 can happen in a weekend if the legal/regulatory/insurance pieces are in place.

### 7.5 Immediate Next Steps

1. **Add cooperative governance tools to the admin dashboard spec** — member registration, voting, financial transparency dashboard, patronage dividend calculation
2. **Design the white-label system** — configuration-driven branding, not code forks
3. **Write the "Start a Rideshare Cooperative" guide** — legal, regulatory, insurance, and operational playbook for someone who wants to launch in their city
4. **Contact The Drivers Cooperative** — they need better tech, OpenRide needs a pilot partner. This is the most obvious partnership in the space.
5. **Research NEMT/paratransit contracts** — this is the most viable first market for cooperatives (guaranteed demand, government funding)
6. **Model the economics** — build a spreadsheet that a potential cooperative can fill in with their city's numbers (driver count, ride volume, insurance costs, hosting costs) and see if it pencils out

---

## 8. Key Takeaways

1. **Platform cooperativism is proven in rideshare.** The Drivers Cooperative, Eva, Green Taxi Cooperative, and Namma Yatri collectively demonstrate that drivers will join cooperatives, riders will use them, and the economics work — IF the technology works.

2. **Technology is the bottleneck.** Every rideshare cooperative either built fragile custom tech or operates without adequate technology. OpenRide solves this directly.

3. **The hybrid model (Foundation + local co-ops) is the right structure.** Separating technology (shared) from operations (local) lets OpenRide scale without a single cooperative needing to be enormous.

4. **Per-ride flat fees + rider booking fees are the most practical revenue model.** They're simple, predictable, and scale with usage. Avoid percentage commissions — the "keep 100% of your fares" message is too powerful to give up.

5. **Paratransit/NEMT is the best first market.** Guaranteed government demand solves the chicken-and-egg problem. Multiple cooperatives (including The Drivers Cooperative) have already pivoted here.

6. **Governance at scale is a real challenge.** OpenRide should build governance tools into the admin dashboard — voting, transparency, member communication — to make democratic ownership practical, not just theoretical.

7. **Regulatory complexity is local.** Don't try to solve it centrally. Provide templates and guidance; let each cooperative handle its own jurisdiction.

8. **The Drivers Cooperative in NYC is the most obvious pilot partner.** They have 8,000+ drivers, a cooperative structure, and chronically broken technology. If OpenRide can replace their tech stack, that's the proof point the entire cooperative rideshare movement needs.

---

## Sources and Further Reading

- Scholz, Trebor. *Platform Cooperativism: Challenging the Corporate Sharing Economy* (Rosa Luxemburg Foundation, 2016)
- Schneider, Nathan. *Everything for Everyone: The Radical Tradition That Is Shaping the Next Economy* (Nation Books, 2018)
- Platform Cooperativism Consortium (The New School): https://platform.coop/
- The Drivers Cooperative: https://drivers.coop/
- Eva Coop: https://eva.coop/ [verify current URL]
- Green Taxi Cooperative: https://greentaxicooperative.com/ [verify current URL]
- Namma Yatri: https://nammayatri.in/
- Beckn Protocol: https://becknprotocol.io/
- International Cooperative Alliance (Rochdale Principles): https://www.ica.coop/
- USDA Rural Cooperative Development Grants: https://www.rd.usda.gov/
- National Cooperative Bank: https://www.ncb.coop/
- Internet of Ownership (directory of platform co-ops): https://ioo.coop/ [verify current status]

---

*This document should be updated as OpenRide's ownership structure decisions are made and as new cooperative rideshare data becomes available. Mark any updates with dates.*
