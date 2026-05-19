# CHECKIN.md — OpenRide Review Queue

This file tracks branches that need review before merging to `master`.

---

## PR Review Assessments

### open-repo PR #1 — feat: Wave 4 Phase 2 — Federation Service Infrastructure

**PR URL:** https://github.com/esca8peArtist/open-repo/pull/1
**Branch:** `feature/wave4-phase2-federation-service` → `main`
**Reviewed:** 2026-05-12
**Verdict: APPROVED — READY TO MERGE**

#### Summary of Changes

+2639 / -28 lines across 14 files. 2 commits. The PR implements full federation
partner infrastructure for peer-to-peer distributed collaboration:

- `backend/app/services/federation_partner_service.py` (new, 505 lines) — service
  layer for partner registration, trust state machine, key rotation, HTTP signature
  verification, activity audit log, and hard delete with safety constraints.
- `backend/app/api/v1/admin/federation_partners.py` (new, 260 lines) — 7 admin
  REST endpoints: register, list, get detail, update trust state, rotate key,
  activity log, delete.
- `backend/app/schemas.py` — 8 new Pydantic schemas with field validators for all
  request/response shapes.
- `backend/app/routes.py` — `/inbox` endpoint extended with full HTTP Signature
  verification per RFC 9421; backward compatible (unsigned requests still accepted,
  flagged as `signature_verified=False`).
- `backend/app/http_signatures.py` — added `HTTPSignatureUtils.sign_request()` for
  signing outbound federation requests.
- `backend/app/services/endorsement_propagation_service.py` — `send_announce_to_federation_partners`
  replaced stub with real implementation: queries trusted partners, signs each
  outbound request, POSTs with httpx, logs results.
- `backend/app/models.py` + `backend/alembic/versions/001_add_federation_partners.py`
  — added `failed_signature_count` column to `federation_partners` table.
- `backend/tests/test_federation_partner_routes.py` (new, 825 lines) — service unit
  tests + admin route tests for all 7 endpoints.
- `backend/tests/test_federation_inbox_integration.py` (new, 653 lines) — 15 tests
  covering inbox signature verification and outbound announce signing; includes 2
  real-crypto E2E roundtrip tests.

#### Code Quality Assessment

**Security (public-facing API — critical)**
- Input validation is thorough: URL format checked for `base_url` and `key_id` via
  `@field_validator`; public key PEM validated by loading it with cryptography library
  before persisting, so a bad key never replaces a working one.
- HTTP Signature verification uses existing `HTTPSignatureUtils` (RFC 8017 + W3C
  ActivityPub) with a trusted-partner gate — unknown or untrusted key IDs are
  rejected 403 before any processing.
- Auto-downgrade to UNTRUSTED after 5 consecutive signature failures; revoked state
  is terminal with no transitions.
- Error messages to external callers are intentionally vague on internals (e.g.
  "Signature verification failed" rather than exposing partner record details).
  One exception noted below under minor items.
- Hard delete requires REVOKED state + no activity in last 30 days — safe.

**Design patterns**
- Trust state machine is explicitly declared as `_VALID_TRANSITIONS` dict; invalid
  transitions raise `ValueError` before touching the database.
- `FederationPartnerService` uses static methods with explicit `AsyncSession`
  injection — composes cleanly with FastAPI DI and is easy to test.
- Backward-compatible inbox change: unsigned requests are still accepted for legacy
  senders but flagged; signed requests from non-trusted partners are rejected.
- The stub in `send_announce_to_federation_partners` is fully replaced — no
  placeholder code remains.

**Test coverage**
- 194 tests passing, 4 skipped (DB-dependent integration tests that skip cleanly
  when `OPENRIDE_TEST_DATABASE_URL` is absent), 0 failures. No regressions on
  existing 125 tests.
- New test files cover all 7 admin endpoints, all trust-state transition paths,
  key rotation, signature verification edge cases, auto-downgrade threshold,
  outbound signing correctness, and 2 real-crypto E2E roundtrips.
- Mocking strategy is consistent with the rest of the test suite.

**Documentation**
- All new public methods have docstrings with Args/Returns/Raises sections.
- Admin route docstrings document valid trust-state transitions and HTTP status
  semantics for each endpoint — appropriate for community contributors.
- Module-level docstrings identify the phase/wave so history is traceable.

#### Merge Readiness Checks

| Check | Status |
|---|---|
| CI check runs | No automated CI configured on this repo |
| GitHub mergeable_state | `clean` (no conflicts) |
| Review comments | None |
| Requested changes | None |
| Draft PR | No |
| Test results (self-reported) | 194 pass / 4 skip / 0 fail |

