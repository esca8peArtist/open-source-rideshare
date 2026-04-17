# Beckn Protocol Interoperability — Research and Design Document

**Project**: OpenRide (open-source rideshare)
**Date**: 2026-04-17
**Status**: Research / Pre-decision
**Author**: Design research for community review

---

## 1. What Is Beckn Protocol?

Beckn is an open, decentralized protocol for digital commerce. The core idea is that any buyer-side application can discover and transact with any seller-side platform without both parties being on the same proprietary platform, and without a central aggregator brokering the connection.

The canonical analogy: HTTP allowed any browser to talk to any web server. SMTP allowed any email client to send to any mail server. Beckn aims to do the same for commerce transactions — define a message format and handshake sequence so that buyer apps and seller apps can interoperate without bilateral integration agreements.

**Current spec version**: Beckn Protocol Core Specification 1.x (1.0.0 is the published stable version as of this writing). The mobility-specific extension layer (the "Beckn Mobility" domain specification) builds on top of the core with ride-hailing-specific schemas for fulfillment states, vehicle categories, and fare structures.

**Governance**: Beckn Protocol Foundation (Linux Foundation collaborative project). Not controlled by any single company or government.

**Key adoption**: India's Open Network for Digital Commerce (ONDC), where Beckn is the underlying protocol layer. Namma Yatri, Ola, and others participate as BPPs. Any ONDC-compliant buyer app can book rides from any participating driver network without separate integration.

---

## 2. Architecture: BAP, BPP, BG

The protocol defines three participant roles. Every transaction involves at least two of them, and typically all three during discovery.

### 2.1 BAP — Beckn Application Provider (buyer side)

The BAP is the consumer-facing application. It formulates search intents, sends them into the network, collects responses from multiple BPPs, presents options to the user, and handles the transaction flow on the user's behalf.

In ride-hailing terms: a map app, a super-app (like Google Maps or PayTM), or a standalone rideshare app acting as the rider interface. The BAP does not have its own driver fleet. It discovers driver supply from one or more BPPs.

**The BAP does not need to know about any specific BPP in advance.** It broadcasts a search intent to the network; BPPs that can fulfill it respond.

### 2.2 BPP — Beckn Provider Platform (seller side)

The BPP is the service provider. It has supply — drivers, vehicles, availability — and responds to search requests with catalog items (available rides), handles select/init/confirm to move toward a booking, and manages fulfillment state transitions throughout the ride.

In ride-hailing terms: a platform with a driver pool. Namma Yatri is a BPP. A taxi cooperative running our platform would be a BPP.

**The BPP does not need to know about any specific BAP in advance.** It publishes its presence to the registry and responds to any conformant search request.

### 2.3 BG — Beckn Gateway (network infrastructure)

The BG is the routing layer. During the search phase, a BAP sends its intent to the BG, which fans the request out to all registered BPPs that match the domain and location criteria. BPPs respond directly back to the BAP (not through the BG). The BG's role ends after discovery — select/init/confirm/status messages go BAP-to-BPP directly.

**OpenRide does not need to run a BG.** A shared BG is operated by the network (in India, ONDC runs this infrastructure). If a Western equivalent emerges, we connect to it.

### 2.4 Registry

A central registry (operated per network, e.g., ONDC registry for India) stores subscriber records for all BAPs, BPPs, and BGs, with their public keys and endpoint URLs. All participants register here. Message authentication uses Ed25519 signatures verified against the registry.

---

## 3. Transaction Flow

All communication is asynchronous. When a BAP sends a `search`, it does not block waiting for a response — the BPP calls back via a separate `on_search` request to the BAP's callback URL. This is important for implementation: our adapter must handle both outbound and inbound HTTP.

The standard flow for a ride booking:

```
BAP                    BG                   BPP (us)
 |                      |                      |
 |-- search ----------->|                      |
 |                      |-- search (fan-out) -->|
 |                      |                      | (match drivers, build catalog)
 |<--------------------------------------------| on_search
 |                      |                      |
 |-- select ---------------------------------->| (user picks an option)
 |<--------------------------------------------| on_select (fare quote, ETA)
 |                      |                      |
 |-- init  ---------------------------------->| (provide billing/rider info)
 |<--------------------------------------------| on_init (draft order, payment terms)
 |                      |                      |
 |-- confirm -------------------------------->| (commit to the ride)
 |<--------------------------------------------| on_confirm (order confirmed, driver assigned)
 |                      |                      |
 |-- status  -------------------------------->| (poll for updates)
 |<--------------------------------------------| on_status (fulfillment state)
 |                      |                      |
 |-- track   -------------------------------->| (request live location)
 |<--------------------------------------------| on_track (location URL/stream)
 |                      |                      |
 |-- cancel  -------------------------------->| (if rider cancels)
 |<--------------------------------------------| on_cancel
```

