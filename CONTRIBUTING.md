# Contributing to OpenRide

Thank you for your interest in OpenRide. This project exists to give driver cooperatives and communities the tools to run their own rideshare services. Every contribution — code, docs, regulatory research, design — moves that goal closer.

## Getting Started

### Prerequisites

- Python 3.11+
- Docker and Docker Compose
- Flutter SDK 3.x (for mobile apps)
- Node.js 20+ (for admin dashboard)
- Git

### Development Setup

```bash
# Clone the repo
git clone https://github.com/your-org/openride.git
cd openride

# Start infrastructure (PostgreSQL, Redis, OSRM)
docker compose -f deploy/docker-compose.dev.yml up -d db redis osrm

# Backend setup
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
alembic upgrade head          # Run migrations
pytest                        # Run tests
uvicorn app.main:app --reload # Start dev server

# Admin dashboard
cd ../admin_dashboard
npm install
npm run dev

# Mobile apps (rider or driver)
cd ../rider_app   # or driver_app
flutter pub get
flutter run
```

### Running Tests

```bash
# Backend
cd backend
pytest                          # All tests
pytest tests/test_matching.py   # Specific file
pytest -m "not integration"     # Unit tests only
pytest --cov=app                # With coverage

# Admin dashboard
cd admin_dashboard
npm test

# Mobile apps
cd rider_app
flutter test
```

## How to Contribute

### 1. Find Something to Work On

- Check [open issues](../../issues) — look for `good first issue` or `help wanted` labels
- Check the project board for current priorities
- If you want to work on something not yet tracked, open an issue first to discuss

### 2. Branch and Develop

```bash
git checkout -b feature/your-feature    # or fix/your-fix
# Make your changes
# Write tests for new functionality
# Ensure all tests pass
git commit -m "feat: description"       # Use conventional commits
```

### 3. Submit a Pull Request

- Keep PRs focused — one feature or fix per PR
- Include tests for new functionality
- Update documentation if you change APIs or user-facing behavior
- Fill out the PR template

### Commit Messages

We use [Conventional Commits](https://www.conventionalcommits.org/):

```
feat: add driver matching by vehicle type
fix: correct fare calculation for short trips
docs: add TNC requirements for California
test: add integration tests for payment flow
refactor: simplify trip state machine
```

## Code Standards

### Python (Backend)

- Format with `ruff format`
- Lint with `ruff check`
- Type hints on all public functions
- Tests for all new endpoints and services

### Dart (Mobile Apps)

- Format with `dart format`
- Lint with `flutter analyze`
- Widget tests for UI components
- Unit tests for business logic

### TypeScript (Admin Dashboard)

- Format with Prettier
- Lint with ESLint
- Tests with Vitest

## Architecture Decisions

Major architectural decisions are documented in [ARCHITECTURE.md](ARCHITECTURE.md). If you want to propose a significant change to the architecture, open a discussion issue first. We value simplicity and accessibility for cooperative operators who may not have large engineering teams.

## Non-Code Contributions

We need more than code:

- **Regulatory research**: Document TNC licensing, insurance, and compliance requirements for specific states and cities
- **Cooperative partnerships**: Connect us with driver cooperatives who could pilot the platform
- **Translations**: Help make the apps accessible in multiple languages
- **Design**: UI/UX for rider and driver apps, branding, marketing materials
- **Documentation**: Deployment guides, operator manuals, troubleshooting guides

## Code of Conduct

This project serves communities that are often exploited by the gig economy. We expect all contributors to treat each other with respect. See [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md) for details.

## Questions?

Open an issue or start a discussion. We're happy to help you get started.
