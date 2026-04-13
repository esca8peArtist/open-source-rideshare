# OpenRide

**Open source rideshare infrastructure for cooperatives.**

OpenRide is a complete, deployable rideshare stack — rider app, driver app, backend, and admin dashboard — designed for worker-owned cooperatives, community organizations, and municipal transit authorities. It's not another Uber clone. It's the tools so your community can run its own.

## Why This Exists

Uber and Lyft extract 25-40% of every fare. Drivers earn less, riders pay more, and billions flow to shareholders instead of the communities these services operate in. Meanwhile, driver cooperatives like [The Drivers Cooperative](https://drivers.coop/) in NYC prove that the cooperative model works — but they're held back by unreliable, expensive tech.

[Namma Yatri](https://nammayatri.in/) in India proved that a zero-commission, open source rideshare platform can work at scale — 100M+ rides, 500K+ drivers, and growing. But no equivalent exists for Western markets.

OpenRide fills that gap: a modern, Western-deployable, open source rideshare stack that cooperatives can run for their drivers and riders.

## How It Works

- **Drivers** pay a small flat fee (set by the cooperative), keep 100% of fares
- **Riders** pay fair, transparent fares — no surge pricing, no algorithmic manipulation
- **Cooperatives** own and operate the platform for their community
- **No data monetization** — rider and driver data stays with the cooperative

## Tech Stack

| Component | Technology | Why |
|---|---|---|
| Backend | Python (FastAPI) | Async, large contributor pool, great geospatial ecosystem |
| Mobile Apps | Flutter (Dart) | Single codebase for iOS + Android |
| Admin Dashboard | React + TypeScript | Modern SPA for cooperative operators |
| Database | PostgreSQL + PostGIS | Geospatial queries, proven at scale |
| Cache | Redis | Real-time driver locations, trip state |
| Routing | OSRM on OpenStreetMap | Free, self-hosted, no API fees |
| Maps | MapLibre GL | Open source vector tile rendering |
| Payments | Stripe Connect | Marketplace payments with driver payouts |

## What's Included

| Component | Status | Details |
|---|---|---|
| **Backend API** | Complete | Auth, rides, matching, payments, safety, admin, earnings, geocoding, routing, WebSocket |
| **Rider App** | Complete | Flutter — login, map search, fare estimate, ride tracking, ratings, history, profile |
| **Driver App** | Complete | Flutter — online/offline, ride offers, active ride, earnings, history, profile |
| **Admin Dashboard** | Complete | React — analytics, driver management, ride monitoring, payments, settings |
| **Deployment** | Complete | Docker Compose (dev + prod), Caddy reverse proxy, OSRM routing |
| **CI/CD** | Complete | GitHub Actions — lint + test on every push |
| **Tests** | 309 tests | Unit + integration coverage across all backend services |

See [ARCHITECTURE.md](ARCHITECTURE.md) for the full technical design.

### Roadmap

- [x] Research and feasibility analysis
- [x] Architecture and tech stack definition
- [x] Backend API (auth, rides, matching, payments, safety, admin)
- [x] Driver app (Flutter)
- [x] Rider app (Flutter)
- [x] Admin dashboard (React)
- [x] Docker Compose deployment
- [ ] Pilot deployment with a cooperative partner
- [ ] Scheduled rides and ride pooling
- [ ] Beckn Protocol interoperability
- [ ] Multi-language support (i18n)
- [ ] Accessibility / WAV matching

## Running Locally

```bash
# Clone the repo
git clone https://github.com/your-org/openride.git
cd openride

# Start all services (PostgreSQL, Redis, OSRM, API)
docker compose -f deploy/docker-compose.dev.yml up

# Backend API: http://localhost:8000
# Admin dashboard: http://localhost:3000
# API docs (Swagger): http://localhost:8000/docs
```

See [docs/deployment.md](docs/deployment.md) for production setup with Caddy, TLS, and OSRM.

## Deployment

OpenRide is designed to run cheaply:

| Scale | Infrastructure | Cost |
|---|---|---|
| Small (100-500 drivers) | Single VPS, Docker Compose | ~$20-40/mo |
| Medium (500-5000 drivers) | 2-3 servers, load balanced | ~$100-200/mo |
| Large (5000+ drivers) | Kubernetes cluster | ~$500-2000/mo |

See [docs/deployment.md](docs/deployment.md) for detailed setup instructions.

## Backend Services

The backend implements all core rideshare operations:

- **Authentication** — JWT tokens, phone verification, OAuth2
- **Matching Engine** — Redis geospatial queries, nearest-driver algorithm, configurable radius (2-8km)
- **Pricing** — Transparent fare calculation: base + distance + time, configurable per cooperative, no surge
- **Payments** — Stripe Connect marketplace with direct driver payouts
- **Safety** — SOS alerts, trip sharing tokens, emergency contacts, driver verification
- **Routing** — OSRM integration for ETA, distance, and turn-by-turn directions
- **Geocoding** — Nominatim forward/reverse geocoding
- **WebSocket** — Real-time ride events, location updates, driver notifications
- **Admin API** — Driver approval, ride monitoring, analytics, pricing configuration

## For Cooperatives

If you're a driver cooperative or community organization interested in using OpenRide:

1. **Read the [Deployment Guide](docs/deployment.md)** — understand the technical requirements
2. **Review the [Regulatory Research](regulatory-compliance-research.md)** — TNC licensing and compliance across US jurisdictions
3. **Open an issue** — tell us about your organization and what you need. We want to build for real operators.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for development setup, coding standards, and how to submit changes.

We especially need:
- **Backend engineers** (Python/FastAPI)
- **Mobile developers** (Flutter/Dart)
- **Frontend developers** (React/TypeScript)
- **People with TNC regulatory knowledge** — help us document compliance requirements state by state
- **Cooperative organizers** — tell us what features matter most for your drivers and riders
- **Designers** — the apps need to be as good as Uber/Lyft for riders and drivers to switch

## License

[AGPL-3.0](LICENSE) — you can use, modify, and deploy OpenRide freely. If you modify the code and run it as a service, you must share your modifications. This ensures the project stays open and prevents proprietary forks.

## Acknowledgments

- [Namma Yatri](https://nammayatri.in/) — proved the zero-commission model works at scale
- [The Drivers Cooperative](https://drivers.coop/) — proved the cooperative model works in the US
- [OSRM](https://project-osrm.org/) — open source routing that makes this affordable
- [OpenStreetMap](https://www.openstreetmap.org/) — the map data that makes this possible
