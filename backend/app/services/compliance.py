"""Compliance gate service for driver eligibility checks.

Determines whether a driver is permitted to go online based on their
membership status and the currency of their compliance documents
(license, background check, vehicle inspection, insurance endorsement).

Grace periods are per-jurisdiction:
- License: 14 days (configurable via Jurisdiction.license_grace_days)
- Background check: 30 days (configurable via Jurisdiction.background_check_grace_days)

Vehicle inspection and insurance endorsement currently have no grace period —
they must be current on the day of the check.

Nightly cron integration:
    The ``run_nightly_compliance_check`` coroutine is designed to be called
    by the existing dispatch scheduler or a dedicated cron task.  It updates
    all drivers whose docs have lapsed since the last run.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.driver import DriverProfile, MembershipStatus

if TYPE_CHECKING:
    from app.models.jurisdiction import Jurisdiction


class ComplianceField(str, enum.Enum):
    """Named compliance document / status fields checked during gate evaluation."""

    MEMBERSHIP_STATUS = "membership_status"
    LICENSE = "license"
    BACKGROUND_CHECK = "background_check"
    VEHICLE_INSPECTION = "vehicle_inspection"
    INSURANCE_ENDORSEMENT = "insurance_endorsement"


@dataclass
class ComplianceIssue:
    """A single compliance problem found during a gate check.

    Attributes:
        field: Which document or status field caused the issue.
        message: User-facing message (safe to display; does not leak internals).
        days_until_expiry: Positive means not yet expired; negative means already
            past expiry.  None if the field is missing entirely.
    """

    field: ComplianceField
    message: str
    days_until_expiry: int | None = None


@dataclass
class ComplianceResult:
    """Outcome of a single driver compliance check.

    Attributes:
        driver_id: The DriverProfile.id that was evaluated.
        eligible: True only when the driver may go online right now.
        issues: Zero or more issues found.  Empty when eligible=True.
        checked_at: UTC timestamp of the evaluation (for logging).
    """

    driver_id: int
    eligible: bool
    issues: list[ComplianceIssue] = field(default_factory=list)
    checked_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


# ── Grace-period constants (overridden by Jurisdiction when available) ──────

_DEFAULT_LICENSE_GRACE_DAYS = 14
_DEFAULT_BACKGROUND_CHECK_GRACE_DAYS = 30


def _days_until(expiry: date | None, today: date) -> int | None:
    """Return the number of days until *expiry*, or None if not set.

    Positive = days remaining; negative = days past expiry.
    """
    if expiry is None:
        return None
    return (expiry - today).days


def _is_expired_beyond_grace(days_remaining: int | None, grace_days: int) -> bool:
    """Return True when a document is past its grace period.

    A None expiry (document never recorded) is treated as immediately expired
    with no grace period, because we cannot confirm currency.
    """
    if days_remaining is None:
        return True  # Unknown = not current
    return days_remaining < -grace_days


def check_driver_compliance(
    profile: DriverProfile,
    jurisdiction: Jurisdiction | None = None,
    today: date | None = None,
) -> ComplianceResult:
    """Evaluate whether *profile* is currently eligible to go online.

    Args:
        profile: The DriverProfile to evaluate.
        jurisdiction: Optional jurisdiction config; used for grace-period
            overrides.  Falls back to module-level defaults when None.
        today: Override the current date (useful for testing).

    Returns:
        A ComplianceResult with eligible=True only when all checks pass.
    """
    today = today or date.today()

    license_grace = (
        jurisdiction.license_grace_days if jurisdiction else _DEFAULT_LICENSE_GRACE_DAYS
    )
    bgcheck_grace = (
        jurisdiction.background_check_grace_days
        if jurisdiction
        else _DEFAULT_BACKGROUND_CHECK_GRACE_DAYS
    )

    issues: list[ComplianceIssue] = []

    # ── 1. Membership status ───────────────────────────────────────────────
    if profile.membership_status == MembershipStatus.SUSPENDED:
        issues.append(ComplianceIssue(
            field=ComplianceField.MEMBERSHIP_STATUS,
            message="Your account is currently suspended. Contact support to resolve.",
        ))
    elif profile.membership_status == MembershipStatus.TERMINATED:
        issues.append(ComplianceIssue(
            field=ComplianceField.MEMBERSHIP_STATUS,
            message="Your cooperative membership has been terminated.",
        ))
    elif profile.membership_status == MembershipStatus.COMPLIANCE_HOLD:
        issues.append(ComplianceIssue(
            field=ComplianceField.MEMBERSHIP_STATUS,
            message=(
                "Your account is on a compliance hold due to expired documents. "
                "Please upload current documents to continue."
            ),
        ))
    # PROBATION is allowed online — no issue added.

    # ── 2. Driver's license ────────────────────────────────────────────────
    license_days = _days_until(profile.license_expiry, today)
    if _is_expired_beyond_grace(license_days, license_grace):
        if license_days is None:
            msg = "No license expiry date on file. Please upload a current license."
        elif license_days < 0:
            msg = f"Your license expired {-license_days} day(s) ago. Please upload a renewal."
        else:
            # Within grace window but technically expired
            msg = f"Your license expires in {license_days} day(s). Please renew before going online."
        issues.append(ComplianceIssue(
            field=ComplianceField.LICENSE,
            message=msg,
            days_until_expiry=license_days,
        ))

    # ── 3. Background check ────────────────────────────────────────────────
    bgcheck_days = _days_until(profile.background_check_expiry, today)
    if _is_expired_beyond_grace(bgcheck_days, bgcheck_grace):
        if bgcheck_days is None:
            msg = "No background check on file. Please complete a background check."
        elif bgcheck_days < 0:
            msg = (
                f"Your background check expired {-bgcheck_days} day(s) ago. "
                "Please contact support to initiate a new check."
            )
        else:
            msg = (
                f"Your background check expires in {bgcheck_days} day(s). "
                "Please arrange a renewal soon."
            )
        issues.append(ComplianceIssue(
            field=ComplianceField.BACKGROUND_CHECK,
            message=msg,
            days_until_expiry=bgcheck_days,
        ))

    # ── 4. Vehicle inspection (no grace period) ────────────────────────────
    inspection_days = _days_until(profile.vehicle_inspection_expiry, today)
    if inspection_days is not None and inspection_days < 0:
        issues.append(ComplianceIssue(
            field=ComplianceField.VEHICLE_INSPECTION,
            message=(
                f"Your vehicle inspection expired {-inspection_days} day(s) ago. "
                "Please have your vehicle inspected before driving."
            ),
            days_until_expiry=inspection_days,
        ))
    elif inspection_days is None:
        # Missing is not a hard block for now — cooperative may not have collected yet
        pass

    # ── 5. Insurance endorsement (no grace period) ─────────────────────────
    ins_days = _days_until(profile.insurance_endorsement_expiry, today)
    if ins_days is not None and ins_days < 0:
        issues.append(ComplianceIssue(
            field=ComplianceField.INSURANCE_ENDORSEMENT,
            message=(
                f"Your TNC insurance endorsement expired {-ins_days} day(s) ago. "
                "Please upload a current certificate before driving."
            ),
            days_until_expiry=ins_days,
        ))

    eligible = len(issues) == 0
    return ComplianceResult(driver_id=profile.id, eligible=eligible, issues=issues)


# ── Nightly cron helper ──────────────────────────────────────────────────────

async def run_nightly_compliance_check(db: AsyncSession) -> dict[str, int]:
    """Update membership status for all drivers whose documents have lapsed.

    Intended to be called at 02:00 UTC by the cooperative's scheduler.

    For each driver:
    - If any hard-blocked document is beyond its grace period and the
      driver is currently ``active`` or ``probation``, set status to
      ``compliance_hold``.
    - If the driver is already on ``compliance_hold`` and all documents
      are now current, status is NOT automatically restored — reinstatement
      requires an admin action (upload + manual review).

    Returns:
        A summary dict with keys ``checked``, ``placed_on_hold``.
    """
    today = date.today()
    result = await db.execute(select(DriverProfile))
    profiles = result.scalars().all()

    checked = 0
    placed_on_hold = 0

    for profile in profiles:
        checked += 1

        # Only auto-hold drivers who are currently reachable
        if profile.membership_status not in (
            MembershipStatus.ACTIVE, MembershipStatus.PROBATION
        ):
            continue

        # Load jurisdiction if set (lazy — avoids N+1 on most deployments
        # where jurisdiction is set; falls back to defaults otherwise)
        jurisdiction: Jurisdiction | None = None
        if profile.jurisdiction_id:
            from app.models.jurisdiction import Jurisdiction as JModel  # local import
            j_result = await db.execute(
                select(JModel).where(JModel.id == profile.jurisdiction_id)
            )
            jurisdiction = j_result.scalar_one_or_none()

        compliance = check_driver_compliance(profile, jurisdiction=jurisdiction, today=today)

        if not compliance.eligible:
            profile.membership_status = MembershipStatus.COMPLIANCE_HOLD
            placed_on_hold += 1

    await db.commit()
    return {"checked": checked, "placed_on_hold": placed_on_hold}
