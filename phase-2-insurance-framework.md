---
title: Phase 2 Insurance & Risk Management Framework
project: open-source-rideshare (OpenRide)
date: 2026-05-05
status: research complete — actionable for Phase 2 planning
author: research agent
related_files:
  - cooperative-models-research.md
  - regulatory-compliance-research.md
  - regulatory-comparison-by-city.csv
---

# Phase 2 Insurance & Risk Management Framework

## Most Important Finding

The cooperative rideshare model is financially viable from an insurance standpoint, but the path to viability is narrow and city-dependent. Two live US cooperatives — Fare Co-op and Drivers Cooperative Colorado — have solved the insurance problem. Fare Co-op secured a $1,000,000 commercial auto liability policy through specialty insurer Y-Risk covering 49 states. Drivers Cooperative Colorado waited five months to secure coverage and required $500,000 in seed capital before any insurer would write the policy. NYC is the worst launch city: insurance premiums are rising 25% over three years due to the 2025 American Transit Insurance Co. insolvency, with TLC coverage already at $3,000–$10,000+ per vehicle annually and climbing. Portland (Oregon), Georgia (Atlanta metro), and California (mid-sized cities, not SF) are the lowest-friction markets for Phase 2.

---

## 1. Insurance Products for Platform Cooperatives

### 1.1 The Three-Period Framework (Universal US Baseline)

All US TNC insurance operates on the NAIC Model Bill three-period structure, enacted across all 50 states between 2014 and 2019:

| Period | Driver State | Required Coverage (Federal Minimum) |
|---|---|---|
| Period 1 | App on, no match | $50K/person, $100K/incident, $25K property |
| Period 2 | Match accepted, no passenger | $1M combined single limit |
| Period 3 | Passenger in vehicle | $1M combined single limit |

The model bill allows flexibility: "Coverage may be maintained by the TNC, the TNC driver, or a combination of the two." In practice, Uber and Lyft carry Period 2/3 coverage at the platform level — the cooperative model must do the same. Period 1 coverage is the persistent regulatory gray zone where cooperatives differ from traditional platforms.

### 1.2 Commercial Auto Insurance

**What it covers**: Third-party bodily injury and property damage while a driver is operating in app mode. This is the non-negotiable foundational product.

**Platform-level vs. driver-level**: For cooperatives, platform-level commercial auto (carried by the cooperative entity itself) is far superior to driver-level individual policies for several reasons:
- Consistent coverage eliminates gaps when a driver's personal policy lapses
- Pooled risk lowers per-driver premium as fleet grows
- Provides single claims contact for passengers and third parties
- Satisfies TNC licensing requirements more cleanly

**Cost benchmarks**:
- Individual commercial auto policy (full-time driver): $180–$320/month ($2,160–$3,840/year)
- NYC TLC commercial policy (per vehicle): $3,000–$7,000/year in 2025, rising to $4,000–$10,000+ by 2028 per DFS projections
- California TNC driver full coverage (individual): $113–$281/month ($1,356–$3,372/year)
- Non-NYC markets baseline: $2,000–$4,500/year per vehicle

**Key provider options for cooperatives**:
- Y-Risk: Specialty MGA that has already written a policy for Fare Co-op covering 49 states. This is the most important finding for OpenRide — a live precedent with a named carrier.
- Progressive Commercial: Offers commercial auto for TNCs; has worked with smaller platforms
- National General (Allstate): Commercial auto for transportation companies
- State Auto: Regional carrier with TNC commercial products in Southeast
- Note: Mainstream carriers (Travelers, Hartford) generally require 3+ years of loss history before writing a new TNC — this is a Phase 2 blocker that Fare Co-op solved by going through a specialty MGA (Y-Risk) rather than direct

### 1.3 General Liability (Platform Operator Liability)

**What it covers**: Non-auto claims arising from the platform's operations — passenger injury not related to vehicle accident, discrimination claims, premises liability if the cooperative maintains physical offices, product liability for app design defects.

**Cost**: $30–$70/month ($363–$840/year) for a startup technology platform at $1M/$2M limits. This is relatively inexpensive and should be carried from day one.

**Cooperative-specific exposure**: A platform cooperative faces the same general liability exposure as any TNC, plus member governance claims (disputes about democratic processes, member expulsion, voting irregularities). General liability does not cover these — D&O does.

### 1.4 Workers' Compensation Equivalents: The Classification Problem

