"""Accessibility and WAV (Wheelchair Accessible Vehicle) API endpoints.

Rider-facing:
  GET  /riders/me/accessibility          — get own accessibility profile
  PUT  /riders/me/accessibility          — update accessibility needs

Driver-facing:
  GET  /drivers/me/wav                   — get own WAV certification status
  PUT  /drivers/me/wav                   — submit / update WAV certification

Admin-facing:
  GET  /admin/accessibility/stats        — WAV coverage platform stats
  POST /admin/drivers/{driver_id}/wav/verify — approve or reject a certification
  GET  /admin/drivers/wav                — list all WAV certifications (with status filter)
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, require_admin, require_driver
from app.models.accessibility import DriverWAVCertification, WAVCertificationStatus
from app.models.user import User
from app.schemas.accessibility import (
    AdminWAVVerifyRequest,
    DriverWAVCertificationResponse,
    DriverWAVCertificationSubmit,
    RiderAccessibilityProfileResponse,
    RiderAccessibilityProfileUpdate,
    WAVPlatformStats,
)
from app.services.accessibility import (
    admin_verify_wav,
    get_driver_wav,
    get_or_create_rider_profile,
    get_wav_platform_stats,
    submit_driver_wav,
    update_rider_profile,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["accessibility"])


# ---------------------------------------------------------------------------
# Rider endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/riders/me/accessibility",
    response_model=RiderAccessibilityProfileResponse,
    summary="Get my accessibility profile",
)
async def get_my_accessibility(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return the authenticated rider's accessibility profile.

    A blank profile (all flags False) is created and returned if one does not
    yet exist — no signup prompt required.
    """
    profile = await get_or_create_rider_profile(db, user.id)
    return RiderAccessibilityProfileResponse.model_validate(profile)


@router.put(
    "/riders/me/accessibility",
    response_model=RiderAccessibilityProfileResponse,
    summary="Update my accessibility needs",
)
async def update_my_accessibility(
    data: RiderAccessibilityProfileUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Upsert the authenticated rider's accessibility profile.

    All fields are replaced with the values in the request body.  Omit
    a field to reset it to its default (False / null).
    """
    profile = await update_rider_profile(db, user.id, data)
    return RiderAccessibilityProfileResponse.model_validate(profile)


# ---------------------------------------------------------------------------
# Driver WAV endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/drivers/me/wav",
    response_model=DriverWAVCertificationResponse,
    summary="Get my WAV certification status",
)
async def get_my_wav(
    user: User = Depends(require_driver),
    db: AsyncSession = Depends(get_db),
):
    """Return the authenticated driver's WAV certification record.

    Returns 404 if the driver has not yet submitted a certification.
    """
    cert = await get_driver_wav(db, user.id)
    if cert is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No WAV certification on file. Submit one via PUT /drivers/me/wav.",
        )
    return DriverWAVCertificationResponse.model_validate(cert)


@router.put(
    "/drivers/me/wav",
    response_model=DriverWAVCertificationResponse,
    status_code=status.HTTP_200_OK,
    summary="Submit or update WAV certification",
)
async def submit_my_wav(
    data: DriverWAVCertificationSubmit,
    user: User = Depends(require_driver),
    db: AsyncSession = Depends(get_db),
):
    """Create or update the driver's WAV certification submission.

    The certification enters *pending* status and must be verified by an admin
    before the driver appears in the WAV dispatch pool.  Re-submitting a
    rejected or expired cert resets the status to *pending*.
    """
    cert = await submit_driver_wav(db, user.id, data)
    return DriverWAVCertificationResponse.model_validate(cert)


# ---------------------------------------------------------------------------
# Admin endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/admin/accessibility/stats",
    response_model=WAVPlatformStats,
    summary="WAV coverage statistics (admin only)",
)
async def admin_wav_stats(
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return platform-wide WAV coverage metrics.

    Useful for regulatory reporting (e.g. ADA compliance audits) and for
    admin prioritisation of WAV certification reviews.
    """
    stats = await get_wav_platform_stats(db)
    return stats


@router.post(
    "/admin/drivers/{driver_id}/wav/verify",
    response_model=DriverWAVCertificationResponse,
    summary="Approve or reject a WAV certification (admin only)",
)
async def admin_verify_driver_wav(
    driver_id: int,
    body: AdminWAVVerifyRequest,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Admin decision on a pending WAV certification.

    Set ``approve=true`` to verify the driver as WAV-capable; set to ``false``
    to reject.  An optional ``admin_note`` is stored for audit purposes.
    If ``expires_at`` is provided (on approval), it overrides any date the
    driver submitted.
    """
    try:
        cert = await admin_verify_wav(
            db,
            driver_id=driver_id,
            admin_id=user.id,
            approve=body.approve,
            admin_note=body.admin_note,
            expires_at=body.expires_at,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        )
    return DriverWAVCertificationResponse.model_validate(cert)


@router.get(
    "/admin/drivers/wav",
    response_model=list[DriverWAVCertificationResponse],
    summary="List WAV certifications (admin only)",
)
async def admin_list_wav_certifications(
    cert_status: WAVCertificationStatus | None = Query(
        default=None, description="Filter by certification status"
    ),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return all WAV certification records with optional status filter."""
    q = select(DriverWAVCertification)
    if cert_status is not None:
        q = q.where(DriverWAVCertification.status == cert_status)
    q = q.order_by(DriverWAVCertification.submitted_at.desc()).offset(skip).limit(limit)
    result = await db.execute(q)
    certs = list(result.scalars().all())
    return [DriverWAVCertificationResponse.model_validate(c) for c in certs]
