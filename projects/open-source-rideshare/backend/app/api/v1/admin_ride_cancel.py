"""Admin ride force-cancel endpoint.

POST /admin/rides/{ride_id}/cancel  — force-cancel any non-terminal ride.

Allows admins to cancel rides that are otherwise uncancellable (e.g. IN_PROGRESS),
as required for safety incident response or fraud intervention.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_admin
from app.db.database import get_db
from app.models.user import User
from app.schemas.admin_ride_cancel import AdminRideCancelRequest, AdminRideCancelResponse
from app.services.admin_ride_cancel import admin_force_cancel_ride

logger = logging.getLogger(__name__)

router = APIRouter(tags=["admin-ride-cancel"])


@router.post(
    "/admin/rides/{ride_id}/cancel",
    response_model=AdminRideCancelResponse,
    status_code=status.HTTP_200_OK,
    summary="Force-cancel a ride (admin only)",
)
async def force_cancel_ride(
    ride_id: int,
    body: AdminRideCancelRequest,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> AdminRideCancelResponse:
    """Cancel any non-terminal ride as an admin.

    Works on SCHEDULED, REQUESTED, MATCHED, DRIVER_EN_ROUTE, ARRIVED, and IN_PROGRESS
    rides. Issues a full refund to the rider and sends RIDE_CANCELLED notifications
    to both parties (unless notify_parties=false).
    """
    try:
        result = await admin_force_cancel_ride(
            db=db,
            ride_id=ride_id,
            admin_id=admin.id,
            reason=body.reason,
            notify_parties=body.notify_parties,
        )
    except ValueError as exc:
        detail = str(exc)
        if "not found" in detail:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail)
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detail)

    await db.commit()
    return result
