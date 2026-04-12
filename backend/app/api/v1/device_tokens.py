"""Device token registration endpoints for FCM push notifications.

Endpoints:
  POST   /me/device-tokens           — register or refresh a token (upsert)
  DELETE /me/device-tokens/{token}   — deregister a token
  GET    /me/device-tokens           — list active tokens
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.database import get_db
from app.models.device_token import DevicePlatform, DeviceToken
from app.models.user import User
from app.schemas.device_token import DeviceTokenResponse, RegisterDeviceTokenRequest

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/me/device-tokens", tags=["device-tokens"])


@router.post("", response_model=DeviceTokenResponse, status_code=status.HTTP_201_CREATED)
async def register_device_token(
    req: RegisterDeviceTokenRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Register an FCM device token for push notifications.

    Upserts: if the token already exists (from any user), it is reassigned
    to the current user and reactivated.  This handles token re-use after
    app reinstalls.
    """
    try:
        platform = DevicePlatform(req.platform)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid platform '{req.platform}'. Valid: ios, android, web",
        )

    # Upsert: find existing token regardless of owner
    result = await db.execute(
        select(DeviceToken).where(DeviceToken.token == req.token)
    )
    existing = result.scalar_one_or_none()

    if existing:
        # Re-assign and reactivate
        existing.user_id = user.id
        existing.platform = platform
        existing.is_active = True
        existing.last_used_at = datetime.now(timezone.utc)
        await db.flush()
        logger.info("Device token upserted for user %d (platform=%s)", user.id, platform.value)
        return existing

    token_record = DeviceToken(
        user_id=user.id,
        token=req.token,
        platform=platform,
        is_active=True,
        last_used_at=datetime.now(timezone.utc),
    )
    db.add(token_record)
    await db.flush()
    logger.info("Device token registered for user %d (platform=%s)", user.id, platform.value)
    return token_record


@router.delete("/{token}", status_code=status.HTTP_204_NO_CONTENT)
async def deregister_device_token(
    token: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Deregister a device token — marks it inactive.

    Only the owning user can deregister their token.
    """
    result = await db.execute(
        select(DeviceToken).where(
            DeviceToken.token == token,
            DeviceToken.user_id == user.id,
        )
    )
    record = result.scalar_one_or_none()
    if not record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Device token not found.",
        )

    record.is_active = False
    await db.flush()
    logger.info("Device token deregistered for user %d", user.id)


@router.get("", response_model=list[DeviceTokenResponse])
async def list_device_tokens(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List the current user's active device tokens."""
    result = await db.execute(
        select(DeviceToken).where(
            DeviceToken.user_id == user.id,
            DeviceToken.is_active == True,  # noqa: E712
        ).order_by(DeviceToken.created_at.desc())
    )
    tokens = result.scalars().all()
    return tokens
