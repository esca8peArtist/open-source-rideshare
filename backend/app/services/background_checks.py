"""Checkr background check integration service.

Provides async methods for creating candidates, ordering checks, polling
status, and handling webhooks.  When OPENRIDE_CHECKR_API_KEY is not
configured the service degrades gracefully — calls return simulated
pending status so development / CI can run without real credentials.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.background_check import BackgroundCheck, BackgroundCheckStatus

logger = logging.getLogger(__name__)

_CHECKR_BASE_URL = "https://api.checkr.com/v1"

# Allowed packages
VALID_PACKAGES = {"driver_pro", "motor_vehicle_report", "basic"}

# Statuses that indicate the check is complete (terminal)
TERMINAL_STATUSES = {
    BackgroundCheckStatus.CLEAR,
    BackgroundCheckStatus.CONSIDER,
    BackgroundCheckStatus.SUSPENDED,
    BackgroundCheckStatus.DISPUTE,
    BackgroundCheckStatus.CANCELLED,
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _checkr_configured() -> bool:
    return bool(getattr(settings, "checkr_api_key", None))


def _auth() -> tuple[str, str]:
    """Return (username, password) for Checkr HTTP basic auth."""
    return (settings.checkr_api_key, "")  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Candidate management
# ---------------------------------------------------------------------------


async def create_candidate(
    first_name: str,
    last_name: str,
    email: str,
    phone: str | None = None,
    dob: str | None = None,
    ssn_last4: str | None = None,
    zip_code: str | None = None,
) -> dict[str, Any]:
    """Create a Checkr candidate record.

    Returns a dict with ``id`` (candidate_id) and ``object`` = "candidate".
    When Checkr is not configured, returns a simulated response.
    """
    if not _checkr_configured():
        logger.info(
            "Checkr not configured — returning simulated candidate for %s %s",
            first_name,
            last_name,
        )
        return {
            "id": f"sim_candidate_{email.replace('@', '_')}",
            "object": "candidate",
            "email": email,
            "simulated": True,
        }

    try:
        import aiohttp

        payload: dict[str, Any] = {
            "first_name": first_name,
            "last_name": last_name,
            "email": email,
        }
        if phone:
            payload["phone"] = phone
        if dob:
            payload["dob"] = dob
        if ssn_last4:
            payload["ssn"] = ssn_last4
        if zip_code:
            payload["zipcode"] = zip_code

        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{_CHECKR_BASE_URL}/candidates",
                json=payload,
                auth=aiohttp.BasicAuth(*_auth()),
            ) as resp:
                resp.raise_for_status()
                data = await resp.json()
                logger.info("Checkr candidate created: %s", data.get("id"))
                return data
    except ImportError:
        logger.error("aiohttp not installed — cannot call Checkr API")
        raise
    except Exception:
        logger.exception("Failed to create Checkr candidate for %s %s", first_name, last_name)
        raise


# ---------------------------------------------------------------------------
# Ordering checks
# ---------------------------------------------------------------------------


async def order_check(
    candidate_id: str,
    package: str = "driver_pro",
) -> dict[str, Any]:
    """Order a background check for an existing Checkr candidate.

    Returns a dict with ``id`` (report / check id) and ``status``.
    """
    if package not in VALID_PACKAGES:
        raise ValueError(f"Invalid package '{package}'. Valid: {VALID_PACKAGES}")

    if not _checkr_configured() or candidate_id.startswith("sim_"):
        logger.info("Checkr not configured — returning simulated check order")
        return {
            "id": f"sim_check_{candidate_id}_{package}",
            "object": "report",
            "status": "pending",
            "package": package,
            "candidate_id": candidate_id,
            "simulated": True,
        }

    try:
        import aiohttp

        payload = {
            "package": package,
            "candidate_id": candidate_id,
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{_CHECKR_BASE_URL}/reports",
                json=payload,
                auth=aiohttp.BasicAuth(*_auth()),
            ) as resp:
                resp.raise_for_status()
                data = await resp.json()
                logger.info(
                    "Checkr check ordered: %s (status=%s)",
                    data.get("id"),
                    data.get("status"),
                )
                return data
    except ImportError:
        logger.error("aiohttp not installed — cannot call Checkr API")
        raise
    except Exception:
        logger.exception("Failed to order Checkr check for candidate %s", candidate_id)
        raise


# ---------------------------------------------------------------------------
# Status polling
# ---------------------------------------------------------------------------


async def get_check_status(check_id: str) -> dict[str, Any]:
    """Fetch the current status of a Checkr report.

    Returns dict with ``id``, ``status``, and optional ``report_url``.
    """
    if not _checkr_configured() or check_id.startswith("sim_"):
        return {
            "id": check_id,
            "status": "pending",
            "simulated": True,
        }

    try:
        import aiohttp

        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{_CHECKR_BASE_URL}/reports/{check_id}",
                auth=aiohttp.BasicAuth(*_auth()),
            ) as resp:
                resp.raise_for_status()
                return await resp.json()
    except ImportError:
        logger.error("aiohttp not installed — cannot call Checkr API")
        raise
    except Exception:
        logger.exception("Failed to get Checkr check status for %s", check_id)
        raise


# ---------------------------------------------------------------------------
# Webhook handling
# ---------------------------------------------------------------------------


def _verify_webhook_signature(payload_body: bytes, signature: str) -> bool:
    """Validate Checkr HMAC-SHA256 webhook signature.

    Checkr sends ``X-Checkr-Signature`` as hex digest.
    Returns True if valid (or if webhook secret not configured — dev mode).
    """
    secret = getattr(settings, "checkr_webhook_secret", None)
    if not secret:
        logger.warning("Checkr webhook secret not configured — accepting all webhooks (dev mode)")
        return True

    expected = hmac.new(
        secret.encode("utf-8"),
        payload_body,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


def _parse_checkr_status(raw_status: str) -> BackgroundCheckStatus:
    """Map Checkr report status string to our enum."""
    mapping = {
        "clear": BackgroundCheckStatus.CLEAR,
        "consider": BackgroundCheckStatus.CONSIDER,
        "suspended": BackgroundCheckStatus.SUSPENDED,
        "dispute": BackgroundCheckStatus.DISPUTE,
        "cancelled": BackgroundCheckStatus.CANCELLED,
        "pending": BackgroundCheckStatus.PENDING,
    }
    return mapping.get(raw_status.lower(), BackgroundCheckStatus.PENDING)


async def handle_webhook(
    payload: dict[str, Any],
    signature: str,
    payload_body: bytes,
    db: AsyncSession,
) -> dict[str, str]:
    """Process a Checkr webhook event.

    Validates the signature, finds the matching BackgroundCheck record,
    updates status, and triggers driver profile side effects as needed.

    Returns ``{"status": "ok"}`` or raises on validation failure.
    """
    if not _verify_webhook_signature(payload_body, signature):
        logger.warning("Checkr webhook signature validation failed")
        return {"status": "invalid_signature"}

    event_type = payload.get("type", "")
    data = payload.get("data", {}).get("object", {})

    if event_type not in {"report.completed", "report.updated"}:
        logger.debug("Ignoring Checkr webhook event type: %s", event_type)
        return {"status": "ignored"}

    check_id = data.get("id")
    if not check_id:
        logger.warning("Checkr webhook missing report id")
        return {"status": "missing_id"}

    result = await db.execute(
        select(BackgroundCheck).where(BackgroundCheck.checkr_check_id == check_id)
    )
    check = result.scalar_one_or_none()
    if not check:
        logger.warning("No BackgroundCheck found for Checkr report %s", check_id)
        return {"status": "not_found"}

    raw_status = data.get("status", "pending")
    new_status = _parse_checkr_status(raw_status)
    check.status = new_status
    check.report_url = data.get("report_url")

    if new_status in TERMINAL_STATUSES:
        check.completed_at = datetime.now(timezone.utc)

    await db.flush()
    logger.info(
        "Background check %d (Checkr %s) updated to %s",
        check.id,
        check_id,
        new_status.value,
    )

    # Trigger driver profile side effects
    await _handle_check_completed(db, check)

    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Driver profile integration
# ---------------------------------------------------------------------------


async def _handle_check_completed(db: AsyncSession, check: BackgroundCheck) -> None:
    """Side effects when a background check completes.

    - CLEAR: update driver.background_check_status; attempt auto-approve if
      all required documents are also approved.
    - CONSIDER / SUSPENDED: flag driver for admin review.
    """
    from app.models.driver import DriverProfile

    result = await db.execute(
        select(DriverProfile).where(DriverProfile.id == check.driver_profile_id)
    )
    profile = result.scalar_one_or_none()
    if not profile:
        return

    if check.status == BackgroundCheckStatus.CLEAR:
        profile.background_check_status = "clear"
        await db.flush()
        # Try auto-approve if all required docs are verified
        await _attempt_auto_approve(db, check.driver_profile_id, profile)

    elif check.status in {BackgroundCheckStatus.CONSIDER, BackgroundCheckStatus.SUSPENDED}:
        profile.background_check_status = check.status.value
        await db.flush()
        logger.info(
            "Driver profile %d flagged for admin review (background check: %s)",
            check.driver_profile_id,
            check.status.value,
        )


async def _attempt_auto_approve(
    db: AsyncSession, driver_profile_id: int, profile: Any
) -> None:
    """Auto-approve driver if background check is clear AND all docs verified."""
    try:
        from app.services.verification import get_verification_status

        verification = await get_verification_status(db, driver_profile_id)
        if verification["all_required_approved"]:
            if not profile.is_approved:
                profile.is_approved = True
                await db.flush()
                logger.info(
                    "Driver profile %d auto-approved (background check clear + all docs verified)",
                    driver_profile_id,
                )
    except Exception:
        logger.exception(
            "Error during auto-approve check for driver profile %d", driver_profile_id
        )


# ---------------------------------------------------------------------------
# Admin override
# ---------------------------------------------------------------------------


async def admin_override_check(
    db: AsyncSession,
    check_id: int,
    new_status: BackgroundCheckStatus,
    reason: str,
    admin_user_id: int,
) -> BackgroundCheck:
    """Admin override of a background check result.

    Allowed target statuses: CLEAR, CONSIDER, CANCELLED.
    """
    allowed = {BackgroundCheckStatus.CLEAR, BackgroundCheckStatus.CONSIDER, BackgroundCheckStatus.CANCELLED}
    if new_status not in allowed:
        raise ValueError(
            f"Admin may only override to: {', '.join(s.value for s in allowed)}"
        )

    result = await db.execute(
        select(BackgroundCheck).where(BackgroundCheck.id == check_id)
    )
    check = result.scalar_one_or_none()
    if not check:
        raise ValueError(f"BackgroundCheck {check_id} not found")

    check.status = new_status
    check.admin_override_reason = reason
    check.overridden_by = admin_user_id
    check.completed_at = check.completed_at or datetime.now(timezone.utc)
    await db.flush()

    logger.info(
        "Admin %d overrode background check %d to %s: %s",
        admin_user_id,
        check_id,
        new_status.value,
        reason,
    )

    # Re-run driver side effects with new status
    await _handle_check_completed(db, check)

    return check
