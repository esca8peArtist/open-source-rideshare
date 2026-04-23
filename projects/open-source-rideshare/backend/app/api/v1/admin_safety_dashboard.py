"""Admin safety dashboard endpoint.

GET /admin/safety/dashboard — consolidated view of all active safety events.

Returns active SOS alerts, route deviation flags, speeding flags, and recently
expired check-in timers. Restricted to admin users only.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_admin
from app.db.database import get_db
from app.models.user import User
from app.schemas.admin_safety_dashboard import AdminSafetyDashboard
from app.services.admin_safety_dashboard import get_safety_dashboard

logger = logging.getLogger(__name__)

router = APIRouter(tags=["admin-safety-dashboard"])


@router.get(
    "/admin/safety/dashboard",
    response_model=AdminSafetyDashboard,
    status_code=status.HTTP_200_OK,
    summary="Admin safety dashboard (admin only)",
)
async def safety_dashboard(
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> AdminSafetyDashboard:
    """Return a consolidated snapshot of all active platform safety events.

    Includes:
    - **active_sos_alerts**: SOS alerts with status ACTIVE
    - **route_deviation_flags**: IN_PROGRESS rides with a route deviation flag set
    - **speeding_flags**: IN_PROGRESS rides with a speeding flag set
    - **expired_check_ins**: Expired rider check-in timers from the last 24 hours

    Each section also has a corresponding summary count field.
    """
    return await get_safety_dashboard(db)
