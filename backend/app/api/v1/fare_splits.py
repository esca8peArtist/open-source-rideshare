import logging

import stripe
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.database import get_db
from app.models.fare_split import FareSplit, SplitStatus
from app.models.ride import Ride
from app.models.user import User
from app.schemas.fare_split import (
    CreateFareSplitRequest,
    FareSplitDetailResponse,
    FareSplitResponse,
    RespondToSplitRequest,
    SplitPaymentResponse,
)
from app.services.fare_splitting import (
    cancel_fare_split,
    create_fare_split,
    create_split_payment,
    get_fare_split,
    respond_to_split,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/fare-splits", tags=["fare-splits"])


@router.post("/rides/{ride_id}", response_model=FareSplitDetailResponse)
async def initiate_fare_split(
    ride_id: int,
    req: CreateFareSplitRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a fare split for a ride. Only the ride initiator can do this."""
    participants = [
        {
            "user_id": p.user_id,
            "phone": p.phone,
            "email": p.email,
            "share_percentage": p.share_percentage,
        }
        for p in req.participants
    ]

    result = await create_fare_split(
        ride_id=ride_id,
        initiator_id=user.id,
        participants=participants,
        split_equally=req.split_equally,
        db=db,
    )

    if "error" in result:
        raise HTTPException(status_code=409, detail=result["error"])

    return result


@router.get("/rides/{ride_id}", response_model=FareSplitDetailResponse)
async def get_ride_fare_split(
    ride_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get fare split details for a ride."""
    result = await get_fare_split(ride_id, user.id, db)

    if "error" in result:
        if result["error"] == "Ride not found":
            raise HTTPException(status_code=404, detail=result["error"])
        if result["error"] == "No fare split found for this ride":
            raise HTTPException(status_code=404, detail=result["error"])
        if "Not authorized" in result["error"]:
            raise HTTPException(status_code=403, detail=result["error"])
        raise HTTPException(status_code=409, detail=result["error"])

    return result


@router.post("/{split_id}/respond", response_model=FareSplitResponse)
async def respond_to_fare_split(
    split_id: int,
    req: RespondToSplitRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Accept or decline a fare split invitation."""
    result = await respond_to_split(split_id, user.id, req.accept, db)

    if "error" in result:
        if "not found" in result["error"].lower():
            raise HTTPException(status_code=404, detail=result["error"])
        if "not authorized" in result["error"].lower():
            raise HTTPException(status_code=403, detail=result["error"])
        raise HTTPException(status_code=409, detail=result["error"])

    return result


@router.post("/{split_id}/pay", response_model=SplitPaymentResponse)
async def pay_fare_split(
    split_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a payment intent for a participant's share of the fare."""
    try:
        result = await create_split_payment(split_id, user.id, db)
    except stripe.StripeError as e:
        logger.error("Stripe error for split %d: %s", split_id, e)
        raise HTTPException(status_code=502, detail="Payment service unavailable")

    if "error" in result:
        if "not found" in result["error"].lower():
            raise HTTPException(status_code=404, detail=result["error"])
        if "not authorized" in result["error"].lower():
            raise HTTPException(status_code=403, detail=result["error"])
        raise HTTPException(status_code=409, detail=result["error"])

    return result


@router.delete("/rides/{ride_id}")
async def cancel_ride_fare_split(
    ride_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Cancel all fare splits for a ride. Only the initiator can cancel."""
    result = await cancel_fare_split(ride_id, user.id, db)

    if "error" in result:
        if "not found" in result["error"].lower():
            raise HTTPException(status_code=404, detail=result["error"])
        if "not authorized" in result["error"].lower() or "Only the ride" in result["error"]:
            raise HTTPException(status_code=403, detail=result["error"])
        raise HTTPException(status_code=409, detail=result["error"])

    return result


@router.get("/my-splits")
async def get_my_splits(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get all fare split invitations for the current user."""
    result = await db.execute(
        select(FareSplit).where(
            FareSplit.user_id == user.id,
            FareSplit.status.notin_([SplitStatus.CANCELLED]),
        ).order_by(FareSplit.created_at.desc())
    )
    splits = result.scalars().all()

    return {
        "splits": [
            {
                "id": s.id,
                "ride_id": s.ride_id,
                "user_id": s.user_id,
                "is_initiator": s.is_initiator,
                "status": s.status.value,
                "share_amount": s.share_amount,
                "share_percentage": s.share_percentage,
                "created_at": s.created_at.isoformat() if s.created_at else None,
                "responded_at": s.responded_at.isoformat() if s.responded_at else None,
            }
            for s in splits
        ],
        "pending_count": sum(1 for s in splits if s.status == SplitStatus.PENDING),
        "total_count": len(splits),
    }