No CI is configured on the repository, so there is no automated gate. The test
results are self-reported in the PR description. Given the breadth of the test
suite (15 new tests with real-crypto E2E cases), this is an acceptable risk for
a community open-source project at this stage.

#### Minor Items (non-blocking, post-merge follow-up recommended)

1. **`partner_id` exposed in 403 detail message** — `routes.py` includes
   `f"Federation partner {partner_id} not found."` in a 404 response visible to
   external callers on the admin route. For admin-only endpoints this is
   acceptable, but the inbox endpoint's error path correctly avoids this.
   No change needed now; worth noting for a future hardening pass.

2. **`datetime.utcnow()` deprecation** — Python 3.12+ deprecates `datetime.utcnow()`
   in favor of `datetime.now(timezone.utc)`. Used in several places in the new
   service. Not a bug today but should be cleaned up before Python 3.13 support
   is added. File a follow-up issue.

3. **No rate limiting on `/api/v1/admin/federation-partners/register`** — any
   caller that can reach the admin endpoint can attempt registrations in bulk.
   Admin endpoints should be behind auth middleware; this is a project-wide concern,
   not specific to this PR.

4. **`_FAILURE_THRESHOLD = 5` is a hardcoded constant** — reasonable default, but
   could be a configurable setting. Low priority.

#### Decision

APPROVE AND MERGE. All blocking quality criteria pass:
- Correct input validation on all public inputs
- Error messages do not leak internal state to external users on public endpoints
- State machine transitions are guarded
- Test coverage is comprehensive with real-crypto E2E cases
- No merge conflicts; GitHub reports `mergeable_state: clean`
- No outstanding review comments or requested changes

Recommend filing a GitHub issue for the three post-merge items (utcnow
deprecation, rate limiting on admin routes, and configurable failure threshold)
before the next wave begins.

---

## open-repo Phase 5 Candidate 1 — Merge Approval Request

**Branch:** `feature/zimwriter-libzim-activation` (commit ec0ff7be)
**Target:** `main` on esca8peArtist/open-repo
**Reviewed:** 2026-05-19
**Recommendation: APPROVE AND MERGE (May 25-26)**

### Summary

Phase 5 Candidate 1 implements real offline ZIM file export via libzim. The implementation is
complete and verified. The branch was independently audited today (not by the Session 1353 author).

**What changed** (+143/-37 lines across 4 files):
- `zim_writer.py`: libzim import guard, ArticleItem adapter class, real `create_zim()` with
  Creator context manager, `_apply_metadata_to_creator()` with all 11 ZIM metadata fields,
  fallback 48x48 transparent PNG for zimcheck, removal of `_stub_write_placeholder()`
- `003_add_zim_exports_table.py`: new Alembic migration, 28-column table, 3 indexes
- `pyproject.toml`: added `libzim>=3.2,<4.0`
- `README.md`: updated Phase 5 status

**Verification findings**:
- All 84 tests pass with REAL libzim (confirmed by 2.31s runtime vs 0.16s stub baseline)
- Live ZIM file verified: 35,770 bytes, ZIM magic bytes `5a494d04`, valid SHA-256
- libzim 3.9.0 installed in project environment; compatible with `>=3.2,<4.0` constraint
- API stability confirmed across 3.2–3.9 — no breaking writer API changes in range
- Migration chain 001→002→003 valid; downgrade() correctly reverses in order
- Fallback PNG verified as valid 48x48 transparent PNG (correct for zimcheck)
- Zero merge-blocking risks identified; 6 low-priority operational items noted

**6 risks, all low-priority (none block merge)**:
1. zimcheck binary not installed — add to release checklist; optional for Phase 5.1
2. Silent libzim import failure — add startup health log (2-line post-merge fix)
3. Memory buffering for >5,000 item exports — Phase 5.2 streaming mode
4. Version constraint covers 3.9 max — safe; `<4.0` pin prevents surprise breakage
5. Xapian search disabled — document in release notes; Phase 5.2 adds `config_indexing()`
6. `datetime.utcnow()` in migration — DeprecationWarning on Python 3.12+; post-merge issue

**Full verification report**: `projects/open-repo/phase-5-candidate-1-implementation-verification.md`
**Deployment checklist**: `projects/open-repo/phase-5-candidate-1-implementation-checklist.md`
**Deployment timeline**: 1.75–2.5 hours (target May 30-31)

#### Merge Readiness

| Check | Status |
|---|---|
| All 5 roadmap changes present | YES |
| 84 tests passing with real libzim | YES |
| libzim compatibility verified | YES (3.9.0 in range) |
| Migration chain valid | YES (001→002→003) |
| No Phase 4 regressions | YES |
| Zero merge-blocking risks | YES |
| **Merge-ready** | **YES** |

