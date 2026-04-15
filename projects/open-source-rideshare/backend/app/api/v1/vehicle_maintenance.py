"""Driver vehicle maintenance tracking endpoints.

Driver endpoints (require DRIVER role):
  POST /drivers/me/vehicles/{vehicle_id}/maintenance
      Log a maintenance event for one of the driver's vehicles.

  GET  /drivers/me/vehicles/{vehicle_id}/maintenance
      Paginated history for a specific vehicle.

  GET  /drivers/me/maintenance/upcoming
      Upcoming and overdue maintenance across all of the driver's vehicles.
      Optional query param: days (default 30) — lookahead window.

Admin endpoints (require ADMIN role):
  GET  /admin/maintenance/fleet
      Fleet-wide maintenance summary: overdue count, due-soon count,
      vehicles with overdue items, and the 10 most recent logs.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_admin, require_driver
from app.db.database import get_db
from app.models.driver import DriverProfile
from app.models.user import User
from app.models.vehicle import Vehicle
from app.schemas.vehicle_maintenance import (
    FleetMaintenanceSummary,
    MaintenanceHistoryResponse,
    MaintenanceLogCreate,
    MaintenanceLogResponse,
    UpcomingMaintenanceItem,
    UpcomingMaintenanceResponse,
)
from app.services.vehicle_maintenance import (
    get_driver_maintenance_history,
    get_fleet_maintenance_summary,
    get_upcoming_maintenance,
    get_vehicle_maintenance_history,
    log_maintenance,
)

router = APIRouter(tags=["vehicle-maintenance"])


async def _get_driver_profile(user: User, db: AsyncSession) -> DriverProfile:
    result = await db.execute(
        select(DriverProfile).where(DriverProfile.user_id == user.id)
    )
    profile = result.scalar_one_or_none()
    if not profile:
        raise HTTPException(status_code=404, detail="Driver profile not found")
    return profile


async def _assert_vehicle_owned(
    vehicle_id: int, driver_profile_id: int, db: AsyncSession
) -> Vehicle:
    """Return vehicle if it belongs to this driver; raise 404 otherwise."""
    result = await db.execute(
        select(Vehicle).where(
            Vehicle.id == vehicle_id,
            Vehicle.driver_profile_id == driver_profile_id,
        )
    )
    vehicle = result.scalar_one_or_none()
    if not vehicle:
        raise HTTPException(status_code=404, detail="Vehicle not found")
    return vehicle


# ---------------------------------------------------------------------------
# Driver: log maintenance
# ---------------------------------------------------------------------------


@router.post(
    "/drivers/me/vehicles/{vehicle_id}/maintenance",
    response_model=MaintenanceLogResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Log a maintenance event for one of my vehicles",
)
async def create_maintenance_log(
    vehicle_id: int,
    req: MaintenanceLogCreate,
    user: User = Depends(require_driver),
    db: AsyncSession = Depends(get_db),
):
    """Record a completed maintenance event (oil change, tyre rotation, etc.)
    and optionally schedule the next service date or mileage target."""
    profile = await _get_driver_profile(user, db)
    await _assert_vehicle_owned(vehicle_id, profile.id, db)

    entry = await log_maintenance(
        db=db,
        vehicle_id=vehicle_id,
        driver_profile_id=profile.id,
        maintenance_type=req.maintenance_type,
        date_serviced=req.date_serviced,
        description=req.description,
        service_provider=req.service_provider,
        notes=req.notes,
        mileage_at_service=req.mileage_at_service,
        cost_usd=req.cost_usd,
        next_service_date=req.next_service_date,
        next_service_mileage=req.next_service_mileage,
    )
    await db.commit()
    await db.refresh(entry)
    return MaintenanceLogResponse.model_validate(entry)


# ---------------------------------------------------------------------------
# Driver: vehicle maintenance history
# ---------------------------------------------------------------------------


@router.get(
    "/drivers/me/vehicles/{vehicle_id}/maintenance",
    response_model=MaintenanceHistoryResponse,
    summary="Maintenance history for one of my vehicles",
)
async def list_vehicle_maintenance(
    vehicle_id: int,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    user: User = Depends(require_driver),
    db: AsyncSession = Depends(get_db),
):
    """Return paginated maintenance logs for a specific vehicle."""
    profile = await _get_driver_profile(user, db)
    await _assert_vehicle_owned(vehicle_id, profile.id, db)

    logs, total = await get_vehicle_maintenance_history(db, vehicle_id, skip, limit)
    return MaintenanceHistoryResponse(
        logs=[MaintenanceLogResponse.model_validate(log) for log in logs],
        total=total,
    )


# ---------------------------------------------------------------------------
# Driver: upcoming maintenance across all vehicles
# ---------------------------------------------------------------------------


@router.get(
    "/drivers/me/maintenance/upcoming",
    response_model=UpcomingMaintenanceResponse,
    summary="Upcoming and overdue maintenance across all my vehicles",
)
async def list_upcoming_maintenance(
    days: int = Query(
        default=30,
        ge=1,
        le=365,
        description="Lookahead window in days. Default 30. Also includes overdue items.",
    ),
    user: User = Depends(require_driver),
    db: AsyncSession = Depends(get_db),
):
    """Return a list of upcoming and overdue maintenance items for all of the
    driver's vehicles based on next_service_date. Overdue items are included
    regardless of the lookahead window."""
    profile = await _get_driver_profile(user, db)
    items = await get_upcoming_maintenance(db, profile.id, days)

    return UpcomingMaintenanceResponse(
        items=[UpcomingMaintenanceItem(**item) for item in items],
        total=len(items),
    )


# ---------------------------------------------------------------------------
# Admin: fleet maintenance summary
# ---------------------------------------------------------------------------


@router.get(
    "/admin/maintenance/fleet",
    response_model=FleetMaintenanceSummary,
    summary="Fleet-wide maintenance overview",
)
async def fleet_maintenance_summary(
    days: int = Query(
        default=30,
        ge=1,
        le=365,
        description="Window for 'due soon' count. Default 30 days.",
    ),
    _user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Admin view: overdue count, vehicles with overdue items, due-soon count,
    and the 10 most recent maintenance logs across the entire fleet."""
    summary = await get_fleet_maintenance_summary(db, days)
    return FleetMaintenanceSummary(
        total_logs=summary["total_logs"],
        overdue_count=summary["overdue_count"],
        due_within_30_days=summary["due_within_30_days"],
        vehicles_with_overdue=summary["vehicles_with_overdue"],
        recent_logs=[
            MaintenanceLogResponse.model_validate(log)
            for log in summary["recent_logs"]
        ],
    )
