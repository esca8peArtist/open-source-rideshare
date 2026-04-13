from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_driver
from app.db.database import get_db
from app.models.driver import DriverProfile
from app.models.user import User
from app.models.vehicle import Vehicle, VehicleType
from app.schemas.vehicle import VehicleCreate, VehicleResponse, VehicleUpdate

router = APIRouter(prefix="/driver/vehicles", tags=["vehicles"])

MAX_VEHICLES_PER_DRIVER = 5


async def _get_profile(user: User, db: AsyncSession) -> DriverProfile:
    result = await db.execute(
        select(DriverProfile).where(DriverProfile.user_id == user.id)
    )
    profile = result.scalar_one_or_none()
    if not profile:
        raise HTTPException(status_code=404, detail="Driver profile not found")
    return profile


@router.post("", response_model=VehicleResponse, status_code=status.HTTP_201_CREATED)
async def add_vehicle(
    req: VehicleCreate,
    user: User = Depends(require_driver),
    db: AsyncSession = Depends(get_db),
):
    profile = await _get_profile(user, db)

    # Check vehicle limit
    count_result = await db.execute(
        select(Vehicle).where(
            Vehicle.driver_profile_id == profile.id,
            Vehicle.is_active.is_(True),
        )
    )
    if len(count_result.scalars().all()) >= MAX_VEHICLES_PER_DRIVER:
        raise HTTPException(
            status_code=409,
            detail=f"Maximum {MAX_VEHICLES_PER_DRIVER} active vehicles allowed",
        )

    # Validate vehicle type
    try:
        vtype = VehicleType(req.vehicle_type)
    except ValueError:
        valid = [t.value for t in VehicleType]
        raise HTTPException(
            status_code=422,
            detail=f"Invalid vehicle type. Must be one of: {', '.join(valid)}",
        )

    vehicle = Vehicle(
        driver_profile_id=profile.id,
        vehicle_type=vtype,
        make=req.make,
        model=req.model,
        year=req.year,
        color=req.color,
        license_plate=req.license_plate,
        capacity=req.capacity,
        is_wheelchair_accessible=req.is_wheelchair_accessible,
    )
    db.add(vehicle)
    await db.commit()
    await db.refresh(vehicle)

    # Auto-set as active vehicle if it's the first one
    if profile.active_vehicle_id is None:
        profile.active_vehicle_id = vehicle.id
        await db.commit()

    return VehicleResponse(
        id=vehicle.id,
        driver_profile_id=vehicle.driver_profile_id,
        vehicle_type=vehicle.vehicle_type.value,
        make=vehicle.make,
        model=vehicle.model,
        year=vehicle.year,
        color=vehicle.color,
        license_plate=vehicle.license_plate,
        capacity=vehicle.capacity,
        is_wheelchair_accessible=vehicle.is_wheelchair_accessible,
        is_active=vehicle.is_active,
        created_at=vehicle.created_at,
    )


@router.get("", response_model=list[VehicleResponse])
async def list_vehicles(
    user: User = Depends(require_driver),
    db: AsyncSession = Depends(get_db),
):
    profile = await _get_profile(user, db)
    result = await db.execute(
        select(Vehicle)
        .where(Vehicle.driver_profile_id == profile.id, Vehicle.is_active.is_(True))
        .order_by(Vehicle.created_at.desc())
    )
    vehicles = result.scalars().all()
    return [
        VehicleResponse(
            id=v.id,
            driver_profile_id=v.driver_profile_id,
            vehicle_type=v.vehicle_type.value,
            make=v.make,
            model=v.model,
            year=v.year,
            color=v.color,
            license_plate=v.license_plate,
            capacity=v.capacity,
            is_wheelchair_accessible=v.is_wheelchair_accessible,
            is_active=v.is_active,
            created_at=v.created_at,
        )
        for v in vehicles
    ]