Updates can also be pushed proactively by the BPP via `on_update` without a BAP `update` request — this is how real-time state changes (driver arrived, trip started, trip completed) would reach the rider app.

---

## 4. How Beckn Is Already Used in Ride-Hailing

### 4.1 India/ONDC

ONDC (Open Network for Digital Commerce) launched its mobility layer in 2023. Namma Yatri was the first major participant, initially in Bengaluru then expanding to Chennai, Hyderabad, Delhi, and other cities. By early 2024, Namma Yatri had processed over 28 million rides.

The key property Beckn gives Namma Yatri: **a driver registered with Namma Yatri is discoverable to any ONDC-compliant buyer app** — not just the Namma Yatri app. This creates immediate network effects in the supply side. A driver joining the cooperative is effectively joining the entire ONDC mobility network, not just one app's user base.

Ola also participates in ONDC as a BPP, meaning Ola drivers are bookable through third-party BAP apps. The competitive effect is significant: driver supply becomes a shared network resource rather than a proprietary moat.

### 4.2 European Interest

Paris and Amsterdam have explored adopting Beckn for interoperable urban mobility. This is at the policy/pilot stage as of 2026, not production. The Beckn Protocol Foundation has been actively working to expand beyond India.

### 4.3 Beckn Onix (November 2025)

Beckn Labs and Google Cloud launched Beckn Onix, an open-source deployment toolkit for standing up Digital Public Infrastructure using Beckn Protocol. This lowers the barrier to deploying Beckn-compliant networks in new geographies. A Western open mobility network using this infrastructure is feasible within a 2-3 year horizon.

### 4.4 Current Western Status

As of April 2026, there is no production Western Beckn mobility network to connect to. ONDC is live only in India. This is a critical constraint for the implementation decision: building BPP compliance now means building infrastructure for a network that does not yet exist in our target markets. The capability would pay off when (not if) a Western network emerges, but there is no immediate rider volume to unlock.

---

## 5. Schema Mapping: OpenRide Models to Beckn

### 5.1 Search Intent

When a BAP sends a `search` for a ride, the message body contains an `intent` object describing what the rider wants.

| Beckn `search.message.intent` field | OpenRide equivalent | Notes |
|---|---|---|
| `fulfillment.type` | `"RIDE"` (fixed for us) | Beckn mobility spec defines RIDE, DELIVERY, etc. |
| `fulfillment.start.location.gps` | `RideRequest.pickup.lat,lng` | `"lat,lng"` string format |
| `fulfillment.start.location.address` | `RideRequest.pickup_address` | Optional; we can provide |
| `fulfillment.end.location.gps` | `RideRequest.dropoff.lat,lng` | |
| `fulfillment.end.location.address` | `RideRequest.dropoff_address` | |
| `fulfillment.vehicle.category` | `RideRequest.vehicle_type_preference` | See vehicle mapping below |
| `fulfillment.tags` (accessibility) | `RideRequest.accessibility_required` | Beckn uses tags for extended attributes |
| `fulfillment.start.time.timestamp` | `RideRequest` (immediate) or `ScheduleRideRequest.scheduled_for` | For scheduled rides |
| `payment.params.amount` | Not in search intent — emerges in `on_search` | Rider requests; we respond with fare |

**Vehicle category mapping** (Beckn mobility spec uses string tags):

| OpenRide `VehicleServiceCategory` | Beckn vehicle category string |
|---|---|
| `STANDARD` | `"STANDARD"` |
| `COMFORT` | `"COMFORT"` |
| `XL` | `"SUV"` |
| `PREMIUM` | `"PREMIUM"` |
| `WAV` | `"WHEELCHAIR_ACCESSIBLE"` |

### 5.2 Provider and Agent (Driver)

When we respond to a `search` with `on_search`, our response includes a `catalog` containing `providers`. Each provider is us (the cooperative), containing `items` (ride options) and `fulfillments` that describe available drivers.

