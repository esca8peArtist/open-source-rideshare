# OpenRide Architecture

**Version**: 0.1.0 (draft)
**Date**: 2026-04-11
**Status**: Pre-implementation — this document defines the target architecture

---

## Design Philosophy

OpenRide is **infrastructure for cooperatives**, not a competing platform. The goal is a clean, modern, deployable open source rideshare stack that cooperative or municipal operators can fork and run. We don't try to be Uber — we build the tools so others can serve their communities.

**Core principles**:
1. **Zero-commission model** — operators set flat subscription fees or minimal per-ride fees, not percentage-based commissions
2. **Cooperative-first** — designed for worker-owned, community-owned, or municipal operation
3. **Low operational cost** — minimize cloud spend, use open source mapping, avoid vendor lock-in
4. **Regulatory-aware** — built-in support for TNC compliance requirements across US jurisdictions
5. **Privacy-respecting** — collect only what's needed, encrypt at rest, no data monetization

---

## System Overview

```
┌─────────────┐  ┌─────────────┐  ┌─────────────┐
│  Rider App  │  │ Driver App  │  │  Admin Web  │
│  (Flutter)  │  │  (Flutter)  │  │   (React)   │
└──────┬──────┘  └──────┬──────┘  └──────┬──────┘
       │                │                │
       └────────┬───────┴────────┬───────┘
                │                │
         ┌──────┴──────┐  ┌─────┴──────┐
         │   REST API  │  │ WebSocket  │
         │  (FastAPI)  │  │  (FastAPI) │
         └──────┬──────┘  └─────┬──────┘
                │               │
       ┌────────┴───────────────┴────────┐
       │         Core Services           │
       │  ┌──────────┐ ┌──────────────┐  │
       │  │ Matching  │ │   Routing    │  │
       │  │  Engine   │ │   (OSRM)    │  │
       │  ├──────────┤ ├──────────────┤  │
       │  │ Pricing   │ │  Payments    │  │
       │  │  Engine   │ │(Stripe Con.) │  │
       │  ├──────────┤ ├──────────────┤  │
       │  │  Trip     │ │  Safety &    │  │
       │  │ Manager   │ │  Compliance  │  │
       │  └──────────┘ └──────────────┘  │
       └────────────────┬────────────────┘
                        │
              ┌─────────┴─────────┐
              │  PostgreSQL/PostGIS │
              │  + Redis (cache)   │
              └────────────────────┘
```

---

## Tech Stack

### Backend: Python (FastAPI)

**Why FastAPI over alternatives**:
- Async-native — essential for real-time location streaming and WebSocket connections
- Automatic OpenAPI docs — makes the API self-documenting for contributors and cooperative operators
- Python has the largest contributor pool of any language — critical for an open source project targeting cooperatives who may not have deep engineering teams
- Type hints + Pydantic validation reduce bugs at the boundary layer
- Excellent ecosystem for geospatial (Shapely, GeoPandas), ML (if we add demand prediction later), and data processing

