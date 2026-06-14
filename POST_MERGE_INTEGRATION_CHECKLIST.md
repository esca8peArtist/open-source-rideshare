# Post-Merge Integration Checklist: Background Checks + Firebase Push + Tipping

**Document Date:** 2026-06-14  
**Merge Target:** `master` (production)  
**Estimated Deployment Window:** June 16–18, 2026  
**Rollback Window:** 2 hours post-deployment

---

## Executive Summary

Post-merge integration requires Firebase Cloud Messaging setup, background check webhook verification, and comprehensive feature validation. Estimated timeline: **8–12 hours** from merge commit to production deployment.

**Critical Path:**
1. Firebase service account configuration (1.5 hours)
2. Checkr webhook registration (1 hour)
3. Environment variable provisioning (30 minutes)
4. Database migration execution (1 hour)
5. Feature validation testing (3–4 hours)
6. Staging deployment (2 hours)
7. Production deployment (1 hour)
8. Monitoring & rollback readiness (1 hour)

---

## Phase 1: Firebase Cloud Messaging Setup (1.5 hours)

### 1.1 Service Account Configuration

**Prerequisite:** Firebase project must exist in Google Cloud Console

**Step 1: Generate Service Account Key**
```bash
# Via Google Cloud Console:
# 1. Go to project-id.firebaseapp.com
# 2. Navigate to Settings → Service Accounts
# 3. Click "Generate New Private Key"
# 4. Save as backend/config/serviceAccountKey.json (DO NOT COMMIT)
```

**Step 2: Set Environment Variable**
```bash
# On deployment server:
export FIREBASE_CREDENTIALS_JSON="$(cat backend/config/serviceAccountKey.json)"

# Verify (should output JSON):
echo $FIREBASE_CREDENTIALS_JSON | head -c 100

# Permanently store (use secrets manager):
# AWS Secrets Manager, HashiCorp Vault, or environment provisioning service
```

**Step 3: Validate Configuration**
```bash
cd backend

# Test Firebase initialization
python -c "
from app.config import settings
from app.services.notification_providers import _get_firebase_app

app = _get_firebase_app()
if app:
    print('✓ Firebase app initialized')
else:
    print('✗ Firebase app not initialized — check credentials')
"

# Expected output: ✓ Firebase app initialized
```

**Risk Mitigation:**
- Service account key should be stored in secrets vault, not in source control
- Add `backend/config/serviceAccountKey.json` to `.gitignore` if not already

**Validation Checklist:**
- [ ] Service account key generated
- [ ] `FIREBASE_CREDENTIALS_JSON` env var set
- [ ] Firebase app initialization test passes
- [ ] No key material in git history

---

### 1.2 Device Token Registration Pipeline

**Description:** Users' devices must register tokens to receive push notifications. The flow is:

```
Mobile App (iOS/Android)
    ↓ get FCM token via Firebase SDK
    ↓
Backend /api/v1/device-tokens/register
    ↓ save to database
    ↓
notifications_providers.send_push() can now reach the device
```

**Step 1: Verify Device Token Model**
```bash
cd backend

# Check migration exists
grep -r "device_token" app/models/ app/schemas/

# Expected: 
# - app/models/device_token.py (model)
# - app/schemas/device_token.py (schemas)
# - app/api/v1/device_tokens.py (endpoints)
```

**Step 2: Register Device Token Endpoints**
```bash
# Verify main.py includes device token router
grep "device_token" app/main.py

# Expected: app.include_router(device_tokens_router)
```

**Step 3: Test Device Token Registration (Manual)
```bash
# In local environment:
python -m pytest tests/test_device_tokens.py -v --tb=short

# Expected: All tests pass
# Common tests:
# - test_register_device_token
# - test_unregister_device_token
# - test_duplicate_token_registration
# - test_invalid_user_rejected
```

**Database Schema Validation:**
```sql
-- On staging/prod PostgreSQL:
SELECT * FROM device_tokens LIMIT 1;

-- Expected columns:
-- id (UUID)
-- user_id (foreign key to users)
-- token (text, unique per user)
-- platform (enum: 'ios', 'android', 'web')
-- created_at (timestamp)
-- last_used_at (timestamp)
```

