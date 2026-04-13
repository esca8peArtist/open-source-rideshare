# Regulatory Compliance Research: Open-Source Rideshare Platform

**Document Version**: 1.0
**Date**: 2026-04-11
**Scope**: United States — Federal, State, and Municipal Requirements
**Purpose**: Comprehensive regulatory landscape analysis for an open-source cooperative rideshare platform

> **Notation**: Items marked with [VERIFY] indicate areas where regulations may have changed since last confirmed or where jurisdiction-specific details should be validated with current legal counsel before relying on them for compliance decisions.

---

## Table of Contents

1. [Federal Requirements](#1-federal-requirements)
2. [State-Level TNC Licensing](#2-state-level-tnc-licensing)
3. [Major City-Specific Requirements](#3-major-city-specific-requirements)
4. [Insurance Requirements](#4-insurance-requirements)
5. [Driver Requirements](#5-driver-requirements)
6. [Accessibility and ADA Compliance](#6-accessibility-and-ada-compliance)
7. [Data Privacy and Security](#7-data-privacy-and-security)
8. [Tax Implications](#8-tax-implications)
9. [Recommendations for a Cooperative Model](#9-recommendations-for-a-cooperative-model)

---

## 1. Federal Requirements

### 1.1 Federal Trade Commission (FTC)

The FTC does not regulate rideshare companies through a dedicated licensing regime, but its authority applies in several critical ways:

- **Deceptive Practices (Section 5 of the FTC Act)**: Pricing must be transparent. Surge pricing, if implemented, must be clearly communicated before a rider confirms a trip. The FTC has investigated Uber's "upfront pricing" disclosures in the past.
- **Data Security**: The FTC enforces reasonable data security practices. A rideshare platform collecting rider location data, payment information, and driver PII is subject to FTC enforcement if a breach occurs due to inadequate security. The FTC's enforcement actions against Uber (2017-2018 consent decree) set precedent — failure to disclose breaches or misrepresenting security practices triggers enforcement.
- **Truth in Advertising**: Driver earnings claims must be substantiated. The FTC has taken action against gig platforms for misleading earnings projections.
- **Algorithmic Transparency**: Emerging FTC guidance on algorithmic pricing and matching may apply. [VERIFY — FTC rulemaking on algorithmic systems may have advanced since mid-2025]

### 1.2 Americans with Disabilities Act (ADA)

- **Title III (Public Accommodations)**: Rideshare platforms are generally treated as public accommodations or, at minimum, as services that must not discriminate against people with disabilities.
- **Service Animals**: Drivers cannot refuse rides to passengers with service animals. The platform must have a clear policy and enforce it — driver deactivation for refusal is standard.
- **Wheelchair Accessible Vehicles (WAV)**: The DOJ and DOT have taken the position that TNCs must provide equivalent service to wheelchair users. This does not necessarily mean every vehicle must be accessible, but the platform must have a plan (partnerships, WAV sub-fleets, etc.).
- **App Accessibility**: The rider and driver apps must comply with WCAG 2.1 AA standards — screen reader compatibility, sufficient contrast, alternative text, voice navigation support.
- **Communication Access**: Deaf or hard-of-hearing riders and drivers must be able to use the platform effectively (text-based communication, visual notifications).

### 1.3 Department of Transportation (DOT)

- **FMCSA**: The Federal Motor Carrier Safety Administration generally does not regulate rideshare (passenger vehicles under 10,001 lbs carrying fewer than 16 passengers are exempt from FMCSA jurisdiction). However, if the platform expands to van-pool or shuttle services, FMCSA registration may be required.
- **NHTSA**: Vehicle safety recalls are relevant — the platform should verify vehicles against NHTSA recall databases during onboarding.
- **FAA**: Not directly applicable unless the platform integrates drone delivery or air taxi services. [VERIFY — urban air mobility regulations are evolving]

### 1.4 Federal Tax — IRS Requirements

- **1099-NEC Reporting**: The platform must issue Form 1099-NEC to any driver earning $600 or more in a calendar year. This is a hard obligation — failure triggers penalties.
- **1099-K Reporting**: If the platform processes payments, Form 1099-K applies for drivers receiving more than $600 in gross payment transactions (threshold lowered from $20,000/200 transactions under the American Rescue Plan Act, though implementation has been phased in). [VERIFY — the IRS has delayed the $600 threshold multiple times; confirm current enforcement year]
- **Backup Withholding**: If a driver fails to provide a valid TIN (W-9), the platform must withhold 24% of payments.
- **Worker Classification**: The IRS applies a multi-factor test. Rideshare drivers are currently treated as independent contractors (1099), not employees (W-2), at the federal level. The cooperative model may complicate this — see Section 9.
- **FICA/Self-Employment Tax**: Drivers are responsible for self-employment tax (15.3%). The platform has no obligation to withhold, but must provide accurate reporting.

### 1.5 Other Federal Considerations

- **CFPB (Consumer Financial Protection Bureau)**: If the platform offers driver financing, instant pay, or any financial product, CFPB oversight applies.
- **EEOC**: Anti-discrimination requirements in driver onboarding and deactivation. Even with independent contractors, discriminatory algorithmic decisions (ride matching, deactivation patterns) can trigger federal civil rights scrutiny.
- **FCRA (Fair Credit Reporting Act)**: Background checks on drivers must comply with FCRA — adverse action notices, dispute rights, and use of consumer reporting agencies.

---

## 2. State-Level TNC Licensing

### 2.1 Overview

As of mid-2025, all 50 states plus the District of Columbia have enacted some form of TNC legislation or regulation. The regulatory landscape coalesced rapidly between 2014 and 2019, driven by Uber and Lyft's national expansion.

### 2.2 Common Requirements Across States

Nearly every state TNC framework includes these elements:

| Requirement | Typical Standard | Notes |
|---|---|---|
| TNC License/Permit | Required | Annual or biennial application with state PUC/DOT |
| Application Fee | $1,000 - $100,000+ | Varies enormously by state |
| Annual Renewal | Required | Often with updated insurance certificates |
| Insurance Filing | Required | Certificate of insurance or surety bond |
| Background Checks | Required | Criminal + driving record; see Section 5 |
| Vehicle Inspections | Varies | Some states require annual; others accept self-certification |
| Trade Dress | Usually required | Visible identifier (logo/emblem) on vehicle |
| Zero Tolerance Drug/Alcohol | Required | Immediate deactivation policy |
| Non-Discrimination Policy | Required | Must file with regulatory body |
| Record Keeping | Required | Trip records retained 2-7 years depending on state |
| Accident Reporting | Required | Typically within 10-30 days to state regulator |

### 2.3 State-by-State Licensing Details

#### Tier 1: Straightforward Registration States

These states have relatively simple, statewide TNC frameworks with modest fees:

- **Texas**: TNC permit through the Texas Department of Licensing and Regulation. $5,000 annual fee. [VERIFY — fee amount] Statewide preemption of most local regulations (Austin fought this and lost in 2017 when the state passed HB 100).
- **Florida**: Statewide regulation through the Department of Highway Safety and Motor Vehicles. $5,000 annual fee. Strong preemption of local regulation. Fingerprint-based background checks NOT required at state level.
- **Arizona**: Minimal regulation. TNC permit via the Department of Weights and Measures [VERIFY — may have moved agencies]. Low fee structure. Pro-business regulatory environment.
- **Georgia**: TNC permit through the Georgia Public Service Commission. $75,000 annual fee [VERIFY]. Statewide preemption.
- **Ohio**: Regulated by the Public Utilities Commission of Ohio (PUCO). Statewide preemption enacted 2015.
- **Indiana**: Secretary of State registration. Relatively low barriers.
- **Tennessee**: Statewide TNC Act. Tennessee Public Utility Commission oversight.

#### Tier 2: Moderate Regulation States

- **Illinois**: Statewide framework but Chicago has extensive additional requirements (see Section 3). Illinois Commerce Commission oversight.
- **Pennsylvania**: PUC-regulated. Certificate of public convenience required — more involved than a simple permit. Experimental period for autonomous vehicles.
- **Massachusetts**: DPU (Department of Public Utilities) regulation. $0.20/ride assessment fee directed to various state funds. Requires state background checks (CORI) in addition to national checks. Annual vehicle inspections required.
- **Colorado**: PUC permit. $111,250 annual fee for large TNCs [VERIFY — this is the historical Uber/Lyft fee; smaller operators may have different tiers]. Extensive insurance requirements.
- **Washington State**: Regulated by the UTC (Utilities and Transportation Commission) at the state level, but Seattle has significant additional requirements (see Section 3).
- **Maryland**: PSC (Public Service Commission) regulation. Statewide framework with some local flexibility.
- **Virginia**: DMV-administered TNC program. Reasonable fee structure.

#### Tier 3: Heavy Regulation States

- **California**: CPUC (California Public Utilities Commission) TCP (Transportation Charter-Party Carrier) permit or TNC-specific permit. Extensive requirements including Proposition 22 (2020) which established specific driver compensation rules, healthcare subsidies, and occupational accident insurance requirements for app-based drivers. Annual reporting on driver demographics, accessibility, and service equity. San Francisco and Los Angeles impose additional requirements (see Section 3).
- **New York**: TLC (Taxi and Limousine Commission) regulates in NYC (see Section 3). Outside NYC, the DMV and DOT regulate. Separate frameworks for upstate vs. downstate. Among the most complex regulatory environments in the country.
- **Connecticut**: DOT regulation. Moderate fees but detailed operational requirements.
- **New Jersey**: Motor Vehicle Commission. Required to participate in the state's Clean Air initiative [VERIFY].

#### Tier 4: Unique or Evolving Frameworks

- **Alaska**: Statewide TNC law enacted relatively recently. Lighter touch regulation. [VERIFY — exact regulatory body and requirements]
- **Hawaii**: Regulated by the PUC. Unique island-specific considerations for insurance and service availability.
- **Oregon**: Statewide regulation through ODOT, but Portland retains significant local authority (see Section 3).
- **Nevada**: Nevada Transportation Authority. Las Vegas/Clark County has additional requirements related to airport operations. Significant taxi industry lobbying historically.

### 2.4 Insurance Minimums by State (Summary)

Most states follow a three-period insurance model (detailed in Section 4), but minimums vary:

| Period | Most Common State Minimum | Higher-Requirement States |
|---|---|---|
| Period 1 (App on, no match) | 50/100/25 ($50K per person / $100K per accident / $25K property) | CA, NY, CO: often higher |
| Period 2 (En route to pickup) | $1M combined single limit | Uniform across most states |
| Period 3 (Passenger in vehicle) | $1M combined single limit | Uniform across most states |

### 2.5 State Preemption Landscape

A critical consideration for the platform:

- **Strong Preemption** (cities cannot add requirements): Texas, Florida, Arizona, Georgia, Indiana, Ohio, Tennessee, North Carolina
- **Partial Preemption** (cities can regulate some areas): Illinois, Washington, Pennsylvania, Virginia
- **Weak/No Preemption** (cities can heavily regulate): New York, Oregon, Colorado (in practice), Nevada

Understanding preemption determines whether state-level compliance alone is sufficient or whether city-by-city analysis is needed.

---

## 3. Major City-Specific Requirements

### 3.1 New York City — TLC (Taxi and Limousine Commission)

NYC is the most heavily regulated rideshare market in the United States.

**Licensing**:
- The TNC must hold a TLC base license (or partner with a licensed base).
- All drivers must hold a TLC driver's license (FHV license), which requires:
  - 24-hour TLC driver education course [VERIFY — hours may have changed]
  - FHV (For-Hire Vehicle) drug test
  - Fingerprint-based background check through the DCJS
  - Medical examination (DOT medical card equivalent)
  - Valid NYS driver's license held for minimum 1 year [VERIFY]

**Vehicle Requirements**:
- All vehicles must be TLC-licensed (FHV plates)
- Vehicle age limit: no more than 7 years old for most categories [VERIFY — may vary by vehicle class]
- Annual TLC vehicle inspection at authorized facility
- Vehicles must meet TLC insurance requirements (higher than state minimum)

**Driver Cap**: In August 2018, NYC imposed a cap on new FHV licenses (Local Law 147). New TNC vehicle licenses are effectively frozen except for wheelchair-accessible vehicles. This means any new rideshare entrant must either:
  - Use existing licensed FHV drivers/vehicles, or
  - Apply for WAV licenses (which are exempt from the cap), or
  - Lobby for cap relief (unlikely for a new entrant)

**Minimum Pay Rate**: NYC established a minimum per-minute and per-mile pay rate for drivers ($1.3108/mile, $0.5457/minute after expenses as of 2023 [VERIFY — rates are adjusted periodically]). The formula accounts for utilization rate. This is a floor — the platform cannot pay drivers less regardless of what riders pay.

**Congestion Surcharge**: $2.75 per ride in Manhattan below 96th Street (added to rider fare, remitted to state). [VERIFY — surcharge amount may have been adjusted]

**Accessibility**: 
- TNCs must meet WAV dispatch targets — a growing percentage of trips must be fulfilled by wheelchair-accessible vehicles.
- The TLC's Accessibility Improvement Surcharge funds WAV programs.

**Data Reporting**: Extensive trip-level data must be reported to the TLC (pickup/dropoff locations, times, fares, driver IDs). The TLC publishes aggregated trip data publicly.

**Estimated Cost to Enter NYC**: $500,000 - $2,000,000+ in first year (base license, insurance, legal, compliance staff, WAV fleet partnerships) [VERIFY]

### 3.2 Chicago

**Licensing**: 
- TNCs must obtain a license from the City of Chicago Department of Business Affairs and Consumer Protection (BACP).
- License fee: $10,000 annually [VERIFY]
- Per-trip fee: $0.72 for single rides, $0.53 for shared rides in downtown zone; reduced rates outside downtown [VERIFY — Chicago has adjusted these fees multiple times]

**Driver Requirements**:
- City-issued chauffeur's license (in addition to state driver's license)
- Fingerprint-based background check through the Chicago Police Department [VERIFY — Chicago has debated fingerprinting requirements]
- Additional city vehicle inspection

**Airport Operations**:
- Special permits for O'Hare (ORD) and Midway (MDW) pickup/dropoff
- Geofenced pickup zones
- Airport-specific surcharges ($4-5 per trip) [VERIFY]

**Accessibility**: Chicago requires TNCs to submit accessibility plans and pay into a WAV fund.

### 3.3 San Francisco

San Francisco operates within California's CPUC framework but adds:

**Airport (SFO)**:
- Ground Transportation Permit required
- Annual permit fee
- Designated pickup/dropoff areas (specific terminal locations)
- Trip fees remitted to SFO

**SFMTA Regulations**:
- Curb management rules — TNCs cannot stage in certain zones
- Congestion management restrictions in the Financial District during peak hours [VERIFY]
- Data sharing requirements with SFMTA for transportation planning

**Local Fees**:
- San Francisco imposes a per-ride tax on TNC trips that originate or terminate within the city. Rate varies for solo vs. shared rides.
- Revenue directed to transit and infrastructure improvements.

**Environmental**: 
- California's Clean Miles Standard (SB 1014) requires TNCs to reduce greenhouse gas emissions per passenger-mile. By 2030, 90% of VMT must be in zero-emission vehicles. [VERIFY — implementation timeline and current targets]

### 3.4 Los Angeles

**LADOT**: 
- Los Angeles Department of Transportation requires data sharing through its Mobility Data Specification (MDS) — originally developed for scooters/bikes but expanded to TNCs for certain planning purposes. [VERIFY — MDS applicability to TNCs specifically]
- Airport (LAX) requires a separate Ground Transportation permit with specific pickup rules (LAX-it lot, designated rideshare areas).

**Local Fees**: Per-ride fees apply, particularly for airport trips.

**Equity Requirements**: LA has pushed for equity metrics — TNCs may need to demonstrate service availability in underserved neighborhoods.

### 3.5 Austin, Texas

Austin's history is instructive for the open-source rideshare project:

- In 2016, Austin passed a local ordinance requiring fingerprint-based background checks. Uber and Lyft withdrew from the city rather than comply.
- Multiple local alternatives emerged (RideAustin, Fasten, Fare) — open-source/nonprofit models temporarily filled the gap.
- In 2017, Texas passed HB 100, preempting local TNC regulation statewide. Uber and Lyft returned. Local alternatives mostly shut down.

**Current State**: Austin follows the statewide Texas framework. No additional city permits required beyond state TNC registration. Airport (AUS) operations require compliance with Austin-Bergstrom's ground transportation rules.

**Lesson for the Project**: Austin's history demonstrates both the opportunity (local alternatives can emerge when incumbents withdraw) and the risk (state preemption can eliminate local regulatory advantages).

### 3.6 Seattle

**City of Seattle Requirements**:
- TNC license through the City of Seattle (separate from Washington State UTC permit)
- Per-trip fee: $0.57 [VERIFY — Seattle adjusts periodically]
- Minimum pay standard for drivers: enacted in 2020 (Ordinance 126124), establishing per-mile and per-minute minimums. Seattle was among the first cities to establish TNC driver minimum pay. [VERIFY — current rates]

**Driver Requirements**:
- City business license
- Washington State Patrol background check

**Accessibility**:
- Seattle has an active WAV incentive program
- Per-trip accessibility surcharge funds WAV service

**Airport (SEA-TAC)**:
- Port of Seattle Ground Transportation permit
- Designated pickup areas (3rd floor of parking garage, typically)
- Per-trip fee to the Port

**Data Sharing**: Seattle requires trip data reporting for transportation planning purposes.

### 3.7 Portland, Oregon

**City of Portland PBOT (Bureau of Transportation)**:
- Private For-Hire Transportation (PFHT) permit required
- Annual permit fee for TNC
- Per-trip fee (approximately $0.50) [VERIFY]
- Portland retained more local regulatory authority than many cities

**Driver Requirements**:
- City-issued For-Hire Driver Permit
- Portland-specific background check
- Vehicle inspection at city-authorized facility

**Equity and Accessibility**:
- Portland requires service equity reporting — demonstrating rides are available across the entire city, not just affluent neighborhoods
- WAV service requirements

**Airport (PDX)**:
- Port of Portland Ground Transportation permit
- Specific cell phone lot / pickup area rules
- Per-trip fees

---

## 4. Insurance Requirements

### 4.1 The Three Coverage Periods

The rideshare insurance framework was developed specifically for the TNC industry and is now codified in most state TNC laws. It addresses the gap between personal auto insurance (which typically excludes commercial use) and full commercial fleet insurance.

#### Period 1: App On, No Match Accepted

The driver has the app open and is available for rides but has not yet accepted a trip request.

- **Typical Minimums**: $50,000 per person bodily injury / $100,000 per accident bodily injury / $25,000 property damage (50/100/25)
- **Who Provides**: The TNC provides contingent/excess coverage that kicks in if the driver's personal insurance denies the claim
- **Key Issue**: Many personal auto policies exclude rideshare use entirely. Some insurers now offer "rideshare endorsements" that bridge the gap for Period 1

#### Period 2: Match Accepted, En Route to Pickup

The driver has accepted a trip and is driving to pick up the rider.

- **Typical Minimums**: $1,000,000 combined single limit (CSL) for bodily injury and property damage
- **Who Provides**: The TNC must provide primary commercial coverage
- **Additional**: Uninsured/underinsured motorist (UM/UIM) coverage, typically $1M

#### Period 3: Passenger in Vehicle

The rider is in the vehicle from pickup to dropoff.

- **Typical Minimums**: $1,000,000 CSL for bodily injury and property damage
- **Who Provides**: The TNC must provide primary commercial coverage
- **Additional**: UM/UIM coverage, typically $1M. Some states also require medical payments (MedPay) or personal injury protection (PIP)

### 4.2 State-Specific Insurance Variations

**Higher-Requirement States**:

| State | Period 1 | Periods 2-3 | Notable Requirements |
|---|---|---|---|
| California | 50/100/30 | $1M CSL | SB 1264 requirements; contingent comprehensive/collision [VERIFY] |
| New York | 75/150/50 (NYC: higher) | $1.25M CSL [VERIFY] | TLC vehicles require separate coverage tiers |
| Colorado | 50/100/30 | $1M CSL | PUC may require higher based on fleet size |
| Massachusetts | 50/100/25 | $1M CSL | PIP requirements apply |
| New Jersey | State minimum varies | $1.5M CSL [VERIFY] | Higher than most states |
| Washington | 50/100/30 | $1M CSL | UM/UIM explicitly required |

**No-Fault States**: In no-fault insurance states (Michigan, New York, Florida, New Jersey, Pennsylvania, Hawaii, Kansas, Kentucky, Massachusetts, Minnesota, North Dakota, Utah), PIP (Personal Injury Protection) requirements add complexity. The TNC's commercial policy must comply with the state's no-fault regime.

### 4.3 Insurance Cost Estimates

For a new TNC platform, insurance is typically the single largest operational expense:

- **Small operation (1 city, 100 drivers)**: $200,000 - $500,000 annually [VERIFY — highly variable by market]
- **Medium operation (5 cities, 1,000 drivers)**: $1M - $5M annually
- **National operation**: $50M+ annually

**Key Cost Factors**:
- Claims history (new entrants pay higher premiums due to lack of actuarial data)
- Geographic concentration (NYC, LA, and Miami are among the most expensive markets)
- Fleet size and utilization rates
- Deductible structure

### 4.4 Insurance for the Cooperative Model

A cooperative model may have insurance advantages and disadvantages:

**Advantages**:
- Some cooperative insurance structures (mutual insurance, risk retention groups) may offer lower premiums
- Driver-owners may be more careful, leading to lower claims rates [VERIFY — anecdotal, not proven]
- A cooperative could form a Risk Retention Group (RRG) under the Liability Risk Retention Act — this allows the cooperative to self-insure across state lines without needing separate licenses in each state [VERIFY — RRG formation requirements and applicability to TNCs]

**Disadvantages**:
- Smaller risk pools mean higher per-unit costs initially
- Less negotiating power with commercial insurers
- Capitalization requirements for self-insurance are substantial

---

## 5. Driver Requirements

### 5.1 Background Check Requirements

#### Federal / FCRA Compliance

All background checks must comply with the Fair Credit Reporting Act:
- Use FCRA-compliant consumer reporting agency (CRA)
- Provide pre-adverse action notice before rejecting an applicant
- Provide adverse action notice with copy of report and summary of rights
- Allow dispute period (typically 5 business days)
- Do not use arrest records without convictions (per EEOC guidance)

#### State Background Check Variations

**Name-Based Checks** (most states):
- Multi-state criminal database search
- National Sex Offender Registry check
- Social Security number trace
- County-level criminal records search (in counties of residence for past 7 years)
- Driving record (MVR) check

**Fingerprint-Based Checks** (additional requirement in some jurisdictions):
- New York City (TLC): fingerprint-based through DCJS
- Chicago: fingerprint-based through CPD [VERIFY — status of this requirement]
- Massachusetts: CORI (Criminal Offender Record Information) check
- Houston: fingerprint requirement [VERIFY — may have been preempted by Texas HB 100]

The fingerprint vs. name-based debate is significant. Fingerprint checks access FBI databases and catch aliases/name changes. Name-based checks can miss records filed under different names. However, fingerprint requirements increase onboarding friction and cost.

#### Disqualifying Offenses (Common Across States)

**Automatic Disqualification** (lifetime or extended lookback):
- Any felony conviction involving violence, sexual offenses, or terrorism
- Sex offender registry listing
- DUI/DWI within the past 7 years (some states: 10 years)
- Any felony conviction within past 7 years

**Typically Disqualifying** (varies by state):
- More than 3 moving violations in past 3 years
- Any at-fault accidents in past 3 years
- Drug-related felonies (lookback period varies)
- Hit-and-run
- Driving on suspended/revoked license
- Fraud or theft convictions within 7 years

### 5.2 Driving Record Requirements

| Requirement | Common Standard |
|---|---|
| Minimum license tenure | 1-3 years (varies by state; 1 year most common) |
| Maximum moving violations (3 years) | 3-4 |
| Maximum at-fault accidents (3 years) | 0-1 |
| DUI/DWI lookback | 7-10 years |
| License status | Must be valid, unrestricted |
| License type | Standard (Class D or equivalent); CDL not required |

### 5.3 Vehicle Requirements

| Requirement | Common Standard | Strictest Markets |
|---|---|---|
| Maximum vehicle age | 10-15 years | NYC: 7 years; some states: 10 years |
| Minimum doors | 4 doors | Universal |
| Branded/salvage title | Prohibited | Universal |
| Annual inspection | Required in some states | NYC: TLC inspection; MA: state inspection |
| In-state registration | Required | Universal |
| Trade dress/emblem | Required in most states | Visible from outside, illuminated in some |
| Seating capacity | 4+ passengers (excl. driver) | Some allow motorcycles/mopeds for certain categories [VERIFY] |

### 5.4 Training Requirements

Most states do not mandate formal driver training for TNC drivers. Notable exceptions:

- **New York City**: 24-hour TLC driver education course covering safety, navigation, customer service, accessibility [VERIFY — hours]
- **Massachusetts**: Requires completion of an online course [VERIFY]
- **California**: No formal training requirement, but platforms must provide safety information

**Recommended (Not Required)**:
- Defensive driving
- Accessibility awareness (service animals, wheelchair assistance)
- De-escalation and safety
- Platform-specific app training
- Local navigation knowledge

### 5.5 Ongoing Monitoring

Several states require continuous or periodic re-checking:

- **Annual background check re-run**: Required in many states (California, Massachusetts, Washington, others)
- **Continuous MVR monitoring**: Some states require real-time driving record monitoring through services like SambaSafety or LENS [VERIFY — specific states]
- **Drug/Alcohol**: Zero-tolerance policy required. Random testing is NOT typically required for TNC drivers (unlike CDL holders)

---

## 6. Accessibility and ADA Compliance

### 6.1 Federal ADA Framework for TNCs

The ADA's application to TNCs has been an evolving area of law. Key rulings and guidance:

- **DOJ Guidance**: The DOJ has indicated that TNCs are subject to ADA requirements as places of public accommodation or as service providers.
- **Service Animals**: Refusal to transport a rider with a service animal violates the ADA. The platform must:
  - Train drivers on service animal obligations
  - Enforce no-refusal policies
  - Deactivate drivers who refuse service animal rides (typically after one warning for first offense, immediate for subsequent)
  - Track and report service animal complaints

- **NFD v. Uber (2021)** [VERIFY — case citation]: Courts have found that TNCs can be liable for systemic failure to provide accessible service.

### 6.2 Wheelchair Accessible Vehicle (WAV) Requirements

WAV requirements vary dramatically by jurisdiction:

**NYC (TLC)**:
- TNCs must meet escalating WAV wait-time targets
- The goal is equivalent wait times for WAV and standard requests
- TNCs can comply through partnerships with WAV providers, dedicated WAV fleets, or the Accessible Dispatch program
- WAV trip surcharges help fund compliance

**California (CPUC)**:
- The CPUC's Access for All Act requires TNCs to either provide WAV service or pay $0.10 per non-WAV trip into the state's Access Fund [VERIFY — current per-trip amount]
- Annual accessibility reports required
- Offset program: TNCs can reduce payments by directly providing WAV trips

**Chicago**:
- Per-ride accessibility fee
- WAV service plans required

**Other Cities**: Most major cities either require WAV service plans or charge per-trip fees to fund accessible transportation alternatives.

### 6.3 App Accessibility Requirements

The platform's rider and driver apps must meet:

- **WCAG 2.1 Level AA**: This is the de facto legal standard for digital accessibility
  - Screen reader compatibility (VoiceOver for iOS, TalkBack for Android)
  - Minimum contrast ratios (4.5:1 for normal text)
  - Touch target sizes (minimum 44x44 points)
  - Alternative text for all images and icons
  - Keyboard/switch navigation support
  - Captions for any audio/video content
  - No information conveyed by color alone
  - Focus management for dynamic content

- **Communication Accessibility**:
  - In-app text messaging (not just phone calls) for rider-driver communication
  - Visual notifications (not just audio) for driver app
  - Pre-set messages/quick responses for drivers who are deaf or hard-of-hearing
  - Estimated arrival communicated through multiple modalities

### 6.4 Penalties for Non-Compliance

- **DOJ/ADA lawsuits**: Injunctive relief plus damages ($75,000 first violation, $150,000 subsequent)
- **State AG enforcement**: Varies; California, New York, and Illinois have been active
- **Private lawsuits**: Individual and class actions; attorney fees recoverable by plaintiff
- **TLC/local enforcement**: Fines per violation, potential license revocation
- **Regulatory penalties**: CPUC, for example, can impose per-trip fines for failure to meet WAV targets [VERIFY]

### 6.5 Cooperative Model Advantage

A cooperative rideshare platform has an opportunity to differentiate through accessibility:
- Driver-owners may be more motivated to provide quality service
- The platform can build accessibility features natively (not as afterthoughts)
- Partnership with disability advocacy organizations for testing and feedback
- WAV driver-owners could be given governance priority in the cooperative

---

## 7. Data Privacy and Security

### 7.1 Data Collected by a Rideshare Platform

Understanding the regulatory surface requires mapping the data collected:

| Data Category | Examples | Sensitivity Level |
|---|---|---|
| Rider PII | Name, email, phone, payment info | High |
| Rider Location | GPS coordinates, trip history, home/work addresses | Very High |
| Driver PII | Name, SSN, driver's license, address, bank account | Very High |
| Driver Background Check Data | Criminal records, driving records | Very High |
| Trip Data | Routes, timestamps, fares, ratings | Medium-High |
| Communication Data | In-app messages, support tickets | Medium |
| Device Data | Device ID, OS version, IP address | Medium |
| Biometric Data | Photo (for identity verification), potentially fingerprints | Very High (biometric-specific laws apply) |

### 7.2 State Data Privacy Laws

#### California — CCPA/CPRA (California Consumer Privacy Act / California Privacy Rights Act)

**Applicability**: Applies to businesses that collect personal information of California residents AND meet thresholds (annual revenue >$25M, or data of 100,000+ consumers, or 50%+ revenue from data sales). A cooperative rideshare platform operating in California would likely meet these thresholds at scale.

**Key Requirements**:
- Right to know what data is collected and how it is used
- Right to delete personal information
- Right to opt out of sale/sharing of personal information
- Right to correct inaccurate information
- Right to limit use of sensitive personal information (geolocation is "sensitive" under CPRA)
- Privacy policy disclosures
- Data protection assessments for high-risk processing
- 12-month lookback for consumer requests

**Geolocation Specific**: CPRA classifies precise geolocation (within 1,850 feet / ~563 meters) as sensitive personal information. Riders must be able to limit use of their location data beyond what is strictly necessary for the service. [VERIFY — implementation details of geolocation sensitivity requirements]

#### Illinois — BIPA (Biometric Information Privacy Act)

**Applicability**: If the platform uses facial recognition for driver identity verification (photo matching), BIPA applies.

**Key Requirements**:
- Written informed consent before collecting biometric data
- Published retention and destruction schedule
- Cannot sell or profit from biometric data
- Private right of action with statutory damages ($1,000 per negligent violation, $5,000 per intentional violation)
- BIPA litigation has resulted in multi-billion dollar settlements (Facebook: $650M, Google: various)

**Critical for the Platform**: Driver photo verification features must include BIPA-compliant consent flows for Illinois drivers.

#### Virginia — VCDPA (Virginia Consumer Data Protection Act)

- Similar to CCPA but with some differences in thresholds and rights
- Applies to entities processing data of 100,000+ Virginia consumers, or 25,000+ if >50% revenue from data sales
- Data protection assessments required for targeted advertising, profiling, and sensitive data processing

#### Colorado — CPA (Colorado Privacy Act)

- Similar framework to VCDPA
- Universal opt-out mechanism required
- Effective July 2023

#### Connecticut — CTDPA, Utah — UCPA, Texas — TDPSA, Oregon — OCPA, Montana — MCDPA, Iowa — ICDPA, Indiana — INCDPA, Tennessee — TIPA, Delaware — DPDPA

[VERIFY — multiple additional state privacy laws have been enacted between 2023-2026. A complete audit of all state privacy laws in effect should be conducted before launch.]

### 7.3 Data Breach Notification

All 50 states plus DC have data breach notification laws. Key parameters:

| State | Notification Deadline | AG Notification | Notable Features |
|---|---|---|---|
| California | "Most expedient time possible" / 72 hours to AG | Required if 500+ residents affected | Must offer 12 months free credit monitoring |
| New York | "Most expedient time possible" | Required | SHIELD Act adds data security requirements |
| Florida | 30 days | Required within 30 days if 500+ residents | |
| Texas | 60 days | Required if 250+ residents | |
| Colorado | 30 days | Required | |
| Illinois | "Most expedient time possible" | Required | |

**Platform Obligation**: The platform must have an incident response plan, breach detection capabilities, and state-by-state notification procedures before collecting user data.

### 7.4 Payment Card Industry (PCI DSS)

If the platform processes credit card payments:
- PCI DSS compliance is required (not a law, but a contractual obligation from card networks)
- Level depends on transaction volume (Level 1: >6M transactions/year; Level 4: <20,000)
- Most rideshare platforms use a payment processor (Stripe, Square) to minimize PCI scope
- The cooperative model should use a PCI-compliant payment processor rather than handling card data directly

### 7.5 Children's Data — COPPA

If the platform allows riders under 13 (unlikely but worth noting):
- COPPA applies and requires verifiable parental consent
- Most TNCs set a minimum rider age of 18 to avoid COPPA entirely
- Some allow unaccompanied minors (14-17) with parental account authorization [VERIFY — current Uber/Lyft teen account policies]

### 7.6 Open-Source Specific Considerations

An open-source platform faces unique data privacy challenges:
- **Code Transparency**: The codebase is public, meaning data handling practices are visible. This is a double-edged sword — it builds trust but also exposes vulnerabilities if security is not robust.
- **Self-Hosted Deployments**: If cooperatives can self-host, each deployment becomes a separate data controller with its own compliance obligations.
- **Data Portability**: As an open-source project, supporting data portability (export user data in machine-readable format) aligns with both privacy law requirements and open-source values.
- **Encryption Standards**: Document and enforce minimum encryption standards (AES-256 at rest, TLS 1.3 in transit) in the codebase.

---

## 8. Tax Implications

### 8.1 Platform Tax Obligations

#### Federal

- **Corporate Income Tax**: If structured as a C-corp: 21% federal corporate rate. If structured as a cooperative (Subchapter T): patronage dividends are deductible, potentially eliminating or reducing federal tax liability on distributed earnings.
- **Payroll Tax**: If any employees (staff, not drivers): standard payroll tax obligations (FICA, FUTA).
- **1099 Reporting**: Issue 1099-NEC to drivers earning $600+; issue 1099-K for payment processing if applicable (see Section 1.4).
- **Information Returns**: Various information returns depending on corporate structure.

#### State

- **State Corporate Income Tax**: Varies by state (0% in some states like Wyoming, South Dakota, Nevada, Texas [franchise tax instead], Washington [B&O tax instead]; up to ~12% in New Jersey, Iowa).
- **Franchise Tax**: Texas and some other states impose franchise/gross receipts taxes instead of income tax.
- **Sales Tax on Rides**: This is a critical and complex area:

### 8.2 Sales Tax on Rideshare Trips

The taxability of TNC rides varies by state:

| State | Sales Tax on TNC Rides? | Rate | Notes |
|---|---|---|---|
| California | No state sales tax on transportation | N/A | But local utility user taxes may apply [VERIFY] |
| New York | Yes | State rate + local (combined ~8%) | NYC surcharges are separate from sales tax |
| Illinois | No [VERIFY] | N/A | Chicago imposes per-trip fees instead |
| Texas | No state sales tax on transportation services | N/A | |
| Florida | No [VERIFY] | N/A | |
| Pennsylvania | Yes | 8.5% in Philadelphia [VERIFY] | Assessment on TNC rides |
| Washington | No sales tax, but B&O tax applies to TNC | 1.5% [VERIFY] | Based on gross income |
| Massachusetts | Yes | 6.25% | Applies to TNC rides |
| South Carolina | Yes | 6% [VERIFY] | Rides are taxable |

[VERIFY — sales tax applicability to TNC rides is an evolving area. Several states have added or changed their treatment between 2023-2026.]

### 8.3 Per-Trip Fees and Surcharges

Separate from sales tax, many jurisdictions impose per-trip fees:

| Jurisdiction | Fee | Purpose |
|---|---|---|
| NYC | $2.75 (Manhattan below 96th) | Congestion pricing |
| NYC | $0.75 (other areas) [VERIFY] | MTA funding |
| Chicago | $0.72 single / $0.53 shared (downtown) | City revenue |
| Massachusetts | $0.20/trip | State transportation fund |
| California | $0.10/trip (non-WAV) | Access for All fund |
| Seattle | $0.57/trip [VERIFY] | Driver compensation fund |
| San Francisco | $0.50-$3.25/trip [VERIFY] | Congestion/transit fund; varies by solo vs. shared |
| Portland | $0.50/trip [VERIFY] | City transportation fund |
| Colorado | $0.30/trip [VERIFY] | State transportation fund |

The platform must collect these fees from riders and remit to the appropriate jurisdiction. This requires per-jurisdiction fee calculation logic in the pricing engine.

### 8.4 Driver Tax Implications

**Drivers as Independent Contractors (1099)**:
- Drivers are responsible for self-employment tax (15.3% — 12.4% Social Security + 2.9% Medicare)
- Drivers can deduct business expenses (standard mileage rate: $0.70/mile for 2025 [VERIFY — 2026 rate]; or actual expenses)
- Drivers may need to make quarterly estimated tax payments
- The platform should provide tax summary tools (annual earnings, miles driven, etc.)

**If Drivers Are Reclassified as Employees**:
- The platform would owe employer-side FICA (7.65%), FUTA, state unemployment (SUTA), workers' compensation
- Significant cost increase (20-30% above contractor payments)
- See Section 9 for cooperative model implications on worker classification

### 8.5 State Income Tax Withholding

If drivers are classified as employees (or reclassified), the platform must withhold state income tax. Even for independent contractors, some states require information reporting to the state tax authority when 1099s are issued.

### 8.6 Tax Benefits of Cooperative Structure

Under Subchapter T of the Internal Revenue Code, cooperatives receive favorable tax treatment:

- **Patronage Dividends**: Earnings distributed to members (drivers) based on patronage (trips completed) are deductible by the cooperative, avoiding double taxation.
- **Section 199A Deduction**: Cooperative members may qualify for a 20% deduction on qualified business income from the cooperative [VERIFY — Section 199A was part of TCJA and may have been extended or modified].
- **Retained Patronage**: Even undistributed earnings can receive favorable treatment if properly allocated.
- **State Tax Benefits**: Some states offer additional tax incentives for cooperatives (e.g., reduced franchise tax, exemptions from certain fees).

---

## 9. Recommendations for a Cooperative Model

### 9.1 Cooperative Structure Options

**Option A: Worker Cooperative (Recommended)**

A worker cooperative where drivers are the member-owners.

- **Structure**: Incorporated as a cooperative corporation under state cooperative law (varies by state)
- **Governance**: One member, one vote. Board elected by driver-members.
- **Economics**: Surplus distributed as patronage dividends based on trips completed
- **Legal Entity**: Cooperative corporation (available in most states) or LLC structured as cooperative

**Option B: Platform Cooperative (Multi-Stakeholder)**

Both drivers and riders are member-owners.

- **Advantages**: Broader governance, rider buy-in
- **Disadvantages**: Potentially conflicting interests (drivers want higher pay, riders want lower fares), more complex governance
- **Implementation**: Multi-stakeholder cooperative law (available in some states: California, Colorado, Minnesota, Wisconsin) [VERIFY — which states have multi-stakeholder cooperative statutes]

**Option C: Nonprofit Model**

501(c)(3) or 501(c)(12) structure.

- **Advantages**: Tax-exempt, eligible for grants, public trust
- **Disadvantages**: Cannot distribute profits to members, more restrictions on activities, harder to capitalize
- **Suitability**: Better for the technology platform (open-source development) than for the operating entity

**Recommended Approach**: Separate the open-source technology (nonprofit or foundation) from the operating cooperative (worker cooperative in each market). The technology foundation develops and maintains the software; market-specific cooperatives operate the service.

### 9.2 Worker Classification Under the Cooperative Model

The cooperative structure interacts with worker classification in important ways:

**Potential Advantage**: If drivers are member-owners of the cooperative, the argument that they are "independent business operators" is stronger than for Uber/Lyft drivers. Member-owners:
- Have governance rights (vote on policies, elect board)
- Share in profits/losses
- Set their own policies (collectively)
- Are not subject to unilateral algorithmic control

**Potential Risk**: Some labor regulators may still classify driver-members as employees, especially if:
- The platform sets fares (even if democratically decided)
- The platform deactivates drivers (even through cooperative governance)
- Drivers cannot meaningfully influence working conditions

**California (AB 5 / Prop 22)**: AB 5's ABC test for employee classification is strict. Prop 22 created a carve-out for app-based drivers, but Prop 22's application to a cooperative (vs. a traditional TNC) is untested. [VERIFY — current status of Prop 22 legal challenges]

**Recommendation**: Consult employment law counsel in each target market. Structure the cooperative to maximize member autonomy: allow members to set their own schedules, accept/reject rides without penalty, participate in fare-setting, and exercise genuine governance rights.

### 9.3 Compliance Simplification Under Cooperative Model

**Areas Where Cooperative Structure Simplifies Compliance**:

1. **Trust and Transparency**: Cooperative governance inherently provides transparency that regulators value. Open books, democratic decision-making, and member accountability can lead to easier regulatory relationships.

2. **Data Privacy**: Member-owners have a direct interest in data stewardship. The cooperative can implement privacy-by-design with member oversight.

3. **Accessibility**: Member-driven policy can prioritize accessibility without the profit-maximization tension of VC-backed companies.

4. **Tax Efficiency**: Subchapter T taxation avoids the double-taxation problem and aligns incentives between the platform and drivers.

5. **Community Relations**: Cooperatives often receive warmer regulatory reception than out-of-state VC-backed companies. Local ownership matters in local politics.

**Areas Where Cooperative Structure Complicates Compliance**:

1. **Capitalization**: Meeting insurance requirements and regulatory fees requires significant capital. Cooperatives have limited access to venture capital (which demands equity returns). Options:
   - Member equity contributions (driver buy-in)
   - Community Development Financial Institutions (CDFIs) loans
   - Cooperative development grants (USDA Rural Cooperative Development Grants, etc.) [VERIFY — availability for urban rideshare cooperatives]
   - Revenue-based financing
   - Patronage-based capital retention

2. **Multi-State Operations**: Each market may need a separate cooperative entity or complex federated governance structure. Operating across 50 states as a single cooperative is impractical.

3. **Speed of Compliance**: Cooperative decision-making (democratic governance) is slower than corporate fiat. Regulatory deadlines and compliance requirements do not accommodate lengthy consensus processes.

4. **Background Check / Deactivation**: The cooperative must still enforce safety standards, including deactivating member-owners who fail background checks or violate policies. This creates governance tension — you are removing an owner.

### 9.4 Phased Market Entry Strategy

#### Phase 1: Single-Market Launch (Months 1-12)

**Recommended First Market**: Austin, TX or Portland, OR

**Austin Rationale**:
- Strong preemption (state-level compliance only)
- History of accepting alternative rideshare models (RideAustin precedent)
- Tech-friendly population
- Moderate market size for testing
- Texas has cooperative corporation law
- Lower insurance costs than coastal cities

**Portland Rationale**:
- Active cooperative/alternative economy culture
- PBOT has process for new TNC entrants
- Oregon has strong cooperative law
- Moderate market size
- Social/political alignment with cooperative values

**Phase 1 Compliance Checklist**:
- [ ] Incorporate cooperative entity in chosen state
- [ ] Obtain state TNC permit/license
- [ ] Obtain city permit (if applicable — Portland yes, Austin no)
- [ ] Secure commercial auto insurance (Periods 1-3)
- [ ] Establish FCRA-compliant background check process
- [ ] Implement vehicle inspection program
- [ ] File required insurance certificates with regulator
- [ ] Register for state/local tax obligations
- [ ] Implement privacy policy compliant with state law
- [ ] Develop accessibility plan and file with regulator
- [ ] Obtain airport ground transportation permit (if airport service planned)
- [ ] Set up 1099 reporting infrastructure
- [ ] Legal review of cooperative bylaws by employment and cooperative law attorneys

**Estimated Phase 1 Compliance Cost**: $150,000 - $400,000 (legal, insurance, licensing, background check infrastructure) [VERIFY — obtain actual quotes]

#### Phase 2: Regional Expansion (Months 12-24)

Expand to 2-3 additional markets within the same state or in states with similar regulatory frameworks.

**If starting in Texas**: Expand to Houston, Dallas/Fort Worth, San Antonio (all under same state TNC framework, minimal incremental compliance cost)

**If starting in Portland**: Expand to Seattle (different state, similar culture, but significant additional compliance for Washington State UTC permit + Seattle city permit + minimum pay standards)

**Phase 2 Focus**:
- Refine compliance processes based on Phase 1 lessons
- Build relationships with regulators in expansion markets
- Develop federated cooperative governance model (local cooperative per market, national technology cooperative)
- Establish insurance track record to negotiate better premiums

#### Phase 3: Major Market Entry (Months 24-36)

Enter California (San Francisco or LA) as the first Tier 3 regulatory market.

**Why Wait for California**: CPUC process is complex and expensive. Prop 22 implications need careful legal analysis. Clean Miles Standard requires fleet electrification planning. But California's market is the largest and most important for establishing national viability.

**Phase 3 Compliance Additions**:
- CPUC TNC permit application
- CCPA/CPRA compliance (likely needed by this point anyway)
- Clean Miles Standard compliance plan
- Access for All fund participation
- California-specific insurance requirements

#### Phase 4: National Scaling (Months 36+)

Systematic expansion with standardized compliance playbook.

**Do Not Attempt Early**:
- NYC (TLC complexity, vehicle cap, cost)
- Chicago (fingerprinting debate, per-trip fees)
- Nevada (taxi industry politics)

**Consider for Later Phase**:
- East Coast mid-size cities (Washington DC, Boston, Philadelphia)
- Sun Belt growth markets (Phoenix, Nashville, Charlotte, Denver)

### 9.5 Compliance Infrastructure Recommendations

**Technology**:
- Build compliance modules into the platform from day one (not as afterthoughts)
- Per-jurisdiction fee calculation engine
- Automated 1099/tax reporting
- Background check integration API (partner with Checkr, Sterling, or similar)
- Trip data retention and reporting pipelines
- Privacy controls (data deletion, export, consent management)
- Accessibility testing as part of CI/CD pipeline

**Legal**:
- Engage cooperative law attorney (NCBA CLUSA or cooperative law firms)
- Engage TNC regulatory attorney in each target market
- Establish regulatory monitoring process (legislation tracking)
- Template regulatory filings that can be adapted per jurisdiction

**Insurance**:
- Engage insurance broker specializing in commercial transportation
- Explore cooperative insurance options (National Cooperative Insurance Company [VERIFY], risk retention groups)
- Build claims management process
- Driver education on insurance coverage and incident reporting

**Governance**:
- Draft bylaws that balance democratic governance with operational agility
- Compliance committee within the cooperative board
- Delegate regulatory compliance to professional management (not direct member vote on every filing)
- Regular compliance audits (quarterly in first year, semi-annually thereafter)

### 9.6 Regulatory Risk Matrix

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| State reclassifies drivers as employees | Medium | Very High | Strengthen cooperative member autonomy; engage labor law counsel |
| Insurance lapse or inadequate coverage | Low | Very High | Multiple insurance partners; excess coverage; compliance monitoring |
| Data breach | Medium | High | Security-first development; incident response plan; cyber insurance |
| Failure to comply with local permit requirements | Medium | High | Jurisdiction-specific compliance checklists; local counsel |
| Accessibility lawsuit (ADA) | Medium | Medium-High | Proactive WAV partnerships; accessible app development; disability advocacy partnerships |
| Background check FCRA violation | Low-Medium | Medium | Use established CRA; train staff on adverse action procedures |
| Tax reporting errors (1099) | Low | Medium | Automated reporting systems; annual audit |
| New regulation makes operations unviable in a market | Low | High | Diversified market portfolio; regulatory monitoring; lobby through cooperative associations |
| Worker classification challenge from a member | Low | High | Clear bylaws; genuine member governance; legal review |

---

## Appendix A: Key Regulatory Bodies by State

| State | Primary TNC Regulator | Website |
|---|---|---|
| California | CPUC | cpuc.ca.gov |
| New York | DMV / TLC (NYC) | nyc.gov/tlc |
| Texas | TDLR | tdlr.texas.gov |
| Florida | FLHSMV | flhsmv.gov |
| Illinois | ICC | icc.illinois.gov |
| Pennsylvania | PUC | puc.pa.gov |
| Washington | UTC | utc.wa.gov |
| Oregon | ODOT | oregon.gov/odot |
| Colorado | PUC | puc.state.co.us |
| Massachusetts | DPU | mass.gov/dpu |
| Ohio | PUCO | puco.ohio.gov |
| Georgia | PSC | psc.ga.gov |
| Virginia | DMV | dmv.virginia.gov |
| Nevada | NTA | nta.nv.gov [VERIFY] |
| Arizona | ADOT [VERIFY] | azdot.gov |

## Appendix B: Key Federal Statutes and Regulations

| Statute | Relevance |
|---|---|
| Americans with Disabilities Act (42 U.S.C. 12101 et seq.) | Accessibility requirements |
| Fair Credit Reporting Act (15 U.S.C. 1681) | Background check procedures |
| FTC Act Section 5 (15 U.S.C. 45) | Unfair/deceptive practices |
| Internal Revenue Code Subchapter T (26 U.S.C. 1381-1388) | Cooperative taxation |
| Liability Risk Retention Act (15 U.S.C. 3901-3906) | Cooperative insurance options |
| CCPA/CPRA (Cal. Civ. Code 1798.100 et seq.) | California data privacy |
| BIPA (740 ILCS 14) | Illinois biometric privacy |
| California AB 5 / Prop 22 | Worker classification |

## Appendix C: Estimated First-Year Compliance Costs (Single Market)

| Category | Low Estimate | High Estimate |
|---|---|---|
| State TNC license/permit | $1,000 | $100,000 |
| City permit (if applicable) | $0 | $25,000 |
| Insurance (100 drivers) | $200,000 | $500,000 |
| Legal (regulatory + cooperative) | $50,000 | $150,000 |
| Background check infrastructure | $10,000 | $30,000 |
| Background checks (per driver, ~$30-80 each) | $3,000 | $8,000 |
| Vehicle inspections | $5,000 | $15,000 |
| Privacy compliance (tooling, policy drafting) | $15,000 | $50,000 |
| Accessibility (WAV partnerships, app audit) | $20,000 | $75,000 |
| Tax/accounting setup | $10,000 | $25,000 |
| Airport permits | $5,000 | $20,000 |
| **Total** | **$319,000** | **$998,000** |

[VERIFY — all cost estimates should be validated with current market quotes before budgeting]

---

## Document Notes

This research document is based on the regulatory landscape as understood through mid-2025 training data. The TNC regulatory environment changes frequently — states amend their TNC laws, cities adjust per-trip fees, and court decisions alter the compliance landscape.

**Before relying on this document for operational decisions**:
1. Validate all [VERIFY] items with current sources
2. Engage licensed attorneys in each target market
3. Contact each relevant regulatory body directly for current requirements
4. Review any legislation enacted between mid-2025 and the date of implementation
5. Obtain actual insurance quotes from transportation-specialist brokers
6. Consult with cooperative development organizations (NCBA CLUSA, Democracy at Work Institute, US Federation of Worker Cooperatives)

**Recommended Legal Resources**:
- National Cooperative Business Association (NCBA CLUSA)
- US Federation of Worker Cooperatives
- Transportation regulatory attorneys (jurisdiction-specific)
- Cooperative development centers (state-level; USDA maintains a directory)

---

*This document was prepared as research for the open-source cooperative rideshare project. It is not legal advice and should not be treated as a substitute for consultation with qualified legal counsel.*