**Not Haskell** (Namma Yatri's choice): exotic, tiny contributor pool, hostile to cooperative dev teams.
**Not Go**: better performance but smaller contributor base and less ecosystem for geospatial.
**Not Node.js**: viable alternative but Python wins on geospatial tooling and data science ecosystem.

### Mobile Apps: Flutter (Dart)

- Single codebase for iOS and Android
- Excellent map integration (via maplibre_gl or flutter_map)
- Good enough performance for rideshare (not a game, not a video editor)
- Growing contributor community
- **Two apps**: `rider_app/` and `driver_app/` — separate binaries, shared core library

### Admin Dashboard: React + TypeScript

- Vite-based SPA for cooperative operators
- Features: driver management, trip monitoring, analytics, compliance reporting, pricing configuration
- Connects to same REST API as mobile apps

### Database: PostgreSQL + PostGIS

- PostGIS for geospatial queries (nearest-driver, pickup zones, surge areas, geofencing)
- JSONB columns for flexible per-jurisdiction compliance data
- Proven at scale, excellent open source tooling
- **Migrations**: Alembic (Python)

### Cache / Real-time State: Redis

- Driver location cache (updated every 3-5 seconds, TTL 30s)
- Active trip state
- Rate limiting
- Pub/sub for real-time events between API instances

### Routing: OSRM (Open Source Routing Machine)

- Self-hosted on OpenStreetMap data
- Free, no API costs, no vendor lock-in
- ETA calculations, turn-by-turn directions, distance/duration matrices
- Can be swapped for Valhalla if needed (similar interface)
- Containerized — operators run it alongside the backend

### Maps (Client-side): MapLibre GL

- Open source fork of Mapbox GL JS
- Free vector tile rendering
- Works with free tile sources (OpenMapTiles, Protomaps)
- No per-request API fees

### Payments: Stripe Connect

- Marketplace payment splitting (rider pays → platform takes fee → driver receives payout)
- Handles KYC/identity verification for drivers
- Supports instant payouts to driver bank accounts
- Well-documented, available in most Western markets
- **Abstraction layer**: payments are behind an interface so operators could swap in a different processor

### Authentication

- JWT tokens (access + refresh)
- Phone number verification via SMS (Twilio or equivalent — behind an interface)
- OAuth2 social login optional
- Driver identity verification as a separate compliance flow

### Infrastructure / Deployment

- **Docker Compose** for single-server deployment (small cooperatives)
- **Kubernetes Helm chart** for scaled deployment
- Designed to run on a single $20/mo VPS for a small market (100-500 drivers)
- All services containerized: API, PostgreSQL, Redis, OSRM, worker processes

---

## Core Services Detail

### 1. Matching Engine

The matching engine connects riders with nearby available drivers.

**Algorithm**: Nearest-available with configurable constraints.
- Query PostGIS for drivers within radius (starts at 2km, expands to 8km)
- Filter by: vehicle type, rating threshold, active status, compliance (valid license, insurance)
- Rank by: distance, then ETA (via OSRM), then driver rating
- Offer to top-ranked driver with 15-second acceptance timeout
- If declined/expired, offer to next driver
- After 3 rejections, re-query with expanded radius

**No surge pricing** by default. Operators can configure optional time-of-day multipliers for high-demand periods, but the system does not algorithmically surge based on demand/supply ratio. This is a design choice aligned with the zero-exploitation model.

### 2. Trip Manager

Manages the trip lifecycle:

```
REQUESTED → MATCHED → DRIVER_EN_ROUTE → ARRIVED → IN_PROGRESS → COMPLETED
                                                                → CANCELLED
```

Each state transition is recorded with timestamp and location. The full trip record is immutable after completion (audit trail for compliance).

### 3. Pricing Engine

**Default model**: distance + time + base fee, configured per-market.

```
fare = base_fee + (distance_km * per_km_rate) + (duration_min * per_min_rate)
```

- Rates configured by the cooperative operator (not algorithmically optimized)
- Optional: time-of-day adjustments (e.g., late-night premium)
- No dynamic/surge pricing by default
- Fare estimate shown to rider before booking, final fare calculated from actual route
- Tip support (100% to driver)

### 4. Safety & Compliance

- **SOS button**: In-app emergency that shares trip details + live location with local emergency services and/or designated contacts
- **Trip sharing**: Riders can share live trip status via link
- **Driver verification**: Photo match at trip start (optional, configurable)
- **Trip recording**: Optional dash-cam style audio recording (configurable per jurisdiction, with consent)
- **Compliance data**: Per-jurisdiction configuration for TNC requirements (background check provider, vehicle inspection rules, insurance requirements)

### 5. Routing Service

Thin wrapper around OSRM:
- ETA calculation (driver to pickup, pickup to dropoff)
- Distance calculation for fare computation
- Turn-by-turn navigation data for driver app
- Batch distance matrix for matching engine optimization

---

## API Design

RESTful JSON API with WebSocket channels for real-time updates.

### REST Endpoints (key routes)

```
# Auth
POST   /api/v1/auth/register
POST   /api/v1/auth/login
POST   /api/v1/auth/verify-phone
POST   /api/v1/auth/refresh

# Rider
POST   /api/v1/rides/estimate          # Get fare estimate
POST   /api/v1/rides/request            # Request a ride
GET    /api/v1/rides/{id}               # Get ride status
POST   /api/v1/rides/{id}/cancel        # Cancel ride
POST   /api/v1/rides/{id}/rate          # Rate driver

# Driver
POST   /api/v1/driver/go-online         # Start accepting rides
POST   /api/v1/driver/go-offline        # Stop accepting rides
POST   /api/v1/driver/location          # Update location
POST   /api/v1/rides/{id}/accept        # Accept ride request
POST   /api/v1/rides/{id}/arrive        # Mark arrived at pickup
POST   /api/v1/rides/{id}/start         # Start trip
POST   /api/v1/rides/{id}/complete      # Complete trip

# Admin
GET    /api/v1/admin/drivers            # List drivers
GET    /api/v1/admin/rides              # List rides (with filters)
GET    /api/v1/admin/analytics          # Dashboard data
PUT    /api/v1/admin/pricing            # Update pricing config
GET    /api/v1/admin/compliance         # Compliance status
```

### WebSocket Channels

```
ws://api/v1/ws/rider/{rider_id}
  → Events: driver_matched, driver_location, driver_arrived,
            trip_started, trip_completed, ride_cancelled

ws://api/v1/ws/driver/{driver_id}
  → Events: ride_request, ride_cancelled, navigation_update

ws://api/v1/ws/admin
  → Events: trip_events, driver_status_changes, alerts
```

### Location Updates

Drivers send GPS updates every 3-5 seconds while online. These go to Redis (not PostgreSQL) for performance. Only significant location changes (>50m movement) trigger WebSocket pushes to connected riders.

---

## Data Model (Key Entities)

```
users
  id, phone, email, name, role (rider|driver|admin), created_at

driver_profiles
  user_id (FK), vehicle_type, vehicle_make, vehicle_model, vehicle_year,
  license_plate, license_number, insurance_policy, background_check_status,
  rating_avg, total_trips, is_online, current_location (POINT geometry)

rides
  id, rider_id (FK), driver_id (FK), status, pickup_location (POINT),
  dropoff_location (POINT), pickup_address, dropoff_address,
  estimated_fare, actual_fare, distance_km, duration_min,
  requested_at, matched_at, started_at, completed_at,
  rider_rating, driver_rating, cancellation_reason

payments
  id, ride_id (FK), stripe_payment_intent_id, amount, platform_fee,
  driver_payout, status, created_at

jurisdictions
  id, name, state, tnc_license_required, background_check_provider,
  vehicle_inspection_rules (JSONB), insurance_requirements (JSONB),
  pricing_config (JSONB)
```

---

## Project Structure

```
openride/
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI application entry
│   │   ├── config.py            # Settings (Pydantic BaseSettings)
│   │   ├── models/              # SQLAlchemy models
│   │   ├── schemas/             # Pydantic request/response schemas
│   │   ├── api/
│   │   │   ├── v1/
│   │   │   │   ├── auth.py
│   │   │   │   ├── rides.py
│   │   │   │   ├── drivers.py
│   │   │   │   └── admin.py
│   │   │   └── websocket.py
│   │   ├── services/
│   │   │   ├── matching.py
│   │   │   ├── pricing.py
│   │   │   ├── trips.py
│   │   │   ├── routing.py
│   │   │   ├── payments.py
│   │   │   └── safety.py
│   │   └── db/
│   │       ├── database.py
│   │       └── migrations/
│   ├── tests/
│   ├── Dockerfile
│   └── pyproject.toml
├── rider_app/                   # Flutter rider application
│   ├── lib/
│   ├── pubspec.yaml
│   └── ...
├── driver_app/                  # Flutter driver application
│   ├── lib/
│   ├── pubspec.yaml
│   └── ...
├── admin_web/                   # React admin dashboard
│   ├── src/
│   ├── package.json
│   └── ...
├── shared/                      # Shared Dart code (models, API client)
│   └── lib/
├── deploy/
│   ├── docker-compose.yml       # Single-server deployment
│   ├── docker-compose.dev.yml   # Local development
│   ├── helm/                    # Kubernetes deployment
│   └── osrm/                    # OSRM container config
├── docs/
│   ├── api.md
│   ├── deployment.md
│   ├── regulatory-guide.md      # TNC compliance by state
│   └── insurance-guide.md       # Insurance requirements and options
├── LICENSE                      # AGPL-3.0
├── README.md
├── CONTRIBUTING.md
└── CODE_OF_CONDUCT.md
```

---

## Deployment Models

### Small Cooperative (100-500 drivers, 1 city)

Single server deployment via Docker Compose:
- 1 VPS: 4 vCPU, 8GB RAM, 100GB SSD (~$20-40/mo on Hetzner/OVH)
- PostgreSQL + Redis + OSRM + FastAPI all on one machine
- Handles ~50 concurrent trips comfortably
- OSM data for the operating region only (small OSRM footprint)

### Medium Cooperative (500-5000 drivers, multi-city)

- Separate database server
- 2-3 API instances behind a load balancer
- Dedicated OSRM instance with larger region data
- Redis cluster for location data
- ~$100-200/mo infrastructure cost

### Large / Municipal (5000+ drivers)

- Kubernetes deployment via Helm chart
- Horizontal scaling of API and WebSocket servers
- PostgreSQL with read replicas
- Regional OSRM instances
- CDN for static assets
- ~$500-2000/mo depending on scale

---

## Licensing

**AGPL-3.0** — ensures that any operator running a modified version must share their changes. This prevents Uber-style companies from taking the code and making it proprietary. Cooperatives that run it unmodified have no obligations beyond what they'd normally do. Cooperatives that customize it must share their customizations — which is aligned with the cooperative ethos anyway.

---

## Phase 1 Scope (MVP)

The minimum viable product for a pilot deployment:

1. **Backend API** — auth, ride request/matching/completion, driver management, fare calculation
2. **Driver app** — go online/offline, accept rides, navigate to pickup, complete trip
3. **Rider app** — request ride, see driver on map, fare estimate, trip tracking, payment
4. **Admin dashboard** — driver approval, trip monitoring, basic analytics
5. **Payments** — Stripe Connect integration for rider→driver payments
6. **Deployment** — Docker Compose single-server setup with OSRM

**Not in Phase 1**: scheduled rides, ride pooling/sharing, multi-stop trips, driver subscription billing, regulatory compliance automation, safety features beyond basic SOS.

---

## Open Questions (For Community Discussion)

1. **Beckn Protocol integration**: Should we build Beckn compatibility from the start? This would allow interoperability with other Beckn-compliant services but adds complexity.
2. **Ride pooling**: When to add shared rides? This is a major matching algorithm change.
3. **Driver subscription vs. per-ride fee**: Which model do cooperatives prefer? Namma Yatri uses subscription, but US cooperatives may prefer per-ride.
4. **Accessibility**: What accessibility requirements should be in Phase 1 vs. Phase 2? WAV (wheelchair accessible vehicle) matching is critical for some markets.
5. **Multi-language support**: i18n from the start or add later?
