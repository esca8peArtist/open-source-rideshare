# Open Source Rideshare: Research Report
**Date**: 2026-04-10  
**Purpose**: Assess whether viable open source rideshare infrastructure exists before starting a new project

---

## Executive Summary

The open source rideshare ecosystem is fragmented and mostly abandoned — with one major exception: **Namma Yatri** in India, which is a fully open source, production-deployed rideshare platform with 100M+ rides completed and forcing Uber and Ola to copy its model. No equivalent exists in the West. The Western cooperative attempts (Drivers Cooperative NYC) exist but are tech-starved and operationally weak. **There is no production-ready, deployable open source rideshare stack for a US/Western context.** The blocker is not technology — it's regulatory complexity, insurance liability, and driver network bootstrapping.

---

## Part 1: What Exists

### 1.1 LibreTaxi
- **GitHub**: [ro31337/libretaxi](https://github.com/ro31337/libretaxi) (~4.5K stars)
- **Status**: Dead. Last meaningful commit ~2017. No active development.
- **Model**: Works through Telegram bot — no native app. Passengers post ride requests; drivers respond; price negotiated in chat. Cash-only.
- **Stack**: Node.js, Firebase, Redis
- **Usability**: Proof-of-concept only. No driver tracking, no safety features, no payments, no ratings. Not deployable as a real service.
- **Verdict**: Historical curiosity. Not buildable-on.

### 1.2 Namma Yatri (Most Significant)
- **GitHub**: [nammayatri/nammayatri](https://github.com/nammayatri/nammayatri)
- **Status**: Active, production, ~100M rides completed as of mid-2025
- **Deployed in**: Bengaluru, Delhi, and other Indian cities
- **Model**: Zero-commission. Drivers pay a small flat subscription fee (~$1-2/day), keep 100% of fares. No surge pricing manipulation.
- **Stack**: Haskell backend (unusual choice), Beckn Protocol / ONDC open network, fully open source
- **Features**: Full rider/driver apps (Android/iOS), real-time matching, payments, ratings, open public data dashboard
- **Funding**: $11M raised (Google, Blume Ventures, Antler, 2024)
- **Metrics**: 100M+ rides, ₹1,600 crore (~$190M) in driver earnings, 5 lakh (500K) drivers, 1 crore (10M) riders
- **Business model**: Subscription-based platform fee, not profit-extracting commission
- **Key differentiator**: Built on **Beckn Protocol** — an open, decentralized mobility protocol, meaning any app can plug into the same driver/rider network (like HTTP for mobility)
- **Western applicability**: Significant re-work needed. Haskell stack is exotic. ONDC/Beckn is India-specific. Regulatory environment entirely different. But the architecture and zero-commission model are directly relevant.
- **Verdict**: The most important project in this space. Proves the model works at scale.

### 1.3 MOTIS Project
- **GitHub**: [motis-project/motis](https://github.com/motis-project/motis)
- **Status**: Active, maintained, used in Germany (NRW Mobidrom partnership, 2024)
- **Model**: Multimodal routing engine — walking, bike, car, transit, sharing mobility — not a full rideshare platform
- **Stack**: C++, REST API with OpenAPI spec, has a Flutter rideshare app companion
- **Features**: Routing, geocoding, map tiles, multi-modal trip planning. A rideshare Flutter app exists as a separate companion.
- **Usability**: Excellent as a routing/dispatch backend. Not a complete rideshare product — you'd build on top of it.
- **Verdict**: Strong infrastructure component for routing/dispatch. Not a turn-key solution.

### 1.4 Educational / Demo Projects
These exist in large numbers on GitHub and are not relevant for deployment:
- `amitshekhariitbhu/ridesharing-uber-lyft-app` — Android tutorial app, not a service
- `hypertrack/ridesharing-android` — HyperTrack SDK demo
- `jurajmajerik/rides` — full-stack simulation (Go/Node/React), for learning only
- Various carpooling/django apps — hobbyist projects, no production history

### 1.5 Adjacent Infrastructure (Worth Knowing)
- **Fleetbase** — open source logistics/fleet management platform. Not ride-hailing but shares dispatch primitives.
- **OpenStreetMap + Valhalla/OSRM** — open source map routing engines that can replace Google Maps for a serious deployment (significant cost reduction).
- **Beckn Protocol** — open mobility interoperability protocol. India's ONDC uses it. Could theoretically be used to build an open, federated rideshare network anywhere.

---

## Part 2: Non-Tech Cooperative Attempts (Western Context)

### 2.1 The Drivers Cooperative (NYC)
- **Status**: Operating but struggling. App stability issues reported in 2024 (crashes frequently).
- **Model**: Worker-owned cooperative. Drivers are equity members.
- **Performance**: $5.9M revenue in 2022, 162K trips, $5.2M paid to drivers. 9,000 driver members (~15% of NYC ride-hailing workforce).
- **Niche**: Has pivoted toward paratransit and non-emergency medical transport (NEMT) — lower competition, more predictable demand.
- **Problem**: Tech is an afterthought. The cooperative infrastructure is impressive but the app is chronically unreliable. They need an engineering team, not more drivers.
- **Verdict**: Proof the cooperative model can attract drivers. Proof that without solid tech, it stalls.

### 2.2 Minnesota Cooperative Attempts (2024)
- Several Uber/Lyft alternatives launched in Minneapolis in 2024 after the city raised minimum driver pay.
- Results were mixed — some launched, others delayed. No open source involvement noted.

---

## Part 3: What's Blocking Adoption

### 3.1 Regulatory / Legal (Hardest Blocker)
- Ride-hailing platforms in the US are licensed as **Transportation Network Companies (TNCs)** at the state level. Each state has different requirements.
- **Background checks**: Must use approved vendors (e.g., Checkr). Cannot self-certify.
- **Vehicle requirements**: Year, type, inspection standards vary by jurisdiction.
- **Driver licensing**: Commercial vs. personal — rules vary.
- A new platform must go through this in every market it enters. Uber spent years fighting these battles and had billions to do it.

### 3.2 Insurance (Second-Hardest Blocker)
- Standard personal auto insurance explicitly excludes ride-hailing activity.
- Platforms must provide **Period 1** (app on, no ride accepted), **Period 2** (ride accepted, en route), and **Period 3** (passenger in vehicle) coverage.
- Period 1 is the coverage gap most platforms struggle with.
- Commercial ride-hailing insurance is expensive and hard to source for small/new operators.
- Without insurance, drivers have no coverage and can't legally operate.
- Uber/Lyft spend hundreds of millions annually on insurance — this is a structural cost that doesn't scale down easily.

### 3.3 Driver Network Effects (Chicken-and-Egg)
- Riders won't use an app with long wait times.
- Drivers won't work an app with no rides.
- Uber solved this with massive subsidies ($40B+ in losses before profitability). Namma Yatri solved it by being the *only zero-commission app* in a market where drivers hated Uber/Ola commissions — a genuinely better deal for drivers bootstrapped supply.
- In the US, drivers already have Uber/Lyft income. Switching requires a significantly better deal AND enough passengers.

### 3.4 Payment Infrastructure
- Stripe/Braintree/etc. require business verification and terms compliance for marketplace payments (where you pay a third party, not yourself).
- Platform must handle: passenger payment → split with driver → driver payout → dispute resolution → refunds.
- This is solved but has compliance and fraud-risk overhead.
- Cash-only (LibreTaxi model) is a non-starter in the US market.

### 3.5 Mapping / Routing Costs
- Google Maps API at scale is expensive. Uber moved to its own mapping infra; Lyft uses OpenStreetMap + internal tools.
- A new platform can use OpenStreetMap + Valhalla/OSRM/MOTIS for free routing, but needs engineering to set it up and maintain it.
- This is **solvable** with open source tools — not a genuine blocker, just engineering work.

### 3.6 Real-Time Infrastructure
- WebSocket connections, GPS location streaming, sub-second matching — this requires serious backend engineering and cloud costs.
- Solvable with standard cloud services (AWS/GCP/Azure) but costs real money at scale.
- Not a *blocker*, but it's ongoing operational overhead that a small org must budget for.

### 3.7 Safety Features
- In-app emergency SOS, ride tracking shared with contacts, driver identity verification photos, trip recording.
- Regulatory requirements vary but passengers expect these from safety-critical transport.
- All implementable but non-trivial engineering effort.

### 3.8 Trust and Brand (Underrated)
- Riders trust Uber/Lyft because of brand recognition, reviews, and accountability.
- A new platform must establish equivalent trust — which takes time, incidents, and reputation management regardless of how good the tech is.

---

## Part 4: What Would It Take to Actually Deploy

### Minimal Viable Deployment (Small City / Cooperative)
A realistic deployment for a pilot market (1 city, 100-500 drivers):

| Component | Approach | Difficulty |
|---|---|---|
| Rider app (iOS + Android) | Fork Namma Yatri or build Flutter | Medium |
| Driver app (iOS + Android) | Same | Medium |
| Backend / matching engine | Fork Namma Yatri or Node.js + PostGIS | Hard (Haskell stack) |
| Routing / maps | OSRM or Valhalla on OSM data | Medium |
| Payments | Stripe Connect | Medium |
| Real-time infrastructure | WebSockets on AWS/GCP | Medium |
| Insurance | Commercial TNC policy | Very Hard / Expensive |
| TNC licensing | State-by-state | Hard |
| Driver recruitment | Community organizing | Hard |
| Customer support | Manual + tooling | Medium |

**Rough engineering estimate**: 6-12 months for a small team (3-5 engineers) to get to a pilot-ready state, assuming the regulatory and insurance pieces are handled in parallel by someone who knows what they're doing.

**Cost**: Aside from engineering salaries, ongoing infra for a small deployment is surprisingly low (cloud + OSM is cheap). Insurance and compliance are the budget-killers.

---

## Part 5: Assessment — Is This Worth Building?

### The Case For
- **No viable Western open source stack exists.** This is a real gap.
- **Namma Yatri proves the zero-commission model works** at massive scale. The demand for driver-favorable platforms is real.
- **Tech is not the hard part.** The hard part is regulatory/insurance/network bootstrapping — which means good software alone isn't enough, but it's a necessary precondition.
- **Cooperatives need better tech.** Drivers Cooperative NYC is hamstrung by a broken app. A solid open source stack donated to cooperative movements could unlock what they're already trying to do.
- **Beckn Protocol exists.** If a Western equivalent of ONDC emerged, open federated rideshare becomes dramatically more tractable.

### The Case Against
- **Regulatory/insurance complexity** means you can't just deploy software — you need legal, insurance, and lobbying infrastructure in every market. That's not a software project.
- **Network effects are brutal.** Uber/Lyft have density. Matching quality (wait times) degrades significantly with low driver density, and low density is where every competitor starts.
- **Namma Yatri's success was contextual.** Indian drivers actively despised Ola/Uber commissions and had a strong union to bootstrap supply. The US context is different — drivers are less organized, commissions are high but drivers are accustomed to them.

### Recommended Direction
Rather than building a new competing platform from scratch, the highest-leverage contribution would be:

1. **Build a clean, modern, Western-deployable open source rideshare stack** (rider app, driver app, backend, routing) that cooperative or municipal operators can fork and deploy.
2. **Target cooperatives as the customer** — they have driver supply and community trust but lack tech.
3. **Use Namma Yatri as the architectural reference** — zero-commission, open protocol, transparent data.
4. **Solve the insurance problem separately** — partner with insurance companies that serve TNCs, or document the requirements so cooperatives know what they need.
5. **Avoid building a platform** (i.e., don't try to be Uber). Build infrastructure that others can use to run platforms.

---

## Sources

- [Namma Yatri GitHub](https://github.com/nammayatri/nammayatri)
- [Uber and Ola are copying India's fast-growing ride-hailing app — Rest of World](https://restofworld.org/2025/uber-ola-copy-india-zero-commission-ride-hailing-app/)
- [Namma Yatri hits 100 million rides — Business Standard](https://www.business-standard.com/amp/companies/news/namma-yatri-hits-100-million-rides-enables-1-600-cr-driver-earnings-125060600641_1.html)
- [How Namma Yatri Outmaneuvered Ride-Hailing Giants — Blume VC](https://blume.vc/commentaries/code-community-and-capital-efficiency-how-namma-yatri-outmaneuvered-ride-hailing-giants)
- [LibreTaxi GitHub](https://github.com/ro31337/libretaxi)
- [MOTIS Project GitHub](https://github.com/motis-project/motis)
- [The Rise and Fall of NYC's Driver-Owned Ride-Share — Documented](https://documentedny.com/2024/10/07/forman-nyc-driver-cooperative-taxi-ride-share/)
- [Drivers Cooperative](https://drivers.coop/)
- [Namma Yatri — Open Pioneers](https://www.openpioneers.com/p/namma-yatri)
- [Ride-hailing · GitHub Topics](https://github.com/topics/ride-hailing)
- [Beckn Protocol and ONDC — Platform Cooperativism Consortium](https://platform.coop/blog/from-platforms-to-protocol/)
- [Commercial Ride-Sharing Insurance — NAIC](https://content.naic.org/insurance-topics/commercial-ride-sharing)
- [Drivers Cooperative Colorado — Nonprofit Quarterly](https://nonprofitquarterly.org/drivers-cooperative-colorado-building-a-social-co-op-for-rideshare-drivers/)
- [Minnesota Rideshare Alternatives 2024 — MinnPost](https://www.minnpost.com/business/2024/07/checking-in-with-minnesota-new-alternative-rideshare-companies-uber-lyft/)
