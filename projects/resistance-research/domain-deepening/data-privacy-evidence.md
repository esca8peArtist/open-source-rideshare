# Data Privacy and Digital Surveillance — Evidence Deepening

*Prepared April 2026. Supplements Domain 21: Data Privacy and Digital Surveillance in the Democratic Renewal Proposal. Does not restate the reform architecture — deepens the evidentiary foundation with specific data, contested findings, international benchmarks, and fiscal analysis. Read alongside the proposal, not instead of it.*

---

## Gaps This Document Fills

Domain 21 correctly identifies the commercial surveillance ecosystem, the Section 702 warrant gap, facial recognition bias and wrongful arrest risk, the ADPPA's failure, and chilling effects on democratic participation as the core structural problems. What it is thinner on:

- The precise architecture of the real-time bidding (RTB) ecosystem — how location data travels from a smartphone ad impression to a federal agency without a single warrant, and which documented enforcement actions have mapped this pipeline
- The data broker industry's ownership concentration — not a list of company names but the consolidation logic: which parent corporations own the largest brokers, what specific data categories sell for, and the documented pricing of voter data, medical inference data, and financial distress signals from FTC cases and Senate investigations
- The FISA Court's near-perfect approval record and the PCLOB's structural dysfunction, now compounded by the January 2025 firing of three members, which has left the board non-operational
- NIST FRVT error rates by demographic group in precise numbers, not just direction; the false-positive differential reaching a factor of 7,203 for some algorithm-demographic combinations
- The wrongful arrest cases in operational detail — what specific investigative steps were and were not taken in the Robert Williams and Porcha Woodson cases — to distinguish system failure from procedural failure
- The state privacy law proliferation's structural incoherence — which states have private rights of action, which use opt-in vs. opt-out frameworks, and where the industry preemption strategy has succeeded in weakening federal legislation
- GDPR enforcement in full quantitative terms: €5.88 billion in total fines since 2018, the Ireland DPC's €3.5 billion dominance, and what the EU AI Act's February 2025 enforcement trigger means for biometric surveillance specifically
- The surveillance chilling effect literature with methodological precision — Penney's Wikipedia study design, its limitations, and the 2022–2025 replication and extension literature
- The enforcement gap: fewer than 50 FTC staff on privacy versus Ireland's 280-person DPC and France's 298-person CNIL, and what a Federal Data Protection Agency would need to reach functional parity

---

## Executive Overview

The United States maintains the world's most developed commercial surveillance infrastructure with the least corresponding legal constraint. A single smartphone generates location signals that travel through a real-time bidding auction occurring 294 billion times daily in the United States alone, producing data streams accessible to any actor posing as an ad buyer — including federal agencies purchasing without warrants through commercial intermediaries. The government surveillance layer sits atop this commercial substrate: Section 702, reauthorized through April 2026 but not reformed to require warrants for queries of US person data, collected communications from over a dozen major technology companies under PRISM and upstream programs; the FISA Court approved 99.97% of applications in its first 33 years of operation; and the PCLOB, the only independent civilian oversight body for intelligence surveillance, was rendered non-operational in January 2025 when the Trump administration fired three of its five members. Facial recognition deployed by 3,100-plus law enforcement agencies produces false positives at rates up to 7,203 times higher for Black women than for white men on the same algorithms — a disparity documented through four publicly confirmed wrongful arrests in Detroit alone. The aggregate effect — measured empirically in Wikipedia traffic studies, PEN America surveys, and self-reported attorney-client privilege concerns — is a documented erosion of the behavior that democratic participation requires: the willingness to seek information, associate with others, speak freely, and organize collectively. This document provides the granular evidentiary foundation for each reform area.

---

## Section 1: Commercial Surveillance Ecosystem

### 1.1 Market Structure and Ownership Concentration

The data broker industry reported a global market size of approximately **$277.97 billion in 2024** and is projected to reach $512 billion by 2033 at a 7.3% compound annual growth rate, according to Grand View Research. The $350 billion figure cited in the proposal reflects some projections extrapolating to the broader surveillance-enabled advertising economy; the narrower data resale market is documented at $278 billion. The industry presents the appearance of fragmentation — estimates place the number of data brokers globally at up to 5,000 — but beneficial ownership analysis reveals significant consolidation among the firms that hold the highest-value databases.

The top tier is structured around a small number of parent corporations that have acquired multiple broker entities over the past decade. **Experian PLC** (Irish-domiciled, FTSE 100) controls one of the three largest credit-referencing databases alongside its marketing data subsidiary, holding profiles on approximately 235 million US consumers. **Publicis Groupe** acquired **Epsilon Data Management** in 2019 for $4.4 billion — the second-largest deal in advertising history at that time — giving the French advertising conglomerate direct access to Epsilon's 250 million US consumer profiles and 7,000 proprietary audience segments. **Oracle** acquired multiple data broker entities through its Oracle Data Cloud division, including Datalogix, AddThis, and Crosswise, assembling a first- and third-party data network before divesting the advertising data business to a private equity group in 2022. **LiveRamp Holdings** (formerly Acxiom) manages the largest commercially available offline-to-online identity resolution infrastructure in the United States, linking browser cookies, device identifiers, email addresses, and physical addresses to enable advertisers to reach specific individuals across platforms without the individuals' awareness. The pattern: credit bureau infrastructure, advertising conglomerate ownership, and enterprise software companies each control a node of the surveillance pipeline, and their data assets are routinely licensed to one another.

A Senate Commerce Committee investigation published in December 2022 documented specific data category pricing that illustrates the granularity of available product. Location data providing a week's worth of movement history for visits to more than 600 Planned Parenthood locations was available for purchase from **SafeGraph** for just over **$160**, as documented by Vice/Motherboard in May 2022. The same investigation found that data on people's visits to addiction recovery centers, domestic violence shelters, and mental health facilities was available without restriction. **Acxiom** maintains product categories including "Alcoholic Beverages — Heavy Users," "Gambling — Casino," and "Smoker in Household." Multiple brokers sell lists inferring or directly reporting on **financial distress signals** — bankruptcy filings, credit score ranges, "financially stressed" household flags — that are used in both commercial targeting and, as documented by CFPB, potentially in predatory financial product marketing. Voter registration data, party affiliation, donation history, and precinct-level vote history are available through specialized political data brokers for prices as low as $0.005 per record in bulk — a pricing structure that makes comprehensive national voter targeting datasets accessible to any actor with a few thousand dollars.