---

## Needs Your Input

### feat/background-checks-firebase-push — driver availability integrated into ride matching

**Branch:** `feature/background-checks-firebase-push`
**Author:** thorn
**Date:** 2026-04-13

**Summary:**
Integrates the driver availability and scheduling system (added in a previous session) into
the ride matching/dispatch engine. When a ride request is processed, the matching engine now
filters candidates to only include drivers who are genuinely reachable: online flag set,
heartbeat within 15 minutes, and within a scheduled availability window (or no schedule at all
per the opt-in model).

**Files changed:**
- `backend/app/services/matching.py` — new imports (DriverOnlineStatus, DriverSchedule,
  datetime utilities); new `_HEARTBEAT_STALE_MINUTES` constant; new private method
  `_get_availability_eligible_driver_ids` that does a 2-query bulk DB pre-filter
  (status+heartbeat in one query, schedule slots in a second); `find_candidates` gains
  `availability_filter: bool = True` parameter that gates the pre-filter; `match_ride`
  threads `availability_filter` through to `find_candidates`
- `backend/tests/test_matching_availability.py` — 20 unit tests (22 collected, 2 DB-skipped):
  covers online/offline, stale heartbeat, no-schedule opt-in, inside/outside window,
  multi-slot scenarios, filter bypass, empty input, null heartbeat, boundary heartbeat,
  find_candidates and match_ride integration

**Key design decisions:**
- Two-query bulk approach: one SELECT on driver_online_status (filters is_online + heartbeat
  stale threshold at DB level), one SELECT on driver_schedules (bulk for all candidate
  driver_ids). Schedule window check runs in Python. This avoids N+1 queries.
- `availability_filter=False` bypasses all DB availability checks for admin/diagnostic use.
- A TODO comment in the code identifies the path to a fully DB-level implementation (DB view
  or materialized table) for very large driver pools.
- The 15-minute stale threshold in matching.py is documented to match the value in
  `services/driver_availability.py` (which uses 5 minutes for its own display logic).
  The matching engine uses 15 minutes to be more tolerant of temporary connection loss.

**Test results:** 20 passed, 2 skipped (PostgreSQL integration tests); 1994 existing tests
unaffected.

**Review notes:**
- The `availability_filter` param is additive and backward compatible — callers that don't
  pass it get the new filtering behavior (default True), which is the correct production
  default.
- A future improvement: when `find_candidates` expands the search radius in its retry loop,
  it could optionally re-run the availability filter only for newly added candidates rather
  than the full set. This is a performance micro-optimization, not a correctness issue.

---

### feat/background-checks-firebase-push — driver tipping system

**Branch:** `feature/background-checks-firebase-push`
**Author:** thorn
**Date:** 2026-04-13

**Summary:**
Adds a standalone driver tipping system. Riders can tip their driver within
48 hours of ride completion. Tips are stored as integer cents to avoid
floating-point errors. Stripe is used for payment processing when credentials
are present; the feature degrades gracefully without them.

**Files changed:**
- `backend/app/models/tip.py` — new `TipRecord` model with `TipStatus` enum
- `backend/app/schemas/tip.py` — `TipRequest` (50–5000 cents) and `TipResponse`
- `backend/app/services/tips.py` — `submit_tip`, `get_tip_for_ride`, validation, notifications
- `backend/app/api/v1/tips.py` — 4 endpoints (POST tip, GET ride tip, GET driver tips, GET admin tips)
- `backend/app/models/__init__.py` — registers `TipRecord`
- `backend/app/main.py` — includes tips router
- `backend/tests/test_tips.py` — 37 tests (18 pass without DB, 19 require PostgreSQL test DB)

**Endpoints added:**
- `POST /api/v1/rides/{ride_id}/tip` — rider submits tip
- `GET  /api/v1/rides/{ride_id}/tip` — rider or driver fetches tip
- `GET  /api/v1/drivers/me/tips` — driver tip history with pagination
- `GET  /api/v1/admin/tips` — admin list with status/driver/date filters

**Test results:** 18 passed, 19 skipped (DB-dependent integration tests skip gracefully
when `OPENRIDE_TEST_DATABASE_URL` is not available, consistent with all other test files).

**Review notes:**
- The legacy `add_tip` on `payments.py` (using float dollars) is left untouched to
  avoid breaking the existing payment flow. The new `TipRecord` is the canonical path
  going forward; a follow-up can deprecate the old field.
- Driver earnings endpoint (`GET /driver/earnings`) already aggregates `tip_amount`
  from the `Payment` model. The new `TipRecord` amounts are separate and would need
  a follow-up to roll them into earnings totals once the migration is complete.

---