| Beckn `Provider` field | OpenRide equivalent | Notes |
|---|---|---|
| `id` | Operator's registered Beckn subscriber ID | Assigned at network registration |
| `descriptor.name` | Cooperative operator name | e.g., "Drivers Cooperative NYC" |
| `descriptor.short_desc` | Operator tagline | |
| `rating` | Derived from driver pool avg rating | Aggregate; individual driver rating is in `Agent` |
| `locations[].gps` | Driver's `current_location` (PostGIS POINT) | Nearest available driver location |

The `fulfillment.agent` represents the individual driver:

| Beckn `Agent` field | OpenRide equivalent | Notes |
|---|---|---|
| `person.name` | `User.name` (driver's) | Disclosed after `confirm` only |
| `rating` | `DriverProfile.rating_avg` | |
| `tags` (vehicle info) | `DriverProfile.vehicle_make/model/year/color/license_plate` | Disclosed after `confirm` |
| `contact.phone` | `User.phone` | Disclosed after `confirm` only |

**Privacy note**: Beckn's spec does not specify when to disclose agent details, but the convention (and the correct choice) is to withhold driver PII from `on_search` and `on_select` responses. Reveal name, phone, and plate only in `on_confirm` after the booking is committed. This aligns with our existing data model where driver details are only surfaced to matched riders.

### 5.3 Item (Ride Option)

In Beckn, an `item` in the catalog represents a purchasable service. For rides, each item is a ride option (standard, comfort, WAV, etc.) available right now.

| Beckn `Item` field | OpenRide equivalent | Notes |
|---|---|---|
| `id` | Generated per-search UUID | Items are ephemeral — they represent current availability, not persistent records |
| `descriptor.name` | `VehicleServiceCategory` label | e.g., "Standard", "WAV" |
| `price.currency` | `"USD"` (or operator-configured) | `FareEstimateResponse.currency` |
| `price.value` | `FareEstimateResponse.estimated_fare` | Run our pricing engine to compute |
| `price.maximum_value` | Fare estimate + buffer | Handles route variance |
| `fulfillment_ids[]` | References `Fulfillment.id` | Links item to a specific fulfillment/driver |
| `tags` (ETA) | Computed by matching engine + OSRM | ETA to pickup in minutes |
| `tags` (fare breakdown) | `FareBreakdownResponse` fields | Base, distance, time, multiplier — expose for transparency |

### 5.4 Order (Ride)

After `confirm`, the BPP creates an `Order`. This maps directly to our `Ride` model.

| Beckn `Order` field | OpenRide `Ride` field | Notes |
|---|---|---|
| `id` | `Ride.id` (as string) | |
| `state` | `Ride.status` | See fulfillment state mapping below |
| `provider.id` | Operator subscriber ID | |
| `items[0].id` | Selected item ID from search | |
| `fulfillment.id` | `Ride.id` or a separate fulfillment UUID | |
| `fulfillment.state.descriptor.code` | `RideStatus` enum | See below |
| `fulfillment.start.location.gps` | `Ride.pickup_location` | |
| `fulfillment.end.location.gps` | `Ride.dropoff_location` | |
| `fulfillment.start.time.timestamp` | `Ride.started_at` | Actual start |
| `fulfillment.end.time.timestamp` | `Ride.completed_at` | |
| `payment.status` | `Payment.status` | |
| `payment.params.amount` | `Payment.amount` | |
| `payment.params.transaction_id` | `Payment.stripe_payment_intent_id` | |

### 5.5 Fulfillment State Machine

Beckn defines fulfillment states as descriptor codes. Mapping our `RideStatus` enum:

| OpenRide `RideStatus` | Beckn fulfillment `state.descriptor.code` | Triggered by |
|---|---|---|
| `REQUESTED` | `"RIDE_REQUESTED"` | `on_confirm` |
| `MATCHED` | `"DRIVER_ASSIGNED"` | Our matching engine assigns a driver |
| `DRIVER_EN_ROUTE` | `"DRIVER_EN_ROUTE"` | Driver accepts and starts navigation |
| `ARRIVED` | `"DRIVER_ARRIVED"` | Driver marks arrived at pickup |
| `IN_PROGRESS` | `"RIDE_STARTED"` | Driver starts trip |
| `COMPLETED` | `"RIDE_COMPLETED"` | Driver completes trip |
| `CANCELLED` | `"RIDE_CANCELLED"` | Either party cancels |

Each state transition would be communicated to the BAP via a proactive `on_update` callback from our BPP adapter.

### 5.6 Payment

Beckn's payment model has two modes: `ON-ORDER` (payment collected by the BAP before the ride) and `POST-FULFILLMENT` (payment collected after). For our platform, the flow is `POST-FULFILLMENT` — the rider's card is charged after trip completion via Stripe.

In the Beckn context, payment settlement between the BAP and BPP (if they are different entities) is handled off-protocol — Beckn specifies payment parameters and status but does not process money. If we are both the BPP and the rider uses our own app (no external BAP), we handle payment ourselves as today. If a third-party BAP is involved, the payment terms and settlement must be negotiated in the network agreement.

### 5.7 Cancellation

Beckn's `cancel` action maps to our existing cancel flow:

| Beckn `cancel` field | OpenRide equivalent |
|---|---|
| `order_id` | `Ride.id` |
| `cancellation_reason_id` | `CancelRequest.reason` |
| `descriptor.code` | Reason code (RIDER_CANCELLED, DRIVER_CANCELLED, etc.) |

Our existing `CancelResponse` with `cancellation_fee` and `payment_required` maps to Beckn's cancellation terms, which can be embedded in the `on_init` response as a `cancellation_terms` policy.

---

## 6. Integration Architecture: Should We Be BPP, BAP, or Both?

### 6.1 The Case for BPP Only

**BPP (seller side) is the natural fit for OpenRide.** We have drivers. We provide rides. When a rider uses any Beckn-compliant app — whether our own rider app, a government mobility super-app, or a third-party map app — they can discover and book our drivers.

Being a BPP means:
- Our driver pool is discoverable across the entire Beckn network, not just to users of our own app
- Every new BAP that joins the network is a free acquisition channel for our driver-side supply
- Cooperative operators can tell their drivers: "Join us and you'll be visible to every app on the network"

This is exactly the model Namma Yatri uses — they are a BPP on ONDC, and their drivers are bookable through any ONDC-compliant BAP.

### 6.2 The Case for BAP + BPP

If OpenRide is also a BAP, our rider app could aggregate drivers from multiple BPPs — not just our own cooperative's drivers. This is appealing for markets where we have rider demand but thin driver supply. A rider using the OpenRide app could see drivers from our cooperative and from any other Beckn BPP in the area.

However, this creates tension with our cooperative model. If our rider app routes rides to non-cooperative drivers from other platforms, we are building something closer to an aggregator than a pure cooperative tool. The growth strategy document explicitly frames our platform as "infrastructure for cooperatives" — a BAP-only or BAP-dominant mode risks drifting toward becoming an aggregator.

A reasonable middle position: **BPP first, with a limited BAP capability** for fallback coverage in launch markets where our own driver density is insufficient. The BAP role should be treated as a temporary supply supplement, not a core product direction.

### 6.3 Recommended Role: BPP Primary

For Phase 1 and Phase 2, OpenRide should implement Beckn primarily as a BPP. The rider app communicates directly with our own API (as it does today). The Beckn BPP adapter is an additional interface layer that makes our driver pool visible to external BAPs.

When a Western Beckn network exists, cooperative operators running our platform automatically gain network-wide driver discoverability by virtue of being registered BPPs. This is a meaningful long-term benefit with no ongoing cost once the adapter is built.

---

## 7. Implementation Architecture

### 7.1 Adapter Pattern

The right approach is a dedicated Beckn adapter module sitting alongside the existing FastAPI application. The adapter translates between Beckn's protocol messages and OpenRide's internal service layer. Core business logic (matching, pricing, dispatch, trip management) does not change — the adapter is purely a protocol translation layer.

```
External BAP
     |
     | (Beckn HTTP callbacks)
     |
[ Beckn Adapter — new module ]
     |           |
     |           | (translate to/from internal schemas)
     |           |
[ Existing OpenRide services ]
  matching.py  pricing.py  trips.py  payments.py
     |
[ PostgreSQL / Redis / OSRM ]
```

The adapter module would live at `backend/app/beckn/` and expose a sub-application mounted at `/beckn/` in FastAPI. This keeps Beckn routing entirely separate from the existing REST API at `/api/v1/`.

### 7.2 New Endpoint Surface

All Beckn endpoints are HTTP POST. The BPP receives inbound calls from BAPs and must make outbound callback calls to BAPs' registered callback URLs.

**Inbound (BPP receives from BAP)**:

| Beckn action | Our endpoint | Internal service call |
|---|---|---|
| `POST /beckn/search` | Receive search intent | `pricing.estimate()`, `matching.find_available_drivers()` |
| `POST /beckn/select` | Rider selects a quoted option | Soft-lock on driver candidate |
| `POST /beckn/init` | Rider provides billing info | Validate, return cancellation terms |
| `POST /beckn/confirm` | Rider confirms booking | `trips.create_ride()`, `matching.dispatch()` |
| `POST /beckn/status` | BAP polls for order status | Query `Ride.status` |
| `POST /beckn/track` | BAP requests live location | Return Redis driver location |
| `POST /beckn/cancel` | Rider cancels | `trips.cancel_ride()` |
| `POST /beckn/update` | BAP requests order update | Handle mid-ride changes (rare) |

**Outbound (BPP calls BAP callback URLs)**:

The adapter must maintain a queue of outbound callbacks. When internal trip state changes, the adapter fires `on_update` to the BAP that holds that order.

| Internal event | Outbound Beckn call |
|---|---|
| Driver assigned | `on_confirm` (if pending) or `on_update` with `DRIVER_ASSIGNED` |
| Driver en route | `on_update` with `DRIVER_EN_ROUTE` |
| Driver arrived | `on_update` with `DRIVER_ARRIVED` |
| Trip started | `on_update` with `RIDE_STARTED` |
| Trip completed | `on_update` with `RIDE_COMPLETED` |
| Ride cancelled | `on_cancel` or `on_update` with `RIDE_CANCELLED` |

### 7.3 Authentication

All Beckn messages are signed with Ed25519 keys. The sender signs the request body; the receiver verifies against the sender's public key fetched from the registry. Our adapter needs:

1. A key pair generated at registration time
2. Request signing on all outbound callbacks
3. Signature verification on all inbound requests (reject unsigned or invalid requests)
4. Registry lookup (or cached registry records) for each participant

This is non-trivial but well-specified. The Beckn community maintains reference implementations. We should use or adapt an existing Python signing library rather than implementing cryptography from scratch.

### 7.4 Asynchronous Response Pattern

Because all Beckn interactions are async, our adapter cannot use standard request-response HTTP handlers for the outbound callbacks. When a BAP sends `confirm`, we must:

1. Acknowledge receipt immediately with HTTP 200 and an ACK body
2. Perform the actual booking work asynchronously
3. Fire `on_confirm` to the BAP's callback URL once the work is done

This requires a task queue. We already have Redis; we can use it for a lightweight async task queue (or integrate Celery, which is the standard FastAPI async task approach). The existing WebSocket event system handles real-time updates internally — the Beckn adapter needs an equivalent async pathway for outbound HTTP callbacks.

### 7.5 Context Object

Every Beckn message includes a `context` envelope:

```json
{
  "domain": "mobility:ride-hailing",
  "action": "search",
  "version": "1.0.0",
  "bap_id": "buyer-app.example.com",
  "bap_uri": "https://buyer-app.example.com/beckn",
  "bpp_id": "openride-cooperative.example.com",
  "bpp_uri": "https://openride-cooperative.example.com/beckn",
  "transaction_id": "<uuid>",
  "message_id": "<uuid>",
  "timestamp": "2026-04-17T12:00:00Z",
  "ttl": "PT30S"
}
```

The adapter must extract `bap_id` and `bap_uri` from incoming messages to know where to send callbacks. Transaction IDs and message IDs must be tracked to prevent replay attacks and to correlate async responses.

### 7.6 Registry Integration

To participate in a Beckn network, our operator must:
1. Register as a BPP subscriber with the network's registry
2. Submit: subscriber ID, domain (`mobility:ride-hailing`), endpoint URL, public key
3. Pass network compliance checks (spec conformance tests)

Each cooperative operator running our platform would register as a separate BPP subscriber. The adapter configuration must support per-deployment credentials — not hardcoded.

---

## 8. What Would Not Change

Implementing a Beckn BPP adapter does not require modifying:

- The existing REST API at `/api/v1/` — rider and driver apps continue working exactly as today
- The matching engine — it receives ride requests from the adapter the same way it receives them from the REST API
- The pricing engine — the adapter calls it for fare estimates
- The trip state machine — `RideStatus` transitions are unchanged
- The payment system — Stripe integration is unchanged; Beckn does not touch money flow
- The driver app — drivers see ride requests and manage trips identically
- PostgreSQL schema — no new columns needed for the adapter; at most a new table to track Beckn transaction IDs and callback URLs

The adapter is additive, not transformative.

---

## 9. Tradeoffs

### 9.1 Benefits

**Decentralized network effects**: In markets where a Beckn mobility network exists, our drivers become visible to every BAP in that network. This is rider-side acquisition without rider-side marketing spend. In India, Namma Yatri's rider base grew substantially because ONDC BAPs could surface their drivers. The same dynamic would apply in any Western market that adopts Beckn.

**Multi-city federation**: The growth strategy document mentions "federated open protocol" as a long-term competitive moat. Beckn is exactly that protocol. If multiple US cooperatives deploy OpenRide and all register as BPPs on a shared network, a rider in Boston could book a driver registered in NYC through the same BAP. This solves inter-city roaming without us building any inter-platform infrastructure.

**Values alignment**: Beckn is built by the same community that values open, non-exploitative digital commerce. Participating signals alignment with the broader open mobility movement, which helps with cooperative operator trust and community credibility.

**Alignment with Namma Yatri's proven model**: Our growth strategy explicitly names Namma Yatri as the reference implementation. Namma Yatri's Beckn integration is a core part of why their model works — drivers gain multi-app discoverability without multi-app registration. Building Beckn support puts us architecturally in line with the only proven zero-commission rideshare at scale.

**India market entry**: If a cooperative operator wanted to deploy OpenRide in India (where Beckn/ONDC is live), we would be immediately network-compatible without additional integration work.

**Open source credibility**: Being Beckn-compliant is a strong differentiator in the open infrastructure space. It demonstrates we are building a genuine protocol-first platform, not another silo.

### 9.2 Costs and Risks

**No immediate Western network to connect to**: This is the biggest near-term constraint. Building a BPP adapter today produces zero additional rides until a Western Beckn mobility network exists. The engineering investment would sit dormant. However, the adapter's incremental maintenance cost once built is low, so the question is more about when to build it than whether.

**Spec complexity**: Beckn 1.x is reasonably well-specified but the mobility domain extension has gaps and ambiguities. The India ecosystem has resolved many of these through implementation experience that is documented in Namma Yatri's open-source codebase, but a Western deployment may encounter edge cases without community precedent. Staying in spec compliance across version updates requires ongoing attention.

**Async callback infrastructure**: The outbound callback requirement is architecturally more complex than a standard REST API. It requires reliable async task execution, retry logic, dead letter handling, and monitoring of callback delivery. This is non-trivial to build robustly. Getting this wrong means dropped order status updates, which is a user-facing reliability failure.

**Authentication complexity**: Ed25519 request signing and registry integration adds operational surface area — key rotation, registry reachability, signature verification bugs. This is well-trodden territory but it is new infrastructure to maintain.

**Multi-party payment settlement**: If a third-party BAP books rides on our platform, there must be a payment settlement agreement between the BAP operator and the cooperative operator. Beckn does not specify settlement terms — those are bilateral agreements. This is fine for Phase 1 (we control our own rider app), but adds commercial complexity if real third-party BAPs are involved.

**Versioning maintenance**: As the Beckn mobility spec evolves (1.x to eventual 2.x), we would need to maintain spec compliance. This is manageable but must be budgeted as ongoing work, not a one-time build.

---

## 10. Decision Recommendation

### 10.1 Should We Build Beckn Support?

**Yes, but not in Phase 1.**

The values alignment is strong, the architectural fit is clean, and the long-term network effects are real. This is not a question of whether — it is a question of when the investment is rational.

In Phase 1, the priority is getting one cooperative operator's drivers and riders onto a working platform in one city. Adding Beckn BPP compliance before there is a Western network to connect to creates implementation complexity and maintenance burden with zero rider-side benefit during the most critical period (cold start). Every engineering hour in Phase 1 should go toward matching reliability, payment correctness, driver app usability, and deployment simplicity.

### 10.2 Recommended Phasing

**Phase 1 (MVP, current)**: No Beckn work. Close the architecture document's open question with "deferred to Phase 2." Keep the data models and service interfaces clean so the adapter can be added later without rearchitecting. The existing `rides`, `driver_profiles`, `payments` models map cleanly to Beckn schemas — no schema changes are needed now to enable future Beckn work.

**Phase 2 (second market / platform maturity)**: Build the Beckn BPP adapter as a standalone module. Target: register one cooperative operator as a BPP on the ONDC network (India) or whatever Western Beckn mobility network exists by then. This proves out the implementation before it matters for Western markets.

**Phase 3 (network effects)**: If a US or European Beckn mobility network emerges, existing cooperative operators running OpenRide already have a working BPP implementation. They register and gain network-wide driver discoverability with no additional work on their part.

### 10.3 Design Decisions to Make Now (At No Cost)

Regardless of when we build the adapter, these decisions should be made now and documented:

1. **Operator = BPP subscriber**: Each cooperative operator running OpenRide registers as a separate BPP. The adapter must support per-deployment Beckn credentials in the config layer. This is compatible with the existing `config.py` / `BaseSettings` approach.

2. **Clean internal interfaces**: The matching, pricing, and trip services should remain callable from the adapter without modification. Avoid tight coupling to the REST API layer in service logic.

3. **Transaction ID storage**: Reserve a `beckn_transactions` table concept for Phase 2 — it will need to store `transaction_id`, `bap_id`, `bap_uri`, `ride_id`, and callback state. No need to build it now, but noting the design.

4. **No BAP role in Phase 1 or 2**: The rider app talks to our own API. We do not build rider-side BAP aggregation. This can be revisited if cooperative operators in markets with thin driver supply want it, but it should be an explicit opt-in, not a default.

---

## 11. Related Resources

- [Beckn Protocol Core Specification](https://becknprotocol.io/core-specifications/)
- [Beckn Developers Documentation](https://developers.becknprotocol.io/)
- [Beckn Mobility Schema Reference](https://developers.becknprotocol.io/docs/mobility-specification/schema-reference/)
- [Namma Yatri GitHub](https://github.com/nammayatri/nammayatri) — production Beckn BPP reference in Haskell
- [Beckn Protocol Specifications (GitHub)](https://github.com/beckn/protocol-specifications)
- [ONDC Namma Yatri announcement](https://www.ondc.org/blog/all-you-need-to-know-about-namma-yatri-the-ondc-backed-auto-hailing-app-launched-in-delhi/)
- [Paris/Amsterdam Beckn exploration](https://medial.app/news/paris-amsterdam-look-to-adopt-nandan-nilekani-backed-beckn-protocol-for-interoperable-mobility-f0fb515783161)
- [Beckn Onix / Google Cloud partnership](https://www.googlecloudpresscorner.com/2025-11-03-Beckn-Labs-and-Google-Cloud-Partner-to-Accelerate-the-Adoption-of-Open-Networks-Worldwide-with-Beckn-Onix)

---

## Appendix: Open Questions for Community

1. **Network bootstrapping**: If no Western Beckn network exists, should we work with other open-source mobility projects (e.g., LibreRide, any future EU projects) to co-found a Western Beckn registry? This is a governance question beyond our engineering scope alone.

2. **India deployment**: Is there a cooperative operator in India interested in deploying OpenRide? If so, ONDC compatibility becomes Phase 1-relevant for that deployment, not Phase 2. The adapter should be designed to be deployable per-operator, not per-platform.

3. **BAP for supply fallback**: Should the Phase 2 rider app have an optional BAP mode that shows riders available drivers from other Beckn BPPs when our own driver pool has no nearby drivers? This improves rider experience during cold start but muddies the cooperative-only positioning. Community input welcome.

4. **Payment settlement with third-party BAPs**: If a third-party BAP (e.g., a city mobility app) routes rides to our cooperative, who settles the fare? The cooperative collects from the rider via the BAP's payment flow, then pays the driver. Net terms and the platform's role need to be defined before any real BAP partnership.

5. **Spec version commitment**: The mobility domain spec has had relatively slow iteration. Should we commit to a specific spec version (e.g., 1.0.0) and maintain it, or track the latest? Tracking latest is operationally expensive; pinning to a version risks incompatibility as the network evolves.