**Validation Checklist:**
- [ ] Device token model present in code
- [ ] Endpoints registered in main.py
- [ ] Test suite passes
- [ ] Database schema verified

---

### 1.3 Test Push Notification Flow (End-to-End)

**Purpose:** Verify the complete chain: device token → FCM → mobile app notification

**Test Scenario:**
```python
# In test environment with real Firebase app:
import asyncio
from app.models import User, DeviceToken
from app.services.notifications import Notification, NotificationType
from app.services.notification_providers import send_push

async def test_real_push():
    # 1. Create test user & device token
    user = await create_test_user(email="test@example.com")
    device_token = await register_device_token(
        user_id=user.id,
        token="<REAL_DEVICE_TOKEN_FROM_TEST_PHONE>",
        platform="ios"  # or "android"
    )
    
    # 2. Send notification
    notification = Notification(
        type=NotificationType.RIDE_STARTED,
        user_id=user.id,
        title="Test Ride Started",
        body="This is a test push notification",
        data={"ride_id": "test-123"}
    )
    
    # 3. Verify delivery
    success = await send_push(notification, device_tokens=[device_token.token])
    assert success, "Push notification failed"
    
    # 4. Check mobile device for notification
    # (Manual: open test phone and verify notification appears)
```

**Practical Validation:**
```bash
# Option 1: Use Firebase Console Testing
# 1. Go to Firebase Console → Cloud Messaging
# 2. Click "Send your first message"
# 3. Enter test device token
# 4. Verify notification appears on phone

# Option 2: Run pytest with staging environment
cd backend
export OPENRIDE_TEST_DATABASE_URL="postgresql+asyncpg://user:pass@staging-db/test"
export FIREBASE_CREDENTIALS_JSON="<staging service account>"
python -m pytest tests/test_push_notifications.py -v -s

# Expected: All tests pass
```

**Validation Checklist:**
- [ ] Firebase Console accessible
- [ ] Test device token registered
- [ ] Push notification received on test device
- [ ] Notification metadata correct (title, body, data)

---

## Phase 2: Background Check Integration (Checkr) Setup (1 hour)

### 2.1 Checkr API Credentials

