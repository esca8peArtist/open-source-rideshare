"""Business logic for accessibility and WAV certification.

Public API
----------
get_or_create_rider_profile(db, rider_id) -> RiderAccessibilityProfile
update_rider_profile(db, rider_id, data) -> RiderAccessibilityProfile
get_driver_wav(db, driver_id) -> DriverWAVCertification | None
submit_driver_wav(db, driver_id, data) -> DriverWAVCertification
admin_verify_wav(db, driver_id, admin_id, approve, note, expires_at)
    -> DriverWAVCertification
get_wav_platform_stats(db) -> WAVPlatformStats
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.accessibility import (
    DriverWAVCertification,
    RiderAccessibilityProfile,
    WAVCertificationStatus,
)
from app.schemas.accessibility import (
    DriverWAVCertificationSubmit,
    RiderAccessibilityProfileUpdate,
    WAVPlatformStats,
)


# ---------------------------------------------------------------------------
# Rider accessibility
# ---------------------------------------------------------------------------


async def get_or_create_rider_profile(
    db: AsyncSession,
    rider_id: int,
) -> RiderAccessibilityProfile:
    """Return the rider's profile, creating a blank one if it doesn't exist."""
    result = await db.execute(
        select(RiderAccessibilityProfile).where(
            RiderAccessibilityProfile.rider_id == rider_id
        )
    )
    profile = result.scalar_one_or_none()
    if profile is None:
        profile = RiderAccessibilityProfile(
            rider_id=rider_id,
            needs_wav=False,
            has_mobility_device=False,
            visual_impairment=False,
            hearing_impairment=False,
            other_needs=None,
        )
        db.add(profile)
        await db.commit()
        await db.refresh(profile)
    return profile


async def update_rider_profile(
    db: AsyncSession,
    rider_id: int,
    data: RiderAccessibilityProfileUpdate,
) -> RiderAccessibilityProfile:
    """Upsert the rider's accessibility profile with the provided values."""
    profile = await get_or_create_rider_profile(db, rider_id)
    profile.needs_wav = data.needs_wav
    profile.has_mobility_device = data.has_mobility_device
    profile.visual_impairment = data.visual_impairment
    profile.hearing_impairment = data.hearing_impairment
    profile.other_needs = data.other_needs
    await db.commit()
    await db.refresh(profile)
    return profile


# ---------------------------------------------------------------------------
# Driver WAV certification
# ---------------------------------------------------------------------------


async def get_driver_wav(
    db: AsyncSession,
    driver_id: int,
) -> DriverWAVCertification | None:
    """Return the driver's WAV certification row, or None if not submitted."""
    result = await db.execute(
        select(DriverWAVCertification).where(
            DriverWAVCertification.driver_id == driver_id
        )
    )
    return result.scalar_one_or_none()


async def submit_driver_wav(
    db: AsyncSession,
    driver_id: int,
    data: DriverWAVCertificationSubmit,
) -> DriverWAVCertification:
    """Create or update a WAV certification submission for the driver.

    Submitting resets a rejected or expired cert back to *pending* so the
    admin review workflow restarts.  An already-verified cert is updated
    in-place (e.g. driver renews with a new document before expiry).
    """
    cert = await get_driver_wav(db, driver_id)

    if cert is None:
        cert = DriverWAVCertification(
            driver_id=driver_id,
            status=WAVCertificationStatus.pending,
        )
        db.add(cert)
    else:
        # Re-open review for rejected / expired; keep status for pending/verified.
        if cert.status in (WAVCertificationStatus.rejected, WAVCertificationStatus.expired):
            cert.status = WAVCertificationStatus.pending
            cert.verified_at = None
            cert.verified_by_admin_id = None
            cert.admin_note = None

    cert.vehicle_make = data.vehicle_make
    cert.vehicle_model = data.vehicle_model
    cert.vehicle_year = data.vehicle_year
    cert.certification_document_url = data.certification_document_url
    cert.certification_number = data.certification_number
    if data.expires_at is not None:
        cert.expires_at = data.expires_at

    await db.commit()
    await db.refresh(cert)
    return cert


async def admin_verify_wav(
    db: AsyncSession,
    driver_id: int,
    admin_id: int,
    approve: bool,
    admin_note: str | None,
    expires_at: datetime | None,
) -> DriverWAVCertification:
    """Admin approves or rejects a pending WAV certification.

    Raises ValueError if the certification doesn't exist or is not in a
    reviewable state (pending).
    """
    cert = await get_driver_wav(db, driver_id)
    if cert is None:
        raise ValueError(f"No WAV certification found for driver {driver_id}.")

    if cert.status not in (
        WAVCertificationStatus.pending,
        WAVCertificationStatus.verified,  # allow re-verify to update expiry
    ):
        raise ValueError(
            f"Certification status is '{cert.status.value}' — only pending or "
            "verified certs can be actioned by admin."
        )

    now = datetime.now(tz=timezone.utc)
    if approve:
        cert.status = WAVCertificationStatus.verified
        cert.verified_at = now
        cert.verified_by_admin_id = admin_id
        if expires_at is not None:
            cert.expires_at = expires_at
    else:
        cert.status = WAVCertificationStatus.rejected
        cert.verified_at = now
        cert.verified_by_admin_id = admin_id

    cert.admin_note = admin_note

    await db.commit()
    await db.refresh(cert)
    return cert


# ---------------------------------------------------------------------------
# Platform statistics
# ---------------------------------------------------------------------------


async def get_wav_platform_stats(db: AsyncSession) -> WAVPlatformStats:
    """Return aggregate WAV coverage statistics."""
    # Riders needing WAV.
    riders_result = await db.execute(
        select(func.count(RiderAccessibilityProfile.id)).where(
            RiderAccessibilityProfile.needs_wav.is_(True)
        )
    )
    riders_needing_wav: int = riders_result.scalar_one() or 0

    # Driver counts by status.
    async def _driver_count(status: WAVCertificationStatus) -> int:
        r = await db.execute(
            select(func.count(DriverWAVCertification.id)).where(
                DriverWAVCertification.status == status
            )
        )
        return r.scalar_one() or 0

    pending = await _driver_count(WAVCertificationStatus.pending)
    verified = await _driver_count(WAVCertificationStatus.verified)
    rejected = await _driver_count(WAVCertificationStatus.rejected)
    expired = await _driver_count(WAVCertificationStatus.expired)

    if riders_needing_wav == 0:
        coverage = 1.0  # vacuously satisfied
    else:
        coverage = min(1.0, verified / riders_needing_wav)

    return WAVPlatformStats(
        total_riders_needing_wav=riders_needing_wav,
        drivers_pending_wav=pending,
        drivers_verified_wav=verified,
        drivers_rejected_wav=rejected,
        drivers_expired_wav=expired,
        coverage_ratio=coverage,
    )