This is the most legally contested area in cooperative rideshare insurance.

**Current US legal landscape (2025)**:
- **Federal**: DOL final rule effective March 2025 tightens the six-factor test for independent contractor vs. employee classification, but the Trump administration is proposing to roll back to a more employer-friendly standard. Status as of May 2026 is uncertain; the Biden rule may be partially in effect.
- **California**: Proposition 22 (upheld by CA Supreme Court, July 2024) classifies app-based drivers as independent contractors but requires TNC platforms to provide occupational accident insurance covering: $1M in medical expenses; earnings replacement at 66% of average weekly earnings for disability; survivor benefits.
- **Washington State**: Keeps drivers as independent contractors but mandates rideshare companies provide workers' compensation coverage and paid sick leave. This is the most worker-protective non-employee model in the US.
- **All other states**: Traditional workers' comp does not apply to independent contractors. Drivers bear own injury risk unless the platform provides voluntary occupational accident coverage.

**For a cooperative**: The member-owner structure creates a potential reclassification argument. If the cooperative classifies member-drivers as worker-owners (not independent contractors), they may trigger workers' comp obligations in states that extend workers' comp to working owners of cooperatives. New York cooperative law specifically addresses this — worker-owners of cooperative corporations are generally treated as employees for workers' comp purposes. This is a significant cost exposure that must be priced into the model.