@router.get("/{vehicle_id}", response_model=VehicleResponse)
async def get_vehicle(
    vehicle_id: int,
    user: User = Depends(require_driver),
    db: AsyncSession = Depends(get_db),
):
    profile = await _get_profile(user, db)
    result = await db.execute(
        select(Vehicle).where(
            Vehicle.id == vehicle_id, Vehicle.driver_profile_id == profile.id
        )
    )
    vehicle = result.scalar_one_or_none()
    if not vehicle:
        raise HTTPException(status_code=404, detail="Vehicle not found")

    return VehicleResponse(
        id=vehicle.id,
        driver_profile_id=vehicle.driver_profile_id,
        vehicle_type=vehicle.vehicle_type.value,
        make=vehicle.make,
        model=vehicle.model,
        year=vehicle.year,
        color=vehicle.color,
        license_plate=vehicle.license_plate,
        capacity=vehicle.capacity,
        is_wheelchair_accessible=vehicle.is_wheelchair_accessible,
        is_active=vehicle.is_active,
        created_at=vehicle.created_at,
    )


@router.put("/{vehicle_id}", response_model=VehicleResponse)
async def update_vehicle(
    vehicle_id: int,
    req: VehicleUpdate,
    user: User = Depends(require_driver),
    db: AsyncSession = Depends(get_db),
):
    profile = await _get_profile(user, db)
    result = await db.execute(
        select(Vehicle).where(
            Vehicle.id == vehicle_id, Vehicle.driver_profile_id == profile.id
        )
    )
    vehicle = result.scalar_one_or_none()
    if not vehicle:
        raise HTTPException(status_code=404, detail="Vehicle not found")

    update_data = req.model_dump(exclude_unset=True)
    if "vehicle_type" in update_data:
        try:
            update_data["vehicle_type"] = VehicleType(update_data["vehicle_type"])
        except ValueError:
            valid = [t.value for t in VehicleType]
            raise HTTPException(
                status_code=422,
                detail=f"Invalid vehicle type. Must be one of: {', '.join(valid)}",
            )

    for field, value in update_data.items():
        setattr(vehicle, field, value)
    await db.commit()
    await db.refresh(vehicle)

    return VehicleResponse(
        id=vehicle.id,
        driver_profile_id=vehicle.driver_profile_id,
        vehicle_type=vehicle.vehicle_type.value,
        make=vehicle.make,
        model=vehicle.model,
        year=vehicle.year,
        color=vehicle.color,
        license_plate=vehicle.license_plate,
        capacity=vehicle.capacity,
        is_wheelchair_accessible=vehicle.is_wheelchair_accessible,
        is_active=vehicle.is_active,
        created_at=vehicle.created_at,
    )


@router.delete("/{vehicle_id}", status_code=status.HTTP_200_OK)
async def remove_vehicle(
    vehicle_id: int,
    user: User = Depends(require_driver),
    db: AsyncSession = Depends(get_db),
):
    profile = await _get_profile(user, db)
    result = await db.execute(
        select(Vehicle).where(
            Vehicle.id == vehicle_id, Vehicle.driver_profile_id == profile.id
        )
    )
    vehicle = result.scalar_one_or_none()
    if not vehicle:
        raise HTTPException(status_code=404, detail="Vehicle not found")

    # Soft-delete
    vehicle.is_active = False
    # Clear active_vehicle_id if this was the active vehicle
    if profile.active_vehicle_id == vehicle.id:
        profile.active_vehicle_id = None
    await db.commit()

    return {"status": "removed"}


@router.post("/{vehicle_id}/activate", response_model=VehicleResponse)
async def set_active_vehicle(
    vehicle_id: int,
    user: User = Depends(require_driver),
    db: AsyncSession = Depends(get_db),
):
    profile = await _get_profile(user, db)
    result = await db.execute(
        select(Vehicle).where(
            Vehicle.id == vehicle_id,
            Vehicle.driver_profile_id == profile.id,
            Vehicle.is_active.is_(True),
        )
    )
    vehicle = result.scalar_one_or_none()
    if not vehicle:
        raise HTTPException(status_code=404, detail="Vehicle not found or inactive")

    profile.active_vehicle_id = vehicle.id
    await db.commit()

    return VehicleResponse(
        id=vehicle.id,
        driver_profile_id=vehicle.driver_profile_id,
        vehicle_type=vehicle.vehicle_type.value,
        make=vehicle.make,
        model=vehicle.model,
        year=vehicle.year,
        color=vehicle.color,
        license_plate=vehicle.license_plate,
        capacity=vehicle.capacity,
        is_wheelchair_accessible=vehicle.is_wheelchair_accessible,
        is_active=vehicle.is_active,
        created_at=vehicle.created_at,
    )
