from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.api.websocket import notify_admin_sos
from app.config import settings
from app.db.database import get_db
from app.models.user import User
from app.schemas.safety import (
    EmergencyContactCreate,
    EmergencyContactResponse,
    SharedTripView,
    SOSAlertResponse,
    SOSResolveRequest,
    SOSTriggerRequest,
    TripShareRequest,
    TripShareResponse,
)
from app.services.safety import (
    add_emergency_contact,
    create_trip_share_token,
    delete_emergency_contact,
    get_active_alerts,
    get_shared_trip,
    list_emergency_contacts,
    resolve_sos,
    trigger_sos,
)

router = APIRouter(prefix="/safety", tags=["safety"])


# ---- SOS ----

@router.post("/sos", response_model=SOSAlertResponse, status_code=status.HTTP_201_CREATED)
async def sos_trigger(
    req: SOSTriggerRequest,
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        alert = await trigger_sos(
            user_id=user.id,
            db=db,
            ride_id=req.ride_id,
            latitude=req.latitude,
            longitude=req.longitude,
            message=req.message,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))

    await db.commit()
    await db.refresh(alert)

    # Push real-time SOS notification to all connected admins
    await notify_admin_sos(
        alert_id=alert.id,
        user_id=user.id,
        ride_id=alert.ride_id,
        latitude=alert.latitude,
        longitude=alert.longitude,
        message=alert.message,
    )

    from app.services.audit_events import audit_sos_triggered
    await audit_sos_triggered(db, sos_id=alert.id, user_id=user.id, ride_id=alert.ride_id)

    return SOSAlertResponse(
        id=alert.id,
        ride_id=alert.ride_id,
        status=alert.status.value,
        latitude=alert.latitude,
        longitude=alert.longitude,
        message=alert.message,
        created_at=alert.created_at,
    )


@router.post("/sos/{alert_id}/resolve", response_model=SOSAlertResponse)
async def sos_resolve(
    alert_id: int,
    req: SOSResolveRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        alert = await resolve_sos(alert_id, user.id, db, req.resolution)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))

    await db.commit()
    await db.refresh(alert)
    return SOSAlertResponse(
        id=alert.id,
        ride_id=alert.ride_id,
        status=alert.status.value,
        latitude=alert.latitude,
        longitude=alert.longitude,
        message=alert.message,
        created_at=alert.created_at,
        resolved_at=alert.resolved_at,
    )


@router.get("/sos/active", response_model=list[SOSAlertResponse])
async def sos_active(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    alerts = await get_active_alerts(user.id, db)
    return [
        SOSAlertResponse(
            id=a.id,
            ride_id=a.ride_id,
            status=a.status.value,
            latitude=a.latitude,
            longitude=a.longitude,
            message=a.message,
            created_at=a.created_at,
        )
        for a in alerts
    ]


# ---- Trip Sharing ----

@router.post("/share", response_model=TripShareResponse)
async def share_trip(
    req: TripShareRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        share = await create_trip_share_token(req.ride_id, user.id, db)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))

    await db.commit()
    await db.refresh(share)
    return TripShareResponse(
        token=share.token,
        share_url=f"/api/v1/safety/share/{share.token}",
        expires_at=share.expires_at,
    )


@router.get("/share/{token}", response_model=SharedTripView)
async def view_shared_trip(
    token: str,
    db: AsyncSession = Depends(get_db),
):
    """Public endpoint — no auth required. View a shared trip by token."""
    ride = await get_shared_trip(token, db)
    if not ride:
        raise HTTPException(status_code=404, detail="Trip not found or link expired")

    driver_name = None
    vehicle_info = None
    if ride.driver:
        driver_name = ride.driver.name
        profiles = ride.driver.driver_profiles if hasattr(ride.driver, "driver_profiles") else []
        if profiles:
            p = profiles[0]
            vehicle_info = f"{p.vehicle_color} {p.vehicle_make} {p.vehicle_model} ({p.license_plate})"

    return SharedTripView(
        ride_id=ride.id,
        status=ride.status.value,
        pickup_address=ride.pickup_address,
        dropoff_address=ride.dropoff_address,
        driver_name=driver_name,
        vehicle_info=vehicle_info,
        started_at=ride.started_at,
    )


# ---- Emergency Contacts ----

@router.get("/contacts", response_model=list[EmergencyContactResponse])
async def get_contacts(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    contacts = await list_emergency_contacts(user.id, db)
    return [
        EmergencyContactResponse(
            id=c.id,
            name=c.name,
            phone=c.phone,
            relationship_label=c.relationship_label,
            created_at=c.created_at,
        )
        for c in contacts
    ]


@router.post("/contacts", response_model=EmergencyContactResponse, status_code=status.HTTP_201_CREATED)
async def create_contact(
    req: EmergencyContactCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    contact = await add_emergency_contact(
        user_id=user.id,
        name=req.name,
        phone=req.phone,
        db=db,
        relationship_label=req.relationship_label,
    )
    await db.commit()
    await db.refresh(contact)
    return EmergencyContactResponse(
        id=contact.id,
        name=contact.name,
        phone=contact.phone,
        relationship_label=contact.relationship_label,
        created_at=contact.created_at,
    )


@router.delete("/contacts/{contact_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_contact(
    contact_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    deleted = await delete_emergency_contact(contact_id, user.id, db)
    if not deleted:
        raise HTTPException(status_code=404, detail="Contact not found")
    await db.commit()
