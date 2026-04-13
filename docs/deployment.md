# OpenRide Deployment Guide

This guide covers deploying OpenRide from a single VPS to a multi-node production setup. OpenRide is designed to run affordably — a small cooperative (100–500 drivers) can operate on a single $20/month VPS.

## Prerequisites

- Docker and Docker Compose v2
- A domain name with DNS control
- A Stripe account (for payments)
- An SMS provider account (Twilio or compatible) for phone verification
- 2GB+ RAM, 2 vCPUs, 20GB+ disk (minimum for single-server)

## Quick Start (Single Server)

This gets you running on one machine with all services containerized.

### 1. Clone and configure

```bash
git clone https://github.com/OpenRide/openride.git
cd openride

# Copy the example environment file
cp .env.example .env
```

Edit `.env` with your values:

```bash
# Database
POSTGRES_USER=openride
POSTGRES_PASSWORD=<generate-a-strong-password>
POSTGRES_DB=openride

# Application
SECRET_KEY=<generate-with-openssl-rand-hex-32>
DATABASE_URL=postgresql+asyncpg://openride:<password>@db:5432/openride
REDIS_URL=redis://redis:6379/0

# Stripe
STRIPE_SECRET_KEY=sk_live_...
STRIPE_WEBHOOK_SECRET=whsec_...

# SMS (Twilio)
TWILIO_ACCOUNT_SID=AC...
TWILIO_AUTH_TOKEN=...
TWILIO_PHONE_NUMBER=+1...

# OSRM
OSRM_URL=http://osrm:5000
```

### 2. Prepare map data (OSRM)

OSRM needs OpenStreetMap data for your service area. Download and prepare it before first launch:

```bash
mkdir -p deploy/osrm

# Download your region (example: California)
wget https://download.geofabrik.de/north-america/us/california-latest.osm.pbf \
  -O deploy/osrm/map.osm.pbf

# Extract and prepare routing data (this takes 10-30 minutes depending on region size)
docker run --rm -v ./deploy/osrm:/data osrm/osrm-backend \
  osrm-extract -p /opt/car.lua /data/map.osm.pbf

docker run --rm -v ./deploy/osrm:/data osrm/osrm-backend \
  osrm-partition /data/map.osrm

docker run --rm -v ./deploy/osrm:/data osrm/osrm-backend \
  osrm-customize /data/map.osrm
```

