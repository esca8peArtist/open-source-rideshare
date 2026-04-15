"""Vehicle maintenance tracking service.

Drivers log maintenance events against their vehicles (oil changes, brake
jobs, tire rotations, etc.) and set the next-service schedule. The system
surfaces overdue and upcoming service so drivers stay on top of vehicle
health and admins can monitor fleet safety.
"""

from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.vehicle_maintenance import MaintenanceType, VehicleMaintenanceLog
from app.models.vehicle import Vehicle


async def log_maintenance(
    db: AsyncSession,
    vehicle_id: int,
    driver_profile_id: int,
    maintenance_type: MaintenanceType,
    date_serviced: date,
    description: str | None = None,
    service_provider: str | None = None,
    notes: str | None = None,
    mileage_at_service: int | None = None,
    cost_usd: float | None = None,
    next_service_date: date | None = None,
    next_service_mileage: int | None = None,
) -> VehicleMaintenanceLog:
    """Record a maintenance event for a vehicle."""
    entry = VehicleMaintenanceLog(
        vehicle_id=vehicle_id,
        driver_profile_id=driver_profile_id,
        maintenance_type=maintenance_type,
        description=description,
        service_provider=service_provider,
        notes=notes,
        date_serviced=date_serviced,
        mileage_at_service=mileage_at_service,
        cost_usd=float(cost_usd) if cost_usd is not None else None,
        next_service_date=next_service_date,
        next_service_mileage=next_service_mileage,
    )
    db.add(entry)
    await db.flush()
    return entry


async def get_vehicle_maintenance_history(
    db: AsyncSession,
    vehicle_id: int,
    skip: int = 0,
    limit: int = 50,
) -> tuple[list[VehicleMaintenanceLog], int]:
    """Return paginated maintenance history for a single vehicle."""
    count_result = await db.execute(
        select(func.count()).where(
            VehicleMaintenanceLog.vehicle_id == vehicle_id
        )
    )
    total = count_result.scalar_one()

    result = await db.execute(
        select(VehicleMaintenanceLog)
        .where(VehicleMaintenanceLog.vehicle_id == vehicle_id)
        .order_by(VehicleMaintenanceLog.date_serviced.desc())
        .offset(skip)
        .limit(limit)
    )
    logs = list(result.scalars().all())
    return logs, total


async def get_driver_maintenance_history(
    db: AsyncSession,
    driver_profile_id: int,
    skip: int = 0,
    limit: int = 50,
) -> tuple[list[VehicleMaintenanceLog], int]:
    """Return paginated maintenance history across all of a driver's vehicles."""
    count_result = await db.execute(
        select(func.count()).where(
            VehicleMaintenanceLog.driver_profile_id == driver_profile_id
        )
    )
    total = count_result.scalar_one()

    result = await db.execute(
        select(VehicleMaintenanceLog)
        .where(VehicleMaintenanceLog.driver_profile_id == driver_profile_id)
        .order_by(VehicleMaintenanceLog.date_serviced.desc())
        .offset(skip)
        .limit(limit)
    )
    logs = list(result.scalars().all())
    return logs, total


async def get_upcoming_maintenance(
    db: AsyncSession,
    driver_profile_id: int,
    days_ahead: int = 30,
) -> list[dict]:
    """Return upcoming and overdue maintenance items for a driver's vehicles.

    Looks at the most recent log per (vehicle, maintenance_type) that has a
    next_service_date set. If next_service_date <= today it's overdue.
    """
    today = date.today()
    cutoff = today + timedelta(days=days_ahead)

    # Subquery: most recent log id per (vehicle_id, maintenance_type)
    # for logs that have a next_service_date set
    subq = (
        select(
            VehicleMaintenanceLog.vehicle_id,
            VehicleMaintenanceLog.maintenance_type,
            func.max(VehicleMaintenanceLog.id).label("latest_id"),
        )
        .where(
            VehicleMaintenanceLog.driver_profile_id == driver_profile_id,
            VehicleMaintenanceLog.next_service_date.is_not(None),
        )
        .group_by(
            VehicleMaintenanceLog.vehicle_id,
            VehicleMaintenanceLog.maintenance_type,
        )
        .subquery()
    )

    result = await db.execute(
        select(VehicleMaintenanceLog)
        .join(subq, VehicleMaintenanceLog.id == subq.c.latest_id)
        .where(VehicleMaintenanceLog.next_service_date <= cutoff)
        .order_by(VehicleMaintenanceLog.next_service_date)
    )
    logs = list(result.scalars().all())

    items = []
    for log in logs:
        delta = (log.next_service_date - today).days
        items.append({
            "log_id": log.id,
            "vehicle_id": log.vehicle_id,
            "maintenance_type": log.maintenance_type,
            "next_service_date": log.next_service_date,
            "next_service_mileage": log.next_service_mileage,
            "days_until_due": delta,
            "is_overdue": delta < 0,
        })
    return items


async def get_fleet_maintenance_summary(
    db: AsyncSession,
    days_ahead: int = 30,
) -> dict:
    """Admin summary: overdue, due-soon, and recent log counts across all drivers."""
    today = date.today()
    cutoff = today + timedelta(days=days_ahead)

    # Total log count
    total_result = await db.execute(select(func.count(VehicleMaintenanceLog.id)))
    total_logs = total_result.scalar_one()

    # Overdue: latest log per (vehicle, type) where next_service_date < today
    subq = (
        select(
            VehicleMaintenanceLog.vehicle_id,
            VehicleMaintenanceLog.maintenance_type,
            func.max(VehicleMaintenanceLog.id).label("latest_id"),
        )
        .where(VehicleMaintenanceLog.next_service_date.is_not(None))
        .group_by(
            VehicleMaintenanceLog.vehicle_id,
            VehicleMaintenanceLog.maintenance_type,
        )
        .subquery()
    )

    overdue_result = await db.execute(
        select(func.count())
        .select_from(VehicleMaintenanceLog)
        .join(subq, VehicleMaintenanceLog.id == subq.c.latest_id)
        .where(VehicleMaintenanceLog.next_service_date < today)
    )
    overdue_count = overdue_result.scalar_one()

    due_soon_result = await db.execute(
        select(func.count())
        .select_from(VehicleMaintenanceLog)
        .join(subq, VehicleMaintenanceLog.id == subq.c.latest_id)
        .where(
            VehicleMaintenanceLog.next_service_date >= today,
            VehicleMaintenanceLog.next_service_date <= cutoff,
        )
    )
    due_within_30 = due_soon_result.scalar_one()

    # Distinct vehicles with overdue items
    vehicles_overdue_result = await db.execute(
        select(func.count(VehicleMaintenanceLog.vehicle_id.distinct()))
        .select_from(VehicleMaintenanceLog)
        .join(subq, VehicleMaintenanceLog.id == subq.c.latest_id)
        .where(VehicleMaintenanceLog.next_service_date < today)
    )
    vehicles_with_overdue = vehicles_overdue_result.scalar_one()

    # 10 most recent logs
    recent_result = await db.execute(
        select(VehicleMaintenanceLog)
        .order_by(VehicleMaintenanceLog.date_serviced.desc())
        .limit(10)
    )
    recent_logs = list(recent_result.scalars().all())

    return {
        "total_logs": total_logs,
        "overdue_count": overdue_count,
        "due_within_30_days": due_within_30,
        "vehicles_with_overdue": vehicles_with_overdue,
        "recent_logs": recent_logs,
    }