**Prerequisites:**
- Checkr business account created (https://checkr.com)
- API keys generated

**Step 1: Set Environment Variables**
```bash
export CHECKR_API_KEY="sk_live_xxxxxxxxxxxxxxxx"
export CHECKR_WEBHOOK_SECRET="whsec_xxxxxxxxxxxxxxxx"
```

**Step 2: Verify Checkr Credentials**
```bash
cd backend

python -c "
import asyncio
from app.services.background_checks import create_candidate

# Test with non-existent email (should return simulated result, no API call)
result = asyncio.run(
    create_candidate(
        email='test@example.com',
        first_name='Test',
        last_name='Driver'
    )
)
print(f'Candidate created: {result.id}')
"
```

**Expected Behavior:**
- If `CHECKR_API_KEY` set: Creates real candidate in Checkr
- If not set: Returns simulated candidate (graceful fallback)
- No errors in logs

**Validation Checklist:**
- [ ] `CHECKR_API_KEY` env var set
- [ ] `CHECKR_WEBHOOK_SECRET` env var set
- [ ] Checkr credentials valid (test call succeeds or returns simulated)
- [ ] No credential exposure in logs

---

### 2.2 Checkr Webhook Registration & Verification

**Purpose:** Checkr sends status updates (clear, dispute, suspended, etc.) via webhook. Backend must:
1. Verify webhook signature (HMAC-SHA256)
2. Parse event type
3. Update background check status
4. Trigger side effects (auto-approve, notifications)

**Step 1: Expose Webhook Endpoint**
```bash
# Verify endpoint exists in production:
# POST /api/v1/background-checks/webhook

# Check code:
grep -r "background.*webhook" backend/app/api/

# Expected: app/api/v1/background_checks.py contains webhook handler
```

**Step 2: Register Webhook in Checkr Console**
```
1. Go to https://dashboard.checkr.com/settings/webhooks
2. Add webhook URL:
   https://your-api.example.com/api/v1/background-checks/webhook
3. Select events:
   ✓ report.completed
   ✓ report.disputed
   ✓ report.suspended
   ✓ report.cancelled
4. Copy "Webhook Signing Secret" → set as CHECKR_WEBHOOK_SECRET
```

**Step 3: Test Webhook Signature Verification**
```python
# In test:
from app.services.background_checks import verify_webhook_signature
from app.config import settings

# Checkr test payload
test_payload = {
    "event": "report.completed",
    "data": {
        "report_id": "report_xxxx",
        "status": "clear"
    }
}

# Generate valid signature (Checkr format):
import hmac
import json
signature = hmac.new(
    settings.checkr_webhook_secret.encode(),
    json.dumps(test_payload).encode(),
    'sha256'
).hexdigest()

# Verify in code
is_valid = verify_webhook_signature(signature, test_payload)
assert is_valid, "Signature verification failed"
```

**Step 4: End-to-End Webhook Test**
```bash
# Use Checkr's webhook testing tool or simulate:
cd backend
python -m pytest tests/test_background_checks.py::TestWebhookEndpoint -v

# Expected: All webhook endpoint tests pass
```

**Validation Checklist:**
- [ ] Webhook endpoint accessible from internet
- [ ] Webhook registered in Checkr console
- [ ] Signature verification test passes
- [ ] Webhook event parsing test passes

---

### 2.3 Background Check Status Tracking

**Step 1: Verify Auto-Approve Logic**
```bash
# Background check flow:
# 1. Driver orders check → status = "pending"
# 2. Checkr processes → webhook received (e.g., status = "clear")
# 3. Auto-approve trigger:
#    - IF status == "clear" AND all required docs verified → auto-approve driver
#    - IF status in ["consider", "suspended"] → flag for manual review

# Test:
cd backend
python -m pytest tests/test_background_checks.py::TestAutoApproveLogic -v

# Expected: Tests pass for clear/consider/suspended flows
```

**Step 2: Verify Driver Notifications**
```python
# Background check result notification:
# - Driver receives SMS + push notification when check completes
# - Message varies by status:
#   - "clear" → "Congratulations! Your background check passed."
#   - "consider" → "Your background check needs review. Please check your email for next steps."
#   - "suspended" → "Your background check is suspended. Contact support."

cd backend
python -m pytest tests/test_background_checks.py::TestNotifyDriverCheckResult -v
```

**Validation Checklist:**
- [ ] Auto-approve test passes
- [ ] Notification test passes
- [ ] SMS/push delivery validated (Phase 1)
- [ ] Status enum covers all Checkr statuses

---

## Phase 3: Environment & Configuration (30 minutes)

### 3.1 Environment Variables Checklist

**Create `.env` file (not committed) or configure via secrets manager:**

```bash
# ============================================================================
# Firebase Cloud Messaging
# ============================================================================
FIREBASE_CREDENTIALS_JSON={"type":"service_account",...}  # Service account JSON
NOTIFICATIONS_PUSH_ENABLED=true

# ============================================================================
# Checkr Background Checks
# ============================================================================
CHECKR_API_KEY=sk_live_xxxxx
CHECKR_WEBHOOK_SECRET=whsec_xxxxx

# ============================================================================
# Twilio SMS for Background Checks & Tipping
# ============================================================================
TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxxxxxx
TWILIO_AUTH_TOKEN=xxxxxxxxxxxxxxxxxxxx
TWILIO_PHONE_NUMBER=+1201555XXXX
NOTIFICATIONS_SMS_ENABLED=true

# ============================================================================
# Stripe for Tipping
# ============================================================================
STRIPE_API_KEY=sk_live_xxxxx

# ============================================================================
# Existing (verify no changes)
# ============================================================================
OPENRIDE_DATABASE_URL=postgresql+asyncpg://user:pass@db-host/openride
OPENRIDE_ENV=production
```

**Step 1: Validate All Variables Present**
```bash
# Load .env and check:
python -c "
from app.config import settings

# Print configuration status
checks = {
    'Firebase': bool(settings.firebase_credentials_json),
    'Checkr API': bool(settings.checkr_api_key),
    'Twilio Account': bool(settings.twilio_account_sid),
    'Stripe': bool(settings.stripe_api_key),
    'Database URL': bool(settings.database_url),
}

for name, configured in checks.items():
    status = '✓' if configured else '✗'
    print(f'{status} {name}')

missing = [k for k, v in checks.items() if not v]
if missing:
    print(f'\\nMissing: {missing}')
    exit(1)
else:
    print('\\nAll critical configs present')
"
```

**Step 2: Update .env.example (for documentation)**
```bash
# Edit .env.example to include all new variables:
cat .env.example

# Should include:
# FIREBASE_CREDENTIALS_JSON=...
# CHECKR_API_KEY=...
# TWILIO_ACCOUNT_SID=...
# STRIPE_API_KEY=...
```

**Validation Checklist:**
- [ ] All environment variables set
- [ ] No hardcoded secrets in code
- [ ] `.gitignore` includes `.env`
- [ ] `.env.example` updated with all variables
- [ ] Secrets manager integration working (if used)

---

## Phase 4: Database Migrations (1 hour)

### 4.1 Apply All Migrations

```bash
cd backend

# Step 1: Verify current migration state
python -m alembic current
# Expected: Shows latest migration before feature merge

# Step 2: List pending migrations
python -m alembic upgrade --sql head | head -20
# Expected: Shows background check, device token, tips, scheduling migrations

# Step 3: Apply all migrations
python -m alembic upgrade head
# Expected: All migrations applied without error

# Step 4: Verify final state
python -m alembic current
# Expected: Shows latest migration (e.g., "05_add_tips_table")
```

### 4.2 Verify Migration Chain

**Expected Alembic migrations:**

```
001_add_background_checks_table.py
  ├── background_checks table
  ├── background_check_status enum
  └── Foreign key to users

002_add_driver_online_status_table.py
  ├── driver_online_status table
  ├── is_online column
  ├── last_heartbeat_at column
  └── Foreign key to users

003_add_driver_schedules_table.py
  ├── driver_schedules table
  ├── day_of_week enum
  ├── start_time, end_time columns
  └── Foreign key to users

004_add_tips_table.py
  ├── tips table (TipRecord)
  ├── amount_cents integer column
  ├── tip_status enum
  ├── Foreign keys to rides & users

005_add_device_tokens_table.py
  ├── device_tokens table
  ├── token text unique
  ├── platform enum
  └── Foreign key to users
```

**Validation Test:**
```bash
# Run migration validation
cd backend
python -c "
from sqlalchemy import inspect
from app.config import settings
from sqlalchemy.ext.asyncio import create_async_engine
import asyncio

async def check_tables():
    engine = create_async_engine(settings.database_url)
    async with engine.begin() as conn:
        result = await conn.run_sync(
            lambda c: inspect(c).get_table_names()
        )
    expected_tables = {
        'users', 'background_checks', 'device_tokens',
        'driver_online_status', 'driver_schedules', 'tips'
    }
    actual = set(result)
    missing = expected_tables - actual
    if missing:
        print(f'Missing tables: {missing}')
        return False
    print(f'✓ All {len(expected_tables)} tables present')
    return True

asyncio.run(check_tables())
"
```

**Validation Checklist:**
- [ ] All migrations applied without error
- [ ] `alembic history` shows complete chain
- [ ] All new tables exist in database
- [ ] All foreign keys valid
- [ ] No rollback errors on reverse migration test

---

## Phase 5: Feature Validation Testing (3–4 hours)

### 5.1 Background Check Feature Test Suite

**Run comprehensive background check tests:**

```bash
cd backend

# Full test suite
python -m pytest tests/test_background_checks.py -v --tb=short

# Expected results:
# - 74 tests total
# - 0 failures
# - Coverage includes:
#   - Model validation
#   - Schema validation
#   - Checkr API integration (simulated if no API key)
#   - Webhook signature verification
#   - Status transitions
#   - Auto-approve logic
#   - Admin override endpoints
#   - Notification side effects

# Run with coverage
python -m pytest tests/test_background_checks.py --cov=app.services.background_checks --cov-report=term-missing
# Expected: >95% coverage
```

**Manual Test Scenarios:**

#### Scenario A: Order Background Check (Happy Path)
```bash
# Via API or test client:
# 1. POST /api/v1/background-checks/order with valid driver_id
# 2. Verify response includes check_id
# 3. Verify database record created with status="pending"
# 4. Verify SMS sent (if SMS enabled)
# 5. Verify push notification sent (if Firebase configured)
```

#### Scenario B: Webhook Received — Status "Clear"
```bash
# 1. Simulate Checkr webhook (POST to /api/v1/background-checks/webhook)
# 2. Verify webhook signature accepted
# 3. Verify database status updated to "clear"
# 4. Verify auto-approve triggered (if docs complete)
# 5. Verify driver receives "Approved" notification
```

#### Scenario C: Admin Override
```bash
# Via API:
# 1. POST /api/v1/background-checks/{id}/override with status="clear" + reason
# 2. Verify override recorded in database
# 3. Verify driver notified of override
```

**Validation Checklist:**
- [ ] All 74 background check tests pass
- [ ] Order check flow works end-to-end
- [ ] Webhook integration works
- [ ] Admin override works
- [ ] Notifications sent (SMS + push)

---

### 5.2 Driver Availability in Matching Test Suite

**Run availability tests:**

```bash
cd backend

python -m pytest tests/test_matching_availability.py -v --tb=short

# Expected results:
# - 20 tests total
# - 0 failures
# - Coverage includes:
#   - Online/offline filtering
#   - Heartbeat staleness detection (15-min threshold)
#   - Schedule window matching
#   - No-schedule opt-in
#   - Empty input handling
#   - Bulk query efficiency (no N+1)

# Performance validation
python -m pytest tests/test_matching_availability.py -v --durations=10
# Expected: All tests complete in <500ms
```

**Manual Test Scenario:**

#### Scenario: Driver Availability Integration in Ride Matching
```bash
# 1. Create driver + set online status
# 2. Set heartbeat timestamp (within 15 minutes)
# 3. Set optional schedule window (e.g., 9am–5pm weekdays)
# 4. Create ride request
# 5. Run matching engine
# 6. Verify driver included in candidates (if within schedule)
# 7. Change heartbeat to >15 minutes old
# 8. Re-run matching
# 9. Verify driver NOT included in candidates
```

**Validation Checklist:**
- [ ] All 20 availability tests pass
- [ ] Driver filtering works correctly
- [ ] No performance regressions
- [ ] Schedule window logic correct

---

### 5.3 Tipping Feature Test Suite

**Run tipping tests:**

```bash
cd backend

python -m pytest tests/test_tips.py tests/test_tip_analytics.py -v --tb=short

# Expected results:
# - 45 tests total (37 tips + 8 analytics)
# - 0 failures
# - Coverage includes:
#   - Tip amount validation (50–5000 cents)
#   - Ride completion gating (completed rides only)
#   - 48-hour window enforcement
#   - Duplicate detection
#   - Stripe integration (graceful fallback)
#   - Driver notifications
#   - Admin filtering & pagination
#   - Tax summary integration
```

**Manual Test Scenario:**

#### Scenario: Submit Tip for Ride (Happy Path)
```bash
# 1. Complete a ride as rider + driver
# 2. POST /api/v1/rides/{ride_id}/tip with amount_cents=500 (+ optional Stripe token)
# 3. Verify tip record created with status="pending"
# 4. Verify Stripe intent created (if Stripe key configured)
# 5. Verify driver notified
# 6. GET /api/v1/rides/{ride_id}/tip as rider → verify tip visible
# 7. GET /api/v1/drivers/me/tips as driver → verify tip in list
```

#### Scenario: Tip Validation
```bash
# 1. POST /api/v1/rides/{ride_id}/tip with amount_cents=25 (below 50 min)
#    → Expect 422 Unprocessable Entity
# 2. POST /api/v1/rides/{ride_id}/tip with amount_cents=5100 (above 5000 max)
#    → Expect 422 Unprocessable Entity
# 3. POST /api/v1/rides/{non_completed_ride_id}/tip
#    → Expect 409 Conflict (ride not completed)
# 4. POST /api/v1/rides/{ride_id}/tip twice
#    → Expect 409 Conflict (duplicate)
# 5. POST /api/v1/rides/{old_ride_id}/tip (>48h after completion)
#    → Expect 409 Conflict (window closed)
```

**Validation Checklist:**
- [ ] All 45 tipping tests pass
- [ ] Amount validation enforced
- [ ] Window enforcement working
- [ ] Stripe integration tested (graceful fallback)
- [ ] Driver notifications sent
- [ ] Admin filtering works

---

### 5.4 Full Integration Test Suite

```bash
cd backend

# Run all backend tests
python -m pytest tests/ -v --tb=short -x

# Expected results:
# - ~1,994 tests total
# - 0 failures
# - Database integration tests may skip if OPENRIDE_TEST_DATABASE_URL not set

# Run with coverage report
python -m pytest tests/ --cov=app --cov-report=html
# Open htmlcov/index.html to review coverage

# Performance check
python -m pytest tests/ --durations=20
# Identify slow tests; should complete in <5 minutes total
```

**Validation Checklist:**
- [ ] All tests pass
- [ ] No new test warnings
- [ ] Coverage >80%
- [ ] Test suite runtime acceptable (<5 min)

---

## Phase 6: Staging Deployment (2 hours)

### 6.1 Pre-Staging Checklist

```bash
# Verify no uncommitted changes
git status
# Expected: Clean working directory

# Verify branch is at merge commit
git log -1 --oneline
# Expected: "merge: reintegrate background-checks..."

# Verify all tests pass locally
cd backend && python -m pytest tests/ --tb=short -q
# Expected: All tests pass
```

### 6.2 Deploy to Staging Environment

**Deployment steps (environment-specific):**

```bash
# Option 1: Docker-based deployment
cd projects/open-source-rideshare
docker build -t openride:staging .
docker-compose -f docker-compose.test.yml up -d
# Wait for container to start
sleep 10

# Option 2: Kubernetes
kubectl set image deployment/openride-backend openride-backend=openride:staging
kubectl rollout status deployment/openride-backend --timeout=5m

# Option 3: Traditional server
git pull origin master
cd backend && pip install -e ".[dev]"
alembic upgrade head
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

### 6.3 Staging Validation Tests

**Run integration tests against staging:**

```bash
# Set staging database URL
export OPENRIDE_TEST_DATABASE_URL="postgresql+asyncpg://user:pass@staging-db/openride"
export FIREBASE_CREDENTIALS_JSON="<staging firebase credentials>"
export CHECKR_API_KEY="<staging checkr key>"

cd backend

# Run integration tests
python -m pytest tests/ -m integration -v --tb=short

# Expected: All database-dependent tests pass
# Examples:
# - Database migration tests
# - Real (not mocked) Checkr API integration
# - Real Firebase initialization
# - Real Stripe payment flow (if test Stripe key configured)
```

### 6.4 Smoke Test Checklist

**Manual smoke tests on staging:**

| Test | Command | Expected |
|---|---|---|
| API Health | `curl https://staging-api.example.com/health` | `200 OK` |
| Background Check Order | `POST /api/v1/background-checks/order` with valid driver_id | `201 Created` with check_id |
| Device Token Register | `POST /api/v1/device-tokens` with valid token | `201 Created` |
| Push Notification | Manual: trigger notification to test device | Notification appears on phone |
| Webhook Delivery | `POST /api/v1/background-checks/webhook` with Checkr payload | `200 OK` |
| Tip Submission | `POST /api/v1/rides/{ride_id}/tip` with amount | `201 Created` |
| Admin Override | `POST /api/v1/background-checks/{id}/override` with admin auth | `200 OK` |

**Validation Checklist:**
- [ ] All smoke tests pass
- [ ] No error logs in application output
- [ ] Database migrations complete
- [ ] Firebase authentication works
- [ ] Checkr API connectivity verified
- [ ] Twilio SMS sending verified
- [ ] Stripe integration (if applicable) verified

---

## Phase 7: Production Deployment (1 hour)

### 7.1 Pre-Deployment Verification

```bash
# Final safety checks
git log master -1 --oneline
# Expected: Merge commit from feature branch

git diff origin/master master | wc -l
# Expected: ~6,076 new commits (large diff is OK)

# Verify no unstaged changes
git status
# Expected: Working tree clean

# Last-minute test run
cd backend && python -m pytest tests/ -q --tb=line
# Expected: All tests pass
```

### 7.2 Deployment Steps (Production)

**Option 1: Rolling Deployment (Zero Downtime)**

```bash
# 1. Apply database migrations (non-blocking)
cd backend && alembic upgrade head --sql | head -5  # Preview
alembic upgrade head  # Execute (usually <1 min)

# 2. Health check before next step
curl https://api.example.com/health --connect-timeout 2
# Expected: 200 OK

# 3. Deploy new code (rolling update)
# - If using Kubernetes:
kubectl set image deployment/openride-backend \
  openride-backend=openride:$(git rev-parse --short HEAD)
kubectl rollout status deployment/openride-backend --timeout=10m

# - If using Docker Compose:
docker pull openride:latest
docker-compose up -d --no-deps --build openride-backend

# 4. Smoke test production
curl https://api.example.com/api/v1/health
# Expected: 200 OK with full schema

# 5. Monitor for errors (next 30 minutes)
# Watch: error logs, failed push notifications, database connection errors
tail -f /var/log/openride/app.log
```

**Option 2: Blue-Green Deployment**

```bash
# 1. Deploy new code to "green" environment (parallel, idle)
# 2. Run full smoke test suite against green
# 3. Switch load balancer from "blue" (old) to "green" (new)
# 4. Monitor for 30 minutes, rollback if needed
```

### 7.3 Post-Deployment Monitoring (1 hour)

**Monitor these metrics:**

| Metric | Normal | Alert Threshold |
|---|---|---|
| API Response Time | <100ms p95 | >500ms |
| Error Rate | <0.1% | >1% |
| Database Connection Pool | 70–90% utilization | >95% |
| Push Notification Delivery | >99% | <95% |
| Background Check Webhooks | <5 min latency | >1 hour |

**Log monitoring:**

```bash
# Watch for errors
grep -i "error\|exception" /var/log/openride/app.log | tail -20

# Watch for Firebase issues
grep "firebase" /var/log/openride/app.log | tail -10

# Watch for Checkr issues
grep "checkr" /var/log/openride/app.log | tail -10

# Watch for database errors
grep "postgres\|database" /var/log/openride/app.log | tail -10
```

**Validation Checklist:**
- [ ] Deployment completed without errors
- [ ] All services healthy
- [ ] API responding normally
- [ ] No spike in error rate
- [ ] Database migrations verified in production
- [ ] Push notifications delivering
- [ ] Background check webhooks working

---

## Phase 8: Rollback Plan (2 hours max)

### If Deployment Fails

**Decision Tree:**

```
Post-deployment error detected?
  ├─ API not responding? → Rollback (5 min)
  ├─ Database migration failed? → Rollback & fix (30 min)
  ├─ Firebase not working? → Disable feature flag, continue (10 min)
  ├─ Checkr webhook failing? → Disable background check orders, continue (5 min)
  ├─ Push notifications broken? → Disable, continue (5 min)
  └─ Performance degradation >50%? → Rollback (5 min)
```

### Rollback Steps

**Option 1: Fast Rollback (Code Only, <5 min)**

```bash
# Revert to previous stable deployment
git revert -m 1 <merge-commit-sha>
git push origin master

# Redeploy previous version
docker pull openride:previous
docker-compose up -d --no-deps openride-backend

# Or Kubernetes:
kubectl rollout undo deployment/openride-backend
kubectl rollout status deployment/openride-backend --timeout=5m

# Verify rolled back
curl https://api.example.com/api/v1/health
```

**Option 2: Database Rollback (If Migration Failed, ~30 min)**

```bash
# Identify which migration failed
alembic current
# Expected: Shows previous stable migration

# Downgrade to previous state
alembic downgrade -1  # Revert last migration

# Verify rollback
alembic current

# Then redeploy code
docker pull openride:previous
docker-compose up -d --no-deps openride-backend
```

### Rollback Decision Criteria

**DO rollback if:**
- [ ] API error rate >5% (vs. normal <0.1%)
- [ ] Database connection pool exhausted (can't create new connections)
- [ ] Push notifications failing completely (0% delivery)
- [ ] Cascading failures affecting multiple features

**DO NOT rollback if:**
- [ ] Minor feature (tipping) not working, others OK → disable feature flag instead
- [ ] Single provider (Checkr) failing → disable gracefully, continue
- [ ] Logging/monitoring issues → fix and monitor, no rollback

### Rollback Validation

```bash
# After rollback:
cd backend && python -m pytest tests/ -q --tb=line
# Expected: All tests pass

# Verify previous version working
curl https://api.example.com/api/v1/health
# Expected: 200 OK, no new errors

# Monitor for 1 hour
tail -f /var/log/openride/app.log
```

---

## Summary Checklist

### Pre-Merge
- [ ] Feature audit complete
- [ ] Conflict assessment understood
- [ ] Team aware of deployment timeline

### Phase 1: Firebase Setup
- [ ] Service account key generated
- [ ] FIREBASE_CREDENTIALS_JSON env var set
- [ ] Device token registration pipeline tested
- [ ] Push notification E2E test passed

### Phase 2: Checkr Setup
- [ ] CHECKR_API_KEY and CHECKR_WEBHOOK_SECRET set
- [ ] Webhook endpoint registered in Checkr console
- [ ] Webhook signature verification test passed
- [ ] Auto-approve logic tested

### Phase 3: Environment
- [ ] All env vars present (Firebase, Checkr, Twilio, Stripe)
- [ ] .env.example updated
- [ ] Secrets manager integration working

### Phase 4: Database
- [ ] All migrations applied
- [ ] All tables verified in database
- [ ] Migration chain validated

### Phase 5: Testing
- [ ] Background check tests (74) all pass
- [ ] Availability tests (20) all pass
- [ ] Tipping tests (45) all pass
- [ ] Full test suite (1,994) all pass
- [ ] Coverage >80%

### Phase 6: Staging
- [ ] Staging deployment successful
- [ ] Integration tests pass on staging
- [ ] Smoke test checklist complete
- [ ] No errors in staging logs

### Phase 7: Production
- [ ] Pre-deployment verification complete
- [ ] Deployment completed without errors
- [ ] Post-deployment monitoring clear
- [ ] Rollback plan understood by team

### Phase 8: Monitoring
- [ ] Metrics normal (response time, error rate)
- [ ] Push notifications delivering
- [ ] Background check webhooks working
- [ ] Logs clean (no exceptions)
- [ ] 1-hour post-deployment review passed

---

## Timeline Estimate

| Phase | Estimated Duration | Actual Start | Actual End |
|---|---|---|---|
| 1. Firebase Setup | 1.5 hours | | |
| 2. Checkr Setup | 1 hour | | |
| 3. Environment Config | 30 min | | |
| 4. Database Migrations | 1 hour | | |
| 5. Feature Validation | 3–4 hours | | |
| 6. Staging Deployment | 2 hours | | |
| 7. Production Deployment | 1 hour | | |
| 8. Monitoring & Sign-Off | 1 hour | | |
| **TOTAL** | **10–11 hours** | | |

**Recommended deployment window:** June 16 17:00 UTC → June 17 04:00 UTC (11-hour window, allows rollback if needed before business hours)

---

## Contact & Escalation

- **Deployment Lead:** [Name]
- **Checkr Account Manager:** [Contact]
- **Firebase Support:** firebase-support@anthropic.com
- **Rollback Authority:** [Name]

**Escalation Criteria:**
- Any phase takes >2x estimated time → escalate to tech lead
- Database migration fails → escalate to DBA
- Firebase issues → escalate to Firebase support + internal DevOps
- Rollback needed → notify all stakeholders immediately