For other regions, find the appropriate `.osm.pbf` file at [download.geofabrik.de](https://download.geofabrik.de/).

### 3. Launch

```bash
docker compose -f deploy/docker-compose.prod.yml up -d
```

### 4. Run database migrations

```bash
docker compose -f deploy/docker-compose.prod.yml exec api alembic upgrade head
```

### 5. Create initial admin user

```bash
docker compose -f deploy/docker-compose.prod.yml exec api \
  python -m app.cli create-admin --phone +15551234567 --name "Admin"
```

### 6. Verify

```bash
# Check all services are running
docker compose -f deploy/docker-compose.prod.yml ps

# Health check
curl http://localhost:8000/health

# API docs (disable in production if desired)
open http://localhost:8000/docs
```

---

## Production Docker Compose

Create `deploy/docker-compose.prod.yml`:

```yaml
services:
  db:
    image: postgis/postgis:16-3.4
    restart: unless-stopped
    environment:
      POSTGRES_USER: ${POSTGRES_USER}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
      POSTGRES_DB: ${POSTGRES_DB}
    volumes:
      - pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER}"]
      interval: 10s
      timeout: 5s
      retries: 5
    networks:
      - internal

  redis:
    image: redis:7-alpine
    restart: unless-stopped
    command: redis-server --requirepass ${REDIS_PASSWORD:-}
    volumes:
      - redisdata:/data
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 5s
      retries: 5
    networks:
      - internal

  osrm:
    image: osrm/osrm-backend:latest
    restart: unless-stopped
    volumes:
      - ./osrm:/data:ro
    command: osrm-routed --algorithm mld --max-table-size 1000 /data/map.osrm
    networks:
      - internal

  api:
    build: ../backend
    restart: unless-stopped
    env_file: ../.env
    ports:
      - "8000:8000"
    depends_on:
      db:
        condition: service_healthy
      redis:
        condition: service_healthy
      osrm:
        condition: service_started
    networks:
      - internal
      - external

  caddy:
    image: caddy:2-alpine
    restart: unless-stopped
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./Caddyfile:/etc/caddy/Caddyfile:ro
      - caddy_data:/data
      - caddy_config:/config
    depends_on:
      - api
    networks:
      - external

volumes:
  pgdata:
  redisdata:
  caddy_data:
  caddy_config:

networks:
  internal:
  external:
```

---

## Reverse Proxy (Caddy)

Create `deploy/Caddyfile`:

```
api.yourdomain.com {
    reverse_proxy api:8000
}

admin.yourdomain.com {
    root * /srv/admin
    file_server
    try_files {path} /index.html
}
```

Caddy automatically provisions and renews TLS certificates via Let's Encrypt.

---

## Database Backups

### Automated daily backups

```bash
#!/bin/bash
# deploy/scripts/backup.sh
BACKUP_DIR=/backups/openride
DATE=$(date +%Y%m%d-%H%M%S)

mkdir -p $BACKUP_DIR

docker compose -f deploy/docker-compose.prod.yml exec -T db \
  pg_dump -U openride -Fc openride > "$BACKUP_DIR/openride-$DATE.dump"

# Keep last 30 days
find $BACKUP_DIR -name "*.dump" -mtime +30 -delete
```

Add to crontab:

```bash
0 3 * * * /path/to/openride/deploy/scripts/backup.sh
```

### Restore from backup

```bash
docker compose -f deploy/docker-compose.prod.yml exec -T db \
  pg_restore -U openride -d openride --clean < backup.dump
```

---

## Environment Variables Reference

| Variable | Required | Description |
|----------|----------|-------------|
| `POSTGRES_USER` | Yes | Database username |
| `POSTGRES_PASSWORD` | Yes | Database password |
| `POSTGRES_DB` | Yes | Database name |
| `SECRET_KEY` | Yes | JWT signing key (256-bit hex) |
| `DATABASE_URL` | Yes | Full async PostgreSQL connection string |
| `REDIS_URL` | Yes | Redis connection string |
| `REDIS_PASSWORD` | No | Redis auth password (recommended in production) |
| `STRIPE_SECRET_KEY` | Yes | Stripe API secret key |
| `STRIPE_WEBHOOK_SECRET` | Yes | Stripe webhook signing secret |
| `TWILIO_ACCOUNT_SID` | Yes | Twilio account SID |
| `TWILIO_AUTH_TOKEN` | Yes | Twilio auth token |
| `TWILIO_PHONE_NUMBER` | Yes | Twilio phone number for SMS |
| `OSRM_URL` | Yes | OSRM routing server URL |
| `CORS_ORIGINS` | No | Comma-separated allowed origins (default: `*`) |
| `LOG_LEVEL` | No | Logging level (default: `info`) |
| `MAX_MATCHING_RADIUS_KM` | No | Maximum driver search radius (default: `8`) |
| `DRIVER_LOCATION_TTL_S` | No | Redis TTL for driver locations (default: `30`) |

---

## Monitoring

### Health check endpoint

`GET /health` returns service status:

```json
{
  "status": "healthy",
  "database": "connected",
  "redis": "connected",
  "osrm": "connected",
  "version": "0.1.0"
}
```

### Logs

```bash
# All services
docker compose -f deploy/docker-compose.prod.yml logs -f

# API only
docker compose -f deploy/docker-compose.prod.yml logs -f api

# Since a specific time
docker compose -f deploy/docker-compose.prod.yml logs --since 1h api
```

### Recommended monitoring stack (optional)

For production cooperatives handling real rides, add Prometheus + Grafana:

- FastAPI exposes metrics at `/metrics` (when `prometheus-fastapi-instrumentator` is installed)
- PostgreSQL metrics via `postgres_exporter`
- Redis metrics via `redis_exporter`
- Grafana dashboards for: active rides, driver availability, matching latency, payment success rate

---

## Scaling Beyond a Single Server

### When to scale

A single server handles approximately:
- 500 concurrent active drivers
- 100 concurrent active rides
- 1,000 requests/second to the API

Signs you need to scale:
- API response times exceed 500ms (p95)
- Database CPU consistently above 70%
- WebSocket connection drops increase

### Horizontal scaling approach

1. **Separate database**: Move PostgreSQL to a managed service (AWS RDS, DigitalOcean Managed DB, or a dedicated server)
2. **Redis cluster**: Separate Redis for caching vs. pub/sub
3. **Multiple API instances**: Run 2+ API containers behind a load balancer. WebSocket connections require sticky sessions or Redis-backed session state (already implemented via Redis pub/sub)
4. **OSRM scaling**: OSRM is CPU-intensive for table queries. For large regions, run multiple instances behind a load balancer
5. **CDN**: Put static assets and admin dashboard behind Cloudflare or equivalent

### Kubernetes deployment

A Helm chart is planned for cooperatives that need auto-scaling. For now, the Docker Compose setup scales to ~500 drivers comfortably on a $40/month VPS.

---

## Updating

```bash
cd /path/to/openride
git pull origin main

# Rebuild and restart
docker compose -f deploy/docker-compose.prod.yml build api
docker compose -f deploy/docker-compose.prod.yml up -d api

# Run any new migrations
docker compose -f deploy/docker-compose.prod.yml exec api alembic upgrade head
```

### Zero-downtime updates

With multiple API instances behind a load balancer, use rolling restarts:

```bash
docker compose -f deploy/docker-compose.prod.yml up -d --no-deps --scale api=2 api
# Wait for new instance to be healthy, then scale back
docker compose -f deploy/docker-compose.prod.yml up -d --no-deps --scale api=1 api
```

---

## Security Checklist

Before going live, verify:

- [ ] Strong, unique database password
- [ ] `SECRET_KEY` is a random 256-bit value
- [ ] Redis is password-protected and not exposed to the internet
- [ ] Database is not exposed to the internet (internal network only)
- [ ] HTTPS is enforced (Caddy handles this automatically)
- [ ] `CORS_ORIGINS` is restricted to your actual domains
- [ ] Stripe webhook endpoint validates signatures
- [ ] API rate limiting is configured
- [ ] Database backups are running and tested
- [ ] Log rotation is configured
- [ ] OS security updates are applied
- [ ] SSH key-only authentication (no password login)
- [ ] Firewall allows only ports 80, 443, and SSH

---

## Troubleshooting

**API won't start / database connection refused**: Check that the database is healthy (`docker compose ps`) and that `DATABASE_URL` matches the PostgreSQL credentials.

**OSRM returns errors**: Ensure map data was extracted and prepared (Step 2). The `.osrm` file must exist in `deploy/osrm/`.

**WebSocket connections drop**: Check that your reverse proxy supports WebSocket upgrades. Caddy handles this automatically. If using Nginx, add `proxy_set_header Upgrade` and `proxy_set_header Connection "upgrade"` directives.

**Stripe webhooks fail**: Verify `STRIPE_WEBHOOK_SECRET` matches the webhook endpoint in your Stripe dashboard. Test with `stripe listen --forward-to localhost:8000/api/v1/payments/webhook`.

**SMS verification not working**: Check Twilio credentials and ensure the phone number is SMS-capable. Twilio trial accounts can only send to verified numbers.