**Practical paths**:
1. Independent contractor model with voluntary occupational accident insurance (California Prop 22 approach): ~$0.10–$0.25/mile or roughly $500–$1,500/driver/year depending on coverage level
2. Employee-owner model with workers' comp: Workers' comp rates for transportation workers range 5–12% of payroll — at $25,000/year driver income this is $1,250–$3,000/year
3. Washington model (contractor + mandatory workers' comp): Cooperative may adopt this voluntarily as best practice even outside WA

**Recommendation for OpenRide**: Implement California/Washington-style occupational accident insurance at launch as a platform-level benefit. This is affordable ($500–$1,500/year per driver), builds member loyalty, and positions the cooperative ahead of likely federal reclassification.

### 1.5 Cargo/Goods Liability

Relevant if OpenRide expands to include delivery (analogous to FareEats, CoopCycle's model). Not needed for pure rideshare.

If delivery is included:
- Cargo liability: $10,000–$50,000/load limit, $1,500–$3,000/year for small fleet
- MAIF's CoopCycle partnership model (France) covered professional civil liability, employee/manager coverage, and transported goods — all three in a single tailored product. This three-layer structure is the template for any delivery cooperative.

### 1.6 Cyber Liability

**Why it matters**: A rideshare platform holds driver PII (SSN, address, financial account), rider payment cards, trip location history, and background check results. A data breach triggers federal and state notification obligations, potential FTC enforcement, and class action exposure.

**Average cost**: $1,200–$7,000/year for small technology businesses at $1M coverage. Median is approximately $2,000/year.

**TNC-specific exposure**: The 2016 Uber breach (57M records) settled for $148M with state attorneys general. The FTC 2017–2018 consent decree required Uber to implement a 20-year privacy program. For a cooperative, a breach involving driver SSNs or immigration status (common among immigrant driver populations) would be reputationally and legally severe.

**Recommendation**: Carry $1M cyber liability from first driver onboarded. Budget $3,000–$5,000/year at launch scale; this can be packaged with general liability for a discount.

### 1.7 Directors & Officers (D&O) Insurance

**What it covers**: Claims against elected board members and cooperative officers arising from governance decisions — member disputes over dividends, board election challenges, wrongful expulsion, alleged breach of fiduciary duty.

**Cost for small cooperative**: $600–$1,700/year for $1M coverage. At the low end for a young cooperative with fewer than 50 employees.

**Critical point for OpenRide**: Because the cooperative's governance is its differentiator, member disputes are more likely than at a traditional corporation. An angry driver who was deactivated can sue the board; a member faction challenging a fare increase can sue the directors. D&O is cheap insurance against the cooperative's own democracy.

---

## 2. Existing Platform Cooperative Insurance Models

### 2.1 Fare Co-op (US, active 2024–present) — Most Directly Relevant

Fare Co-op is a federated, multi-stakeholder rideshare cooperative operating in California, Georgia, Florida, and Oregon as of late 2025. It is America's third-largest fully licensed rideshare.

**Insurance structure**: Single $1,000,000 commercial auto liability policy through Y-Risk (a specialty MGA). Coverage is platform-level, in effect in 49 states (New York excluded). This is the clearest direct precedent for OpenRide.

**Driver economics**: Drivers retain 90% of fares (85% after Stripe payment processing fee on instant payouts). This compares favorably to Uber's 60–70% driver share.

**Governance**: Federated structure with local chapters. Locals can set their own pricing within the platform. Drivers hold 50% of cooperative ownership.

**Key lesson**: Y-Risk is the insurer of record for at least one live US cooperative rideshare. The 49-state exclusion of New York reflects New York's hostile insurance market, not a limitation of the cooperative model itself.

### 2.2 Drivers Cooperative Colorado (Denver, active fall 2024)

**Structure**: Multistakeholder limited cooperative association (LCA) with both worker-members and nonprofit (RMEOC) as member classes. RMEOC holds a social mission seat.

**Insurance**: Platform-level coverage secured after a five-month search. No carrier is publicly named. The cooperative requires $500,000 minimum capitalization before any insurer would write the policy — this is a documented Phase 2 blocker. If drivers have an accident during a trip, they are covered by the cooperative's insurance.

**Driver economics**: Drivers retain 80% of fares.

**Scale**: Over 4,600 drivers and 15,600 riders within months of launch, across Denver, Colorado Springs, Fort Collins, and Vail.

**Key lesson**: Securing insurance for a cooperative rideshare requires significant startup capital as collateral. Budget at minimum $500,000 for the cooperative entity before expecting an insurer to write coverage. The five-month search time is also significant — factor this into launch planning.

### 2.3 The Drivers Cooperative (NYC, active 2021)

**Insurance**: NYC-specific TLC insurance, required individually per vehicle. No platform-level pooling confirmed in public records. The cooperative has discussed leveraging member purchasing power to negotiate group insurance rates, but the TLC's per-vehicle requirement makes true platform-level pooling difficult.

**Key complication**: TLC insurance must be individually filed per vehicle with the TLC. This prevents the cooperative from holding a single blanket policy the way Fare Co-op does in other states. This is unique to NYC.

**Key lesson**: NYC's per-vehicle TLC structure is a specific obstacle to cooperative insurance pooling. Every other US market should be easier.

### 2.4 Modo Car-Sharing (Vancouver, Canada) — Fleet Cooperative Insurance

**Structure**: Canada's first car-sharing cooperative. Not rideshare, but the fleet insurance model is instructive.

**Insurance**: Platform carries ICBC (provincial insurer) third-party liability for the entire fleet. All-inclusive in membership — members are covered by the cooperative's policy during use. Offers a $50/year damage pool buy-in to reduce member deductible to $0.

**Key lesson**: The damage pool (risk pool) model works at cooperative scale. Members self-fund a supplementary layer on top of commercial insurance. At $50/member/year with 10,000 members, this generates $500,000 in damage pool capital annually — a meaningful cushion.

### 2.5 CoopCycle / MAIF (France, active 2022)

**Structure**: Federation of ~50 bike delivery cooperatives across France, federated through CoopCycle.

**Insurance**: Negotiated a federation-wide tailored insurance product with MAIF (a French mutual insurer). Coverage includes three layers: professional civil liability and legal protection; coverage of employees and managers; coverage of assets including bicycles and transported goods.

**How it was built**: MAIF co-constructed the product with CoopCycle over 18 months after working with "Les Coursiers Niortais," a small delivery cooperative, as a test case. The cooperative federation gave MAIF a large enough risk pool to create an actuarially viable product.

**Key lesson**: The federation/consortium model is the path to custom insurance products. A single cooperative cannot compel an insurer to create new products; a federation with 50+ members can. OpenRide, as open-source infrastructure deployed by multiple cooperatives, is structurally positioned to replicate this. The platform can broker a federation-wide insurance arrangement once 5–10 cooperatives are operational.

---

## 3. Risk Pooling and Mutual Insurance

### 3.1 Mutual Insurance Companies: Basics and Barriers

A mutual insurance company is owned by its policyholders rather than outside shareholders. Major US mutual insurers (State Farm, USAA, Erie, COUNTRY Financial) are mature and large. Forming a new mutual insurer specifically for cooperative rideshare is theoretically possible but practically prohibitive for Phase 2:

- **Minimum capital**: Most states require initial capital of $250,000–$1,000,000+ to form a mutual insurer, plus actuarial opinions, regulatory filings, and a board of directors
- **Premium threshold**: New mutual insurers need annual premium volume of at least $3,000,000 to be actuarially stable — this requires roughly 600–1,500 active drivers paying full platform-level commercial premiums
- **Formation time**: 2–5 years from inception to licensed operation
- **State regulatory approval**: Each state requires separate approval

**Verdict**: Forming a dedicated mutual insurer is a Phase 4 or Phase 5 aspiration. It is not viable as a Phase 2 solution.

### 3.2 Group Captive Insurance

A group captive is an insurance company owned by a group of similar businesses (or cooperative members) that insures only its own members' risks. Members capitalize the captive with collateral and share in underwriting profits.

**How it works**:
- Members contribute premiums into the captive
- The captive pays claims up to a per-occurrence retention limit
- Reinsurance covers catastrophic losses above the retention
- Unused loss funds are returned to members as dividends after 3–4 years
- Administrative costs consume roughly 35% of premium; 65% goes to a loss fund

**Formation requirements**:
- Feasibility study: $15,000–$60,000 (one-time)
- Initial capitalization: $250,000–$1,000,000+
- Annual administration: $75,000–$300,000
- Premium threshold for viability: $200,000–$500,000/year combined P&C premiums, or roughly 50–150 drivers contributing platform-level commercial auto premiums

**Regulatory home**: Vermont is the preferred US captive domicile (favorable regulation, reasonable capital requirements). Delaware and Hawaii are also used.

**Break-even calculation**:
- At $2,500/driver/year average insurance cost (non-NYC market):
- 100 drivers = $250,000/year premium → at the low end of viability
- 200 drivers = $500,000/year premium → clearly viable
- 500 drivers = $1,250,000/year premium → well above the $1M single-parent captive threshold

**Verdict**: A group captive becomes viable at approximately 150–200 drivers in a single cooperative, or when multiple smaller cooperatives aggregate through a federation. This is a Phase 3 target (12–24 months post-launch). Phase 2 should use commercial insurance with Y-Risk or equivalent, building toward captive formation.

### 3.3 Risk Retention Groups (RRGs)

A Risk Retention Group is a federal charter (Liability Risk Retention Act, 1986) that allows groups with similar liability exposures to form their own insurance company. RRGs can write liability insurance across state lines with a single domicile license (though must notify each state of intent to operate).

**For rideshare cooperatives**:
- Can write commercial auto liability and general liability
- Cannot write workers' comp or property insurance
- Minimum capital varies by domicile: Vermont requires approximately $500,000
- Operating budget: $150,000–$500,000/year for small RRGs

An RRG formed by a federation of rideshare cooperatives could eventually provide the platform-level commercial liability coverage at lower cost than commercial markets. This is analogous to what medical malpractice RRGs did for physician groups in the 1980s.

**Verdict**: An RRG formed by the OpenRide federation is viable at scale (Phase 4, 5+ cooperatives with 500+ total drivers). It requires the federation infrastructure that OpenRide's open-source deployment model is positioned to provide.

### 3.4 Damage Pool / Member Self-Insurance

The Modo model (Canada) is the most immediately replicable. Members contribute to a pooled damage fund that supplements (not replaces) commercial coverage, reducing individual deductibles.

At cooperative scale:
- 100 drivers × $100/year = $10,000 pool (covers small claims, deductibles)
- 100 drivers × $500/year = $50,000 pool (meaningful buffer)

This requires no regulatory approval, no minimum capital, and generates immediate member buy-in through visible cost reduction. It is the easiest risk-pooling mechanism to implement in Phase 2.

---

## 4. Capital and Financial Implications

### 4.1 Per-Driver Insurance Cost Benchmarks by Market

| Market | Commercial Auto (platform-level) | Occupational Accident | Total Est. Annual/Driver |
|---|---|---|---|
| NYC (current, 2025) | $4,000–$7,000 | $500–$1,000 | $4,500–$8,000 |
| NYC (projected 2028, +25%) | $5,000–$10,000 | $500–$1,000 | $5,500–$11,000 |
| San Francisco / CA | $1,500–$3,500 | $500–$1,500 | $2,000–$5,000 |
| Seattle | $2,000–$4,000 | $500–$1,000 | $2,500–$5,000 |
| Portland / Oregon | $1,500–$3,000 | $300–$800 | $1,800–$3,800 |
| Denver / Colorado | $2,000–$3,500 | $300–$800 | $2,300–$4,300 |
| Chicago | $2,000–$4,000 | $300–$800 | $2,300–$4,800 |
| Atlanta / Georgia | $1,500–$2,800 | $300–$800 | $1,800–$3,600 |
| Austin / Texas | $1,200–$2,500 | $300–$800 | $1,500–$3,300 |

*Note: These are platform-level cost allocations per driver. When the platform carries commercial auto collectively, per-driver cost decreases as fleet size grows (pooled risk).* All figures are estimates based on market data and should be verified with a commercial insurance broker.

### 4.2 Cost Scaling (Platform Commercial Policy)

Commercial auto insurance for fleets scales with:
- Number of vehicles and drivers
- Aggregate miles driven
- Claims history (improves over time as the cooperative builds track record)

Rough trajectory for a cooperative deploying a platform-level policy:
- **10 drivers (seed)**: $30,000–$70,000/year total; $3,000–$7,000/driver — highest per-driver cost, near-individual pricing
- **50 drivers**: $100,000–$180,000/year total; $2,000–$3,600/driver — first economies of scale
- **100 drivers**: $175,000–$300,000/year total; $1,750–$3,000/driver — viable range
- **500 drivers**: $600,000–$1,200,000/year total; $1,200–$2,400/driver — significant pooling benefit; group captive viability threshold
- **1,000 drivers**: $900,000–$1,800,000/year total; $900–$1,800/driver — group captive clearly optimal

**The non-linear cost improvement between 10 and 100 drivers is the critical argument for fast member acquisition.** A cooperative at 10 drivers is price-disadvantaged relative to drivers buying individual policies; at 100 drivers the cooperative offers meaningful cost savings.

### 4.3 How Insurance Costs Affect Driver Economics

Using a driver earning $40,000/year gross fare (typical full-time rideshare in a mid-cost market):

| Scenario | Commission | Insurance Cost | Net Driver Earnings |
|---|---|---|---|
| Uber/Lyft | 25–30% ($10K–$12K) | Driver-paid: ~$2,000–$3,500 | $24,500–$28,000 |
| Cooperative (platform pays insurance) | 15% ($6,000) + $2,500 insurance | $0 direct | $31,500 |
| Cooperative (driver pays insurance, 15% commission) | 15% ($6,000) | Driver-paid: ~$1,500 (pooled discount) | $32,500 |

In both cooperative scenarios, the driver nets $31,500–$32,500 vs. $24,500–$28,000 under Uber/Lyft — a 12–28% earnings improvement. The earnings advantage survives even when insurance cost is factored in, which validates the cooperative model financially.

### 4.4 Insurance Cost as Membership Fee Structure

OpenRide should structure insurance as a transparent membership cost rather than a hidden commission:

**Recommended structure**:
- Platform retains 10–12% of fares (covers technology, operations, reserves)
- Insurance cost covered from platform revenue share (not driver deduction)
- Members see: "Your fare is $20. Platform receives $2.00. You receive $18.00. Your insurance is included."

This transparency is a powerful driver recruitment tool and aligns with cooperative values. The actual insurance cost is hidden in the platform's 10–12%, but members can request full financial disclosure.

---

## 5. Risk Allocation and Accountability

### 5.1 Driver Causes Accident (Injury or Property Damage)

**During Period 2/3 (ride accepted or passenger present)**:
- Platform's $1M commercial auto policy is primary
- If damage exceeds $1M (rare but possible — multi-vehicle accidents, catastrophic injury), umbrella/excess liability policy at $5M–$10M should be carried
- Driver's personal auto policy is generally not triggered during platform operations
- Claim process: passenger or third party files against the platform's insurer; insurer investigates; platform may subrogate against driver if negligence is established

**During Period 1 (app on, no match)**:
- State minimum coverage ($50K/$100K) applies
- Driver's personal policy should not exclude TNC activity (requires rideshare endorsement or commercial policy)
- Gray zone: if the driver has only personal insurance without TNC endorsement, coverage may be denied, leaving the driver personally exposed

**For the cooperative specifically**: As the platform entity, the cooperative is likely to be named in any lawsuit as a defendant even if not legally required to be primary payor. Maintain umbrella excess liability ($5M+) from the first day of operations to protect the cooperative entity and its member-owners.

### 5.2 Driver Passes Background Check but Causes Harm

**Negligent entrustment claim**: If the platform approves a driver who later harms a passenger, and the platform's background check process was inadequate, the cooperative faces negligent entrustment liability. Courts have found Uber liable under this theory.

**Mitigation**:
- Use FCRA-compliant consumer reporting agencies with motor vehicle records, criminal background, and sex offender registry checks
- Document the background check process in the cooperative's written policies
- Maintain records for at minimum 7 years
- The cooperative's D&O policy will not cover this claim — it falls under commercial auto or general liability

**Financial exposure**: Negligent entrustment verdicts have ranged from $100K to $25M+. Adequate umbrella coverage ($5M–$10M) is essential.

### 5.3 Data Breach Exposing Driver PII

**Exposure profile**: Rideshare cooperatives often serve immigrant driver populations who may have mixed immigration status. A breach exposing driver names, addresses, or immigration documents is reputationally catastrophic and legally severe beyond the usual PII breach costs.

**Required response obligations**: All 50 states have breach notification laws. Typical requirements: notify affected individuals within 30–90 days; notify state attorney general; provide credit monitoring.

**Financial exposure**: Average US data breach cost is $4.88M (IBM, 2024). For a small cooperative, this is an existential threat.

**Mitigation**:
- Cyber liability at minimum $1M coverage (strongly recommend $2M for any cooperative with 500+ drivers)
- Annual penetration testing
- Driver PII should be stored with minimal retention — no full SSN stored post-background-check; only hash/tokenize what's necessary
- Contractual data processing agreements with all third-party vendors (background check providers, payment processors)

### 5.4 Passenger Injured Due to Platform Design / UX

**Theory of liability**: If a passenger is injured because the app routed a driver through a dangerous area, or the app failed to communicate a safety feature, the cooperative faces product liability. This is a general liability claim.

**Mitigation**: Carry errors & omissions / technology E&O coverage in addition to general liability. For a technology platform, E&O is the product liability equivalent. Cost: $1,500–$5,000/year at $1M coverage.

---

## 6. Platform-Level Insurance Portfolio Recommendation

For OpenRide's first cooperative deployment (50–100 drivers, non-NYC market):

| Coverage Type | Carrier Strategy | Annual Budget | Priority |
|---|---|---|---|
| Commercial Auto (Period 1/2/3) | Platform-level via specialty MGA (Y-Risk or equivalent) | $100,000–$250,000 | Critical |
| Commercial Auto Umbrella/Excess | $5M–$10M excess layer | $15,000–$35,000 | Critical |
| Occupational Accident | Voluntary benefit for driver-members | $25,000–$75,000 | High |
| General Liability ($1M/$2M) | Bundle with BOP | $1,000–$2,000 | High |
| Cyber Liability ($1M) | Stand-alone or bundle | $3,000–$6,000 | High |
| D&O ($1M) | Stand-alone | $1,000–$2,000 | High |
| Errors & Omissions ($1M) | Stand-alone tech E&O | $2,000–$5,000 | Medium |
| Cargo/Goods (if delivery) | Add-on to commercial auto | $2,000–$5,000 | Medium (if applicable) |

**Total annual insurance budget (50–100 drivers, non-NYC)**: $147,000–$375,000

**Per-driver equivalent (100 drivers)**: $1,470–$3,750/year

---

## 7. City-by-City Strategic Assessment

### Best Launch Cities (Low Insurance Burden, Regulatory Clarity)

**1. Atlanta / Georgia** — Recommended first launch
- Georgia has state authority letter precedent (Fare Co-op operates here)
- Statewide preemption means city-by-city compliance is not needed
- Insurance costs among the lowest in the US ($1,800–$3,600/driver/year estimate)
- No fingerprint requirement at state level
- $75,000 state annual fee (VERIFY — may differ for small cooperatives)
- No cooperative-specific gray zone: Georgia TNC law does not distinguish cooperative from corporate platform

**2. Portland / Oregon** — Recommended early launch
- Portland Bureau of Transportation has approved Fare Co-op
- City-level regulatory clarity already achieved by a cooperative
- Oregon requires UM/UIM coverage ($1M) during trip — slightly higher than some states but manageable
- Cooperative-progressive political environment; driver and rider receptiveness high
- Insurance market less stressed than CA or NY

**3. Austin / Texas** — Strong candidate
- Texas statewide preemption removes city-level fragmentation
- HB 100 (2017) created clean statewide TNC framework
- Insurance minimums are among the most affordable
- $5,000 state annual fee (one of the lowest)
- No fingerprint requirement
- No prior cooperative precedent to overcome; Texas TNC law is carrier-neutral

**4. Denver / Colorado** — Good candidate, some complexity
- Drivers Cooperative Colorado is live proof-of-concept
- Colorado PUC has regulatory framework
- Colorado requires $200,000/$400,000 UM/UIM — higher than basic states
- $111,250 state annual fee for large TNCs (may have lower tier for small cooperatives — VERIFY)
- Known 5-month insurance search time documented by DC Colorado

### Caution Cities (Higher Insurance Burden or Regulatory Friction)

**5. Chicago / Illinois** — Medium complexity
- Statewide framework with Chicago additional requirements
- City chauffeur's license requirement for drivers adds onboarding cost
- Per-trip fees ($3/ride) reduce driver economics
- Insurance market manageable but more expensive than South/Southwest

**6. San Francisco / California** — Viable but expensive
- CPUC TNC permit required; comprehensive reporting obligations
- Insurance cost: $1,500–$3,500/driver/year
- Proposition 22 occupational accident insurance required ($1M medical + 66% disability)
- Statewide annual fee and 0.33% revenue assessment
- Progressive cooperative market, strong labor organizing culture
- Not recommended as first launch but viable in Phase 3

**7. Seattle / Washington** — Highest labor standards, viable for a cooperative
- Washington State requires workers' compensation coverage for TNC drivers (unusual — most states do not)
- Paid sick leave accrual required
- Minimum per-mile and per-minute pay rates, adjusted annually for inflation
- These labor standards are aligned with cooperative values but increase operating costs
- Seattle has significant TNC driver organizing history — likely receptive to cooperative model

### Avoid for Phase 2

**8. New York City** — Not recommended until Phase 4+
- TLC per-vehicle insurance cannot be pooled at platform level
- Insurance costs rising 25% through 2028 ($5,000–$11,000+/driver/year projected)
- FHV cap limits new vehicle licenses
- Driver education course, fingerprint background checks, TLC vehicle inspection
- Medallion regulatory structure was built for incumbents
- Phase 4 launch only after the cooperative is financially stable and has legal resources to navigate TLC compliance

---

## 8. Key Gaps and Confidence Levels

| Finding | Confidence | Gap |
|---|---|---|
| Fare Co-op uses Y-Risk for platform-level commercial auto | High (public source) | Y-Risk premium rates for cooperative rideshare not published |
| NYC TLC insurance rising 25% through 2028 | High (NY DFS announcement) | Per-driver dollar amounts are estimates, not actuals |
| Group captive viable at 150–200 drivers | Medium (derived from general captive literature) | No rideshare-specific captive precedent found in US |
| DC Colorado spent 5 months securing insurance | High (NPQ article) | Carrier name and premium not disclosed |
| California occupational accident insurance ~$500–$1,500/driver | Medium (derived from Prop 22 requirements) | Actual carrier quotes not obtained |
| MAIF-CoopCycle model covers delivery cooperatives in France | High (ICMIF announcement) | No direct US equivalent insurance product confirmed |
| Cooperative model financially viable vs. Uber/Lyft | High (earnings math confirmed) | Long-term actuarial stability of cooperative commercial policy not tested |

---

## 9. Recommendations Summary

1. **Contact Y-Risk directly** as the first action in Phase 2 insurance procurement. They have already written a cooperative rideshare policy and are the clearest path to platform-level commercial auto coverage.

2. **Do not launch in NYC for Phase 2.** The per-vehicle TLC structure and 25% rate increase cycle make it the most expensive and most structurally difficult market for a cooperative.

3. **Target Atlanta or Portland for first launch.** Both markets have existing cooperative rideshare precedent, manageable insurance costs, and favorable regulatory frameworks.

4. **Budget $500,000 minimum in cooperative capitalization** before approaching any insurer. This is the documented requirement from Drivers Cooperative Colorado's experience.

5. **Implement platform-level commercial auto from day one.** Driver-by-driver individual policies create coverage gaps, claims complexity, and undermine the cooperative's value proposition.

6. **Add voluntary occupational accident insurance at launch**, modeled on California's Prop 22 requirement. Cost is manageable (~$500–$1,500/driver/year) and is a powerful member recruitment advantage.

7. **Plan for group captive formation at 150–200 drivers** in a single market. This is the point where self-insurance becomes actuarially viable and where the cooperative can begin recapturing underwriting profit instead of paying it to commercial insurers.

8. **Build the federation insurance play.** OpenRide's structural advantage as open-source infrastructure for multiple cooperatives is the path to a CoopCycle/MAIF-style bespoke insurance product. At 5–10 deployed cooperatives with 500+ total drivers, the cooperative federation has leverage to negotiate a custom product with a US mutual insurer or form an RRG.

---

## Sources

- [NAIC: Insurance Topics — Commercial Ride-Sharing](https://content.naic.org/insurance-topics/commercial-ride-sharing)
- [Fare Co-op: Licenses & Insurance](https://fare.coop/licenses-insurance/)
- [Fare Co-op: This Ride-Hailing Platform is Built Different](https://fare.coop/news/this-ride-hailing-platform-is-built-different-what-does-that-mean-for-drivers/)
- [Fare Co-op's Rapid Rise to America's 3rd Largest Fully Licensed Rideshare](https://highways.today/2025/09/07/fare-co-op/)
- [Drivers Cooperative Colorado (NPQ)](https://nonprofitquarterly.org/drivers-cooperative-colorado-building-a-social-co-op-for-rideshare-drivers/)
- [Drivers Cooperative Colorado: How It's Going (Denverite, April 2026)](https://denverite.com/2026/04/21/denver-startup-rideshare-drivers-cooperative/)
- [MAIF / CoopCycle Insurance Partnership (ICMIF)](https://www.icmif.org/news_story/maif-launches-an-insurance-offer-in-partnership-with-coopcycle-for-users-of-delivery-bicycles/)
- [Modo Car-Sharing Co-op Insurance](https://www.facebook.com/Modo.Coop/posts/how-does-insurance-work-when-driving-a-modo-every-modo-member-gets-full-collisio/2805752576118528/)
- [NYC TLC Insurance Costs & Requirements (AY Royal)](https://www.ayroyal.com/tlc-insurance-in-nyc/)
- [NY Says Rideshare Insurance Rates to Rise 25% (Insurance Journal, Dec 2025)](https://www.insurancejournal.com/news/east/2025/12/16/851228.htm)
- [TLC Insurance Premium Increases 2026](https://tlcinsurancenow.com/blog/tlc-insurance-premium-increases-2026-nyc)
- [CPUC TNC Insurance Requirements](https://www.cpuc.ca.gov/regulatory-services/licensing/transportation-licensing-and-analysis-branch/transportation-network-companies/tnc-insurance-requirements)
- [California Proposition 22 and TNCs](https://www.advocatemagazine.com/article/2021-june/proposition-22-and-transportation-network-carriers)
- [Seattle TNC Drivers' Rights (LNI)](https://lni.wa.gov/workers-rights/industry-specific-requirements/transportation-network-company-drivers-rights/)
- [Seattle TNC Minimum Compensation](https://www.seattle.gov/laborstandards/ordinances/tnc-legislation/minimum-compensation-ordinance)
- [Portland TNC Insurance Requirements](https://www.portland.gov/code/16/40/230)
- [Colorado PUC TNC](https://puc.colorado.gov/tnc)
- [Group Captive Insurance (Captive Resources)](https://www.captiveresources.com/intro-to-member-owned-group-captive-insurance/)
- [Vermont Captive Formation & Licensing](https://dfr.vermont.gov/captive-insurance/formation-licensing)
- [ICMIF Practical Guide to Mutual Insurance](https://www.icmif.org/wp-content/uploads/2020/07/Guide_Mutual-insurance_Icmif.pdf)
- [Washington State Workers' Compensation for TNC Drivers](https://www.sharpelawfirm.org/lni/tnc-driver-rights/)
- [Cyber Insurance Cost 2025 (Embroker)](https://www.embroker.com/blog/cyber-insurance-cost/)
- [D&O Insurance Cost for Nonprofits / Cooperatives (Schneider Insurance)](https://schneider-insurance.com/cost-of-d-o-insurance-for-nonprofits/)
- [Technology E&O Insurance Cost (TechInsurance)](https://www.techinsurance.com/technology-business-insurance/cost)
- [Rideshare Insurance Costs 2026 (The Rideshare Guy)](https://therideshareguy.com/rideshare-insurance/)
