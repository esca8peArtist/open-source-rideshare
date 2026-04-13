from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_driver
from app.api.rate_limit import RateLimit
from app.config import settings
from app.db.database import get_db
from app.models.driver import DriverProfile
from app.models.payment import Payment, PaymentStatus
from app.models.ride import Ride, RideStatus
from app.models.user import User
from app.models.verification import DocumentType, VerificationStatus
from app.models.payment import PaymentType
from app.schemas.driver import (
    DailyEarningsPoint,
    DriverLocationUpdate,
    DriverProfileCreate,
    DriverProfileResponse,
    DriverProfileUpdate,
    EarningsResponse,
    EarningsSummary,
    EarningsTrip,
    RatingDistributionResponse,
    RatingsSummaryResponse,
)
from app.schemas.verification import (
    DocumentResponse,
    DocumentSubmitRequest,
    VerificationStatusResponse,
)
from app.services.verification import (
    VerificationError,
    get_verification_status,
    submit_document,
)

router = APIRouter(prefix="/driver", tags=["driver"])

_location_update_limit = RateLimit(
    settings.rate_limit_location_update, settings.rate_limit_location_update_window, key_prefix="driver_location",
)


@router.post("/profile", response_model=DriverProfileResponse, status_code=201)
async def create_profile(
    req: DriverProfileCreate,
    user: User = Depends(require_driver),
    db: AsyncSession = Depends(get_db),
):
    existing = await db.execute(
        select(DriverProfile).where(DriverProfile.user_id == user.id)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Profile already exists")

    profile = DriverProfile(user_id=user.id, **req.model_dump())
    db.add(profile)
    await db.commit()
    await db.refresh(profile)
    return profile


@router.get("/profile", response_model=DriverProfileResponse)
async def get_profile(
    user: User = Depends(require_driver),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(DriverProfile).where(DriverProfile.user_id == user.id)
    )
    profile = result.scalar_one_or_none()
    if not profile:
        raise HTTPException(status_code=404, detail="Driver profile not found")
    return profile


@router.put("/profile", response_model=DriverProfileResponse)
async def update_profile(
    req: DriverProfileUpdate,
    user: User = Depends(require_driver),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(DriverProfile).where(DriverProfile.user_id == user.id)
    )
    profile = result.scalar_one_or_none()
    if not profile:
        raise HTTPException(status_code=404, detail="Driver profile not found")

    update_data = req.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(profile, field, value)
    await db.commit()
    await db.refresh(profile)
    return profile


@router.post("/go-online")
async def go_online(
    user: User = Depends(require_driver),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(DriverProfile).where(DriverProfile.user_id == user.id)
    )
    profile = result.scalar_one_or_none()
    if not profile:
        raise HTTPException(status_code=404, detail="Driver profile not found")
    if not profile.is_approved:
        raise HTTPException(status_code=403, detail="Driver not yet approved")

    profile.is_online = True
    await db.commit()

    if profile.current_location:
        from geoalchemy2.shape import to_shape
        from app.services.matching import get_matching_engine
        point = to_shape(profile.current_location)
        engine = await get_matching_engine()
        await engine.update_driver_location(user.id, point.y, point.x)

    return {"status": "online"}


@router.post("/go-offline")
async def go_offline(
    user: User = Depends(require_driver),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(DriverProfile).where(DriverProfile.user_id == user.id)
    )
    profile = result.scalar_one_or_none()
    if not profile:
        raise HTTPException(status_code=404, detail="Driver profile not found")

    profile.is_online = False
    await db.commit()

    from app.services.matching import get_matching_engine
    engine = await get_matching_engine()
    await engine.remove_driver(user.id)

    return {"status": "offline"}


@router.post("/location", dependencies=[Depends(_location_update_limit)])
async def update_location(
    req: DriverLocationUpdate,
    user: User = Depends(require_driver),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(DriverProfile).where(DriverProfile.user_id == user.id)
    )
    profile = result.scalar_one_or_none()
    if not profile:
        raise HTTPException(status_code=404, detail="Driver profile not found")

    from geoalchemy2.functions import ST_MakePoint

    profile.current_location = ST_MakePoint(req.lng, req.lat, 4326)
    await db.commit()

    from app.services.matching import get_matching_engine
    engine = await get_matching_engine()
    await engine.update_driver_location(user.id, req.lat, req.lng)

    return {"status": "location_updated"}


def _period_start(period: str) -> date:
    today = date.today()
    if period == "day":
        return today
    elif period == "week":
        return today - timedelta(days=7)
    elif period == "month":
        return today - timedelta(days=30)
    return date(2000, 1, 1)


@router.get("/earnings", response_model=EarningsResponse)
async def get_earnings(
    period: str = Query("week", pattern="^(day|week|month|all)$"),
    user: User = Depends(require_driver),
    db: AsyncSession = Depends(get_db),
):
    today = date.today()
    start = _period_start(period)

    filters = [
        Ride.driver_id == user.id,
        Ride.status == RideStatus.COMPLETED,
    ]
    if period != "all":
        filters.append(func.date(Ride.completed_at) >= start)

    result = await db.execute(
        select(Ride, Payment)
        .outerjoin(Payment, and_(Payment.ride_id == Ride.id, Payment.payment_type == PaymentType.RIDE_FARE))
        .where(and_(*filters))
        .order_by(Ride.completed_at.desc())
    )
    rows = result.all()

    trips = []
    total_fares = 0.0
    total_tips = 0.0

    for ride, payment in rows:
        fare = payment.driver_payout if payment and payment.status == PaymentStatus.COMPLETED else (ride.actual_fare or 0.0)
        tip = payment.tip_amount if payment else ride.tip_amount
        total_fares += fare
        total_tips += tip
        trips.append(EarningsTrip(
            ride_id=ride.id,
            pickup_address=ride.pickup_address,
            dropoff_address=ride.dropoff_address,
            fare=fare,
            tip=tip,
            total=round(fare + tip, 2),
            distance_km=ride.distance_km,
            duration_min=ride.duration_min,
            completed_at=ride.completed_at,
        ))

    # Cancellation fee earnings (driver receives when rider cancels after match)
    cancel_filters = [
        Payment.payment_type == PaymentType.CANCELLATION_FEE,
        Payment.status == PaymentStatus.COMPLETED,
        Payment.driver_payout > 0,
    ]
    # Join to Ride to filter by driver_id
    cancel_query = (
        select(func.coalesce(func.sum(Payment.driver_payout), 0.0))
        .join(Ride, Payment.ride_id == Ride.id)
        .where(Ride.driver_id == user.id, *cancel_filters)
    )
    if period != "all":
        cancel_query = cancel_query.where(func.date(Payment.created_at) >= start)
    total_cancel_fees = (await db.execute(cancel_query)).scalar() or 0.0

    trip_count = len(trips)
    total_earnings = total_fares + total_tips + float(total_cancel_fees)
    return EarningsResponse(
        summary=EarningsSummary(
            total_fares=round(total_fares, 2),
            total_tips=round(total_tips, 2),
            total_cancellation_fees=round(float(total_cancel_fees), 2),
            total_earnings=round(total_earnings, 2),
            trip_count=trip_count,
            average_fare=round(total_fares / trip_count, 2) if trip_count else 0.0,
            average_tip=round(total_tips / trip_count, 2) if trip_count else 0.0,
            period_start=start,
            period_end=today,
        ),
        trips=trips,
    )


@router.get("/earnings/daily", response_model=list[DailyEarningsPoint])
async def get_daily_earnings(
    period: str = Query("week", pattern="^(day|week|month|all)$"),
    user: User = Depends(require_driver),
    db: AsyncSession = Depends(get_db),
):
    start = _period_start(period)

    # Ride fares and tips per day
    ride_date_col = func.date(Ride.completed_at)
    ride_filters = [
        Ride.driver_id == user.id,
        Ride.status == RideStatus.COMPLETED,
    ]
    if period != "all":
        ride_filters.append(ride_date_col >= start)

    ride_query = (
        select(
            ride_date_col.label("day"),
            func.count().label("trips"),
            func.coalesce(func.sum(Ride.actual_fare), 0.0).label("fares"),
            func.coalesce(func.sum(Ride.tip_amount), 0.0).label("tips"),
        )
        .where(and_(*ride_filters))
        .group_by(ride_date_col)
    )
    ride_result = await db.execute(ride_query)
    ride_by_day = {
        str(row.day): {"trips": row.trips, "fares": float(row.fares), "tips": float(row.tips)}
        for row in ride_result.all()
    }

    # Cancellation fee earnings per day
    cancel_date_col = func.date(Payment.created_at)
    cancel_filters = [
        Payment.payment_type == PaymentType.CANCELLATION_FEE,
        Payment.status == PaymentStatus.COMPLETED,
        Ride.driver_id == user.id,
    ]
    if period != "all":
        cancel_filters.append(cancel_date_col >= start)

    cancel_query = (
        select(
            cancel_date_col.label("day"),
            func.coalesce(func.sum(Payment.driver_payout), 0.0).label("cancel_fees"),
        )
        .join(Ride, Payment.ride_id == Ride.id)
        .where(and_(*cancel_filters))
        .group_by(cancel_date_col)
    )
    cancel_result = await db.execute(cancel_query)
    cancel_by_day = {str(row.day): float(row.cancel_fees) for row in cancel_result.all()}

    # Merge
    all_days = sorted(set(ride_by_day.keys()) | set(cancel_by_day.keys()))
    return [
        DailyEarningsPoint(
            date=d,
            fares=ride_by_day.get(d, {}).get("fares", 0.0),
            tips=ride_by_day.get(d, {}).get("tips", 0.0),
            cancellation_fees=cancel_by_day.get(d, 0.0),
            total=round(
                ride_by_day.get(d, {}).get("fares", 0.0)
                + ride_by_day.get(d, {}).get("tips", 0.0)
                + cancel_by_day.get(d, 0.0),
                2,
            ),
            trips=ride_by_day.get(d, {}).get("trips", 0),
        )
        for d in all_days
    ]


@router.get("/ratings", response_model=RatingsSummaryResponse)
async def get_my_ratings(
    user: User = Depends(require_driver),
    db: AsyncSession = Depends(get_db),
):
    from app.services.ratings import get_driver_ratings

    summary = await get_driver_ratings(user.id, db)
    return RatingsSummaryResponse(
        average=summary.average,
        total_ratings=summary.total_ratings,
        distribution=RatingDistributionResponse(
            one_star=summary.distribution.one_star,
            two_star=summary.distribution.two_star,
            three_star=summary.distribution.three_star,
            four_star=summary.distribution.four_star,
            five_star=summary.distribution.five_star,
        ),
        recent_average=summary.recent_average,
        recent_count=summary.recent_count,
    )


# ---- Verification ----


@router.get("/verification", response_model=VerificationStatusResponse)
async def get_driver_verification(
    user: User = Depends(require_driver),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(DriverProfile).where(DriverProfile.user_id == user.id)
    )
    profile = result.scalar_one_or_none()
    if not profile:
        raise HTTPException(status_code=404, detail="Driver profile not found")

    status = await get_verification_status(db, profile.id)
    return VerificationStatusResponse(
        documents=[
            DocumentResponse(
                id=d.id,
                driver_profile_id=d.driver_profile_id,
                document_type=d.document_type.value,
                status=d.status.value,
                document_ref=d.document_ref,
                document_number=d.document_number,
                expiry_date=d.expiry_date,
                reviewed_by=d.reviewed_by,
                reviewed_at=d.reviewed_at,
                rejection_reason=d.rejection_reason,
                review_notes=d.review_notes,
                submitted_at=d.submitted_at,
            )
            for d in status["documents"]
        ],
        missing_required=status["missing_required"],
        all_required_approved=status["all_required_approved"],
    )


@router.post("/verification/documents", response_model=DocumentResponse, status_code=201)
async def submit_verification_document(
    req: DocumentSubmitRequest,
    user: User = Depends(require_driver),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(DriverProfile).where(DriverProfile.user_id == user.id)
    )
    profile = result.scalar_one_or_none()
    if not profile:
        raise HTTPException(status_code=404, detail="Driver profile not found")

    try:
        doc_type = DocumentType(req.document_type)
    except ValueError:
        raise HTTPException(status_code=422, detail=f"Invalid document type: {req.document_type}")

    try:
        doc = await submit_document(
            db,
            driver_profile_id=profile.id,
            document_type=doc_type,
            document_ref=req.document_ref,
            document_number=req.document_number,
            expiry_date=req.expiry_date,
        )
        await db.commit()
        await db.refresh(doc)
    except VerificationError as e:
        raise HTTPException(status_code=409, detail=str(e))

    return DocumentResponse(
        id=doc.id,
        driver_profile_id=doc.driver_profile_id,
        document_type=doc.document_type.value,
        status=doc.status.value,
        document_ref=doc.document_ref,
        document_number=doc.document_number,
        expiry_date=doc.expiry_date,
        reviewed_by=doc.reviewed_by,
        reviewed_at=doc.reviewed_at,
        rejection_reason=doc.rejection_reason,
        review_notes=doc.review_notes,
        submitted_at=doc.submitted_at,
    )