Sources: [Grand View Research: Data Broker Market 2033](https://www.grandviewresearch.com/industry-analysis/data-broker-market-report); [Publicis Epsilon Acquisition (AdAge 2019)](https://adage.com/article/digital/publicis-closes-4-billion-epsilon-deal/2173501); [Vice: SafeGraph Selling Abortion Clinic Location Data](https://www.vice.com/en/article/location-data-abortion-clinics-safegraph-planned-parenthood/); [Senate Commerce Committee Data Broker Investigation (December 2022)](https://www.warren.senate.gov/imo/media/doc/2022.05.17%20Letters%20to%20Safegraph%20and%20Placer.ai%20re%20Abortion%20Clinic%20Data.pdf)

---

### 1.2 Real-Time Bidding: The Architecture of the Surveillance Pipeline

Real-time bidding is the mechanism through which the internet's advertising revenue model doubles as a mass surveillance system. Understanding RTB architecture is essential for reform design because it explains how data moves from a consumer's device to government agencies, data brokers, and foreign intelligence services without triggering any of the legal constraints that govern direct data collection.

When a user loads a webpage or opens an app that carries programmatic advertising, the publisher's **supply-side platform (SSP)** initiates an auction lasting approximately 100 milliseconds. The SSP transmits a **bid request** to hundreds of **demand-side platforms (DSPs)** representing advertisers. That bid request contains a data package describing the user: device identifier, IP address, precise GPS coordinates, inferred age and gender, browsing history segments, and — critically — any third-party audience segments the SSP has licensed from **data management platforms (DMPs)**. Every DSP that receives the bid request receives the full data package whether it wins the auction or not. The FTC's December 2024 enforcement action against **Mobilewalla** documented that this company collected **more than 500 million unique consumer advertising identifiers paired with precise location data** from January 2018 to June 2020, not by selling advertising but by participating in RTB auctions solely to harvest the bid-stream data.

The Irish Council for Civil Liberties estimated in its 2022 report that RTB exposes user data **294 billion times per day in the United States and 197 billion times per day in Europe**. The ICCL characterized this as "the biggest data breach ever recorded" — not a hack but the designed function of the system. The US Senate Select Committee on Intelligence received classified testimony in 2021 that RTB bid-stream data was being accessed by foreign intelligence services, including those of US adversaries, using commercial ad-buying accounts as cover.

**Government access without warrants**: US Customs and Border Protection acknowledged in 2020 that it purchases location data sourced "partially from the [RTB] system powering nearly every ad you see online." CBP paid **Babel Street** more than $2.7 million for an annual subscription to its social media and location tracking tools, plus $265,000 in 2020, according to contract records obtained by BuzzFeed News. The Secret Service purchased app-generated location data from Babel Street using the same mechanism. The DHS OIG's September 2023 investigation found that CBP, ICE, and the Secret Service purchased and used commercial geolocation data in ways that violated internal privacy policies — including employees sharing passwords for tracking databases, supervisors failing to review audit logs, and in one documented instance an employee using the data to track coworkers. In March 2026, more than 70 House and Senate Democrats demanded a new DHS IG investigation after ICE resumed purchasing location data following a brief pause.

Sources: [FTC: Unpacking Real-Time Bidding Through Mobilewalla Case (December 2024)](https://www.ftc.gov/policy/advocacy-research/tech-at-ftc/2024/12/unpacking-real-time-bidding-through-ftcs-case-mobilewalla); [ICCL RTB Report: Google GDPR (TechCrunch 2022)](https://techcrunch.com/2022/05/16/iccl-rtb-report-google-gdpr/); [EFF: Targeted Advertising and Government Location Tracking (March 2026)](https://www.eff.org/deeplinks/2026/03/targeted-advertising-gives-your-location-government-just-ask-cbp); [DHS OIG: CBP, ICE, Secret Service Violated Privacy Policies (EPIC)](https://epic.org/dhs-oig-cbp-ice-and-secret-service-violated-privacy-policies-failed-to-develop-sufficient-policies-before-purchasing-and-using-commercial-geolocation-data/); [70 US Lawmakers Demand Probe into ICE Data Purchases (The Register, March 2026)](https://www.theregister.com/2026/03/03/us_lawmakers_ice_data_purchases/)

---

### 1.3 Data Broker Harm: Documented Cases

The proposal establishes the surveillance ecosystem's scale. The following documented cases ground that scale in concrete harm — which is necessary for legislative framing because abstract privacy violations are politically easier to dismiss than specific injury patterns.

**Stalking and physical violence.** The 2020 murder of US District Judge Esther Salas's son, Roy Den Hollander, was facilitated by a lawyer who obtained her home address from a data broker. Den Hollander arrived at her residence disguised as a FedEx driver. This case directly prompted New Jersey's Daniel Anderl Judicial Security and Privacy Act (2021) and subsequent federal judicial privacy protections. The FTC's 2022 case against **Kochava** alleged that the company's location data products enabled identification of individuals who had visited domestic violence shelters, addiction recovery facilities, and reproductive health clinics, with the FTC finding that a Kochava customer had specifically proposed building a **geofence around the homes of individuals involved in a private lawsuit** to track them over multiple years. The FTC's December 2024 actions against **Gravy Analytics (Venntel)** and **Mobilewalla** documented data products enabling stalking of specific individuals from their homes to sensitive locations, with Mobilewalla's raw data "not anonymized" with "no policies to remove sensitive locations."

**Immigration enforcement.** The EPIC analysis "How Data Brokers Harm Immigrants" (2024) documented that commercial location databases are used by ICE to identify, track, and arrest individuals who have not been the subject of any specific investigation — using pattern-of-life analysis rather than individualized suspicion. ICE acknowledged in April 2026 that it is also using commercial spyware, reported by NPR, with implications for monitoring advocacy organizations and legal service providers serving immigrant communities.

**Discriminatory targeting.** The FTC's September 2024 staff report on nine social media and streaming companies found that platforms maintained audience segments including "divorce support" and "beer and spirits," and that data broker information was combined with behavioral tracking to produce targeting categories with explicit discriminatory potential — including financial distress signals used in payday loan and debt-relief advertising that disproportionately reach consumers already in economic distress.

Sources: [FTC v. Kochava (2022)](https://www.ftc.gov/legal-library/browse/cases-proceedings/ftc-v-kochava-inc); [FTC: Order Against Mobilewalla (December 2024)](https://www.ftc.gov/news-events/news/press-releases/2024/12/ftc-takes-action-against-mobilewalla-collecting-selling-sensitive-location-data); [FTC Staff Report: Social Media Surveillance (September 2024)](https://www.ftc.gov/news-events/news/press-releases/2024/09/ftc-staff-report-finds-large-social-media-video-streaming-companies-have-engaged-vast-surveillance); [EPIC: How Data Brokers Harm Immigrants (2024)](https://epic.org/documents/how-data-brokers-harm-immigrants/); [ICE Spyware Acknowledgment (NPR, April 2026)](https://www.npr.org/2026/04/07/nx-s1-5776799/ice-spyware-privacy)

---

### 1.4 Industry Lobbying Against Federal Privacy Legislation

The ADPPA's failure after passing the House Energy and Commerce Committee 53-2 in July 2022 was not attributable to lack of bipartisan support at the committee level. The decisive fights occurred in floor scheduling and in the Senate, where industry lobbying concentrated on two pressure points: the preemption standard and the private right of action.

The US Chamber of Commerce, **TechNet**, **NetChoice**, **SIIA** (Software and Information Industry Association), and the **Interactive Advertising Bureau (IAB)** each lobbied against the ADPPA's enforcement provisions. The core industry preference — documented in lobbying disclosures — was for weak federal preemption (a ceiling, not a floor, on state protections) and against a private right of action. Industry's strategic calculus favored a weak federal law that would preempt California's CCPA/CPRA and eliminate the most aggressive state-level enforcement framework over no law at all. When California Democrats — led by former House Speaker Nancy Pelosi — refused to accept a preemption standard that would weaken California's stronger protections, the bill stalled. Senator Maria Cantwell's primary objection focused on enforcement provisions she considered inadequate.

The successor American Privacy Rights Act (APRA) of 2024 incorporated modifications but also stalled in the 118th Congress. As of April 2026, the 119th Congress has not advanced comprehensive federal privacy legislation, and the current administration's FTC leadership has signaled reduced interest in commercial surveillance enforcement, making the legislative pathway for the proposed Federal Data Protection Agency (FDPA) more difficult but also more necessary.

---

## Section 2: Government Surveillance Architecture

### 2.1 Section 702: Scope, Structure, and the 2024 Reauthorization

Section 702 of FISA authorizes the intelligence community to collect, without individual warrants, the communications of non-US persons located abroad from US-based electronic communications service providers. The program has two primary collection modalities: **PRISM**, which compels major technology companies (including Google, Meta, Microsoft, Apple, Yahoo, Dropbox, and others as documented by Edward Snowden's 2013 disclosures) to provide content of specified foreign targets; and **upstream collection**, which taps internet backbone infrastructure to collect communications in transit.

The documented scope is significant. NSA transparency reports published for FY 2022 reported that the US intelligence community queried Section 702 data using US person identifiers approximately **204,090 times** — a figure that refers only to FBI queries and does not include NSA and CIA queries, which are reported through a separate counting methodology. The 2021 FISA Court opinion declassified in 2022 found that the FBI had conducted queries that included the names of suspects from the **January 6, 2021 insurrection** and people **protesting the killing of George Floyd** — using foreign intelligence collection authority as a domestic investigation tool.

Congress reauthorized Section 702 on **April 20, 2024** through the Reforming Intelligence and Securing America Act (RISAA), extending the program for **two years**, meaning it will sunset on **April 20, 2026** absent further action. The Senate approved the bill 60–34. An amendment that would have required a warrant before querying US person data was **narrowly defeated in the House** — the reform that civil liberties organizations identified as the minimum necessary to address the documented misuse. The reauthorization added notification requirements and some logging improvements but did not impose the warrant requirement. A March 2025 FISC opinion found that FBI noncompliant querying had decreased; an October 2025 DOJ IG report confirmed that "widespread noncompliant querying of U.S. persons" was no longer occurring — a genuine improvement, but one that depends on the executive branch's continued internal compliance rather than judicial authorization.

A critical point for reform framing: Section 702 is one layer of a three-layer structure. **Executive Order 12333** authorizes collection of foreign intelligence outside FISA's framework, with no court oversight, no congressional authorization requirement, and classified implementing procedures. EO 12333 governs NSA collection from undersea cables and foreign networks, CIA collection, and signals intelligence operations that never touch US person data directly but whose products are routinely combined with Section 702 collection in finished intelligence reports. The existence of EO 12333 means that reforming Section 702 addresses a significant but not complete slice of the warrantless surveillance architecture.

EO 12333 is constitutionally distinct from FISA in a way that makes its reform more difficult: it derives from the President's Article II commander-in-chief authority to conduct foreign intelligence activities, which courts have generally treated as a non-justiciable political question. Congress cannot amend EO 12333 by statute without confronting the separation of powers question; it can restrict funding for activities it deems unauthorized, but the executive branch's view of inherent Article II surveillance authority has consistently exceeded Congress's willingness to push back. The **third layer** — the commercial data broker purchase mechanism documented in Sections 1.2 and 2.1 — is, paradoxically, the easiest to reform legislatively: it requires only a statute prohibiting federal agencies from purchasing data they could not obtain through legal process, without raising any Article II authority questions. This "data broker loophole" closure is the reform with the clearest constitutional pathway and the least intelligence community resistance, because it addresses commercial purchases rather than collection programs. As of April 2026, Section 702 faces its second consecutive sunset with no warrant requirement enacted; EO 12333 remains entirely unreformed; and the data broker loophole, which the Biden FTC moved to close through rulemaking, is at risk of administrative reversal.

Sources: [FISA Section 702 and RISAA (Congress.gov CRS)](https://www.congress.gov/crs-product/R48592); [Senate Passes FISA 702 Reauthorization (NPR, April 2024)](https://www.npr.org/2024/04/20/1246076114/senate-passes-reauthorization-surveillance-program-fisa); [EFF: Senate Renews and Expands FISA 702 (April 2024)](https://www.eff.org/deeplinks/2024/04/us-senate-and-biden-administration-shamefully-renew-and-expand-fisa-section-702-0); [NSA Surveillance and Section 702: 2024 in Review (EFF)](https://www.eff.org/deeplinks/2024/11/nsa-surveillance-and-section-702-fisa-2024-year-review); [State of Surveillance: Section 702 and the 2025 Fight](https://stateofsurveillance.org/articles/government/section-702-fisa-renewal-privacy-fight-2025/); [Data Broker Loophole (State of Surveillance 2026)](https://stateofsurveillance.org/news/data-broker-loophole-explainer-government-purchases-your-data-2026/)

---

### 2.2 The FISA Court's Structural Deficiency

The Foreign Intelligence Surveillance Court has operated since 1979. Through 2012 — its first 33 years — federal agencies submitted 33,900 applications. The court **denied eleven** and granted the rest: a **99.97% approval rate**. The court modified an additional 504 applications with substantive changes. To the extent the modifications matter, former Chief Judge Reggie Walton indicated in a 2013 letter to Congress that more than **24% of applications received "substantive" modifications** — suggesting the review is not purely perfunctory, but the near-total absence of outright denial does not reflect adversarial review in any meaningful sense.

The structural problem is design, not competence. The FISC operates as an **ex parte court**: only the government appears. No advocate argues for the target, no public interest attorney appears, and until 2015 (USA FREEDOM Act), there was no amicus curiae mechanism to present contrary legal arguments. The court's legal reasoning, which established binding precedent for the intelligence community, was entirely classified and therefore subject to no external review until declassification. This architecture produces what legal scholars have termed "secret law" — binding interpretations of statutes and constitutional rights that citizens cannot read, challenge, or appeal.

The one structural improvement enacted in recent years — the amicus curiae provision — has operated with limited effect. The court may, but is not required to, appoint an amicus in cases involving "novel or significant" legal interpretations. Between 2015 and 2022, the court appointed amici in only a fraction of its proceedings.

Sources: [EPIC: Foreign Intelligence Surveillance Court Statistics 1979-2022](https://epic.org/foreign-intelligence-surveillance-court-fisc/fisa-stats/); [Stanford Law Review: Is the FISC Really a Rubber Stamp?](https://www.stanfordlawreview.org/online/is-the-foreign-intelligence-surveillance-court-really-a-rubber-stamp/); [CSIS Fact Sheet: FISA Court](https://www.csis.org/analysis/fact-sheet-foreign-intelligence-surveillance-court)

---

### 2.3 PCLOB: Structural Dysfunction and the January 2025 Firing

The Privacy and Civil Liberties Oversight Board was created by the 9/11 Commission recommendations and established by the Intelligence Reform and Terrorism Prevention Act of 2004. Its structure — a five-member bipartisan board requiring Senate confirmation, with authority to review surveillance programs and access classified information — was designed to provide the civilian oversight that no other institution could provide for classified intelligence activities.

The board has operated with chronic vacancy problems throughout its existence. The five-member board requires a **quorum of three** to commence investigations and issue reports. From its creation in 2004 through its reconstitution in 2012, the board was largely non-functional due to vacancies and the White House's resistance to independent appointments. After the Snowden disclosures in 2013, it issued two significant reports — a 2014 analysis concluding that the Section 215 bulk phone metadata program was illegal and should be terminated, and a 2014 analysis of Section 702 — before returning to partial vacancy states.

The board's current situation represents its most severe dysfunction. On **January 27, 2025**, the Trump administration dismissed three Democratic members — Edward Felten, Travis LeBlanc, and Jennifer Das — leaving the board with **one active member** (Republican appointee Beth Williams) and **no quorum**. The board cannot conduct investigations, issue reports, or exercise any of its oversight functions. This single executive action has effectively ended civilian oversight of the intelligence community's surveillance programs for an indefinite period.

The international consequence is significant: the PCLOB's operation was a key mechanism cited by the European Court of Justice in accepting the EU-US Data Privacy Framework (July 2023) as providing adequate remediation for European persons' data transferred to the United States. The board's non-operational status raises questions about the DPF's continued adequacy determination.

Sources: [Watching the Watchers: Future of PCLOB (TechPolicy.Press)](https://www.techpolicy.press/watching-the-watchers-the-future-of-the-privacy-and-civil-liberties-oversight-board/); [Trump's Sacking of PCLOB Members (Lawfare)](https://www.lawfaremedia.org/article/trump-s-sacking-of-pclob-members-threatens-data-privacy); [PCLOB Firings and EU-US Data Privacy Framework (CDT)](https://cdt.org/insights/what-the-pclob-firings-mean-for-the-eu-us-data-privacy-framework/); [Brookings: Dismantling PCLOB Threatens Privacy and National Security](https://www.brookings.edu/articles/why-dismantling-the-pclob-and-csrb-threatens-privacy-and-national-security/)

---

### 2.4 Fusion Centers, JTTFs, and Protest Surveillance

The United States maintains approximately **80 fusion centers** — state and regional intelligence-sharing hubs funded jointly by DHS and state governments — established after 9/11 to improve information sharing between federal, state, and local law enforcement. A 2012 Senate Permanent Subcommittee on Investigations report found that fusion centers produced "predominantly useless information" and "a bunch of police-blotter-type data," while simultaneously raising civil liberties concerns about First Amendment-protected activities being characterized as terrorism threats.

The 2020 Black Lives Matter protests documented the fusion center and JTTF architecture's application to constitutionally protected political activity. A DHS report released in 2022 found that during the 2020 racial justice protests in Portland, DHS developed **dossiers on protesters arrested for trivial infractions having little or no connection to domestic terrorism**. The Department of Homeland Security deployed drones, planes, and helicopters to surveil protesters in at least **15 cities**, logging at least **270 hours of aerial surveillance footage** over racial justice protests in the spring and summer of 2020. California's Highway Patrol conducted aerial surveillance of George Floyd protests in at least **25 cities**, recording images usable for facial identification. Twitter contracted with **Dataminr** — a company with a special API relationship with Twitter — to provide law enforcement with real-time monitoring of protest-related tweets before Twitter's terms of service nominally prohibited this use.

The **Joint Terrorism Task Force (JTTF)** structure — FBI-led joint units operating in 56 field offices with participation from approximately 500 federal, state, and local agencies — has a documented history of targeting First Amendment-protected political activity. A 2023 Democracy Now/podcast investigation documented that in the Denver JTTF's response to 2020 racial justice protests, an informant was paid at least **$20,000** to infiltrate activist organizations, was used to encourage activists to purchase weapons, and employed "snitch-jacketing" tactics to accuse legitimate organizers of being informants — an exact replica of COINTELPRO methodology. The FBI's 2017 "Black Identity Extremist" threat category, created amid BLM protests following police killings, echoed the FBI's COINTELPRO-era characterization of civil rights organizations as national security threats.

Sources: [ACLU: Government Aerial Surveillance of Protesters](https://www.aclu.org/news/national-security/aclu-seeks-information-on-governments-aerial-surveillance-of-protesters); [ACLU v. DOJ FOIA Lawsuit on JTTF Protest Surveillance](https://www.aclu.org/cases/aclu-v-doj-foia-lawsuit-seeking-records-about-the-use-of-jttfs-and-fusion-centers-to-target-protesters-and-communities-of-color); [The Intercept: Dataminr Helped Police Surveil BLM Protests (2020)](https://theintercept.com/2020/07/09/twitter-dataminr-police-spy-surveillance-black-lives-matter-protests/); [Democracy Now: COINTELPRO 2.0, FBI Infiltration of BLM (2023)](https://www.democracynow.org/2023/2/7/alphabet_boys_podcast_fbi_subterfuge)

---

## Section 3: Facial Recognition — Deployment and Harms

### 3.1 NIST FRVT Error Rates in Precise Terms

The proposal cites the GAO finding that error rates are 10–100x higher for Black faces. The NIST Face Recognition Vendor Test (FRVT) results are more granular and more alarming than this summary suggests, and the methodological details matter for policy design.

NISTIR 8280 (December 2019, the primary demographic effects report) evaluated 189 facial recognition algorithms submitted voluntarily by vendors, testing them against four datasets including visa photos, law enforcement mugshots, and border crossing images. The **one-to-many matching** scenario — where an algorithm searches a database to find who matches a probe image — is the operationally relevant scenario for law enforcement use and produces the most consequential errors.

The key findings:

- **False positive rates for one-to-many matching were highest for African American females** across the majority of algorithms tested. The false positive differential between the best-performing demographic (often Asian males or white males, depending on dataset) and Black females varied by algorithm, with some algorithms producing **false positives at rates 10 to 100 times higher** for Black women than for white men.
- The NIST report documented that **within-group false positive rates varied by up to a factor of 7,203** across demographic groups — meaning the worst-performing algorithm on the worst-performing demographic group had false positive rates more than seven thousand times higher than the same algorithm on its best-performing demographic group.
- The disparities were found **even in pristine studio-quality images**, not just degraded surveillance footage, indicating that the bias is structural to the algorithm rather than solely an artifact of image quality differences between demographic groups.

The NIST FRVT Part 8 report (NISTIR 8429, 2022 interim) extended findings to include age and sex intersections, confirming that the demographic disparity pattern persists across newer algorithm generations, though top-performing algorithms have reduced the absolute gap. The critical point: **agencies select algorithms based on performance metrics that may not report demographic disaggregation**, meaning an algorithm advertised as "99.9% accurate" may achieve that accuracy rate on a whitened test set while producing dramatically higher error rates on darker-skinned subjects.

The ITIF's 2020 counterargument — "the best facial recognition algorithms are neither racist nor sexist" — cherry-picks the highest-performing algorithms on specific datasets. NIST's own response to this framing noted that the majority of algorithms deployed by law enforcement agencies are not the top performers on NIST's leaderboard, and that the NIST evaluation was voluntary, meaning some vendors with worse performance characteristics did not submit.

Sources: [NISTIR 8280: FRVT Part 3 Demographic Effects (December 2019)](https://nvlpubs.nist.gov/nistpubs/ir/2019/NIST.IR.8280.pdf); [NISTIR 8429: FRVT Part 8 (2022)](https://pages.nist.gov/frvt/reports/demographics/nistir_8429.pdf); [NIST: Study Evaluates Effects of Race, Age, Sex on Face Recognition](https://www.nist.gov/news-events/news/2019/12/nist-study-evaluates-effects-race-age-sex-face-recognition-software); [Scientific American: How NIST Tested Facial Recognition for Racial Bias](https://www.scientificamerican.com/article/how-nist-tested-facial-recognition-algorithms-for-racial-bias/)

---

### 3.2 Wrongful Arrest Cases: Operational Failure Analysis

Four publicly confirmed wrongful arrests by the Detroit Police Department based on facial recognition misidentification are not four independent data points — they are a pattern from a single agency, and the pattern reveals what the absence of use regulation produces in practice.

**Robert Williams (January 2020).** In 2018, a man stole watches from a Shinola store in Detroit. Officers ran facial recognition on a blurry, low-quality surveillance still. The algorithm returned a match to Williams's expired driver's license photo. Williams was arrested at his home in front of his wife and two young daughters, held for 30 hours, and interrogated before charges were dropped. The ACLU's subsequent investigation found that the officer accepted the algorithm's output without independent corroboration — Williams was plainly not the individual in the surveillance footage, a fact apparent to any observer examining both images simultaneously. Williams v. City of Detroit settled in June 2024; the settlement amount was not disclosed but the case produced the **first publicly confirmed wrongful arrest from facial recognition in the United States**.

**Porcha Woodson (January 2023).** Woodson, a 32-year-old Black woman who was **eight months pregnant** at the time, was arrested for a January 2023 carjacking and robbery she did not commit. She was detained for hours before charges were dropped. Detroit Police acknowledged the arrest was based on a facial recognition match. Woodson's case is the third confirmed wrongful arrest at DPD based on flawed facial recognition — the second and third (before Woodson) involved Michael Oliver and Randal Reid, both Black men arrested in cases where facial recognition produced matches that should have been immediately excluded by any witness description of the actual perpetrator.

In August 2023, following the Woodson case, Detroit Police implemented policy changes: officers are **prohibited from using facial recognition photos in lineups**; a sequential double-blind photo lineup protocol is now required; two captains must review warrant requests when facial recognition is involved. These are meaningful procedural reforms — but they apply only to Detroit. The 3,100-plus agencies using Clearview AI and other systems are subject to no comparable requirement.

**Other documented wrongful arrests**: Nijeer Parks (New Jersey, 2019) spent ten days in jail; Alonzo Sawyer (Maryland, 2023); a New Orleans case reported in 2023 by the New York Times. These cases share a common structure: an algorithm produces a hit; a detective accepts the hit without independent verification; a Black person is arrested. The pattern is not primarily algorithmic failure — it is the absence of any procedural requirement to corroborate a facial recognition match before making an arrest.

Sources: [ACLU: Williams v. City of Detroit](https://www.aclu.org/cases/williams-v-city-of-detroit-face-recognition-false-arrest); [Wrongful Facial Recognition Arrest Leads to Landmark Settlement (Michigan Public, June 2024)](https://www.michiganpublic.org/criminal-justice-legal-system/2024-06-28/it-didnt-make-sense-at-all-wrongful-facial-recognition-arrest-leads-to-landmark-settlement); [ACLU Michigan: DPD and Facial Recognition (2023)](https://www.aclumich.org/en/press-releases/aclu-calls-detroit-police-department-end-use-faulty-facial-recognition-technology); [Facial Recognition in Policing: State-by-State Guardrails (Stateline, February 2025)](https://stateline.org/2025/02/04/facial-recognition-in-policing-is-getting-state-by-state-guardrails/)

---

### 3.3 Clearview AI: Litigation Status and Jurisdictional Actions

The Clearview AI BIPA class action was one of the most significant US biometric privacy cases in the past decade. After five years of litigation, a **nationwide class-action settlement was approved** by US District Judge Sharon Johnson Coleman on **March 20, 2025**. The settlement's structure was unprecedented: rather than cash, class members received a **23% equity stake in Clearview AI**, valued at approximately **$51.75 million** based on Clearview's January 2024 valuation of $225 million. The equity payment triggers on a liquidity event — IPO, merger, or acquisition.

Separately, the **ACLU of Illinois** reached a settlement in 2022 under which Clearview AI is **permanently banned nationwide** from making its faceprint database available to most businesses and private entities, and **banned from selling access to law enforcement agencies in Illinois** for five years. This effectively implements a partial moratorium in Clearview's highest-risk state, leveraging the Illinois BIPA's private right of action — the strongest biometric privacy statute in the country.

Internationally, Clearview AI has been banned or fined by data protection authorities in **France, Italy, Greece, Germany, and Australia**. The UK Information Commissioner's Office fined Clearview £7.5 million in 2022 and ordered deletion of UK residents' biometric data. These international enforcement actions underscore both the legal vulnerability of Clearview's data collection methodology under rights-of-consent frameworks and the absence of equivalent US federal law to produce comparable results.

**DHS Biometric Expansion (October 2025)**: A final rule published October 27, 2025, authorizes CBP to collect facial biometrics from **all noncitizens** upon entry and exit at airports, seaports, and land ports of entry. Photos of non-citizens are retained in DHS's central biometric database for up to **75 years**. US citizens may opt out. The program is expected to reach all major airports and seaports within three to five years. The underlying legal authority is Title 8 authority over border screening — no FISA warrant, no judicial authorization for individual entries into the biometric record.

Sources: [Clearview AI $51.75M Settlement Approved (Regulatory Oversight, April 2025)](https://www.regulatoryoversight.com/2025/04/51-75m-settlement-in-clearview-ai-biometric-privacy-litigation-illustrates-creative-resolution-for-startups-facing-parallel-litigation-and-enforcement-action/); [ACLU: Clearview Illinois Settlement (2022)](https://www.aclu.org/press-releases/big-win-settlement-ensures-clearview-ai-complies-with-groundbreaking-illinois-biometric-privacy-law); [DHS Final Rule: Biometric Entry/Exit Program (CBP, October 2025)](https://www.cbp.gov/newsroom/national-media-release/dhs-announces-final-rule-advance-biometric-entry/exit-program); [DHS Expands Mandatory Facial Biometrics (HSToday)](https://www.hstoday.us/subject-matter-areas/border-security/dhs-final-rule-expands-cbps-facial-biometric-entry-exit-program-to-all-foreign-travelers/)

---

## Section 4: State Privacy Law Analysis

### 4.1 The Architecture of State Law Proliferation

As of April 2026, **nineteen states** have enacted comprehensive consumer privacy laws, with additional states having passed sector-specific legislation. The proliferation creates a patchwork that is systematically less protective than it appears — because the most important structural variables vary by state in ways that determine whether the law functions in practice.

The three variables that determine a state privacy law's operational strength are: (1) whether it includes a private right of action; (2) whether it requires opt-in or opt-out consent for sensitive data processing; and (3) whether it has a sufficiently resourced enforcement mechanism.

| State | Law | Effective | Private Right of Action | Consent Model (Sensitive Data) | Enforcement |
|---|---|---|---|---|---|
| California | CCPA/CPRA | 2020/2023 | Limited (data breach only) | Opt-out (general); opt-in (minors) | CPPA (dedicated agency) |
| Virginia | VCDPA | 2023 | None | Opt-in (sensitive) | AG only |
| Colorado | CPA | 2023 | None | Opt-in (sensitive) | AG only |
| Connecticut | CTDPA | 2023 | None | Opt-in (sensitive) | AG only |
| Texas | TDPSA | 2024 | None | Opt-in (sensitive) | AG only |
| Montana | MCDPA | 2024 | None | Opt-in (sensitive) | AG only |
| Oregon | OCPA | 2024 | None | Opt-in (sensitive) | AG only |
| Indiana | IDPSA | 2026 | None | Opt-in (sensitive) | AG only |
| Tennessee | TIPA | 2025 | None | Opt-in (sensitive) | AG only |
| Delaware | DPDPA | 2025 | None | Opt-in (sensitive) | AG only |

**California CPPA** is the single state with a dedicated, independently funded enforcement agency — the California Privacy Protection Agency, modeled loosely on European data protection authorities. All other states rely on the state attorney general, who must compete for enforcement resources with antitrust, fraud, and consumer protection priorities.

**The private right of action gap**: California's CCPA includes a limited private right of action for data breach incidents only. No other comprehensive state privacy law provides individuals with the right to sue for privacy violations directly. This means that in 18 of 19 states with privacy laws, enforcement depends entirely on the AG's willingness and capacity to bring cases. Illinois is the critical exception: the **Biometric Information Privacy Act (BIPA)**, a sector-specific law, includes a full private right of action with statutory damages of $1,000–$5,000 per violation. This is why virtually all major biometric surveillance litigation — including the Clearview AI BIPA case — has been brought under Illinois law, and why the biometrics industry's most intense lobbying has focused on retroactively narrowing BIPA.

**The government surveillance gap**: An underappreciated structural problem is that virtually no state comprehensive privacy law regulates **government data collection**. These laws govern commercial actors — companies subject to the law's jurisdiction. State law enforcement, state fusion centers, state AG offices, and state benefits agencies are explicitly or effectively excluded. The surveillance that citizens most fear — police facial recognition, fusion center dossier building, benefit agency data matching — is unaddressed by the state privacy law proliferation.

Sources: [US State Privacy Laws Comparison (Recording Law 2026)](https://www.recordinglaw.com/us-laws/data-privacy-laws/us-state-privacy-laws-comparison/); [IAPP: US State Privacy Laws Overview (2025)](https://iapp.org/resources/article/us-state-privacy-laws-overview); [Troutman: US State Privacy Laws Comparison](https://www.troutman.com/insights/us-state-privacy-laws-california-colorado-connecticut-delaware-indiana-iowa-montana-oregon-tennessee-texas-utah-virginia/)

---

### 4.2 The Industry Preemption Strategy

The data broker and ad tech industry's preferred federal privacy legislation has consistently had one structural priority: preemption of state law at the ceiling rather than the floor. A floor-preemption standard (states may exceed federal minimums) preserves California's CPPA as a de facto national enforcement mechanism for companies that do business with California consumers — which is nearly all major companies. A ceiling-preemption standard (states may not exceed federal requirements) neutralizes CPPA, BIPA, and any future state innovations.

The ADPPA as passed by committee included a ceiling-preemption provision with narrow carve-outs for existing sector-specific statutes. California's delegation opposed this on the grounds that it would reduce protections for 40 million Californians. The APRA of 2024 attempted to address this with modified carve-outs for BIPA and CCPA, but the compromise did not satisfy either California Democrats or the industry's preference for complete preemption. The resulting legislative paralysis has left the industry subject to the patchwork it claims to find burdensome — the optimal outcome being a weak federal law that preempts strong states.

The CFPB under the Biden administration's last months proposed a rule (December 2024) to restrict data brokers' sale of sensitive personal data by extending Fair Credit Reporting Act obligations to additional data uses — an administrative workaround that did not require congressional action. The Trump administration's CFPB has signaled it will not finalize this rule.

Sources: [CFPB: Proposed Rule on Data Broker Practices (December 2024)](https://files.consumerfinance.gov/f/documents/cfpb_nprm-protecting-ams-from-harmful-data-broker-practices_2024-12.pdf); [American Privacy Rights Act Analysis (StateScoop)](https://statescoop.com/american-privacy-rights-act-state-laws-data/); [ADPPA Overview (Harvard JOLT)](https://jolt.law.harvard.edu/digest/american-data-privacy-and-protection-act-latest-closest-yet-still-fragile-attempt-toward-comprehensive-federal-privacy-legislation)

---

## Section 5: GDPR Outcomes and International Models

### 5.1 GDPR Enforcement: Quantified

The GDPR entered into force in May 2018. Through January 2025, total documented fines across the EU and EEA reached **€5.88 billion**, according to DLA Piper's annual GDPR survey. Calendar year 2024 produced approximately **€1.2 billion in new fines**, with the Irish DPC as the dominant enforcer.

**Ireland's DPC** has issued **€3.5 billion in total fines since 2018** — more than four times the second-placed Luxembourg, which has issued €746 million (largely from the 2021 Amazon €746 million fine). Ireland's dominance reflects the location of most US technology companies' EU headquarters, making the DPC the **lead supervisory authority** for Meta, Google, Apple, LinkedIn, Twitter, and others. This structural concentration of authority in a small national authority with historically under-resourced enforcement staff produced years of delayed investigations, prompting the European Data Protection Board to use its consistency mechanism to force Ireland to conclude Meta investigations. The resulting fines have been substantial:

- **Meta: €1.2 billion (May 2023)** — for unlawful transfers of EU user data to the United States under Standard Contractual Clauses before the EU-US Data Privacy Framework was established. The largest single GDPR fine in history.
- **Meta: €390 million (January 2023)** — for unlawfully relying on contractual necessity rather than consent to process personal data for behavioral advertising.
- **Meta: €91 million (September 2024)** — for storing user passwords in plaintext.
- **Meta: €251 million (December 2024)** — for a 2018 data breach affecting 29 million user accounts.
- **LinkedIn: €310 million (October 2024)** — for unlawfully processing personal data for behavioral advertising targeting.
- **Amazon: €746 million (Luxembourg, July 2021)** — for advertising targeting without valid consent.

The enforcement trajectory is instructive: the 2023–2024 period represents a significant acceleration in both case conclusions and fine amounts. The GDPR's seven-year ramp from passage to peak enforcement reflects the institutional development time for DPAs to build investigation capacity and legal precedent.

**GDPR and innovation**: The frequently cited claim that GDPR chilled European startup formation is contested. Investment data from NVCA-equivalent European sources shows that European VC investment grew from approximately €23 billion in 2018 to over €100 billion in 2021, the highest growth period in European startup history, occurring during GDPR's first three years. Academic studies on the innovation-privacy relationship (most prominently Janssen et al., 2022) find that while GDPR created compliance costs for small companies, it simultaneously increased consumer trust and created new market opportunities for privacy-protective products. The "GDPR kills innovation" claim is primarily advanced by industry lobbying organizations and does not reflect the empirical European startup trajectory.

Sources: [DLA Piper GDPR Fines Survey January 2025](https://www.dlapiper.com/en/insights/publications/2025/01/dla-piper-gdpr-fines-and-data-breach-survey-january-2025); [Meta Fined Record €1.2 Billion (IAPP, May 2023)](https://iapp.org/news/a/meta-fined-gdpr-record-1-2-billion-euros-in-data-transfer-case); [Ireland DPC Fines Meta €251 Million (December 2024)](https://www.dataprotection.ie/en/news-media/press-releases/irish-data-protection-commission-fines-meta-eu251-million); [Ireland DPC Fines LinkedIn €310 Million (October 2024)](https://www.dataprotection.ie/en/news-media/press-releases/DPC-announces-91-million-fine-of-Meta); [GDPR Fines Summary (DataPrivacyManager.net)](https://dataprivacymanager.net/5-biggest-gdpr-fines-so-far-2020/)

---

### 5.2 EU AI Act: Biometric Surveillance Provisions

The EU AI Act entered into force on **August 1, 2024**. Provisions on prohibited AI practices, including real-time remote biometric identification for law enforcement in public spaces, became enforceable on **February 2, 2025**.

The AI Act's treatment of biometric surveillance is more nuanced than a simple ban and matters for understanding what a viable US reform model might look like. Under Article 5, **real-time remote biometric identification (RBI) systems** deployed in publicly accessible spaces by law enforcement are classified as **prohibited AI practices** — subject to fines of up to **€35 million or 7% of global annual turnover**. However, the prohibition includes exceptions for:

1. Targeted searches for **specific victims of abduction, trafficking, or sexual exploitation**
2. **Imminent terrorist threats** requiring identification of suspects
3. **Prosecution of serious criminal offences** carrying penalties of at least three years of imprisonment

Each use requires prior judicial or independent administrative authorization (with narrow exceptions for imminent threat). Post-hoc RBI (identification from recorded footage) is regulated as a high-risk AI system requiring human oversight, documentation, and registration, but is not prohibited.

The US reform architecture in Domain 21 proposes a moratorium rather than a permanent ban — consistent with the EU model in that it creates a pause for evidentiary development and regulatory framework construction. The AI Act's enforcement for GPAI (general-purpose AI) models takes full effect August 2, 2025, and the full high-risk AI category requirements (including registration, conformity assessments, and human oversight mandates) take effect August 2, 2026.

Sources: [EU AI Act Article 5: Prohibited AI Practices](https://artificialintelligenceact.eu/article/5/); [EU AI Act Implementation Timeline](https://artificialintelligenceact.eu/implementation-timeline/); [IAPP: Biometrics in the EU — GDPR and AI Act](https://iapp.org/news/a/biometrics-in-the-eu-navigating-the-gdpr-ai-act)

---

### 5.3 The Schrems Litigation Arc and Transatlantic Data Transfers

The invalidation of US-EU data transfer frameworks twice in seven years — a pattern driven directly by the surveillance architecture that Domain 21 seeks to reform — is the clearest external documentation that the US surveillance system is legally incompatible with democratic rights standards recognized by peer jurisdictions.

**Schrems I (October 2015)**: Privacy activist Max Schrems filed a complaint with Ireland's Data Protection Commissioner in 2013 following Snowden's disclosure that Facebook had provided NSA access to European users' data under PRISM. The CJEU held in *Maximillian Schrems v. Data Protection Commissioner* that the EU-US Safe Harbor framework — relied upon by approximately 4,500 companies for transatlantic data transfers — failed to provide adequate protection because US national security law permitted access to European data without meaningful legal constraint. Safe Harbor collapsed immediately.

**Privacy Shield (2016–2020)**: The EU and US negotiated the EU-US Privacy Shield framework, which created self-certification requirements and an Ombudsperson mechanism within the State Department. The CJEU invalidated Privacy Shield in **Schrems II** on July 16, 2020, for the same structural reason: Section 702 and Executive Order 12333 permitted US intelligence agencies to collect European persons' data without the oversight or redress mechanisms that the EU Charter requires. The Court specifically named Section 702 of FISA and EO 12333 as the incompatible authorities.

**EU-US Data Privacy Framework (July 2023)**: The Biden administration issued Executive Order 14086 in October 2022, creating a new Signals Intelligence Activities review process — including the PCLOB's role as part of the oversight mechanism — and a Data Protection Review Court within DOJ to adjudicate European complaints about US surveillance. The EU Commission issued an adequacy decision in July 2023 accepting this framework. Max Schrems immediately announced plans to challenge the DPF as Schrems III, arguing the EO's protections are insufficient and that a presidential executive order can be revoked by any subsequent administration.

**The January 2025 PCLOB firings** have materially weakened the DPF's adequacy basis: the oversight mechanism the Commission cited as a key protection for European persons has been rendered non-operational, and the European Parliament's inquiry (Parliamentary Question P-000941/2025) specifically flagged the firings as a potential basis for suspending the adequacy decision. If the CJEU invalidates the DPF — as it invalidated its two predecessors — the transatlantic digital economy worth hundreds of billions of dollars annually in services trade would again lose its legal transfer mechanism.

This is the international consequence that US legislators focused on national competitiveness should understand: failing to reform domestic surveillance creates recurring disruption to transatlantic commercial relationships, not through European regulatory overreach but through US surveillance law that European courts find incompatible with the EU Charter's fundamental rights.

Sources: [Schrems II and Privacy Shield (CookieYes)](https://www.cookieyes.com/blog/schrems-ii-privacy-shield/); [CRS: EU Data Transfer Requirements and US Intelligence Laws (R46724)](https://www.congress.gov/crs-product/R46724); [European Parliament Question on PCLOB Firings (P-000941/2025)](https://www.europarl.europa.eu/doceo/document/P-10-2025-000941_EN.html); [Lawfare: Trump's Sacking of PCLOB Members](https://www.lawfaremedia.org/article/trump-s-sacking-of-pclob-members-threatens-data-privacy)

---

### 5.4 China PIPL and the Comparative Regulatory Landscape

China's **Personal Information Protection Law (PIPL)**, enacted August 2021 and effective November 2021, is worth understanding not as a privacy success story but as evidence of how privacy legislation can be structurally designed to protect government surveillance while providing formal consumer rights protections.

PIPL establishes consent requirements, data minimization obligations, and data subject rights (access, correction, deletion, portability) that are formally similar to GDPR. It includes **extraterritorial reach** for processing of Chinese persons' data by foreign organizations — similar to GDPR Article 3(2). It prohibits personal data from crossing the border without passing a government security assessment, entering a government-certified standard contractual clause regime, or obtaining certification from a designated institution.

The critical structural difference: PIPL explicitly excludes from its coverage data processing by state organs acting under statutory authority. Chinese government surveillance — including the social credit system, mass facial recognition deployment, and political dissident monitoring — operates outside PIPL's framework. This is the inverse of the US problem: the US has extensive commercial data protection gaps alongside insufficient government surveillance constraints; China has formal commercial data protection alongside total exemption for government surveillance. Both systems produce inadequate protection for the data uses that most directly threaten democratic participation. The PIPL comparison is useful in reform framing because it illustrates that a privacy law that covers commercial actors while exempting government surveillance does not protect political freedom — the US state law problem (noted in Section 4.1) replicates this structural error at scale.

Sources: [China PIPL Analysis (IAPP)](https://iapp.org/resources/article/chinas-personal-information-protection-law/); [GDPR Hub: China PIPL](https://gdprhub.eu/index.php?title=China_-_PIPL)

---

### 5.5 UK Post-Brexit Divergence

The United Kingdom retained a domesticated version of GDPR — UK GDPR — at Brexit, maintaining substantive equivalence with EU law sufficient for the European Commission to grant an adequacy decision in June 2021. That adequacy decision runs for four years, expiring in June 2025, subject to review.

The UK government has since pursued a deliberate policy of divergence from EU GDPR, framed as reducing regulatory burden on businesses. The **Data Protection and Digital Information (DPDI) Bill** — which went through multiple iterations from 2022 to 2024 — proposed reducing consent requirements, creating broader legitimate interests exceptions, weakening automated decision-making safeguards, and giving the Secretary of State greater power to override the ICO. The bill was criticized by the ICO itself, which warned that some provisions could undermine the adequacy determination. After falling with the dissolution of Parliament in 2024, the incoming Labour government introduced a revised **Data (Use and Access) Act** that moderated but did not abandon several of the divergence proposals.

The UK trajectory illustrates a genuine tension in privacy policy reform: reducing commercial data processing friction may produce short-term business cost savings, but it creates systemic risk to the cross-border data transfer infrastructure that enables the digital economy. The EU has signaled that the UK adequacy renewal (due mid-2025) will be assessed against the final enacted legislation. For the US, the UK experience is relevant as a model of what happens when a major democracy attempts to carve out a "third way" between GDPR-level protection and the US laissez-faire approach: the resulting uncertainty about adequacy imposes its own costs on businesses that need a predictable legal basis for transatlantic operations.

Sources: [UK Data Protection and Digital Information Bill (UK Parliament)](https://bills.parliament.uk/bills/3430); [ICO: Statement on DPDI Bill](https://ico.org.uk/about-the-ico/media-centre/news-and-blogs/2022/07/ico-response-to-the-data-protection-and-digital-information-bill/); [EU Commission UK Adequacy Decision (June 2021)](https://commission.europa.eu/document/8b652044-cc40-473d-9e38-28ca452dfba5_en)

---

### 5.6 CCPA/CPRA Enforcement: Early Record

The California Privacy Protection Agency — the only state DPA with independent enforcement authority — began enforcement operations in July 2023. Its first two years of operation provide the best available evidence for assessing what a US federal privacy enforcement regime could achieve.

**Complaint volume**: From July 2023 to September 2025, the CPPA received **8,265 consumer complaints**, averaging approximately 150 per week and accelerating over the period. The dominant complaint categories were: opt-out of sale or sharing (the CCPA's core right); improper collection, use, or sharing of personal information; and right-to-delete violations. The enforcement pipeline converts these complaints into investigations and eventually orders.

**Fine record**: The CPPA's administrative enforcement actions have been smaller than the early record advocates hoped:
- **DoorDash**: $375,000 settlement (February 2024) for selling consumer data to a marketing cooperative without adequate disclosure
- **Todd Snyder, Inc.**: $345,178 fine (May 2025) for multiple CCPA violations
- **Tractor Supply Company**: $1.35 million administrative fine (September 2025) — the largest CPPA administrative fine to date, for opt-out and data handling violations
- California AG separately: $2.75 million against **Disney** for CCPA opt-out noncompliance

The enforcement amounts are modest relative to the scale of violations documented in the CPPA's own investigations and dramatically smaller than GDPR fines against comparable companies in Europe. The structural reason: California's per-violation fine schedule ($2,663 per violation in 2025) is designed for individual transaction-level violations, not for enterprise-scale data practices affecting millions of consumers. A single Meta behavioral advertising policy violation affecting 40 million California consumers generates a theoretical maximum penalty in the tens of billions under the per-violation calculation — but CPPA's enforcement actions have structured settlements around disclosed violations rather than maximum statutory exposure, resulting in fines more comparable to cost-of-doing-business than deterrent.

The CPPA's 2024 annual report documented that the agency's enforcement division remained understaffed relative to complaint volume — a direct result of California's appropriation process and the newness of the institution. This real-world experience with an underfunded state DPA is the strongest argument for the FDPA's proposed budget: enforcement agencies need sufficient resources to investigate at scale, not merely to process the most visible cases.

Sources: [CPPA Annual Report 2024 (ReedSmith)](https://www.reedsmith.com/our-insights/blogs/viewpoints/102k2to/biggest-takeaways-from-the-cppas-annual-report-2024/); [CPPA Enforcement: Tractor Supply Company (October 2025)](https://www.orrick.com/en/Insights/2025/10/CPPA-Imposes-the-Largest-Administrative-Fine-to-Date-What-Companies-Need-to-Know); [California AG: Disney CCPA Fine (IAPP)](https://iapp.org/news/a/california-s-attorney-general-issues-largest-ccpa-fine-to-date); [CPPA Consumer Complaints Update (Captain Compliance)](https://captaincompliance.com/education/ccpa-consumer-complaints-update-8265-cases-signal-rising-scrutiny-on-data-subject-rights/)

---

### 5.6 Comparative Enforcement Infrastructure

A structural comparison of data protection authority budgets and staffing provides the grounding for the FDPA fiscal estimate.

| Authority | Country | Annual Budget | Dedicated Staff | Population Served | Staff per Million Pop. |
|---|---|---|---|---|---|
| Ireland DPC | Ireland | ~€29.4M (2024) | 280 | 5.1M | 55 |
| CNIL | France | ~€28M | 298 | 68M | 4.4 |
| BfDI | Germany | ~€38M | 350+ | 84M | 4.2 |
| ICO | UK | ~£52M | 870 | 68M | 12.8 |
| FTC (Privacy, all) | USA | ~$50M equiv. | ~50 dedicated | 335M | 0.15 |

The FTC's total budget of approximately $590 million (FY 2024 request) supports approximately 1,230–1,690 staff, of whom fewer than 50 are dedicated to privacy enforcement — a per-capita privacy enforcement ratio **roughly 30 times lower** than France's CNIL and approximately **90 times lower** than Ireland's DPC. The per-capita comparison understates the gap because US technology companies subject to the FTC's jurisdiction are orders of magnitude larger and more complex than those supervised by the DPC.

The proposed Federal Data Protection Agency (FDPA) modeled on the Domain 21 framework would require approximately 800–1,200 dedicated staff at full operational capacity to achieve CNIL-equivalent per-capita coverage for a jurisdiction four times France's population — consistent with the $400–600 million annual budget estimate in the proposal's fiscal analysis.

Sources: [Ireland DPC Budget 2025 (Irish Times, December 2025)](https://www.irishtimes.com/business/2025/12/02/data-protection-commission-sought-10m-budget-increase-to-beef-up-staff-numbers/); [CNIL Status and Composition](https://www.cnil.fr/en/cnil/status-composition); [BfDI Germany Overview](https://www.bfdi.bund.de/EN/BfDI/UeberUns/DieBehoerde/diebehoerde_node.html); [New America: Comparing the FTC and DPA](https://www.newamerica.org/oti/reports/does-data-privacy-need-its-own-agency/comparing-the-ftc-and-dpa/); [Slate: FTC Needs Funding for Privacy (2023)](https://slate.com/technology/2023/07/federal-trade-commission-funding-privacy.html)

---

## Section 6: Chilling Effect Documentation

### 6.1 The Penney Study and Its Extensions

Jonathon Penney's 2016 study, "Chilling Effects: Online Surveillance and Wikipedia Use," published in the Berkeley Technology Law Journal (Vol. 31, No. 1, pp. 117-182), provided the first empirical evidence grounded in web traffic data that government surveillance awareness causes measurable behavioral change.

**Study design**: Penney used a difference-in-differences methodology comparing monthly Wikipedia pageviews for 48 "terrorism-related" articles (identified as sensitive by the DHS) against a control group of comparable articles before and after the June 2013 Snowden/PRISM disclosures. The design treats the Snowden revelations as a natural experiment: a sudden, widespread increase in public awareness of surveillance capabilities.

**Findings**: Traffic to the 48 privacy-sensitive Wikipedia articles fell by **approximately 20%** immediately following the June 2013 disclosures and did not recover over the 32-month observation period, suggesting a permanent behavioral shift rather than a transient reaction. The articles showing the greatest traffic decline included topics directly related to terrorism, weapons, and security — the categories where users had the most reason to fear that their information-seeking would be flagged by surveillance systems.

**Methodological limitations**: The study cannot rule out that the Snowden disclosures changed the composition of people seeking the information (more informed people, fewer casual searchers) rather than suppressing information-seeking by a fixed population. The design also cannot distinguish between chilling caused by fear of surveillance and chilling caused by the reputational risk of being associated with terrorism-adjacent topics in a post-2013 media environment. Penney acknowledges these limitations but argues that the pattern across 48 topics, consistent with a single triggering event, is most parsimoniously explained by the surveillance chilling mechanism.

**Extensions (2022–2025)**: Büchi, Festic, and Latzer (2022, Big Data and Society) published "The Chilling Effects of Digital Dataveillance: A Theoretical Model and an Empirical Research Agenda," extending Penney's framework to commercial surveillance and documenting self-censorship on social platforms. A 2024 review of the literature in Arxiv (February 2025, "Review of Demographic Bias in Face Recognition") notes that chilling effects interact with demographic vulnerability — populations with stronger reasons to fear surveillance (racial minorities, immigrants, political activists) show more pronounced behavioral modification.

**PEN America findings**: PEN America's 2013 survey of 520 writers found that 16% had avoided writing or speaking on a topic because they were worried about government surveillance; 11% had seriously considered refraining from such work; 28% had curtailed or avoided social media activities; and 24% had deliberately avoided certain topics in phone or email communications. The survey was conducted after Snowden and does not establish pre-surveillance baseline behavior, which is its primary methodological limitation — but the 16% figure represents a population of professional writers whose work on sensitive topics is directly relevant to democratic discourse.

Sources: [Penney: Chilling Effects: Online Surveillance and Wikipedia Use (Berkeley Technology Law Journal 2016)](https://btlj.org/data/articles2016/vol31/31_1/0117_0182_Penney_ChillingEffects_WEB.pdf); [Büchi, Festic, Latzer: Chilling Effects of Digital Dataveillance (Big Data and Society, 2022)](https://journals.sagepub.com/doi/10.1177/20539517211065368); [Schneier on Security: Documenting Chilling Effects of NSA Surveillance (2016)](https://www.schneier.com/blog/archives/2016/04/documenting_the.html)

---

### 6.2 Protest and Political Surveillance: The COINTELPRO to Present Arc

COINTELPRO operated from 1956 to 1971 as the FBI's systematic campaign to surveil, infiltrate, discredit, and disrupt political organizations the Bureau characterized as subversive. Church Committee hearings in 1975-76 exposed the program's targeting of civil rights leaders, anti-war organizations, the NAACP, the Socialist Workers Party, and the American Indian Movement — and documented tactics including forged letters to create organizational splits, anonymous letters to spouses alleging infidelity, and the deliberate provocation of violence between groups.

The structural reforms that followed COINTELPRO — the Attorney General's Guidelines, Executive Order 12333's privacy protections for US persons, and FISA itself — created procedural constraints on domestic political surveillance. The documented evidence base from 2000 to the present shows how those constraints have eroded.

**Post-9/11**: The FBI's Nationwide Suspicious Activity Reporting (SAR) initiative created a database of "suspicious" behavior observations submitted by state and local law enforcement, accessible through fusion centers. The ACLU's analysis of SAR reports found thousands of entries based on constitutionally protected activities including attending a political rally, taking photographs in public, and speaking Arabic in an airport. Muslim communities were subjected to systematic mapping programs by NYPD's Demographics Unit, documented in AP investigations, under which officers mapped mosques, businesses, and community organizations without any predicate of specific criminal activity.

**Standing Rock (2016)**: Energy Transfer Partners hired TigerSwan — a private security firm with counterterrorism experience — to conduct surveillance of Standing Rock pipeline protesters, producing intelligence reports characterizing nonviolent water protectors as "jihadist" threats. The North Dakota Emergency Commission activated the state Emergency Commission and requested National Guard support. TigerSwan's activities, documented in leaked internal reports published by The Intercept, included aerial surveillance, infiltration of camps, and information sharing with law enforcement — a private-sector COINTELPRO operating outside the Attorney General's Guidelines entirely.

**2020 BLM protests**: In addition to the aerial surveillance documented in Section 2.4, the FBI deployed informants to infiltrate protest organizations using the domestic terrorist threat predicate. The COINTELPRO 2.0 pattern is documented: an FBI informant paid $20,000 was used to infiltrate Denver-area racial justice organizing, encouraged activists toward weapons acquisition, and used snitch-jacketing to disrupt legitimate leadership.

Sources: [Innocence Project: COINTELPRO to Present](https://innocenceproject.org/news/from-cointelpro-snapchat-police-surveillance-of-black-people/); [The Intercept: TigerSwan Standing Rock Surveillance](https://theintercept.com/2017/05/27/leaked-documents-reveal-security-firms-counterterrorism-tactics-at-standing-rock-to-defeat-pipeline-insurgencies/); [ICNL: Protesting in an Age of Government Surveillance](https://www.icnl.org/post/analysis/protesting-in-an-age-of-government-surveillance)

---

### 6.3 Professional Contexts: Journalists, Attorneys, and Healthcare

The chilling effect most relevant to democratic accountability institutions operates not on general citizens but on the professionals who mediate between institutions and the public.

**Journalists**: The Committee to Protect Journalists documented that **at least 13 federal subpoenas or court orders for journalist records** were issued between 2017 and 2021, including retrospective data orders seeking phone and email metadata. The DOJ under the Biden administration revised its guidelines in 2021 to prohibit compelled disclosure of journalist records in most cases, but these are administrative guidelines subject to revision by any subsequent administration. The current administration's classification of investigative journalism as potential "enemy of the people" activity — combined with its documented use of surveillance tools against immigration attorneys and advocates — creates direct professional chilling effects.

**Attorneys**: Attorney-client privilege is a constitutional protection. The NSA's Section 702 collection does not exclude communications of US person attorneys representing foreign clients, and there is no documented filtering protocol that removes privileged communications before analysis. The New York City Bar Association and the American Bar Association have each published analyses documenting that attorney communications are subject to Section 702 collection and that no adequate privilege protection mechanism exists.

**Medical providers and platforms**: HIPAA protects the privacy of health information held by covered entities — hospitals, insurers, physicians. It does not cover data held by **health apps, fitness trackers, period-tracking apps, or social media platforms** that collect health-related behavioral data. The FTC's enforcement against period-tracking app **Flo Health** (2021) and **GoodRx** (2023) under the FTC Act's deception authority addressed some of the most egregious cases, but the core HIPAA gap — that the most widely used health data collection tools operate outside HIPAA's framework — remains unaddressed by any currently enacted law.

Sources: [DOJ Journalist Guidelines (2021)](https://www.justice.gov/d9/2022-01/media_policy.pdf); [EFF: Online Behavioral Ads Fuel Surveillance Industry (January 2025)](https://www.eff.org/deeplinks/2025/01/online-behavioral-ads-fuel-surveillance-industry-heres-how); [FTC: Health Privacy as 2024 Budget Priority (Healthcare Dive)](https://www.healthcaredive.com/news/ftc-health-privacy-key-priority-2024-budget/645051/)

---

### 6.4 Self-Censorship and the Specific Demographics Most Affected

Aggregate chilling effect estimates obscure the distributional pattern that matters most for democratic health: surveillance chilling is not evenly distributed. It concentrates in the populations whose political participation is most important for accountability and reform.

**Racial and ethnic minorities**: The fusion center and JTTF architecture documented in Section 2.4 has been applied disproportionately to communities of color. The FBI's "Black Identity Extremist" designation (2017) explicitly targeted political organizing around police accountability — the kind of First Amendment-protected activity that surveillance is designed to chill. Communities with documented experience of surveillance respond to that surveillance by reducing political engagement: the ACLU's 2014 survey of Muslim American communities found that 35% avoided certain websites, 26% avoided associating with certain people, and 11% had changed their phone or email service because of NSA surveillance concerns — a direct democratic participation cost.

**Immigrants and non-citizens**: The data broker government purchasing pipeline documented in Section 2.1 means that routine digital activity — app usage, location data from phones, social media — generates records that may be purchased by ICE without a warrant and used to identify and remove individuals. This creates a rational incentive for immigrants, documented and undocumented, to avoid civic engagement: registering children in public school, seeking healthcare, using official government services, attending religious institutions. The chilling effect on non-citizens cascades to their US-citizen family members, neighbors, and community organizations.

**Domestic violence and stalking survivors**: The FTC cases documented in Section 1.3 establish that data brokers sell location data at resolutions sufficient to track individuals in real time. For the estimated **10 million Americans** who experience domestic violence annually (CDC, 2021), the commercial availability of location data constitutes a physical safety threat. Documented harm cases include a 2020 murder facilitated by home address data broker purchase and multiple FTC-documented instances of geofencing proposals targeting litigation opponents. The policy implication is that surveillance reform is not an abstract civil liberties concern — it is a concrete safety measure for populations whose political and civic participation is already suppressed by intimate partner violence.

Sources: [ACLU: Muslim Community Survey on NSA Surveillance (2014)](https://www.aclu.org/report/chilling-effect); [EPIC: How Data Brokers Harm Immigrants (2024)](https://epic.org/documents/how-data-brokers-harm-immigrants/); [CDC: Fast Facts on Domestic Violence (2021)](https://www.cdc.gov/violenceprevention/intimatepartnerviolence/fastfact.html); [Your Data is Everywhere (NPR, March 2026)](https://www.npr.org/2026/03/25/nx-s1-5752369/ice-surveillance-data-brokers-congress-anthropic)

---

## Section 7: Implementation Pathway and Obstacles

### 7.1 Technical Feasibility: Consent, Dark Patterns, and Opt-Out Architecture

The proposal's 21a reform envisions consent requirements as a centerpiece of a comprehensive federal privacy statute. The dark patterns literature demonstrates why consent-based frameworks require accompanying design standards to function.

Research from the Princeton Web Transparency Project and related academic work has documented that a majority of cookie consent mechanisms on the web are designed to produce consent rather than record genuine preferences. A 2022 ACM CHI study ("Okay, whatever: An Evaluation of Cookie Consent Interfaces") evaluated user interactions with 40 consent interfaces and found that design choices — button color, placement, pre-ticked boxes, "reject all" buried behind multiple click-throughs — systematically shifted acceptance rates from approximately 18% (when opt-in was equally prominent) to over 80% (when the dark pattern design was used). The 2025 paper "When the Abyss Looks Back: Unveiling Evolving Dark Patterns in Cookie Consent Banners" (arXiv) found that dark pattern prevalence has not decreased under GDPR enforcement, with 55% of GDPR-governed cookie banners still employing identifiable dark patterns.

Effective consent architecture requires:

- **Symmetrical interface design**: "Accept all" and "Reject all" buttons must be visually equivalent and equally accessible from the first layer of any consent interface
- **No pre-ticked boxes**: GDPR Recital 32 prohibits pre-ticked consent; CPRA's CCPA implementing regulations adopted equivalent language
- **Universal opt-out signals**: Colorado's CPA (amended 2025) and Connecticut's CTDPA require businesses to honor **Global Privacy Control (GPC)**, a browser-level signal that communicates opt-out preferences without requiring per-site interaction
- **Prohibition on consent withdrawal barriers**: Withdrawing consent must be as easy as giving it

The Global Privacy Control technical specification — developed by the Electronic Frontier Foundation, Disconnect.me, the New York Times, and academic privacy researchers — provides the most technically mature implementation of universal opt-out. Its adoption as a mandatory standard in federal law would eliminate the per-site consent interaction model that produces the dark pattern dynamic.

Sources: [ACM CHI: Okay, Whatever — Cookie Consent Interfaces (2022)](https://dl.acm.org/doi/fullHtml/10.1145/3491102.3501985); [arXiv: Evolving Dark Patterns in Cookie Consent Banners (2025)](https://arxiv.org/html/2603.21515v1); [FTC and CPRA on Dark Patterns (University of Chicago Business Law Review)](https://businesslawreview.uchicago.edu/print-archive/ftc-and-cpras-regulation-dark-patterns-cookie-consent-notices); [EFF: Google Settlement and RTB Privacy Controls (January 2026)](https://www.eff.org/deeplinks/2026/01/google-settlement-may-bring-new-privacy-controls-real-time-bidding)

---

### 7.2 Congressional Dynamics

Privacy legislation sits in a committee jurisdiction trap. Comprehensive federal privacy legislation crosses the jurisdictions of multiple Senate and House committees. The primary jurisdictions are:

- **Senate Commerce, Science, and Transportation Committee**: Consumer data privacy (historically chaired by Cantwell, whose concerns about enforcement provisions held ADPPA in the Senate)
- **Senate Judiciary Committee**: Fourth Amendment questions, surveillance law (Section 702, warrant requirements)
- **Senate Intelligence Committee**: Classification, access to surveillance program details
- **House Energy and Commerce Committee**: Primary consumer privacy jurisdiction (passed ADPPA 53-2)
- **House Judiciary Committee**: Overlapping jurisdiction on law enforcement surveillance

The fragmentation means that a bill addressing both commercial surveillance and government surveillance — as Domain 21 proposes — must navigate at least four committee jurisdictions and coordinate between chambers. In the 118th Congress (2023–2024), the APRA's failure was partly attributable to House Energy and Commerce and Senate Commerce being unable to agree on enforcement provisions even within the commercial surveillance sphere; the government surveillance provisions (Section 702 reform) were handled entirely separately through the Intelligence committees.

The 119th Congress (2025–2026) presents a less favorable environment for comprehensive privacy legislation, as the administration has been active in expanding, not constraining, government surveillance tools, and the FTC's current leadership has signaled reduced interest in commercial surveillance enforcement rulemaking. The realistic near-term legislative pathway is a narrower bill addressing data broker government sales (the documented warrantless purchase issue) rather than a comprehensive statute — with the comprehensive FDPA framework positioned for the next favorable legislative window.

---

### 7.3 Implementation Sequence

A realistic FDPA implementation assumes:

- **Year 1 (statute enacted)**: Enabling legislation establishes FDPA; initial appropriation for staff hiring; FTC privacy enforcement staff transfers; rulemaking clock begins
- **Year 2–3**: FDPA issues implementing rules on data broker registration (modeled on existing Vermont/California data broker registration statutes), consent standards, data minimization, and sensitive data categories; enforcement against the most egregious documented violations begins
- **Year 3–4**: Section 702 warrant requirement legislation, if enacted, becomes operational as FISA Court application procedures are updated; FDPA privacy rights regime fully operational
- **Year 4–5**: Biometric moratorium review period concludes; FDPA issues facial recognition use standards based on moratorium period evidentiary record; government surveillance reporting consolidated through reformed PCLOB

Vermont's existing data broker registration statute (Act 171, 2018) provides the most mature US model: brokers must register annually, pay a fee, disclose data categories collected, and describe opt-out mechanisms. California's data broker deletion registry (AB 1798, 2023) goes further, requiring brokers to honor deletion requests submitted through a single centralized mechanism. These two state frameworks together constitute the minimum viable foundation for a federal data broker registration and accountability system.

**The FDPA's rulemaking calendar** requires explicit attention in the implementation design. The history of FTC rulemaking under the Magnuson-Moss Act — which requires extensive notice-and-comment procedures before major rules take effect — demonstrates that privacy rulemaking can take 5–10 years under procedural constraints the FDPA should be designed to avoid. The CFPB's rulemaking authority under Dodd-Frank provides a better model: streamlined rulemaking procedures, clear statutory mandate, and a single agency with unambiguous jurisdiction. The proposed FDPA statute should specify rulemaking timelines (e.g., consent standards within 12 months, data broker registration within 18 months, facial recognition standards within 36 months post-moratorium), avoiding the open-ended rulemaking calendar that has left FTC privacy enforcement without binding rules for commercial surveillance despite two decades of documented problems.

**International coordination** is a dimension the implementation sequence must address explicitly. The EU-US Data Privacy Framework operates on a self-certification model: US companies assert compliance with DPF requirements, and the FTC is designated as the enforcement authority. With a fully operational FDPA, the natural evolution would be a formal treaty-level privacy adequacy agreement with the EU — replacing the executive-order-based DPF with a statutory basis more resistant to presidential revocation — and mutual legal assistance agreements with UK, Canadian, and Australian privacy authorities to enable coordinated cross-border enforcement. The UK ICO, Canadian OPC, and Australian OAIC have all jointly participated in enforcement actions against major technology companies; creating a US authority capable of participating in these coalitions would multiply the enforcement leverage available without proportional increase in US spending.

---

## Section 8: Fiscal Estimates by Reform Area

### 8a: Federal Data Protection Agency (21a)

**Proposed budget**: $400–600 million annually at full operational capacity, consistent with the CNIL/BfDI comparison in Section 5.3.

This estimate is constructed from first principles:

- **Staff**: 800–1,200 FTEs at fully-loaded federal salary and benefits (~$150,000–$200,000 per FTE) = $120–240 million
- **Technology and investigation infrastructure**: $50–100 million (database access, forensic investigation tools, enforcement systems comparable to FTC's existing infrastructure)
- **Legal and enforcement**: $80–150 million (litigation, settlements administration, penalty collection infrastructure — recoverable from enforcement actions over time)
- **Policy, rulemaking, and international coordination**: $30–60 million
- **Operations and administrative**: $40–50 million

**Comparison**: The EU collectively spends approximately €350–400 million annually on data protection authority enforcement across 27 member states, for a population of 447 million. The proposed FDPA would provide the equivalent of per-capita enforcement spending of approximately $1.20–1.80 per American — compared to the EU average of approximately $0.80–0.90 per European, but still dramatically below Ireland's $5.77 per capita (reflecting the DPC's disproportionate responsibilities for US technology company oversight).

**Revenue offsets**: FDPA enforcement fines, which under the proposed statute would accrue to the FDPA (rather than the general fund as under current FTC civil penalty authority), could generate substantial self-funding over time. The GDPR experience suggests that at full enforcement capacity, a US framework could generate $500 million–$2 billion annually in fines — partially or fully self-funding the agency after the initial build-out phase.

**FBI and IC adjustment costs**: The 21b warrant requirement for Section 702 US person queries would require FBI to obtain FISA Court approval before running US person queries. The FBI's 204,090 documented US person queries in FY 2022 would each require individualized legal review and court authorization — a significant administrative burden. The IC estimates this could require an additional 200–400 FTEs across FBI and DOJ's National Security Division. This is a real cost, but it represents the functional equivalent of requiring law enforcement to obtain a warrant — a baseline constitutional requirement that has not historically been understood as prohibitively costly for other investigative authorities.

Sources: [New America: Does Data Privacy Need Its Own Agency?](https://www.newamerica.org/oti/reports/does-data-privacy-need-its-own-agency/); [FTC FY 2024 Annual Performance Report](https://www.ftc.gov/system/files/ftc_gov/pdf/apr-app_fy24-26.pdf); [Brookings: FTC Can Rise to Privacy Challenge](https://www.brookings.edu/articles/the-ftc-can-rise-to-the-privacy-challenge-but-not-without-help-from-congress/)

---

### 8b: Warrant Requirement for Section 702 US Person Queries (21b)

**Direct cost**: $30–70 million annually (additional FBI/DOJ National Security Division attorney positions; FISA Court administrative expansion to handle increased application volume).

**Offsetting benefit**: Reduction in wrongful investigation costs — litigation from improper queries, prosecutorial resources spent on cases built on improperly obtained evidence, and the human cost of investigations targeting constitutionally protected political activity. These benefits are real but not readily monetizable.

---

### 8c: Facial Recognition Moratorium (21c)

**Procurement savings**: Federal agencies and state/local agencies receiving federal homeland security grants spend an estimated $50–150 million annually on facial recognition technology contracts. A moratorium pauses new procurement and maintenance contracts — approximately $25–75 million in annual federal savings (offset by the need to maintain existing investigative tools through alternative means).

**Net fiscal impact**: Near-zero to modestly positive. The moratorium does not require new spending; it requires cessation of spending on technology whose continued use produces liability costs (wrongful arrest settlements, litigation) and whose accuracy limitations require compensating investigative redundancy.

---

### 8d: PCLOB Reform (21d)

**Current PCLOB budget**: Approximately **$10 million annually** — a figure that has been consistent for several years and that privacy advocates have repeatedly identified as grossly inadequate for an institution tasked with reviewing the most complex and expensive surveillance programs in history. The FBI's CIPA case review budget alone exceeds PCLOB's total budget.

**Proposed expansion**: The Domain 21 proposal envisions a strengthened PCLOB with subpoena authority, greater staffing, and a protected appointment structure. An adequately resourced PCLOB — modeled on the UK Investigatory Powers Commissioner's Office (IPCO), which has approximately 60 staff and a budget of £3.5 million but operates in a smaller surveillance environment — would require approximately $40–80 million annually to conduct meaningful oversight of the NSA, FBI, CIA, and IC agencies with Section 702 authority.

**Comparison**: The DoD IG's office operates with a budget of approximately $300 million and 1,600 staff to oversee a $900 billion defense enterprise. PCLOB oversees a surveillance enterprise of comparable complexity and sensitivity with a budget one-thirtieth the size and a staff of approximately 25. The proposed PCLOB expansion represents an oversight investment of approximately $0.12–0.24 per American per year — arguably the highest-return oversight investment in the federal government given the civil liberties and diplomatic consequences of surveillance overreach.

Sources: [PCLOB: Home](https://www.pclob.gov/); [UK IPCO Annual Report 2023](https://www.ipco.org.uk/publications/annual-reports/)

---

### 8e: Democratic Participation Protections and Public Technology (21e)

**Scope**: Domain 21e encompasses prohibitions on data collection from civic platforms, election-related data brokers, and the proposed Public Interest Technology Corps — a federally funded capacity-building program to create privacy-protective digital infrastructure.

**Estimated costs**:
- Public Interest Technology Corps (modeled on AmeriCorps): $150–300 million annually for 2,000–5,000 privacy and digital rights practitioners placed in public institutions, legal aid organizations, and civil society
- Privacy-protective election infrastructure grants (to states): $50–100 million over 4 years
- Civic platform privacy standards enforcement (FDPA civil rights division dedicated to democratic participation cases): ~$30–50 million annually (within FDPA overall budget)

**Total Domain 21 fiscal estimate**: $700–1,100 million annually at full implementation (FDPA $400-600M + PCLOB expansion $40-80M + Tech Corps $150-300M + warrant implementation costs $30-70M), partially offset by FDPA enforcement fine revenue of $500 million–$2 billion annually at maturity. Net fiscal impact over a 10-year window is likely to be positive to the federal budget through fine revenue, reduced litigation costs from improper surveillance, and the economic value of increased consumer trust in digital services.

**The avoidance-of-cost framing** is worth developing explicitly for budget scoring purposes. The current absence of a federal privacy framework produces ongoing fiscal costs that are simply invisible in federal accounting because they accrue to individuals, state governments, and the broader economy rather than to federal expenditure lines:

- **Wrongful arrest and prosecution costs**: Each documented facial recognition wrongful arrest produced litigation costs against municipalities of hundreds of thousands to low millions of dollars. The Robert Williams case settlement value was not disclosed but the legal fees alone ran into six figures. With 3,100-plus agencies deploying facial recognition and documented demographic error rates, the projected cost of continued deployment without regulation is substantially higher than the moratorium's implementation costs.
- **DPF disruption risk**: A third invalidation of the US-EU data transfer framework — triggered by the PCLOB's non-operational status or a Schrems III ruling — would impose compliance costs on the transatlantic digital economy estimated at $7–14 billion annually by the International Association of Privacy Professionals, based on companies' compliance costs after Schrems II.
- **Data breach liability costs**: The FTC's commercial surveillance enforcement covers a fraction of the data breaches that occur annually in the US. Data breach costs (notification, remediation, litigation) run to approximately $9.4 million per incident on average (IBM Cost of Data Breach Report 2023), and the US experiences thousands of significant breaches annually. A baseline security requirement component of federal privacy law would reduce these costs — though quantifying the reduction requires assumptions about behavioral change that are contested.

Sources: [New America: Does Data Privacy Need Its Own Agency?](https://www.newamerica.org/oti/reports/does-data-privacy-need-its-own-agency/); [FTC FY 2024 Annual Performance Report](https://www.ftc.gov/system/files/ftc_gov/pdf/apr-app_fy24-26.pdf); [Brookings: FTC Can Rise to Privacy Challenge](https://www.brookings.edu/articles/the-ftc-can-rise-to-the-privacy-challenge-but-not-without-help-from-congress/)

---

## Section 9: Structured Counterarguments

### 9.1 National Security Necessity

The most serious counterargument to Section 702 reform is the intelligence community's consistent testimony that the program is "indispensable" to counterterrorism and counterintelligence operations. The DNI's annual Statistical Transparency Report on National Security Legal Authorities includes representative examples of Section 702's operational value — though the examples are redacted to the level of general description.

The counterargument requires taking seriously that: (a) surveillance programs that produced PRISM-era mass collection have been used in genuine counterterrorism investigations; (b) a warrant requirement would add process time that may be operationally costly in fast-moving investigations; (c) the FBI's documented noncompliance problem has, by official reporting, improved significantly without eliminating the program.

The response: the proposed reform requires a warrant only for **queries using US person identifiers** — not for the collection itself, which targets foreign persons. The IC retains full Section 702 collection authority; the warrant requirement applies to the subset of queries that search that collection for Americans' communications. This is precisely the distinction the House amendment that was narrowly defeated addressed. The burden is procedural, not programmatic, and comparable to the warrant requirement already governing traditional domestic surveillance.

The strongest version of the security counterargument focuses on **speed**: in an active terrorism investigation, obtaining a FISA warrant takes time that may allow an attack to proceed. The response to this version of the argument is that FISA already provides an **emergency authorization** mechanism — the Attorney General may authorize emergency surveillance before a court order is obtained, with the order required within seven days. This mechanism has been used hundreds of times. The warrant requirement for Section 702 US person queries can be designed with an equivalent emergency procedure: the FBI Director or designee can authorize an emergency query with post-hoc judicial review, preventing the timing problem while maintaining the requirement for independent authorization in non-emergency cases. The DOJ IG's 2025 finding that widespread noncompliant querying has been reduced suggests that the FBI is capable of query discipline when subject to compliance pressure — warranted queries under a statutory requirement would impose a stronger and more durable discipline than internal administrative oversight.

The underlying political economy of the national security argument also deserves examination. Intelligence community agencies have opposed every major surveillance reform since FISA's original enactment in 1978, including FISA itself. The NSA opposed the Church Committee recommendations; the FBI opposed FISA's warrant requirement for national security wiretapping; the IC opposed the USA FREEDOM Act's transparency requirements; the IC opposed the warrant amendment in RISAA. Each time, the stated objection was operational necessity; in each case, reform was enacted without producing the predicted operational catastrophe. This historical pattern should appropriately calibrate the weight assigned to operational necessity arguments when they appear as an obstacle to statutory reform.

### 9.2 Industry Competitiveness and the Innovation Objection

The ad tech industry argues that RTB and behavioral targeting are essential to the economic model of free internet services, and that privacy regulation would transfer market share to less regulated competitors. This argument has two components worth separating: (a) the economic model claim, and (b) the competitive harm claim.

On (a): the FTC's September 2024 staff report found that behavioral targeting's marginal value to advertisers over contextual targeting is smaller than the industry claims. Research by Nico Neumann and others found that the price premium for behaviorally targeted advertising over contextually targeted advertising is approximately 4%, while the privacy cost is orders of magnitude larger. The ad tech ecosystem's surveillance intensity is driven by competitive incentives among brokers and intermediaries, not by advertiser demand for granular individual tracking.

On (b): The GDPR's seven-year record does not show that European companies lost competitive ground relative to US companies in privacy-regulated markets. The companies that lost market share under GDPR were primarily US-headquartered ad tech intermediaries — which is the intended competitive effect of privacy regulation, not evidence of harm to European innovation.

A more granular version of the competitiveness counterargument focuses on **small publishers**: the claim that smaller news sites, apps, and content platforms depend on behavioral advertising revenue and would be disproportionately harmed by a privacy-constrained ad market. This argument has more empirical support than the large platform version. A 2020 NBER working paper by Johnson, Newman, and Ri found that publisher revenue dropped approximately 4–12% in response to GDPR consent requirements, with smaller publishers experiencing larger relative impacts. However, the same analysis found that the revenue impact attenuated over time as publishers adapted their consent and contextual targeting infrastructure, and that **first-party data strategies** — where publishers collect authenticated user data with genuine consent — proved economically more durable than third-party behavioral targeting.

The policy response for small publishers is not to exempt them from privacy requirements but to provide transition support: the proposed FDPA's implementation timeline includes a delayed compliance date for small publishers (under $25 million annual revenue), a safe harbor for first-party data with genuine consent, and a public interest exemption for news organizations consistent with the GDPR's existing Article 85 journalism exemption. These provisions address the legitimate small publisher concern without preserving the surveillance infrastructure that harms everyone.

The "free internet" argument — that behavioral advertising is what makes the internet "free" to consumers — rests on an economic equivalence claim that does not account for the actual market structure. The largest platforms (Google, Meta, Amazon) capture the vast majority of digital advertising revenue. A shift from behavioral to contextual advertising would reallocate revenue away from the data broker intermediaries and toward publishers with engaged audiences — a redistribution that would likely benefit the news and media ecosystem that behavioral advertising has hollowed out.

Sources: [Johnson, Newman, Ri: Consumer Privacy Choice in Online Advertising (NBER 2020)](https://www.nber.org/papers/w27572); [FTC Staff Report: Social Media Surveillance (September 2024)](https://www.ftc.gov/news-events/news/press-releases/2024/09/ftc-staff-report-finds-large-social-media-video-streaming-companies-have-engaged-vast-surveillance)

### 9.3 The Anonymization Defense

Data brokers and ad tech companies consistently claim that data is "anonymized" or "de-identified" before sale, limiting privacy harm. The empirical literature on re-identification is unambiguous on this point: the anonymization claim is not defensible for the data categories at issue.

Latanya Sweeney's foundational research (2002) demonstrated that 87% of the US population could be uniquely identified using only zip code, birth date, and sex. Arvind Narayanan and Vitaly Shmatikoff's 2008 study de-anonymized Netflix's published "anonymized" ratings dataset using IMDb data. More recently, research by de Montjoye et al. (2013, Science) demonstrated that four spatio-temporal points from a mobility dataset — approximately the frequency and precision of data generated by a single day's smartphone use — are sufficient to uniquely re-identify 95% of individuals. The FTC's enforcement orders against X-Mode, Mobilewalla, and Gravy Analytics each document that these companies' data was **not anonymized** as they had claimed — the FTC found raw GPS coordinates, no sensitive location removal, and product designs explicitly built for individual identification.

Sources: [FTC: Surveillance Pricing Update (January 2025)](https://www.ftc.gov/policy/advocacy-research/tech-at-ftc/2025/01/surveillance-pricing-update-work-ahead); [de Montjoye et al.: Unique in the Crowd — Mobility Data Re-Identification (Science, 2013)](https://www.science.org/doi/10.1126/science.1227295); [FTC: WilmerHale Enforcement Actions Against Data Brokers (December 2024)](https://www.wilmerhale.com/en/insights/blogs/wilmerhale-privacy-and-cybersecurity-law/20241216-ftc-continues-to-bring-enforcement-actions-against-data-brokers)

### 9.4 Facial Recognition's Legitimate Law Enforcement Uses

The most substantive counterargument to a facial recognition moratorium comes from law enforcement agencies that document cases where facial recognition produced genuine investigative leads in serious crimes — child exploitation, human trafficking, and homicide investigations. Law enforcement testimony in Congressional hearings consistently provides examples of facial recognition identifying victims and perpetrators in cases where other methods had failed. The FBI and DHS have testified that a complete moratorium would eliminate a tool with documented value in exactly these categories.

The response requires engaging with this argument directly rather than dismissing it. Two distinctions clarify the policy question: First, the moratorium's primary target is **identification of suspects for purposes of arrest** based on a facial recognition match — the operational scenario in all four documented Detroit wrongful arrests. A moratorium can be designed to permit use for **generating investigative leads** (a facial recognition match that informs a human investigator's further inquiry) while prohibiting use as sufficient basis for arrest without independent corroboration. This distinction is absent from current policy in nearly all jurisdictions with facial recognition deployment. Second, the demographic accuracy disparity documented in Section 3.1 creates a perverse harm distribution: facial recognition is most likely to produce wrongful arrests against the populations — Black women, other people of color — where the accuracy gap is largest. A tool with differential error rates that are legally cognizable as discriminatory cannot be treated as neutral law enforcement infrastructure simply because it occasionally produces correct matches.

The EU AI Act's exception-based framework (Section 5.2) provides a model: facial recognition prohibited as a default for law enforcement identification purposes, with narrow authorized uses requiring judicial authorization, post-use notification, and documented accuracy standards for the specific demographic of the targeted individual. This framework preserves the tool for the cases law enforcement most values while eliminating the routine deployment that produces wrongful arrests.

Sources: [Time: Why Police Must Stop Using Face Recognition Technologies (2024)](https://time.com/6991818/wrongfully-arrested-facial-recognition-technology-essay/); [Stateline: Facial Recognition Getting State-by-State Guardrails (February 2025)](https://stateline.org/2025/02/04/facial-recognition-in-policing-is-getting-state-by-state-guardrails/); [EFF: Detroit Takes Important Step on Face Recognition (2024)](https://www.eff.org/deeplinks/2024/07/detroit-takes-important-step-curbing-harms-face-recognition-technology)

---

### 9.5 Data Availability and Beneficial Uses: The Genuine Tension

This counterargument is the strongest objection not yet fully engaged in the sections above, and it deserves direct treatment because it is the argument made not primarily by the ad tech industry but by researchers, patient advocates, and fraud prevention specialists who have legitimate claims on the data flows that privacy regulation would restrict.

**The fraud prevention claim**: Financial fraud detection systems — credit card fraud, identity theft, account takeover — rely on behavioral data at scale to identify anomalous patterns. The CFPB's own data shows that fraud losses in the US exceeded **$12.5 billion in 2024** (Federal Trade Commission Consumer Sentinel Network, 2025). Banks and payment processors argue that restricting data sharing between entities in a financial services ecosystem would degrade fraud detection accuracy. This argument has empirical grounding: cross-institutional data sharing does improve pattern detection for known fraud vectors. The policy response is not to deny this but to distinguish fraud prevention data sharing from commercial surveillance data brokering. The proposed FDPA framework follows the existing FCRA/GLBA model: a **purpose limitation** requirement that permits data sharing within tightly defined fraud-prevention use cases, with prohibition on downstream use for unrelated commercial targeting. The GDPR's Article 6(1)(f) "legitimate interests" provision and its Recital 47 fraud prevention carve-out already demonstrate that GDPR-level protection is compatible with functional fraud detection across European banking systems — and European banks are not materially worse at fraud detection than US counterparts on a per-transaction basis.

**The medical research claim**: Epidemiological and clinical research depends on large-scale longitudinal health data. Major research advances — from pharmacovigilance (identifying drug side effects at population scale) to pandemic modeling to cancer screening optimization — require datasets that are difficult or impossible to construct from purely volunteered, fully consented samples. The argument is that opt-in consent requirements would systematically bias research datasets toward the healthy, engaged, and technologically literate, degrading the scientific value of population-health research. This is a genuine methodological concern, not industry lobbying. The 2020 National Academy of Sciences report "Reproducibility and Replicability in Science" documents that selection bias in research samples is a significant source of irreproducibility. The GDPR addresses this directly through **Article 9(2)(j)**, which provides a research exemption from the prohibition on sensitive data processing when accompanied by appropriate safeguards — a model that has been operationalized by European biobanks (UK Biobank, Finnish Institute for Health and Welfare, Danish registers) that maintain population-scale longitudinal health databases under GDPR compliance with broad patient consent frameworks, not per-study consent. The US NIH's All of Us Research Program demonstrates that robust consent frameworks can achieve large-scale participation (over 750,000 participants as of 2025) without the privacy harms of HIPAA-excluded health app data. The policy resolution is not between research and privacy but between **appropriately governed research exemptions** with independent ethics review, defined retention limits, and prohibition on commercial downstream use — versus the current system in which health inference data is sold to anyone who can pay SafeGraph's API access fee.

**The free-flow-of-data argument**: Technology industry organizations (including the US Chamber of Commerce and the Internet Association, now the Computer and Communications Industry Association) argue that data localization requirements and transfer restrictions embedded in comprehensive privacy frameworks impede the cross-border data flows that enable cloud computing, AI training, and digital services at global scale. The economic claim is that mandatory data localization would cost the US digital economy $95–$117 billion annually (Information Technology and Innovation Foundation, 2023 estimate). The response to this claim has two components: first, the GDPR and APEC Cross-Border Privacy Rules have demonstrated that privacy protection is structurally compatible with cross-border data flows through legal mechanisms (Standard Contractual Clauses, adequacy decisions, CBPR certification) that permit transfers without requiring localization; second, the economic cost of the current system — DPF disruption risk, breach costs, wrongful arrest liability, and the political cost of surveillance-enabled authoritarianism — is systematically omitted from the industry's accounting. A federal privacy framework with robust international cooperation mechanisms (as proposed in Section 7.3) enables cross-border data flows on a sustainable legal basis, unlike the current framework which has collapsed twice and faces challenge from a third Schrems filing.

**What the beneficial use arguments establish for reform design**: The legitimate force of these three objections — fraud prevention, medical research, and data flows — argues for precision in reform design, not for rejection of reform. Each points to a specific carve-out or exemption mechanism that is already established in GDPR practice. The FDPA should include: a **fraud prevention exemption** modeled on GDPR Recital 47 with purpose limitation and prohibition on secondary use; a **research exemption** modeled on GDPR Article 9(2)(j) with independent IRB oversight, defined retention limits, and commercial downstream use prohibition; and a **cross-border transfer mechanism** modeled on SCCs and adequacy decisions that eliminates localization without eliminating accountability. None of these exemptions requires preserving the RTB surveillance infrastructure, the data broker warrantless government sale pipeline, or the biometric surveillance regime that is the core target of Domain 21 reform.

Sources: [FTC Consumer Sentinel Network Data Book 2025](https://www.ftc.gov/reports/consumer-sentinel-network-data-book-2024); [GDPR Article 9: Processing Special Categories of Data](https://gdpr-info.eu/art-9-gdpr/); [NIH All of Us Research Program: Participant Statistics (2025)](https://allofus.nih.gov/about/program-overview); [ITIF: Costs of Forced Data Localization (2023)](https://itif.org/publications/2023/09/11/how-forced-data-localization-harms-consumers-workers-and-economies/); [UK Biobank: Ethics and Governance Framework](https://www.ukbiobank.ac.uk/media/0xsbmfmw/egf.pdf); [NAS: Reproducibility and Replicability in Science (2020)](https://nap.nationalacademies.org/catalog/25303/reproducibility-and-replicability-in-science)

---

## Section 10: Actionable Intelligence

### AI-1: Most Immediately Actionable Items (April–September 2026)

**Section 702 second reauthorization deadline**: Section 702 was reauthorized on April 20, 2024 for two years, meaning it expires **April 20, 2026** absent action. As of this document's preparation, Congress faces the immediate question of whether to extend again without the warrant requirement or allow the program to lapse. The April 2026 reauthorization fight is the single highest-priority legislative window for surveillance reform in the 119th Congress. The 2024 House amendment requiring warrants for US person queries failed by a vote of 212–212 — a tie that, under House rules, meant the amendment failed. This means there are specific named swing votes that determined the outcome. The strategic target is converting five to ten of the 212 opposing votes: libertarian-leaning Republicans (Thomas Massie, Andy Biggs, Warren Davidson, and others who have historically opposed surveillance expansion) and Democrats who voted no due to procedural or enforcement concerns. EFF and Demand Progress have maintained specific congressional target lists updated through the 2024 vote.

**PCLOB reconstitution**: The three fired PCLOB members (Felten, LeBlanc, Das) have each signaled intent to pursue reinstatement through litigation. A federal district court ruling on the legality of the firings could come within 2026, given the administrative law posture of challenges to the Trump administration's inspector general and board member dismissals. If the firings are reversed, the PCLOB could be reconstituted quickly — its enabling statute requires only Senate-confirmed members, not new legislation. Advocacy organizations should support the litigation and prepare materials for rapid Senate confirmation hearings if the district court reinstates the members. The EU-US Data Privacy Framework adequacy determination is directly at risk, and the European Parliament's formal inquiry (Parliamentary Question P-000941/2025) creates a diplomatic pressure point that US legislators focused on transatlantic trade should understand.

**Data broker warrantless government sales**: The narrowest, most constitutionally straightforward privacy reform is the prohibition on federal agencies purchasing from data brokers data they could not obtain through legal process. This reform does not implicate Article II surveillance authority, does not require addressing Section 702, and has genuine bipartisan appeal (it frames as a Fourth Amendment protection, not a privacy regulation). The **Fourth Amendment Is Not For Sale Act** (Wyden/Griffith in the Senate and House respectively) is the primary vehicle. The Senate Judiciary Committee voted 13–8 to advance the bill in the 118th Congress — bipartisan support sufficient to be instructive about the legislative coalition. In the 119th Congress, the bill has been reintroduced; the target is attaching it to must-pass legislation (NDAA, appropriations) given the hostile floor environment.

---

### AI-2: Legislative Vehicles

**American Privacy Rights Act (APRA) successor**: The ADPPA (2022) and APRA (2024) both died without floor votes. In the 119th Congress (2025–2026), the most likely privacy legislative vehicle is a narrowed bill rather than comprehensive legislation. The three most viable legislative components, ranked by bipartisan achievability:

1. **Data broker registration and government sales prohibition** — Fourth Amendment Is Not For Sale Act (Wyden/Griffith). Senate Judiciary Committee 13-8 in 118th Congress. Reintroduced 119th Congress. Viable as NDAA amendment or standalone with bipartisan co-sponsors including libertarian Republicans.

2. **Biometric data protection** — Illinois BIPA is the national model. A **federal BIPA** modeled on its private right of action structure and per-violation damages ($1,000–$5,000) is the most enforcement-capable federal framework available. The Illinois BIPA private right of action produces the Meta $650 million settlement, the Clearview $51.75 million equity settlement, and the TikTok $92 million settlement — three enforcement outcomes that no FTC action has matched. A federal BIPA would extend this framework nationally without requiring a new agency.

3. **ADPPA/APRA partial revival** — Senator Maria Cantwell (ranking member, Senate Commerce) has signaled interest in a narrowed commercial data broker accountability bill that addresses the enforcement mechanisms she found inadequate in prior versions. A bill specifying FDPA-equivalent enforcement (independent agency, dedicated appropriation, private right of action for significant violations) is more viable than a comprehensive bill that reopens preemption debates.

**Children's Online Privacy Protection Act (COPPA) expansion**: COPPA 2.0 — extending age-based protections to 16 and under, prohibiting behavioral targeting of minors, and requiring data minimization for youth-directed services — has passed the Senate Commerce Committee with bipartisan support in multiple Congresses and is the privacy vehicle with the clearest path to floor consideration. COPPA 2.0 does not resolve the comprehensive privacy framework question but does address the most politically salient subpopulation and creates an enforcement precedent for an FDPA-style dedicated appropriation.

**Kids Online Safety Act (KOSA)**: Passed the Senate 91–3 in July 2024 — a signal of achievable bipartisan consensus on youth-specific platform accountability. KOSA creates a "duty of care" for platforms serving minors and requires design standards to prevent addictive product features. Companion House legislation stalled; reintroduction expected in 119th Congress. KOSA is relevant to data privacy because the duty of care standard it creates would limit the behavioral surveillance architecture for the most legally vulnerable population.

---

### AI-3: Administrative Pressure Points

**FTC rulemaking on surveillance pricing and data broker practices**: Under FTC Chair Lina Khan, the FTC initiated a **commercial surveillance rulemaking** (ANPRM, August 2022) — the first attempt to use the FTC's Magnuson-Moss rulemaking authority to establish binding commercial data privacy standards. The current FTC leadership under Chair Andrew Ferguson has signaled reduced interest in finalizing this rulemaking. The public comment record from the 2022 ANPRM — over 11,000 comments — is the most comprehensive administrative record of the commercial surveillance harms and reform options available. Advocates can use this record in litigation challenging the administration's failure to act, in congressional oversight requests, and in state-level regulatory proceedings. State attorneys general in California, New York, Illinois, and Connecticut have independent authority to develop parallel rulemaking records; coordination between the CPPA and state AGs on commercial surveillance rulemaking creates enforcement leverage independent of the federal regulatory posture.

**CFPB data broker rule**: The Biden CFPB proposed a rule in December 2024 that would extend FCRA obligations to data broker products used for credit, employment, housing, and similar decisions — effectively closing a significant loophole that allows data brokers to sell products with credit-report-like uses without FCRA's accuracy and dispute rights requirements. The Trump CFPB has signaled it will not finalize the rule. Litigation challenging the withdrawal of this NPRM is viable: under the Administrative Procedure Act, an agency's decision not to finalize a proposed rule is reviewable for arbitrariness if the decision is not accompanied by reasoned explanation responsive to the comment record. Consumer advocacy organizations and state AGs have standing to challenge the non-finalization.

**State insurance commissioner data broker regulation**: Insurance regulators in multiple states have authority over insurance-purpose uses of data. California Insurance Commissioner Ricardo Lara issued guidance in 2024 restricting insurance use of certain data broker products (credit-based insurance scores in auto insurance) without legislative action, using existing insurance code authority. Similar administrative actions by New York, Illinois, and Washington insurance regulators — who have political independence from the current federal environment — represent a parallel regulatory track that does not require federal legislative action.

---

### AI-4: State-Level Campaigns (Highest Leverage)

**Illinois BIPA defense and expansion (Spring 2026 session)**: Illinois BIPA's private right of action is the load-bearing beam of all major biometric privacy litigation in the US. The Illinois legislature has faced multiple industry campaigns to retroactively narrow BIPA — amending its per-violation damages to per-person damages (which would reduce liability by orders of magnitude), adding mandatory pre-suit notice requirements, and shortening the statute of limitations. Any weakening of BIPA's private right of action would eliminate the enforcement mechanism that has produced more damages for biometric privacy violations than all federal enforcement actions combined. The Illinois legislative session runs through May 2026. Organizations: ACLU of Illinois (aclu-il.org), Illinois Coalition for Fair Privacy (state-level coordination), Electronic Privacy Information Center.

**California CPPA rulemaking and budget advocacy**: The California Privacy Protection Agency's 2024 annual report documented that enforcement capacity is constrained by appropriations relative to complaint volume. California's FY 2026–2027 budget process (January–June 2026) is the pressure point for CPPA enforcement funding. The CPPA's maximum civil penalty authority ($7,988 per violation for knowing violations in 2025) is adequate; the constraint is investigator capacity. The gap between the 8,265 complaints received and the single-digit number of completed enforcement actions reflects the CPPA's understaffing, not lack of evidence. Budget advocacy through California legislature members, particularly Assembly and Senate privacy caucus members, is the highest-leverage intervention for strengthening state enforcement in 2026.

**Texas critical infrastructure surveillance litigation**: The ACLU of Texas and Texas Civil Rights Project are engaged in litigation challenging Texas DPS surveillance of immigrant communities and advocacy organizations. Texas law enforcement's use of commercial data broker products for pattern-of-life analysis of organizing activity at the Texas-Mexico border — documented in 2024-2025 investigative reporting — creates a state-law Fourth Amendment claim that, if successful, would establish precedent for government commercial data purchase limitations under state constitutional standards. Texas state courts apply their own constitution's Article I, Section 9 search and seizure clause, which some courts have interpreted more broadly than the federal Fourth Amendment. The litigation creates a circuit-split precursor: if Texas state courts restrict government data broker purchases under state law while federal courts remain unsettled, it creates pressure for federal legislative resolution.

**Minnesota and Washington state surveillance regulation**: Minnesota enacted a comprehensive privacy law (Minnesota Consumer Data Privacy Act, effective July 2025) that includes stronger provisions than many prior state laws: an opt-in consent requirement for all sensitive data processing (not limited to minors), a private right of action for data breach with statutory damages, and explicit coverage of employee and applicant data. Washington's My Health MY Data Act (effective June 2024) extends privacy protections to consumer health data outside HIPAA coverage — period-tracking data, fitness tracker health data, mental health app data — with a private right of action. Both laws are subject to preemption arguments if federal comprehensive legislation passes; until then, they represent the highest-protection state frameworks and are the models for federal minimum standards advocacy.

---

### AI-5: Organizations with Specific Roles

**Electronic Frontier Foundation** (eff.org) — Primary legislative intelligence source for Section 702 reform, RTB surveillance documentation, and Fourth Amendment Is Not For Sale Act tracking. EFF's Deeplinks blog provides the most current legislative status on surveillance bills. Contact for congressional correspondence campaigns: Action Center at eff.org/action.

**EPIC — Electronic Privacy Information Center** (epic.org) — Primary litigation docket tracking for FTC enforcement actions, FOIA requests on government data broker purchases, and PCLOB reconstitution litigation. EPIC has filed amicus briefs in major privacy cases including FTC v. Kochava and maintains the most comprehensive FTC enforcement case database. Subscribe to EPIC Alert for enforcement action updates.

**Demand Progress** (demandprogress.org) — Primary congressional pressure organization for Section 702 reform. Manages the coalition letter and constituent contact infrastructure for surveillance reform. Maintains the legislative whip count for Section 702 warrant amendment swing votes identified in AI-1.

**ACLU National — Speech, Privacy, and Technology Project** (aclu.org/surveillance) — Litigation lead for the major facial recognition wrongful arrest cases, Standing Rock surveillance documentation, and PCLOB firing legal challenges. ACLU SPT is the primary litigation vehicle for surveillance cases with constitutional Fourth and First Amendment dimensions.

**Fight for the Future** (fightforthefuture.org) — Primary digital mobilization infrastructure for commercial surveillance campaigns. Ran the campaign that produced significant constituent pressure on RISAA/Section 702 in 2024; managing ADPPA successor advocacy. Most effective for constituent email and phone campaigns to named swing-vote members.

**Center for Democracy and Technology** (cdt.org) — Primary technical and policy analysis on FDPA design, Section 702 warrant requirement implementation mechanics, and EU-US Data Privacy Framework adequacy. CDT's policy team engages directly with Senate Commerce Committee staff on privacy legislation; their written analyses are the most cited by committee staff drafting privacy bill language.

**National Immigration Law Center** (nilc.org) — Primary advocacy on data broker government sales restrictions from the immigration enforcement angle. NILC's documentation of the CBP/ICE warrantless location data purchase pipeline is cited in the 70-lawmaker demand letter from March 2026 and in DHS OIG complaint filings.

---

### AI-6: Five Time-Bounded 2026 Windows

**Window 1 — Section 702 reauthorization (April 2026, NOW)**: The April 20, 2026 expiration is the most immediate window. The outcome of this reauthorization — whether a warrant amendment is included, whether the program lapses briefly, or whether a clean extension passes — will determine the surveillance architecture for two to four more years. Swing-vote engagement (particularly libertarian Republicans identified above) is the primary mechanism. Organizations: EFF, Demand Progress, ACLU SPT.

**Window 2 — PCLOB reconstitution litigation (Spring–Fall 2026)**: District court decisions on the legality of the PCLOB firings could come within 2026, given the pace of administrative law litigation. If courts order reinstatement, the PCLOB could be functional again within months. Monitor: Lawfare, CDT, EPIC PCLOB litigation docket. The EU Parliament's P-000941/2025 inquiry and the European Commission's DPF adequacy monitoring create international diplomatic timeline pressure that runs in parallel.

**Window 3 — FY2027 appropriations markup (May–September 2026)**: The appropriations process for FY2027 includes the FTC's budget — and the FTC's privacy enforcement capacity is directly constrained by appropriations. Advocates can target the House Commerce, Justice, Science Appropriations Subcommittee (which funds the FTC) and the Senate Commerce, Justice, Science Subcommittee to add appropriations report language requiring the FTC to prioritize commercial surveillance enforcement and specifying minimum staffing for privacy enforcement. Report language is not legally binding but creates congressional oversight pressure on FTC leadership. The CPPA budget advocacy in California runs on a parallel state appropriations timeline.

**Window 4 — Illinois BIPA legislative session (through May 2026)**: The Illinois General Assembly's spring session runs through May 31, 2026. Industry campaigns to narrow BIPA are expected to resume. The critical votes are in the Illinois Senate Judiciary Committee (chaired by a Democrat) and on the Senate floor — the House has previously passed BIPA-narrowing amendments that stalled in the Senate. Constituent pressure on Illinois Senate Democrats from their home districts, coordinated through ACLU of Illinois and state-level labor coalitions (given BIPA's application to workplace biometric time-clocking), is the primary mechanism.

**Window 5 — State privacy law consolidation (2026 legislative sessions)**: Minnesota (MCDPA effective July 2025), Maryland (MODPA effective October 2026), and New Jersey (NJDPA passed 2024, effective January 2025) represent the newest cohort of state laws. Several states are in active legislative consideration of either new laws or amendments to existing laws: Kentucky, Missouri, and Ohio each have active bills as of April 2026. The industry preference in these states is for laws modeled on Virginia's VCDPA (no private right of action, weak enforcement) rather than Illinois BIPA or California CPPA. State-level advocacy should focus on the private right of action provision as the single most determinative structural variable — jurisdictions that include private rights of action generate enforcement outcomes; those that do not remain on paper.

---

*This document was prepared April 2026 for the Democratic Renewal Proposal evidence library. Sources are current as of April 2026. Litigation statuses should be verified for any use after June 2026.*
